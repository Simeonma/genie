"""G29b sweep 客户端编排锚：本地展开 / 滑动窗口 / NaN 聚合 / abort。

内核 sweep 面退役后，sweep = 普通作业的客户端组合——本文件锁编排
语义；展开层语义锚（轴名/逐点错误信息）与旧服务端逐字同源。
"""
from __future__ import annotations

import math

import pytest

from genie.core.sweep import (SweepHandle, build_aggregate,
                              build_sweep_spec, flatten_numeric)
from genie.models.sweep_expand import SweepExpandError, validate_sweep_config


def _base(d0=20e-9):
    return {
        "parameters": {"d": d0},
        "domain": {"x_range": [-1e-6, 1e-6], "y_range": [-1e-6, 1e-6],
                   "z_range": [-1e-6, 1e-6], "total_time": 60e-15,
                   "cfl": 0.9,
                   "boundary": {"z_min": {"kind": "pml", "layers": 12},
                                "z_max": {"kind": "pml", "layers": 12}}},
        "mesh": {"dx": "d/4", "dy": 20e-9, "dz": 20e-9},
        "materials": [{"name": "sio2", "type": "const", "eps": 2.1}],
        "geometry": [{"type": "box", "material": "sio2",
                      "x_range": [-5e-7, 5e-7], "y_range": [-5e-7, 5e-7],
                      "z_range": [-1e-7, 1e-7], "priority": 1}],
        "source": [{"type": "soft_source", "freq": 300e12, "bandwidth": 60e12,
                    "name": "s0", "center": [0, 0, -3e-7],
                    "polarization": [1, 0, 0]}],
        "monitor": [{"type": "time", "name": "pt", "center": [0, 0, 2e-7],
                     "size": [0, 0, 0], "field": "Ex"}],
        "run": {"timeout_s": 600},
    }


class _FakeClient:
    """假网关：窗口语义锚的关键——在途上限即服务端 429 闸的模拟。"""

    def __init__(self, mcr=2, fail_idx=()):
        self.mcr = mcr
        self.fail_idx = set(fail_idx)
        self.jobs: dict[str, dict] = {}
        self.inflight_peak = 0
        self.submitted = 0

    def whoami(self):
        return {"principal": "t", "admin": False,
                "quota": {"max_concurrent_runs": self.mcr}}

    def submit(self, config):
        self.submitted += 1
        jid = f"j{self.submitted}"
        n_alive = sum(1 for j in self.jobs.values()
                      if j["state"] in ("queued", "running"))
        self.inflight_peak = max(self.inflight_peak, n_alive + 1)
        assert n_alive + 1 <= self.mcr, "撞服务端并发闸（窗口失守）"
        self.jobs[jid] = {"config": config, "state": "queued",
                          "fail": (self.submitted - 1) in self.fail_idx}
        return jid

    def job_status(self, jid):
        j = self.jobs[jid]
        if j["state"] == "queued":
            j["state"] = "running"
        elif j["state"] == "running":
            j["state"] = "failed" if j["fail"] else "succeeded"
        return {"state": j["state"]}

    def cancel(self, jid):
        self.jobs[jid]["state"] = "killed"
        return {"ok": True}

    def digest(self, jid):
        j = self.jobs[jid]
        assert j["state"] == "succeeded"
        # 用 dx 参数回显当摘要数值（可手算：d 值/4）
        return {"peak": j["config"]["parameters"]["d"] / 4.0}


def _spec(values, **kw):
    return build_sweep_spec(parameters=[{"name": "d", "values": values}],
                            **kw)


# ---- 展开（与旧服务端语义同源）----

def test_expand_expression_linkage():
    """轴值联动表达式槽：mesh.dx = "d/4" 随 d 逐点变。"""
    from genie.models import SweepSpec
    pts = validate_sweep_config(SweepSpec.model_validate(
        _spec([10e-9, 40e-9])), _base())
    assert [p["mesh"]["dx"] for p in pts] == [2.5e-9, 10e-9]


