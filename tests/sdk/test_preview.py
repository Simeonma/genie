"""preview_script 执行捕获引擎的锁测试（genie-service 核心）。

v2 定案「脚本是本体」：这里锁的是这扇门的全部关键性质——
零网络、for 展开、numpy 求值、run 录制、诊断带行号、connect 必恢复。
"""
from __future__ import annotations

import pytest

import genie


BASIC = """
import genie
f = genie.connect("http://preview-test", api_key="YOUR_API_KEY")
f.domain.x_range = (-1e-6, 1e-6)
f.domain.z_range = (-2e-6, 2e-6)
f.domain.total_time = 6e-14
f.mesh.dx = 2e-8
f.mat.add_const().name('sio2').eps(2.1)
f.geom.add_box().material('sio2') \\
    .x_range(-5e-7, 5e-7).y_range(-5e-7, 5e-7).z_range(-1e-7, 1e-7)
f.src.add_soft_source().freq(3e14).bandwidth(6e13).name('s0')
f.mon.add_time().name('pt').center(0, 0, 2e-7).field('Ex')
f.run(timeout_s=600)
print("done", 1 + 1)
"""


def test_basic_capture():
    r = genie.preview_script(BASIC)
    assert r["ok"] is True
    assert r["error"] is None
    cfg = r["cfg"]
    assert tuple(cfg["domain"]["x_range"]) == (-1e-6, 1e-6)
    assert cfg["mesh"]["dx"] == 2e-8
    assert cfg["materials"][0]["name"] == "sio2"
    assert cfg["geometry"][0]["type"] == "box"
    assert cfg["source"][0]["name"] == "s0"
    assert cfg["monitor"][0]["name"] == "pt"
    # 阶段 ④：dense 契约（model_dump）——gpu 默认 None 显式在场
    assert cfg["run"] == {"gpu": None, "timeout_s": 600}
    assert "done 2" in r["stdout"]


def test_zero_network_never_builds_client():
    """connect 被换掉 → 全程无 Client 构造（零网络的结构性证明）。"""
    import genie.net.client as _c
    built = []
    real = _c.Client
    try:
        _c.Client = lambda *a, **k: built.append(a) or real(*a, **k)
        r = genie.preview_script(BASIC)
        assert r["ok"] is True and not built
    finally:
        _c.Client = real


def test_connect_restored_even_on_crash():
    before = genie.connect
    genie.preview_script("import genie\nf = genie.connect('x')\n1/0")
    assert genie.connect is before


def test_syntax_error_has_line():
    r = genie.preview_script("import genie\nf = (")
    assert r["ok"] is False
    assert r["error"]["kind"] == "syntax"
    assert r["error"]["line"] == 2


def test_runtime_error_has_script_frame_line():
    r = genie.preview_script("import genie\nf = genie.connect('x')\n\nraise ValueError('boom')")
    assert r["ok"] is False
    assert r["error"]["kind"] == "ValueError"
    assert r["error"]["line"] == 4
    assert "boom" in r["error"]["message"]
    # 部分捕获照样返回：崩前构建到哪一目了然
    assert isinstance(r["cfg"], dict)


def test_for_loop_unrolls_into_nodes():
    """编译器语义：for = 执行 N 次 = cfg 里 N 个节点。"""
    src = """
import genie
f = genie.connect('x')
for i in range(5):
    f.geom.add_box().material('sio2').x_range(i * 1e-7, i * 1e-7 + 5e-8)
"""
    r = genie.preview_script(src)
    assert r["ok"] is True
    assert len(r["cfg"]["geometry"]) == 5
    assert r["cfg"]["geometry"][3]["x_range"] == [3e-7, 3.5e-7]


def test_numpy_computes_to_literals():
    src = """
import numpy as np
import genie
f = genie.connect('x')
f.mesh.dx = float(np.linspace(2e-8, 4e-8, 3)[1])
"""
    r = genie.preview_script(src)
    assert r["ok"] is True
    assert r["cfg"]["mesh"]["dx"] == pytest.approx(3e-8)


def test_get_results_after_run_is_inert():
    """后处理脚本不崩：get_* 返回宽容占位（显示用预览不做作业）。"""
    src = BASIC + "t = f.get_time('pt')\nprint(t.time[-1])\n"
    r = genie.preview_script(src)
    assert r["ok"] is True
    assert "占位" in r["stdout"]


def test_run_missing_total_time_is_diagnosed():
    src = "import genie\nf = genie.connect('x')\nf.run()\n"
    r = genie.preview_script(src)
    assert r["ok"] is False
    assert "total_time" in r["error"]["message"]


def test_multiple_connect_merges_in_order():
    src = """
import genie
a = genie.connect('x')
a.geom.add_box().material('m')
b = genie.connect('y')
b.geom.add_sphere().material('m')
b.domain.x_range = (-1, 1)
"""
    r = genie.preview_script(src)
    assert r["ok"] is True
    cfg = r["cfg"]
    assert [g["type"] for g in cfg["geometry"]] == ["box", "sphere"]
    assert tuple(cfg["domain"]["x_range"]) == (-1, 1)


def test_deterministic_same_script_same_cfg():
    assert genie.preview_script(BASIC)["cfg"] == genie.preview_script(BASIC)["cfg"]


def test_preview_script_using_dunder_file():
    """引导块类脚本（sys.path/Path(__file__)）在预览态不 NameError——
    live 通道会把含引导头的整份脚本送进 GUI 预览（2026-10 实测坑）。"""
    src = """import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))
import genie
f = genie.connect('x')
f.domain.x_range = (-1e-6, 1e-6)
"""
    r = genie.preview_script(src)
    assert r["ok"] is True, r["error"]
    assert tuple(r["cfg"]["domain"]["x_range"]) == (-1e-6, 1e-6)
