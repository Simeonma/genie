"""G61 单位/边界往返不变量：数值槽的边界形态在 写入→配置→校验 全链保值。

GUI 表单的两套换算（writeBackValue/_dispValue）无法在 pytest 里测，
这里锁的是它们共同落点——**模型层**的边界不变量：边界值进 cfg、
cfg 过 SimConfig 校验、load_config 重建后语义不变。GUI 换算若偏离
这些不变量，模型层会先在这里变红。
"""
from __future__ import annotations

import genie
from genie.models import SimConfig


def _sim():
    f = genie.connect("https://x")
    f.domain.x_range = (-2e-6, 2e-6)
    f.domain.y_range = (-1e-6, 1e-6)
    f.domain.z_range = (-1e-6, 1e-6)
    f.domain.total_time = 6e-14
    f.mesh.dx = 50e-9
    f.mat.add_const().name("m").eps(2.1)
    f.geom.add_box().name("base").material("m") \
        .x_range(0, 1e-6).y_range(0, 1e-6).z_range(0, 1e-6)
    f.src.add_soft_source().name("s0").freq(3e14).bandwidth(6e13) \
        .center(0, 0, -5e-7)
    return f


def test_num3_negative_and_zero_center_roundtrip():
    f = _sim()
    f.mon.add_freq().name("p").center(-1.5e-6, 0.0, 7e-7) \
        .field("all").freq(3e14, 1.2e14, 5)
    f.mon.add_time().name("q").center(0, 0, 0).field("Ex")
    cfg = f.to_config()
    m = {m["name"]: m for m in cfg["monitor"]}["p"]
    assert m["center"] == [-1.5e-6, 0.0, 7e-7]        # 负数/零原样保值
    SimConfig.model_validate(cfg)                      # 边界值过校验
    f2 = genie.connect("https://x")
    f2.load_config(cfg)
    assert f2.to_config() == cfg                       # 重建后逐字段一致


def test_size_slot_boundary_semantics_roundtrip():
    """size 槽三形态：None=全域、负数=单格、正数=实际尺寸。"""
    f = _sim()
    f.mon.add_freq().name("full").size(None, None, None) \
        .field("all").freq(3e14, 1.2e14, 5)
    f.mon.add_freq().name("point").size(-1, -1, -1) \
        .field("all").freq(3e14, 1.2e14, 5)
    f.mon.add_freq().name("thin").size(0, 2e-7, 2e-7) \
        .field("all").freq(3e14, 1.2e14, 5)
    cfg = f.to_config()
    ms = {m["name"]: m for m in cfg["monitor"]}
    assert ms["full"]["size"] == [None, None, None]
    assert ms["point"]["size"] == [-1, -1, -1]         # 负数保持负数（单格语义）
    assert ms["thin"]["size"] == [0, 2e-7, 2e-7]       # 0 也是合法边界
    SimConfig.model_validate(cfg)


def test_range_slot_reversal_rejected_consistently():
    f = _sim()
    f.geom.add_box().name("rev").material("m").x_range(1e-6, -1e-6) \
        .y_range(0, 1e-6).z_range(0, 1e-6)
    try:
        SimConfig.model_validate(f.to_config())
        raise AssertionError("reversed range 应被拒")
    except Exception as e:
        assert "x_range" in str(e) or "lo" in str(e).lower() or "hi" in str(e).lower()


def test_expression_slot_string_preserved_end_to_end():
    """表达式串原样上行（求值在服务端）——本地任何一层都不得预解析。"""
    f = _sim()
    f.parameters({"d": 40e-9})
    f.mesh.dx = "d/4"
    f.geom.add_box().name("exp").material("m").x_range(0, "d")
    cfg = f.to_config()
    assert cfg["mesh"]["dx"] == "d/4"
    exp = {g["name"]: g for g in cfg["geometry"]}["exp"]
    assert exp["x_range"] == [0, "d"]                  # 混合 字面量+表达式 槽保值
    f2 = genie.connect("https://x")
    f2.load_config(cfg)
    assert f2.to_config()["mesh"]["dx"] == "d/4"
