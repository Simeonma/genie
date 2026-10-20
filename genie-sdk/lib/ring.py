"""圆环/盘——径向对称结构（framework §四 lib 起步件）。

``add_ring_z`` 的参数化便捷封装：命名参数直给、常用默认（居中、实心盘
退化），供用户/agent ``from genie.lib import ring`` 直呼。
"""
from __future__ import annotations

from typing import Any


def ring(f: Any, *, material: str, outer_radius: float, height: float,
         inner_radius: float = 0.0,
         center: tuple[float, float, float] = (0.0, 0.0, 0.0),
         priority: int = 0) -> None:
    """一个圆环（z 轴挤出体）。

    Parameters
    ----------
    material : str
        材料名（须已注册）。
    outer_radius / height : float
        外半径与挤出高度（m，均 > 0——服务端守卫裁决）。
    inner_radius : float
        内半径；0 = 实心盘（默认）。须 < outer_radius。
    center : (x, y, z)
        环心（默认原点）。
    priority : int
        几何优先级。
    """
    f.geom.add_ring_z().material(material) \
        .center(center[0], center[1], center[2]) \
        .inner_radius(inner_radius) \
        .outer_radius(outer_radius) \
        .height(height) \
        .priority(priority)
