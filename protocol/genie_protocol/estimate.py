"""genie.models.estimate — 资源估算单一真源（G19a，2026-10-16）。

网格总量 / dt / 步数的估算手，原生于内核 serve（fdtd/serve/schema.py
的 estimate_cells 家族 + G18 的 _estimate_steps）；G3 方向 2 裁决把它
移植 models 层成为单一真源——内核 serve 反向 import 本模块（共享模型
薄壳先例，genie 仍不 import fdtd），Studio preview 与内核守卫从此
同一把尺子。

全部纯数学（无 cupy/fdtd 依赖）。估算是守卫面不是预言：渐变过渡带
可比名义 factor 更细（内核 Mesh.refine docstring），真实步数以 build
后 f.n_steps 为准。
"""
from __future__ import annotations

import math

C0_PHYS = 299792458.0          # 真空光速 SI（fdtd 导出同名常数同值）


def _axis_cells(rng, h: float) -> int:
    return max(1, math.ceil((rng[1] - rng[0]) / h))


def estimate_cells_domain_mesh(domain, mesh) -> int:
    """网格总量估算（含 refine 区加密增量）——逐字移植内核正典体
    （fdtd/serve/schema.py，2026-08-30 Phase A 拆出形态）。

    ``domain``/``mesh`` = 共享线格式模型（DomainSpec/MeshSpec，属性
    访问），kernel serve 与 Studio preview 双端同参。
    """
    dx = mesh.dx
    dy = mesh.dy or mesh.dx
    dz = mesh.dz or mesh.dx
    nx = _axis_cells(domain.x_range, dx)
    ny = _axis_cells(domain.y_range, dy)
    nz = _axis_cells(domain.z_range, dz)
    base = nx * ny * nz
    if not mesh.refine:
        return base
    vol = ((domain.x_range[1] - domain.x_range[0])
           * (domain.y_range[1] - domain.y_range[0])
           * (domain.z_range[1] - domain.z_range[0]))

    def _clip(rng, dom) -> float:
        lo, hi = max(rng[0], dom[0]), min(rng[1], dom[1])
        return max(0.0, hi - lo)

    extra = 0
    for r in mesh.refine:
        fs = [r.factor] * 3 if isinstance(r.factor, int) else list(r.factor)
        mult = fs[0] * fs[1] * fs[2]
        zv = (_clip(r.x_range, domain.x_range)
              * _clip(r.y_range, domain.y_range)
              * _clip(r.z_range, domain.z_range))
        extra += base * (zv / vol) * (mult - 1)
    return int(base + extra)


def estimate_steps_domain_mesh(domain, mesh) -> int:
    """total_time → 步数预估算（G18 换算正典的 models 面镜像）。

    dt = cfl/√3 · min_cell（内核 mesh.py:142 正典公式；sim/SI 经
    ref_length 消去后 steps = √3·c₀·T/(cfl·min_cell_SI)）。min_cell
    取各轴基格距 ÷ 该轴 refine 因子累计积，不追渐变膨胀（同内核
    _estimate_steps 口径：守卫面宁紧勿松的估算，见模块头）。
    """
    fx = fy = fz = 1
    for r in mesh.refine:
        fs = [r.factor] * 3 if isinstance(r.factor, int) else list(r.factor)
        fx, fy, fz = fx * fs[0], fy * fs[1], fz * fs[2]
    cell_x = mesh.dx / fx
    cell_y = (mesh.dy or mesh.dx) / fy
    cell_z = (mesh.dz or mesh.dx) / fz
    min_cell = min(cell_x, cell_y, cell_z)
    dt_lb = domain.cfl * min_cell / (math.sqrt(3.0) * C0_PHYS)
    return max(1, math.ceil(domain.total_time / dt_lb))


def mesh_preview_stats(domain, mesh) -> dict:
    """设计态估算摘要（/api/preview ``estimate`` 节形状）：格数/dt 估/
    步数估/各轴格距。"""
    dx = mesh.dx
    return {
        "cells": estimate_cells_domain_mesh(domain, mesh),
        "dt_est": domain.cfl * min(dx, mesh.dy or dx, mesh.dz or dx)
        / (math.sqrt(3.0) * C0_PHYS),
        "n_steps_est": estimate_steps_domain_mesh(domain, mesh),
        "spacing": {"dx": dx, "dy": mesh.dy or dx, "dz": mesh.dz or dx},
    }
