"""守卫：run 节单旋钮——没有 `n_steps`，唯一时间定义 = `domain.total_time`。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from genie.models import DomainSpec, RunSpec


def test_runspec_defaults():
    r = RunSpec()
    assert r.gpu is None and r.timeout_s > 0


def test_runspec_gpu_timeout_ok():
    r = RunSpec(gpu=2, timeout_s=600)
    assert r.gpu == 2 and r.timeout_s == 600


def test_runspec_n_steps_retired():
    with pytest.raises(ValidationError):
        RunSpec(n_steps=2000)          # 未知字段（严格模型拒）


def test_domain_total_time_is_required_time_knob():
    with pytest.raises(ValidationError):
        DomainSpec(x_range=(-1e-6, 1e-6), y_range=(-1e-6, 1e-6),
                   z_range=(-1e-6, 1e-6))
    d = DomainSpec(x_range=(-1e-6, 1e-6), y_range=(-1e-6, 1e-6),
                   z_range=(-1e-6, 1e-6), total_time=6e-14)
    assert d.total_time == pytest.approx(6e-14)
