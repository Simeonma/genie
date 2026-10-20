"""net/expert 骨架转正锚（阶段 7⑤）。

锁三件事：ExpertSession 经 Simulation.expert 属性到达（对称原则——
SDK 与宿主同一客户端代码）；ask/delegate 打 /expert/* 端点（用户
key 随会话）；参数校验在客户端即报（空 question/cfg）。
"""
from __future__ import annotations

import pytest

import genie
from genie.net.expert import ExpertSession


class FakeClient:
    def __init__(self):
        self.calls = []

    def expert_post(self, path, body):
        self.calls.append((path, body))
        if path == "/expert/ask":
            return {"expert": "design", "conclusion": {"structure": "grating"}}
        return {"expert": "simulation",
                "job": {"job_id": "j-1", "state": "done"},
                "validation": {"verdict": "pass"}}


def test_expert_session_via_simulation():
    from genie.core.preview import _PreviewSim
    f = _PreviewSim()
    assert isinstance(f.expert, ExpertSession)


def test_ask_and_delegate_hit_expert_endpoints():
    f = genie.Simulation(FakeClient())
    out = f.expert.ask("设计一个 1550nm 滤波器")
    assert out["conclusion"]["structure"] == "grating"
    cfg = {"run": {"n_steps": 10}}
    out = f.expert.delegate(cfg=cfg, steps=50)
    assert out["validation"]["verdict"] == "pass"
    paths = [p for p, _ in f._client.calls]
    assert paths == ["/expert/ask", "/expert/delegate"]


def test_empty_args_rejected_client_side():
    f = genie.Simulation(FakeClient())
    with pytest.raises(ValueError):
        f.expert.ask("   ")
    with pytest.raises(ValueError):
        f.expert.delegate()
