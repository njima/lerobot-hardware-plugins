# -*- coding: utf-8 -*-
"""
toio を lerobot の Robot として扱うための実装。
- カメラ周りの初期化とフレーム取得（失敗時ゼロ画像フォールバック）
- BLE 経由でのモータ制御（非同期ランナー）
- 観測は「直近のアクションのエコー（vx, vy）」＋カメラ画像を返す方針
"""

from __future__ import annotations

from typing import Any, Optional, Tuple
import threading
import asyncio
import inspect
import numpy as np

from lerobot.cameras import make_cameras_from_configs
from lerobot.utils.errors import DeviceNotConnectedError, DeviceAlreadyConnectedError
from lerobot.robots.robot import Robot

# 同一ディレクトリ（パッケージ）内の設定クラス
from .config_toio import ToioConfig


def _clip(v: int, lo: int, hi: int) -> int:
    """整数 v を [lo, hi] にクリップする小ヘルパ。"""
    return lo if v < lo else hi if v > hi else v


class _ToioAsyncRunner:
    """
    toio をバックグラウンドの asyncio スレッドで管理するランナー。
    - メインスレッドからは set_motor(L, R) を呼ぶだけ
    - ランナー内部で BLE 接続と非同期送信を処理
    """

    def __init__(self, *, ble_name_prefix: str, ble_scan_timeout_s: float):
        # 独自のイベントループをバックグラウンドスレッドで持つ
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop_main, name="toio-async", daemon=True)
        self._ready_evt = threading.Event()  # 接続完了/失敗の通知
        self._stop_evt = threading.Event()   # 停止指示
        self._exc: Optional[BaseException] = None  # 起動時の例外（あれば保持）

        # モータ指令キュー（最新指令のみを保持する設計）
        self._queue: "asyncio.Queue[Tuple[int, int] | str]" = None  # type: ignore
        self._last_cmd: Optional[Tuple[int, int]] = None

        # BLE スキャン設定（アドレス指定は廃止）
        self._ble_name_prefix = ble_name_prefix
        self._ble_scan_timeout_s = ble_scan_timeout_s

    # --- ライフサイクル -----------------------------------------------------

    def start(self, timeout: float = 30.0) -> None:
        """
        ランナー起動。接続完了（または失敗）まで待機する。
        - timeout 超過時は TimeoutError
        - 起動中に例外が出た場合は RuntimeError として cause 付きで再送出
        """
        self._thread.start()
        if not self._ready_evt.wait(timeout=timeout):
            raise TimeoutError("toio: BLE connection timeout")
        if self._exc:
            raise RuntimeError(f"toio: async runner failed: {self._exc}") from self._exc

    def set_motor(self, left: int, right: int) -> None:
        """
        モータ値（整数、±100 程度）を非同期キューへ投入。
        - キューには常に「最新 1 件」だけが残るようにする（古い指令は捨てる）
        """
        if self._stop_evt.is_set():
            return

        def _put():
            if self._queue is None:
                return
            # 最新指令のみ保持：古いエントリを空にしてから put
            try:
                while True:
                    self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait((left, right))

        self._loop.call_soon_threadsafe(_put)

    def stop(self) -> None:
        """停止用の特殊メッセージを送ってスレッドを合流させる。"""
        def _stop():
            if self._queue is not None:
                self._queue.put_nowait("STOP")
            self._stop_evt.set()

        self._loop.call_soon_threadsafe(_stop)
        self._thread.join(timeout=10.0)

    # --- 内部処理 -----------------------------------------------------------

    def _loop_main(self):
        """バックグラウンドスレッドのエントリポイント。"""
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.Queue()
        try:
            self._loop.run_until_complete(self._runner())
        finally:
            try:
                self._loop.stop()
            except Exception:
                pass
            self._loop.close()

    async def _runner(self):
        """
        実際の BLE 接続とモータ送信ループ。
        - まず toio ライブラリの自動スキャンで接続を試みる
        - 失敗したら bleak でスキャン → 最初の toio を選んで、そのアドレスで再トライ
        - アドレス指定の CLI/設定サポートは廃止（ユーザ指定は受け付けない）
        """
        # toio ライブラリの存在確認
        try:
            from toio import ToioCoreCube  # type: ignore
        except Exception as e:
            self._exc = ImportError(
                "Python package 'toio' が必要です。インストール例: pip install toio "
                f"(original error: {e})"
            )
            self._ready_evt.set()
            return

        # ToioCoreCube の __init__ に存在する引数のみ渡すためのフィルタ
        def _filter_kwargs_for_cube(**kwargs):
            try:
                sig = inspect.signature(ToioCoreCube)
                return {k: v for k, v in kwargs.items() if k in sig.parameters and v is not None}
            except Exception:
                # 署名取得に失敗した場合は安全側で何も渡さない
                return {}

        async def _motor_loop(cube) -> None:
            """接続確立後のモータ送信ループ（重複コード回避のため関数化）。"""
            self._ready_evt.set()
            try:
                await cube.api.motor.motor_control(0, 0)
            except Exception:
                pass

            while not self._stop_evt.is_set():
                try:
                    msg = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if msg == "STOP":
                    try:
                        await cube.api.motor.motor_control(0, 0)
                    finally:
                        break
                left, right = msg
                if self._last_cmd != (left, right):
                    await cube.api.motor.motor_control(int(left), int(right))
                    self._last_cmd = (left, right)

        # --- 1) toio ライブラリの自動スキャンに委ねてみる ---
        try:
            async with ToioCoreCube() as cube:
                await _motor_loop(cube)
                return  # 正常終了
        except Exception:
            # → 後段の bleak スキャンへ
            pass

        # --- 2) bleak でスキャン → 最初の toio を選んで接続 ---
        try:
            from bleak import BleakScanner  # type: ignore

            devices = await BleakScanner.discover(timeout=self._ble_scan_timeout_s)
            cand = [
                d for d in devices
                if (d.name or "").lower().startswith((self._ble_name_prefix or "toio").lower())
            ]
            if not cand:
                names = [(d.name or "unknown", getattr(d, "address", "n/a")) for d in devices]
                raise RuntimeError(
                    "BLE スキャンで toio Core Cube が見つかりませんでした。\n"
                    "- Cube をペアリング/アドバタイズ状態にする\n"
                    "- macOS の Bluetooth 権限（Terminal/Python）を許可\n"
                    "- 他機器との既存接続を解除\n"
                    f"Scanned devices: {names}"
                )

            addr = getattr(cand[0], "address", None)

            # toio ライブラリの引数差を吸収して「それっぽいキー群」を渡す
            retry_kwargs = {}
            for key in ("address", "mac_address", "device", "target", "target_addr"):
                retry_kwargs[key] = addr
            rk = _filter_kwargs_for_cube(**retry_kwargs)

            # 署名上、どの引数も受け付けない場合は（古い実装など）引数なしで再トライ
            if not rk:
                async with ToioCoreCube() as cube:
                    await _motor_loop(cube)
                    return

            async with ToioCoreCube(**rk) as cube:
                await _motor_loop(cube)
                return  # 正常終了

        except Exception as e:
            # アドレス指定のヒントは廃止。一般的な対処のみ提示。
            self._exc = RuntimeError(
                "toio Core Cube への接続に失敗しました。\n"
                "Tips:\n"
                "- Cube をペアリング状態に（長押しでアドバタイズ）\n"
                "- 近距離/電池残量を確認\n"
                "- macOS の Bluetooth 権限を確認（Terminal/Python を許可）\n"
                "- 既存の BLE 接続（スマホ等）を切断\n"
                f"\nOriginal error: {e}"
            )
            self._ready_evt.set()
            return


