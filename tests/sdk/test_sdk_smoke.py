"""SDK 冒烟：builder→to_script 转发 + examples 起步脚本全流程（v1 资产
在 v2 树上照常工作的证明）。"""
from __future__ import annotations

import genie
from genie.core.preview import _PreviewSim


def _build() -> _PreviewSim:
    f = _PreviewSim()
    f.domain.x_range = (-1e-6, 1e-6)
    f.domain.total_time = 6e-14
    f.mesh.dx = 2e-8
    f.mat.add_const().name("sio2").eps(2.1)
    f.geom.add_box().material("sio2").x_range(-5e-7, 5e-7).priority(1)
    f.src.add_soft_source().freq(3e14).bandwidth(6e13).name("s0")
    f.mon.add_freq().name("sp").center(0, 0, 2e-7).field("all") \
        .freq(3e14, 1.2e14, 200)
    f.run(timeout_s=600)
    return f


def test_builder_to_script_roundtrip_smoke():
    f = _build()
    s = f.to_script()
    assert "import genie" in s and "genie.connect(" in s
    assert "f.run(" in s
    # 确定性（v1 字节锁性质的单侧半边）
    assert f.to_script() == s


def test_preview_of_generated_script_roundtrip():
    """to_script 产物再经 preview_script 执行 → cfg 等价（脚本本体的
    自洽闭环：生成物即本体，本体再执行得回模型）。"""
    f = _build()
    r = genie.preview_script(f.to_script())
    assert r["ok"] is True, r["error"]
    assert r["cfg"] == f.to_config()
