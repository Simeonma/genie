"""单一来源锁（DISCIPLINE §5：「X 与 Y 一致」类宣言必须有直接测试）。

锁四件事，任何一件回退（重新本地手抄）即红：

1. 线格式常量单一来源：script/builder 模块里的 FACES/BC_KINDS
   **就是** models._wire 的对象（import 而非复制）；
2. from_library 拟合默认值四处同源：LibraryMatSpec 字段默认 ==
   material.fit_nk 签名默认 == builder.add_from_library 签名默认 ==
   script 省略判据所用的 LIBRARY_FIT_DEFAULTS；
3. polygon 哨兵归一单一实现：builder 的 vertices 归一 ==
   models.norm_vertices_pairs（G2 起委托调用）；
4. polarization 归一跨层同义：script._norm_pol（渲染侧，宽容）对
   合法输入与 models._norm_polarization（线格式侧，严格）结果相等。
"""
from __future__ import annotations

import inspect
import math

import genie.core.builder as builder_mod
import genie.core.script as script_mod
from genie.core import material as material_mod
from genie.models import FACES, LIBRARY_FIT_DEFAULTS, _wire
from genie.models._wire import LibraryMatSpec


def test_constants_single_source():
    assert script_mod.FACES is FACES
    assert builder_mod.FACES is FACES
    assert script_mod.BC_KINDS is _wire.BC_KINDS
    assert builder_mod.BOUNDARY_KINDS is _wire.BC_KINDS


def test_library_fit_defaults_single_source():
    d = LIBRARY_FIT_DEFAULTS
    # ① 线格式字段默认
    fields = LibraryMatSpec.model_fields
    assert fields["fit_range"].default == d["fit_range"]
    assert fields["n_drude"].default == d["n_drude"]
    assert fields["n_lorentz"].default == d["n_lorentz"]
    assert fields["maxfev"].default == d["maxfev"]
    # ②③ 函数签名默认（material.fit_nk / builder.add_from_library）
    for fn in (material_mod.fit_nk, builder_mod.Materials.add_from_library):
        sig = inspect.signature(fn)
        for k, v in d.items():
            assert sig.parameters[k].default == v, f"{fn.__name__}({k}) 默认漂移"


def test_vertices_sentinel_single_implementation():
    from genie.models import norm_vertices_pairs

    # builder 的 vertices 分支必须委托正典（而非内联再写一遍）
    chain_src = _chain_src()
    assert "norm_vertices_pairs" in chain_src, \
        "builder vertices 分支应委托 models.norm_vertices_pairs"
    # 行为等价：哨兵对两种入态归一一致（nan != nan，按位置判哨兵）
    out = norm_vertices_pairs([(None, None), (1, 2)])
    assert len(out) == 2
    sx, sy = out[0]
    assert sx != sx and sy != sy, "JSON [null, null] 应归一为 (nan, nan)"
    assert out[1] == (1.0, 2.0)


def _chain_src() -> str:
    return inspect.getsource(builder_mod._Chain)


def test_polarization_norm_cross_layer_agreement():
    """渲染侧 _norm_pol（宽容、非法返回 None）对合法输入与线格式侧
    _norm_polarization（严格、非法抛错）结果相等——同一语义、两种
    错误策略（DISCIPLINE §5 三诊的「设计权衡」定案）。"""
    wire = _wire._norm_polarization
    for v in ([1, 0, 0], [0.5, -1, 2],
              [[1, 0], [0, 0], [0, 0]], [[0, -1], [1, 0], [0, 0]]):
        assert script_mod._norm_pol(v) == [[float(p[0]), float(p[1])]
                                           for p in wire(v)]
