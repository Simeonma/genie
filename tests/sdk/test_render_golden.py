"""渲染输出与 preview cfg 形状的 golden 锚（迁移阶段 ② 之 ③）。

为什么此刻做：v2 没有渲染器字节锁测试（v1 的 test_script.py 未随迁，
_script.py 头注的"字节锁"是历史指涉）——阶段 ④ 心脏置换（dict→SimConfig，
to_config() 换 model_dump）前必须先把当前渲染字节固化，④ 之后逐字节
不变才算"渲染器不用大改"（migration-plan 原话）的机器证明。

三面锚：
- **A 渲染字节**：render(cfg) 与 golden/<case>.py.txt 逐字节相等；
- **B 稠密等价**（④ 的直接预演）：对可校验配置，
  ``render(model_dump(model_validate(cfg))) == render(cfg)``——阶段 ④ 的
  to_config() 产出的就是 dense dump，此锚今天就证明两种形态渲染同字节
  （渲染器的"等于默认值则省略"表 == 模型默认值，逐字段核对过）；
- **C preview cfg 形状**：preview_script(script) 的 cfg 规范化 JSON 与
  golden/*.cfg.json 相等——阶段 ④ 中此 golden 再生为 dense 新契约
  （diff 评审 = 契约变更完整清单），渲染 golden 则必须不动。

语料覆盖全部渲染分支，特意含 `50e-9` 与 `50*1e-9` 双字面量（ulp 陷阱：
两者不是同一个 double，repr 分别为 5e-08 / 5.0000000000000004e-08——
任何数值重格式化都会被字节锁抓住）。

再生：``GENIE_REGEN_GOLDEN=1 python -m pytest sdk/tests/test_render_golden.py``
（评审 diff 后入库；golden 是审阅产物，不是黑盒）。

比较用规范化文本（json.dumps sort_keys）而非 ``==``：后者 1 == 1.0 为
True，会漏检 int/float 类型漂移。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import genie
from genie.core.script import render

_GOLDEN = Path(__file__).resolve().parent / "golden"
ORIGIN = "https://genie.example.com"
_REGEN = os.environ.get("GENIE_REGEN_GOLDEN") == "1"

# ── 语料（内嵌：对阶段 ④ 目录搬家免疫） ─────────────────────────
# dense 等价锚的适用面：表达式串配置（validate 拒收 str 数值槽）、
# from_library 节点（模型显式拒收）、缺必填的半成品——这三类只锁 A/C。

BASIC = {
    "domain": {"x_range": [-1e-6, 1e-6], "y_range": [-1e-6, 1e-6],
               "z_range": [-2e-6, 2e-6], "total_time": 6e-14,
               "boundary": {"z_min": {"kind": "pml"},
                            "z_max": {"kind": "pml"}}},
    "mesh": {"dx": 2e-8, "dy": 3e-8, "dz": 2e-8},
    "materials": [{"type": "const", "name": "sio2", "eps": 2.1, "mu": 1.2}],
    "geometry": [{"type": "box", "material": "sio2",
                  "x_range": [-5e-7, 5e-7], "y_range": [-5e-7, 5e-7],
                  "z_range": [-1e-7, 1e-7], "priority": 2}],
    # size=(0,0,0) 显式在场：锁"默认值省略"（dense dump 里它恒在场，
    # 稀疏显式设置也不再渲染——语义等价模型默认，同 cfl/layers 纪律）
    "source": [{"type": "soft_source", "freq": 3e14, "bandwidth": 6e13,
                "delay": 1e-15, "phase": 0.5, "name": "s0",
                "center": [0, 0, -3e-7], "size": [0, 0, 0],
                "polarization": [[1.0, 2.0], [0, 0], [0, 0]],
                "amplitude": 2.0, "kind": "magnetic"}],
    "monitor": [{"type": "time", "name": "pt", "center": [0, 0, 2e-7],
                 "size": [0, 0, 0], "field": "Ex",
                 "down_sample": {"time_window": [0, 1e-13], "stride": 2}}],
    "run": {"timeout_s": 600},
}

FULL = {
    "domain": {
        "x_range": [-2e-6, 2e-6], "y_range": [-1e-6, 1e-6],
        "z_range": [-1e-6, 1e-6], "total_time": 6e-14, "cfl": 0.95,
        "boundary": {
            "z_min": {"kind": "pml", "layers": 8, "kappa_max": 1.5,
                      "order": 4},
            "z_max": {"kind": "pml"},
            "x_min": {"kind": "bloch", "k": [1e6, 0.0, 0.0],
                      "n_background": 1.5},
            "x_max": {"kind": "periodic"},
        }},
    "mesh": {"dx": 2e-8, "dy": 3e-8, "dz": 4e-8,
             "max_refinement": 64, "min_cells": 12,
             "refine": [
                 {"x_range": [0.0, 1e-7], "y_range": [0.0, 1e-7],
                  "z_range": [0.0, 1e-7], "factor": [2, 3, 4],
                  "growth_rate": 1.3},
                 {"x_range": [-1e-7, 0.0], "y_range": [-1e-7, 0.0],
                  "z_range": [-1e-7, 0.0], "factor": 3}]},
    "materials": [
        {"type": "const", "name": "sio2", "eps": 2.1, "mu": [1.0, 1.1, 1.2]},
        {"type": "lorentz", "name": "au", "eps_inf": 1.5,
         "poles": [
             {"kind": "drude", "omega_p": 1e15, "gamma": 1e13,
              "alpha": [1.0, 0.0, 0.0], "beta": [0.0, 1.0, 0.0]},
             {"kind": "lorentz", "omega_0": 2e15, "gamma": 2e13,
              "delta_eps": 3.0}],
         "mu_poles": [{"kind": "lorentz", "omega_0": 3e15,
                       "gamma": 3e13}]}],
    "geometry": [
        {"type": "sphere", "material": "au", "center": [1e-7, 0.0, 0.0],
         "radius": 5e-8, "priority": 1},
        {"type": "cylinder", "material": "sio2", "radius": 3e-8,
         "height": 1e-7},
        {"type": "ngon_z", "material": "sio2", "n_sides": 6,
         "circumradius": 4e-8, "height": 1e-7},
        {"type": "polygon_z", "material": "sio2",
         "vertices": [[0.0, 0.0], [1e-7, 0.0], [1e-7, 1e-7],
                      [None, None], [0.0, 1e-7]],
         "z_range": [0.0, 1e-7]},
        {"type": "ellipse_z", "material": "sio2", "rx": 2e-8, "ry": 3e-8,
         "height": 1e-7},
        {"type": "ring_z", "material": "sio2", "inner_radius": 1e-8,
         "outer_radius": 4e-8, "height": 1e-7},
        {"type": "polygon_swept", "material": "sio2",
         "vertices": [[0.0, 0.0], [1e-7, 0.0], [1e-7, 1e-7]],
         "z_range": [0.0, 1e-7], "tilt": [0.1, 0.2]}],
    "source": [
        {"type": "plane_wave", "freq": 3e14, "bandwidth": 6e13,
         "name": "pw", "direction": "-", "amplitude": 2.0,
         "center": [0, 0, -5e-7], "theta": 30.0, "phi": 45.0, "psi": 15.0,
         "size": [1e-6, 1e-6, None], "propagation_axis": "z",
         "from_face": "z_min"},
        {"type": "gaussian_beam", "freq": 3e14, "bandwidth": 6e13,
         "name": "gb", "radius": 2e-6, "center": [0, 0, -5e-7]}],
    "monitor": [
        {"type": "freq", "name": "sp", "center": [0, 0, 2e-7],
         "size": [1e-6, 1e-6, 0], "field": "all",
         "freq": {"center": 3e14, "bw": 1.2e14, "n": 200},
         "apodize": {"side": "both", "time_window": [0, 1e-13],
                     "width": 5e-15}},
        {"type": "index", "name": "ix", "field": "eps"}],
    "run": {"gpu": 2, "timeout_s": 600},
}

# ulp 陷阱语料：50[nm] 求值 = 5e-08，50*1e-9 求值 = 5.0000000000000004e-08
# ——两个"五十纳米"不是同一个 double；参数行/表达式槽的字节被此锚钉死。
PARAMS = {
    "parameters": {"d": "50[nm]", "w": "50*1e-9", "half": "w/2",
                    "plain": 50e-9},
    "domain": {"x_range": ["-d", "d"], "y_range": ["-w", "w"],
               "z_range": [-1e-6, 1e-6], "total_time": 6e-14},
    "mesh": {"dx": "d/4"},
    "materials": [{"type": "const", "name": "sio2", "eps": 2.1}],
    "geometry": [{"type": "box", "material": "sio2",
                  "x_range": ["-half", "half"], "y_range": [-5e-7, 5e-7],
                  "z_range": [-1e-7, 1e-7]}],
    "source": [{"type": "soft_source", "freq": 3e14, "bandwidth": 6e13,
                "name": "s0"}],
    "monitor": [{"type": "time", "name": "pt", "field": "Ex"}],
    "run": {},
}

# from_library 渲染分支（模型显式拒收该线格式节点——拟合归 SDK 糖，
# 渲染器仍为其保留脚本镜像分支；只锁 A）
LIBMAT = {
    "domain": {"x_range": [-1e-6, 1e-6], "y_range": [-1e-6, 1e-6],
               "z_range": [-1e-6, 1e-6], "total_time": 6e-14},
    "mesh": {"dx": 2e-8},
    "materials": [
        {"type": "from_library", "name": "au", "library": "Au",
         "fit_range": [300e-9, 900e-9], "n_drude": 1, "n_lorentz": 3,
         "maxfev": 8000}],
    "source": [{"type": "soft_source", "freq": 3e14, "bandwidth": 6e13,
                "name": "s0"}],
    "run": {},
}

# 缺必填半成品：锁 ⚠ 配置未完成块的字节（preview 容错面的正字）
INCOMPLETE = {
    "domain": {"x_range": [-1e-6, 1e-6]},
    "mesh": {"dy": 3e-8},
    "materials": [{"type": "const", "eps": 2.1}],
    "geometry": [{"type": "box", "material": "sio2",
                  "x_range": [-1e-7, 1e-7]}],
    "source": [],
    "monitor": [{"type": "time", "center": [0, 0, 2e-7]}],
    "run": {},
}

GPU_COUNT2 = {
    "domain": {"x_range": [-1e-6, 1e-6], "y_range": [-1e-6, 1e-6],
               "z_range": [-1e-6, 1e-6], "total_time": 6e-14},
    "mesh": {"dx": 2e-8},
    "source": [{"type": "soft_source", "freq": 3e14, "bandwidth": 6e13,
                "name": "s0"}],
    "run": {"gpu": 2},
}

GPU_INT = {
    "domain": {"x_range": [-1e-6, 1e-6], "y_range": [-1e-6, 1e-6],
               "z_range": [-1e-6, 1e-6], "total_time": 6e-14},
    "mesh": {"dx": 2e-8},
    "source": [{"type": "soft_source", "freq": 3e14, "bandwidth": 6e13,
                "name": "s0"}],
    "run": {"gpu": 1},
}

CASES = [
    ("basic", BASIC),
    ("full_field", FULL),
    ("params_ulp", PARAMS),
    ("from_library", LIBMAT),
    ("incomplete_warn", INCOMPLETE),
    ("gpu_count2", GPU_COUNT2),
    ("gpu_int", GPU_INT),
]
_NO_DENSE = {"params_ulp", "from_library", "incomplete_warn"}


# ── A. 渲染字节 golden ──────────────────────────────────────────

@pytest.mark.parametrize("name,cfg_dict", CASES)
def test_render_golden_bytes(name, cfg_dict):
    out = render(cfg_dict, ORIGIN)
    path = _GOLDEN / f"{name}.py.txt"
    if _REGEN:
        _GOLDEN.mkdir(exist_ok=True)
        path.write_text(out, encoding="utf-8")
        pytest.skip("golden 已再生")
    assert path.exists(), f"{path} 缺失——先 GENIE_REGEN_GOLDEN=1 再生"
    assert out == path.read_text(encoding="utf-8"), (
        f"{name} 渲染字节漂移——改渲染器必须同步评审 golden（或确认是"
        f"有意的契约变化，评审后 GENIE_REGEN_GOLDEN=1 再生）")


# ── B. 稠密等价（阶段 ④ 的直接预演） ───────────────────────────

@pytest.mark.parametrize("name,cfg_dict", CASES)
def test_render_dense_equivalence(name, cfg_dict):
    if name in _NO_DENSE:
        pytest.skip("表达式串/from_library/半成品不走 model_validate")
    from genie.models import SimConfig
    dense = SimConfig.model_validate(cfg_dict).model_dump(mode="json")
    assert render(dense, ORIGIN) == render(cfg_dict, ORIGIN), (
        f"{name}：dense dump 与稀疏 dict 渲染不同字节——阶段 ④ 的"
        f"to_config()=model_dump 将破坏渲染不变性")


# ── C. preview cfg 形状 golden（阶段 ④ 再生为 dense 新契约） ────

P_SCRIPTS = {
    "p_basic": """
