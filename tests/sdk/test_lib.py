"""genie.lib 起步件的 preview 锚（阶段 ④⑥）。

锁两件事：参数化构件在 preview 里正确展开成节点；非法参数在调用点
即刻报错（不是静默生成垃圾几何）。
"""
from __future__ import annotations

import genie


def _base(f):
    f.domain.x_range = (-2e-6, 2e-6)
    f.domain.y_range = (-1e-6, 1e-6)
    f.domain.z_range = (-1e-6, 1e-6)
    f.domain.total_time = 6e-14
    f.mesh.dx = 2e-8
    f.mat.add_const().name("sio2").eps(2.1)


def test_grating_unrolls_to_n_boxes():
    src = """
import genie
from genie.lib.grating import grating
f = genie.connect('x')
f.domain.x_range = (-2e-6, 2e-6)
f.domain.y_range = (-1e-6, 1e-6)
f.domain.z_range = (-1e-6, 1e-6)
f.domain.total_time = 6e-14
f.mesh.dx = 5e-8
f.mat.add_const().name('sio2').eps(2.1)
grating(f, material='sio2', x_range=(0, 9e-7), y_range=(-5e-7, 5e-7),
        z_range=(-1e-7, 1e-7), n=3, pitch=3e-7, duty=0.5)
"""
    r = genie.preview_script(src)
    assert r["ok"] is True, r["error"]
    geo = r["cfg"]["geometry"]
    assert len(geo) == 3
    assert geo[0]["x_range"] == [0.0, 1.5e-7]     # 首条线宽 = pitch*duty
    assert geo[2]["x_range"] == [6e-7, 7.5e-7]    # 末条 = (n-1)*pitch 起


def test_ring_builds_ring_z_node():
    src = """
import genie
from genie.lib.ring import ring
f = genie.connect('x')
f.domain.x_range = (-2e-6, 2e-6)
f.domain.y_range = (-1e-6, 1e-6)
f.domain.z_range = (-1e-6, 1e-6)
f.domain.total_time = 6e-14
f.mesh.dx = 5e-8
f.mat.add_const().name('sio2').eps(2.1)
ring(f, material='sio2', outer_radius=4e-7, height=2e-7,
     inner_radius=1e-7, center=(1e-7, 0, 0), priority=2)
"""
    r = genie.preview_script(src)
    assert r["ok"] is True, r["error"]
    geo = r["cfg"]["geometry"]
    assert len(geo) == 1 and geo[0]["type"] == "ring_z"
    assert geo[0]["inner_radius"] == 1e-7 and geo[0]["priority"] == 2


def test_grating_rejects_bad_duty_at_callsite():
    src = """
import genie
from genie.lib.grating import grating
f = genie.connect('x')
grating(f, material='m', x_range=(0, 1), y_range=(0, 1), z_range=(0, 1),
        n=2, pitch=0.5, duty=1.5)
"""
    r = genie.preview_script(src)
    assert r["ok"] is False
    assert "duty" in r["error"]["message"] and r["error"]["line"] == 5
