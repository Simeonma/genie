"""守卫：`RunSpec.gpu` 上限 4——本机 v2 只许租 4 张；物理面另有 kernel
单元用 CUDA_VISIBLE_DEVICES=4,5,6,7 兜底，此处锁的是**提交边界早拒**
（不让 gpu=5+ 走到内核才失败）。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from genie.models import RunSpec


@pytest.mark.parametrize("ok_gpu", [1, 4])
def test_gpu_within_cap_accepted(ok_gpu):
    assert RunSpec(gpu=ok_gpu).gpu == ok_gpu


def test_runspec_default_single_gpu():
    assert RunSpec().gpu is None


@pytest.mark.parametrize("bad_gpu", [0, 5, 8])
def test_gpu_beyond_cap_rejected(bad_gpu):
    with pytest.raises(ValidationError):
        RunSpec(gpu=bad_gpu)