class Toio(Robot):
    """
    lerobot の Robot 実装。
    - config_class: ToioConfig
    - 観測は「直近のアクション（vx, vy）のエコー」＋カメラ画像
    - send_action では差動二輪への変換を行い、BLE ランナーに出力
    """

    config_class = ToioConfig
    name = "toio"

    def __init__(self, config: ToioConfig):
        super().__init__(config)
        self.config = config

        # ---- カメラの生成（lerobot-record が len(robot.cameras) を参照する）----
        self.cameras = make_cameras_from_configs(config.cameras)

        # 接続状態フラグ
        self._is_connected = False

        # 観測は「直近アクションのエコー」を返す
        self._last_vx: float = 0.0
        self._last_vy: float = 0.0

        # BLE ランナー（※ BLE アドレス指定は廃止）
        self._runner = _ToioAsyncRunner(
            ble_name_prefix=str(getattr(config, "ble_name_prefix", "toio")),
            ble_scan_timeout_s=float(getattr(config, "ble_scan_timeout_s", 8.0)),
        )

        # モータ変換ゲイン
        self._max_motor: int = int(getattr(config, "max_motor", 80))
        self._kv: float = float(getattr(config, "kv", self._max_motor))  # 前後
        self._kw: float = float(getattr(config, "kw", 40.0))             # 旋回（相対比は kw/kv）
        self._deadzone: float = float(getattr(config, "deadzone", 0.05))

        # 画像 shape（ゼロ画像フォールバック用）
        self._cam_shape: dict[str, tuple[int, int, int]] = {
            cam_key: (config.cameras[cam_key].height, config.cameras[cam_key].width, 3)
            for cam_key in self.cameras
        }

    # ===== 接続系 =====

    def connect(self, calibrate: bool = True) -> None:
        """
        カメラを接続 → BLE ランナー起動。
        既に接続済みなら DeviceAlreadyConnectedError。
        """
        if self.is_connected:
            raise DeviceAlreadyConnectedError(f"{self} already connected")

        # カメラ接続
        for cam in self.cameras.values():
            cam.connect()

        # BLE 起動（完了まで待つ）
        self._runner.start(timeout=30.0)

        self._is_connected = True
        print(f"{self} connected (toio BLE & cameras).")

    def disconnect(self) -> None:
        """停止指令を送ってから、BLE/カメラを順に切断。"""
        if not self.is_connected:
            return
        try:
            self._runner.set_motor(0, 0)
        except Exception:
            pass
        self._runner.stop()
        for cam in self.cameras.values():
            cam.disconnect()
        self._is_connected = False
        print(f"{self} disconnected.")

    # ===== Robot 抽象メソッドの最小実装 =====

    def calibrate(self) -> None:
        """toio 側に特別なキャリブレーションは不要なので no-op。"""
        return

    def configure(self) -> None:
        """接続チェック以外に特別な設定は不要なので最小実装。"""
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

    # ===== 必須プロパティ =====

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        self._is_connected = value

    @property
    def is_calibrated(self) -> bool:
        # この実装では接続＝キャリブレーション済み扱い
        return self.is_connected

    @property
    def _cameras_ft(self) -> dict[str, tuple]:
        """観測空間に含めるカメラの shape（lerobot の仕様に合わせる）。"""
        return self._cam_shape

    @property
    def observation_features(self) -> dict[str, Any]:
        """
        観測の特徴量定義。
        - vx, vy（直近アクションのエコー）
        - 各カメラのフレーム（H, W, 3）
        """
        feats: dict[str, Any] = {"vx": float, "vy": float}
        feats.update(self._cameras_ft)
        return feats

    @property
    def action_features(self) -> dict[str, type]:
        """アクションの特徴量定義（vx: 旋回, vy: 前後）。"""
        return {"vx": float, "vy": float}

    # ===== I/O =====

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        アクション（vx: 旋回, vy: 前後）を差動二輪のモータ値 (L, R) に変換し、非同期で送信。
        - deadzone により小出力を 0 に潰す
        - クリップにより安全な範囲（±max_motor）に制限
        """
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

        # 直近コマンドを保持（観測で返す）
        vx = float(action.get("vx", 0.0))  # 右旋回(+)/左旋回(-)
        vy = float(action.get("vy", 0.0))  # 前(+)/後(-)
        self._last_vx = vx
        self._last_vy = vy

        # --- 差動二輪への混合（整数化前の値） ---
        # vy は前後成分、vx は旋回成分（左右差）
        L = int(round(self._kv * vy - self._kw * vx))
        R = int(round(self._kv * vy + self._kw * vx))

        # --- デッドゾーン処理（小さい値は 0 に潰す） ---
        dz = int(self._max_motor * self._deadzone)
        if abs(L) < dz:
            L = 0
        if abs(R) < dz:
            R = 0

        # --- クリップ（±max_motor） ---
        L = _clip(L, -self._max_motor, self._max_motor)
        R = _clip(R, -self._max_motor, self._max_motor)

        # --- 非同期で実機へ送信 ---
        self._runner.set_motor(L, R)

        # データセットには送った action をそのまま返す（エコー）
        return {"vx": vx, "vy": vy}

    def get_observation(self) -> dict[str, Any]:
        """
        観測を取得。
        - 本実装では「直近の vx, vy のエコー」＋「各カメラの最新フレーム」
        - カメラ取得に失敗/未到達のときはゼロ画像でフォールバック
        """
        if not self.is_connected:
            raise DeviceNotConnectedError(f"{self} is not connected.")

        obs: dict[str, Any] = {"vx": float(self._last_vx), "vy": float(self._last_vy)}

        # カメラフレーム取得（フォールバックあり）
        for cam_key, cam in self.cameras.items():
            h, w, c = self._cam_shape[cam_key]
            frame = None
            try:
                if hasattr(cam, "async_read"):
                    frame = cam.async_read()
                elif hasattr(cam, "read"):
                    ok, frame = cam.read()
                    if ok is False:
                        frame = None
            except Exception:
                frame = None

            if frame is None or not isinstance(frame, np.ndarray):
                frame = np.zeros((h, w, c), dtype=np.uint8)

            obs[cam_key] = frame

        return obs