import genie
f = genie.connect('x')
f.domain.x_range = (-1e-6, 1e-6)
f.domain.y_range = (-1e-6, 1e-6)
f.domain.z_range = (-2e-6, 2e-6)
f.domain.total_time = 6e-14
f.mesh.dx = 2e-8
f.mat.add_const().name('sio2').eps(2.1).mu(1.2)
f.geom.add_box().material('sio2') \\
    .x_range(-5e-7, 5e-7).y_range(-5e-7, 5e-7).z_range(-1e-7, 1e-7) \\
    .priority(2)
f.src.add_soft_source().freq(3e14).bandwidth(6e13).name('s0') \\
    .center(0, 0, -3e-7).size(0, 0, 0).delay(1e-15).phase(0.5) \\
    .polarization(complex(1, 2), 0, 0).amplitude(2.0).kind('magnetic')
f.mon.add_time().name('pt').center(0, 0, 2e-7).field('Ex') \\
    .down_sample((0, 1e-13), 2)
f.run(timeout_s=600)
""",
    "p_loop": """
import genie
f = genie.connect('x')
f.domain.x_range = (-2e-6, 2e-6)
f.domain.y_range = (-1e-6, 1e-6)
f.domain.z_range = (-1e-6, 1e-6)
f.domain.total_time = 6e-14
f.mesh.dx = 5e-8
f.mat.add_const().name('sio2').eps(2.1)
for i in range(5):
    f.geom.add_box().material('sio2') \\
        .x_range(i * 2e-7, i * 2e-7 + 1e-7) \\
        .y_range(-1e-7, 1e-7).z_range(-1e-7, 1e-7)
