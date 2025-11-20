# -*- coding: utf-8 -*-
"""
toio のテレオペ (leader) 用 TeleoperatorConfig。
- pygame で取得するジョイスティックの軸割り当て/反転/スケール/デッドゾーン等をここで調整します。
"""

from dataclasses import dataclass
from lerobot.teleoperators.config import TeleoperatorConfig

@TeleoperatorConfig.register_subclass("toio_leader")
@dataclass
class ToioConfig(TeleoperatorConfig):
    port: str = "4443"
    host: str = "0.0.0.0"
    use_gripper: bool = False  # 本テレオペではグリッパは扱いません（互換のFalseため残置）

    # ---- 入力デバイス（ジョイスティック）設定 ----
    joystick_index: int = 0          # 使用するジョイスティック番号（複数繋いだ場合に変更）
    axis_x_index: int = 0            # vx に使う軸番号（既定: X 軸）
    axis_y_index: int = 2            # vy に使う軸番号（既定: 多くのパッドで右/左スティックの Y）
    invert_x: bool = True            # X 軸の符号反転（右を + に揃える等）
    invert_y: bool = True            # Y 軸の符号反転（多くのパッドで「上」がマイナスのため + に反転）

    # ---- 入力整形パラメータ ----
    speed: float = 0.5               # 出力スケール（-1..1 の軸値に掛ける係数、最終的に [-1..1] にクリップ）
    deadzone: float = 0.08           # デッドゾーン（|v| < deadzone は 0 とみなす）
