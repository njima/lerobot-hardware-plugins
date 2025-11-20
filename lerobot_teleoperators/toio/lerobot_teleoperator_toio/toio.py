# -*- coding: utf-8 -*-
"""
toio 用テレオペレーター（leader 側）。
pygame でゲームパッドの軸値を読み取り、毎フレーム {vx, vy} を返します。

設計方針
- 軸値は [-1..1] を想定。反転・デッドゾーン・スケーリングを適用してから Robot へ渡します。
- 軸が不足/未検出などの例外系でも "動作は止まる（vx=vy=0）＋一度だけ警告" とし、
  メインループを落とさず復帰可能にしています。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any

# lerobot base
from lerobot.teleoperators.teleoperator import Teleoperator

# 同パッケージ内のテレオペ設定
from .config_toio import ToioConfig


def _clip(v: float, lo: float, hi: float) -> float:
    """浮動小数点 v を [lo, hi] にクリップする小ヘルパ。"""
    return lo if v < lo else hi if v > hi else v


class Toio(Teleoperator):
    """
    pygame を用いた最小ジョイスティック teleop。
      - 指定軸（既定: X=axis0, Y=axis2）を読み取り、毎フレーム {vx, vy} を返す
      - フィードバックは扱わない（send_feedback は no-op）
    """
    config_class = ToioConfig
    name = "toio"

    # ========= ライフサイクル =========

    def __init__(self, config: ToioConfig):
        super().__init__(config)
        self.config = config

        # 接続・キャリブレーション状態
        self._connected = False
        self._calibrated = True  # 特別なキャリブレーションは不要

        # 直近の出力（観測のエコー用ではないが、デバッグ確認に便利）
        self._vx: float = 0.0
        self._vy: float = 0.0

        # pygame / joystick は遅延 import（環境によって未導入の可能性があるため）
        self._pg = None                    # pygame モジュール
        self._joy = None                   # pygame.joystick.Joystick インスタンス

        # 警告を一度だけ表示するためのフラグ
        self._warned_no_joy = False
        self._warned_axis = False

        # ---- config 値の取り込み（フォールバックは dataclass 側の既定値）----
        self._joy_index = int(getattr(config, "joystick_index", 0))
        self._axis_x_idx = int(getattr(config, "axis_x_index", 0))
        self._axis_y_idx = int(getattr(config, "axis_y_index", 2))
        self._invert_x = bool(getattr(config, "invert_x", True))
        self._invert_y = bool(getattr(config, "invert_y", True))
        self._speed = float(getattr(config, "speed", 0.5))
        self._deadzone = float(getattr(config, "deadzone", 0.08))

    # ----- Teleoperator interface -----

    @property
    def action_features(self) -> dict[str, type]:
        """Robot 側に渡すアクションの特徴量定義。"""
        return {"vx": float, "vy": float}

    @property
    def feedback_features(self) -> dict[str, type]:
        """本テレオペではフィードバックを扱わない。"""
        return {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_calibrated(self) -> bool:
        # 本実装では特別なキャリブレーションは不要なので常に True
        return self._calibrated

    def connect(self, calibrate: bool = True) -> None:
        """
        pygame を初期化し、指定のジョイスティック（config.joystick_index）をオープン。
        - pygame 未導入時は明示的に ImportError を投げ、対処方法を表示
        - ジョイスティックが見つからない場合は vx,vy=0 のまま動作（警告は一度だけ）
        """
        try:
            import pygame  # type: ignore
        except Exception as e:
            raise ImportError(
                "pygame が見つかりません。`pip install pygame` を実行してください。"
            ) from e

        self._pg = pygame
        pygame.init()
        pygame.joystick.init()

        cnt = pygame.joystick.get_count()
        if cnt <= 0:
            print("[teleop/joystick] No joystick detected (vx, vy は 0 のままになります)")
            self._joy = None
        else:
            # 指定 index が範囲外なら 0 にフォールバック
            ji = self._joy_index if 0 <= self._joy_index < cnt else 0
            self._joy = pygame.joystick.Joystick(ji)
            self._joy.init()
            print(
                f"[teleop/joystick] Connected to: {self._joy.get_name()} "
                f"(index={ji}, axes={self._joy.get_numaxes()})"
            )

        self._connected = True

    def calibrate(self) -> None:
        """特別なキャリブレーションは不要。"""
        return

    def configure(self) -> None:
        """本テレオペでは追加の設定は不要。"""
        return

    def disconnect(self) -> None:
        """pygame / joystick をクリーンに終了。"""
        self._connected = False
        try:
            if self._joy is not None:
                self._joy.quit()
        except Exception:
            pass
        try:
            if self._pg is not None:
                self._pg.joystick.quit()
                self._pg.quit()
        except Exception:
            pass
        self._joy = None
        self._pg = None

    # ========= 内部ユーティリティ =========

    def _apply_deadzone_and_scale(self, v: float) -> float:
        """
        軸値 v に対してデッドゾーンとスケールを適用し、最終的に [-1, 1] に収める。
        - デッドゾーン: |v| < deadzone は 0
        - スケール: v *= speed
        - クリップ: [-1, 1]
        """
        if abs(v) < self._deadzone:
            v = 0.0
        # 念のため軸値自体を [-1,1] に収めてからスケール
        v = _clip(v, -1.0, 1.0)
        v = self._speed * v
        # speed が 1 を超えている場合も想定し、最終クリップを行う
        return float(_clip(v, -1.0, 1.0))

    def _read_axes(self) -> None:
        """
        pygame から最新の軸値を取り出して内部状態（_vx, _vy）を更新。
        - ジョイスティック未接続時は 0 を維持し、一度だけ警告。
        - 軸数が不足している場合は安全なフォールバック（例: Y → axis1）へ切替。
        """
        if self._pg is None:
            # 未接続（connect 前）なら何もしない
            return

        # イベントキューを処理（内部状態更新のために必要）
        self._pg.event.pump()

        if self._joy is None:
            # ジョイスティック未検出：常に 0 を出力
            self._vx, self._vy = 0.0, 0.0
            if not self._warned_no_joy:
                print("[teleop/joystick] Warning: joystick not available (vx,vy=0)")
                self._warned_no_joy = True
            return

        num_axes = self._joy.get_numaxes()

        # 軸インデックスの安全化
        ax_x = self._axis_x_idx
        ax_y = self._axis_y_idx
        if num_axes <= max(ax_x, ax_y):
            # 代表的な配置: 0=X, 1=Y があればそれにフォールバック
            if num_axes >= 2:
                ax_x, ax_y = 0, 1
            else:
                # 1 本以下しかない場合は 0 固定
                self._vx, self._vy = 0.0, 0.0
                if not self._warned_axis:
                    print(f"[teleop/joystick] Warning: not enough axes (have {num_axes})")
                    self._warned_axis = True
                return

        # 軸値の取得（-1..1 の想定だが、念のためクリップ）
        try:
            x = float(self._joy.get_axis(ax_x))
            y = float(self._joy.get_axis(ax_y))
        except Exception:
            x, y = 0.0, 0.0

        # 反転（多くのパッドで Y: 上がマイナス → + に揃える）
        if self._invert_x:
            x = -x
        if self._invert_y:
            y = -y

        # デッドゾーン＆スケール＆クリップを適用
        self._vx = self._apply_deadzone_and_scale(_clip(x, -1.0, 1.0))
        self._vy = self._apply_deadzone_and_scale(_clip(y, -1.0, 1.0))

    # ========= メイン I/O =========

    def get_action(self) -> dict[str, Any]:
        """
        毎フレーム呼ばれるエントリ。最新の {vx, vy} を返す。
        - Robot ループがこの戻り値をそのまま受け取り、差動二輪へ変換します。
        """
        self._read_axes()
        return {"vx": float(self._vx), "vy": float(self._vy)}

    def send_feedback(self, feedback: dict[str, float]) -> None:
        """本テレオペではフィードバックは扱わない（no-op）。"""
        return