f.src.add_plane_wave().freq(3e14).bandwidth(6e13).from_face('z_min')
f.mon.add_freq().name('sp').field('all').freq(3e14, 1.2e14, 200)
f.run()
""",
    "p_params": """
import genie
f = genie.connect('x')
f.load_config({
    'parameters': {'d': '50[nm]', 'w': '50*1e-9', 'half': 'w/2'},
    'domain': {'x_range': ['-d', 'd'], 'y_range': ['-w', 'w'],
               'z_range': [-1e-6, 1e-6], 'total_time': 6e-14},
    'mesh': {'dx': 'd/4'},
    'materials': [{'type': 'const', 'name': 'sio2', 'eps': 2.1}],
    'geometry': [{'type': 'box', 'material': 'sio2',
                  'x_range': ['-half', 'half'],
                  'y_range': [-5e-7, 5e-7], 'z_range': [-1e-7, 1e-7]}],
    'source': [{'type': 'soft_source', 'freq': 3e14,
                'bandwidth': 6e13, 'name': 's0'}],
    'monitor': [{'type': 'time', 'name': 'pt', 'field': 'Ex'}],
    'run': {},
})
""",
}


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=repr)


@pytest.mark.parametrize("name", list(P_SCRIPTS))
def test_preview_cfg_golden(name):
    r = genie.preview_script(P_SCRIPTS[name])
    assert r["ok"] is True, r["error"]
    path = _GOLDEN / f"{name}.cfg.json"
    if _REGEN:
        _GOLDEN.mkdir(exist_ok=True)
        path.write_text(_canon(r["cfg"]) + "\n", encoding="utf-8")
        pytest.skip("golden 已再生")
    assert path.exists(), f"{path} 缺失——先 GENIE_REGEN_GOLDEN=1 再生"
    assert _canon(r["cfg"]) + "\n" == path.read_text(encoding="utf-8"), (
        f"{name} preview cfg 形状漂移（阶段 ④ 换 model_dump 后此处**预期"
        f"再生一次**：dense 新契约的 diff 即契约变更完整清单，须评审）")


# ── 确定性 + 随包示例仍可预览 ────────────────────────────────

def test_render_deterministic():
    for _, c in CASES:
        assert render(c, ORIGIN) == render(c, ORIGIN)


def test_shipped_examples_preview_ok():
    """随 wheel 分发的示例必须能被 preview 解析（GUI「载入示例」直接用它们）。

    只锚包内 `genie/examples/`（2026-10 从 studio/static/examples 上移）：仓根
    曾有一批演示脚本，它们从不随包分发、且引导路径写死拆包前的布局，已删除。
    """
    root = Path(__file__).resolve().parents[2]
    exs = sorted((root / "genie-sdk" / "examples").glob("*.py"))
    assert len(exs) >= 3, f"包内示例少于 3 个：{[p.name for p in exs]}"
    for p in exs:
        r = genie.preview_script(p.read_text(encoding="utf-8"))
        assert r["ok"] is True, f"{p.name}: {r['error']}"
