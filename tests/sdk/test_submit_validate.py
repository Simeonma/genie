"""提交边界校验 + 心脏置换行为锚（迁移阶段 ④，framework §四）。

锁五件事：
1. **_cfg 即 SimConfig**（§四字面验证）与 to_config() 的 dense 契约；
2. **提交前一次性预检**：合法配置透明通过、payload 逐位 = 原文 dump
   （表达式串不预求值——原文上行是方言定案）；
3. 非法配置本地即拒（GenieConfigError，错误带 loc/指路）；
4. 行为变化登记面：`_Chain` 未知方法即刻 ValueError、load_config 未知键
   显式拒（framework §三 强类型纪律落地——不再静默等服务端 422）；
5. preview 半成品不受预检影响（_PreviewSim 的宽容语义不变）。
"""
from __future__ import annotations

import pytest

import genie
from genie import GenieConfigError
from genie.core.simulate import Simulation
from genie.core.preview import _PreviewSim


class FakeClient:
    def __init__(self):
        self.submitted: list = []
        self.sweeps: list = []

    def submit(self, cfg):
        self.submitted.append(cfg)
        return "job-1"

    def wait(self, job_id, poll_interval=2.0, progress=None):
        return {"job_id": job_id, "state": "done"}

    def sweep_submit(self, config, spec):
        self.sweeps.append((config, spec))
        return {"sweep_id": "sw-1"}


def _valid_sim() -> tuple[Simulation, FakeClient]:
    c = FakeClient()
    f = Simulation(c)
    f.domain.x_range = (-1e-6, 1e-6)
    f.domain.y_range = (-1e-6, 1e-6)
    f.domain.z_range = (-1e-6, 1e-6)
    f.domain.total_time = 6e-14
    f.mesh.dx = 2e-8
    f.mat.add_const().name("sio2").eps(2.1)
    f.geom.add_box().material("sio2") \
        .x_range(-5e-7, 5e-7).y_range(-5e-7, 5e-7).z_range(-1e-7, 1e-7)
    f.src.add_soft_source().freq(3e14).bandwidth(6e13).name("s0")
    f.mon.add_time().name("pt").field("Ex")
    return f, c


# ── 1. §四 字面验证 ────────────────────────────────────────────

def test_cfg_is_simconfig_instance():
    f, _ = _valid_sim()
    from genie.models import SimConfig
    assert isinstance(f._cfg, SimConfig)
    assert isinstance(f._cfg.domain, SimConfig.model_fields["domain"].annotation)
    dump = f.to_config()
    # dense 契约：默认值显式在场（GUI/渲染的新形状）
    assert dump["domain"]["cfl"] == 0.9
    assert dump["run"]["gpu"] is None and dump["run"]["timeout_s"] == 3600
    assert dump["source"][0]["amplitude"] == 1.0


def test_to_config_does_not_mutate_workspace():
    f, _ = _valid_sim()
    d1 = f.to_config()
    f.mesh.dx = 4e-8
    assert d1["mesh"]["dx"] == 2e-8          # dump 是快照，不是引用
    f.mesh.dx = 2e-8
    assert f.to_config() == d1


# ── 2. 合法配置透明通过，payload = 原文 dump ───────────────────

def test_submit_valid_passes_payload_verbatim():
    f, c = _valid_sim()
    f.run(timeout_s=600)
    assert c.submitted, "应已提交"
    sent = c.submitted[0]
    assert sent == f.to_config()             # 逐位 = 原文 dump
    assert sent["run"] == {"gpu": None, "timeout_s": 600}


def test_submit_payload_keeps_expressions_raw():
    """表达式串原文上行（方言定案：求值只在服务端）——预检在旁路副本做。"""
    f, c = _valid_sim()
    f.load_config({
        "parameters": {"d": "50[nm]"},
        "domain": {"x_range": ["-d", "d"], "y_range": ["-d", "d"],
                   "z_range": ["-d", "d"], "total_time": 6e-14},
        "mesh": {"dx": "d/4"},
        "materials": [{"type": "const", "name": "sio2", "eps": 2.1}],
        "geometry": [{"type": "box", "material": "sio2",
                      "x_range": ["-d", "d"], "y_range": ["-d", "d"],
                      "z_range": ["-d", "d"]}],
        "source": [{"type": "soft_source", "freq": 3e14,
                    "bandwidth": 6e13, "name": "s0"}],
        "monitor": [{"type": "time", "name": "pt", "field": "Ex"}],
        "run": {},
    })
    f.run()
    sent = c.submitted[0]
    assert sent["mesh"]["dx"] == "d/4"                       # 原文，未求值
    assert sent["parameters"] == {"d": "50[nm]"}


# ── 3. 非法配置本地即拒 ────────────────────────────────────────

def test_submit_rejects_config_error_with_loc():
    f, c = _valid_sim()
    f.mat.add_const().name("sio2").eps(2.1)
    f.geom.add_box().material("ghost_mat") \
        .x_range(0, 1e-7).y_range(0, 1e-7).z_range(0, 1e-7)  # 引用未定义材料
    with pytest.raises(GenieConfigError, match="ghost_mat"):
        f.run()
    assert not c.submitted


def test_submit_rejects_negative_dx():
    f, c = _valid_sim()
    f.mesh.dx = -2e-8
    with pytest.raises(GenieConfigError, match="mesh"):
        f.run()
    assert not c.submitted