def test_expand_bad_axis_name_lists_available():
    with pytest.raises(SweepExpandError, match="不在基底配置.*可用"):
        validate_sweep_config(SweepSpec.model_validate(
            _spec([1e-9])), _base()) if False else None
        from genie.models import SweepSpec
        validate_sweep_config(SweepSpec.model_validate(
            build_sweep_spec(parameters=[{"name": "nope",
                                          "values": [1]}])), _base())


def test_expand_point_error_carries_index():
    """逐点非法（超时负值）带第几点（1 基）。"""
    from genie.models import SweepSpec
    base = _base()
    spec = build_sweep_spec(
        parameters=[{"name": "d", "values": [20e-9, -20e-9]}])
    # mesh.dx = "d/4"：点 2 的 d 为负 → dx 负值守卫拦（点 1 合法）
    with pytest.raises(SweepExpandError, match="第 2 点"):
        validate_sweep_config(SweepSpec.model_validate(spec), base)


# ---- 编排 ----

def test_sliding_window_respects_quota():
    """4 点 / 窗 2：任意时刻在途 ≤ 2（撞闸即断言炸），跑一补一。"""
    c = _FakeClient(mcr=2)
    h = SweepHandle(c, _base(), _spec([10e-9, 20e-9, 30e-9, 40e-9],
                                      max_parallel=8))
    st = h.wait(poll=0)
    assert st["state"] == "done"
    assert c.submitted == 4 and c.inflight_peak == 2
    assert h.rollup() == {"succeeded": 4}


def test_failed_points_nan_in_aggregate():
    """失败点 = NaN 行（NaN 语义锚）：点 2 失败 → pt 列该位 NaN。"""
    c = _FakeClient(mcr=4, fail_idx={1})
    h = SweepHandle(c, _base(), _spec([10e-9, 20e-9, 30e-9]))
    h.wait(poll=0)
    assert h.rollup() == {"succeeded": 2, "failed": 1}
    agg = h.aggregate()
    assert agg["param_d"][1] == 20e-9
    peak = agg["pt_peak"]
    assert math.isnan(peak[1]), "失败点必须 NaN"
    assert peak[0] == 10e-9 / 4 and peak[2] == 30e-9 / 4


def test_abort_cancels_rest():
    """on_failure=abort：首失败即取消在途、余点 canceled，终态 failed。"""
    c = _FakeClient(mcr=1, fail_idx={0})   # 串行窗，首点必失败
    h = SweepHandle(c, _base(), _spec([10e-9, 20e-9, 30e-9],
                                      on_failure="abort"))
    with pytest.raises(Exception):
        h.wait(poll=0)
    assert h.state == "canceled"
    assert h.rollup()["canceled"] >= 1


def test_build_aggregate_hand_computed():
    """聚合纯函数逐列手算：2 点 1 轴 + 1 失败点。"""
    points = [{"parameters": {"d": 1.0}}, {"parameters": {"d": 2.0}},
              {"parameters": {"d": 4.0}}]
    digests = [{"peak": 0.25}, None, {"peak": 1.0, "extra": 5}]
    arrays, meta = build_aggregate(points, ["d"], digests)
    assert arrays["param_d"] == [1.0, 2.0, 4.0]
    assert arrays["pt_peak"][:1] + arrays["pt_peak"][2:] == [0.25, 1.0]
    assert math.isnan(arrays["pt_peak"][1])          # NaN != NaN（IEEE）
    assert arrays["pt_extra"][2] == 5.0
    assert all(math.isnan(v) for v in arrays["pt_extra"][:2])
    assert meta["n_result_columns"] == 2
    assert meta["axes"] == {"param_d": "d"}


def test_flatten_numeric_bool_skipped():
    out, skipped = flatten_numeric({"a": 1.5, "b": True, "c": "x",
                                    "n": {"d": 2}})
    assert out == {"a": 1.5, "n.d": 2.0}
    assert skipped == ["b", "c"]
