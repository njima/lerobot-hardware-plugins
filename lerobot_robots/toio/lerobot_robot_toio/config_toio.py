# -*- coding: utf-8 -*-
"""
toio 用 RobotConfig 定義。
- カメラ設定
- モータ/制御ゲイン
- BLE スキャン設定（名前プレフィックス + タイムアウト）

補足:
- x 側（旋回）の相対比は kw/kv で決まります。
  例) kv=80, kw=40 → vx は vy の約 1/2 の効き。
"""

from dataclasses import dataclass, field
from typing import Dict
from lerobot.cameras import CameraConfig
from lerobot.robots.config import RobotConfig


@RobotConfig.register_subclass("toio_follower")
@dataclass
class ToioConfig(RobotConfig):
    # ---- カメラ設定 ----
    cameras: Dict[str, CameraConfig] = field(default_factory=dict)

    # ---- モータ/制御ゲイン ----
    max_motor: int = 80               # モータ出力のクリップ上限（±max_motor）
    kv: float = 80.0                  # vy（前後）→ モータ値へのゲイン
    kw: float = 20.0                  # vx（旋回）→ モータ値へのゲイン（既定で kv の約 1/2）
    deadzone: float = 0.05            # 小さなモータ値は 0 に潰す比率（±max_motor に対する割合）
    integrate_pose: bool = True       # （拡張用フラグ、ここでは未使用）

    # ---- BLE スキャン設定 ----
    ble_name_prefix: str = "toio"     # スキャン時のデバイス名プレフィックス
    ble_scan_timeout_s: float = 8.0   # bleak によるスキャンのタイムアウト