def test_submit_rejects_expression_guard_violation():
    """表达式求值结果过不了值守卫 → 预检指路表达式（同服务端两段式）。"""
    f, c = _valid_sim()
    f.load_config({
        "parameters": {"d": "50[nm]"},
        "domain": {"x_range": [-1e-6, 1e-6], "y_range": [-1e-6, 1e-6],
                   "z_range": [-1e-6, 1e-6], "total_time": 6e-14},
        "mesh": {"dx": "-d"},        # 求值 = -5e-8 ≤ 0
        "materials": [{"type": "const", "name": "sio2", "eps": 2.1}],
        "source": [{"type": "soft_source", "freq": 3e14,
                    "bandwidth": 6e13, "name": "s0"}],
        "run": {},
    })
    with pytest.raises(GenieConfigError) as ei:
        f.run()
    assert "-d" in str(ei.value) and "mesh.dx" in str(ei.value)
    assert not c.submitted


def test_sweep_validates_base_config():
    f, c = _valid_sim()
    f.mesh.dx = -2e-8
    with pytest.raises(GenieConfigError):
        f.sweep(parameters=[{"name": "d", "linspace": [1e-8, 2e-8, 3]}])
    assert not c.sweeps


# ── 4. 行为变化登记面（强类型纪律落地） ────────────────────────

def test_chain_unknown_method_raises_immediately():
    """拼错的方法名即刻 ValueError（pydantic extra=forbid）——不再静默
    记录等服务端 422；preview 里表现为带脚本行号的报错。"""
    f, _ = _valid_sim()
    with pytest.raises(ValueError, match="prioraty"):
        f.geom.add_box().material("sio2").prioraty(1)


def test_load_config_rejects_unknown_keys():
    f, _ = _valid_sim()
    with pytest.raises(GenieConfigError, match="prioraty"):
        f.load_config({
            "domain": {"x_range": [-1e-6, 1e-6], "y_range": [-1e-6, 1e-6],
                       "z_range": [-1e-6, 1e-6], "total_time": 6e-14},
            "mesh": {"dx": 2e-8},
            "source": [{"type": "soft_source", "freq": 3e14,
                        "bandwidth": 6e13}],
            "run": {"gpu": 1},
            "prioraty": 1,
        })


def test_load_config_constructs_nested_models():
    """装载后 builder 继续可用（嵌套 dict → 子模型；实证 E2 的修复）。"""
    f, c = _valid_sim()
    f.load_config({
        "domain": {"x_range": [-1e-6, 1e-6], "y_range": [-1e-6, 1e-6],
                   "z_range": [-1e-6, 1e-6], "total_time": 6e-14,
                   "boundary": {"z_min": {"kind": "pml", "layers": 8}}},
        "mesh": {"dx": 2e-8},
        "materials": [{"type": "const", "name": "sio2", "eps": 2.1}],
        "geometry": [{"type": "box", "material": "sio2",
                      "x_range": [0, 1e-7], "y_range": [0, 1e-7],
                      "z_range": [0, 1e-7]}],
        "source": [{"type": "soft_source", "freq": 3e14,
                    "bandwidth": 6e13, "name": "s0"}],
        "monitor": [{"type": "time", "name": "pt", "field": "Ex"}],
        "run": {"gpu": 1},
    })
    f.geom.add_sphere().material("sio2").radius(3e-8)       # 装载后继续链式
    assert f.to_config()["domain"]["boundary"]["z_min"]["layers"] == 8
    assert [g["type"] for g in f.to_config()["geometry"]] == ["box", "sphere"]


# ── 5. preview 半成品不受预检影响 ──────────────────────────────

def test_preview_partial_config_never_validates():
    r = genie.preview_script(
        "import genie\n"
        "f = genie.connect('x')\n"
        "f.domain.x_range = (-1e-6, 1e-6)\n")      # 缺 mesh/source/run：照常
    assert r["ok"] is True
    assert r["cfg"]["domain"]["x_range"] == [-1e-6, 1e-6]
    assert r["cfg"]["run"] == {"gpu": None, "timeout_s": 3600}  # dense 契约


def test_preview_unknown_chain_method_reports_line():
    r = genie.preview_script(
        "import genie\n"
        "f = genie.connect('x')\n"
        "f.geom.add_box().material('m').prioraty(1)\n")
    assert r["ok"] is False
    assert "prioraty" in r["error"]["message"]
    assert r["error"]["line"] == 3                 # 带脚本行号


# ── 真入口回归（2026-10 用户实测暴露：connect 惰性 import 在阶段 4③
#    搬家时漏改，pytest/e2e 均不覆盖——本锚锁死 SDK 头号入口） ──────

def test_connect_entrypoint_wires_fake_transport(monkeypatch):
    """genie.connect 可用：入口 import 正确解析到 net.client，
    Client 注入后返回携带它的 Simulation。"""
    import genie
    sent = []

    class FakeClient:
        def __init__(self, url, key, username=None, timeout=30.0):
            sent.append((url, key, username))

    monkeypatch.setattr(genie.net.client, "Client", FakeClient)
    f = genie.connect("http://x", api_key="k", username="u")
    assert isinstance(f, genie.Simulation) and sent == [("http://x", "k", "u")]


def test_client_wait_supports_progress_true(monkeypatch):
    """progress=True = 打进度条约定（与 SweepHandle.wait 一致）。"""
    from genie.net.client import Client
    c = Client.__new__(Client)               # 免构造（不碰传输）
    states = [{"state": "running", "progress": {"step": 1, "n_steps": 2}},
              {"state": "succeeded", "progress": {"step": 2, "n_steps": 2}}]
    monkeypatch.setattr(c, "job_status", lambda jid: states.pop(0))
    lines = []
    st = c.wait("j1", poll_interval=0, progress=True)
    assert st["state"] == "succeeded"
