"""单一来源锁（DISCIPLINE §5：「X 与 Y 一致」类宣言必须有直接测试）。

锁五件事，任何一件回退（重新本地手抄 / 尾部再写一遍）即红：

1. 线格式常量单一来源：script/builder 模块里的 FACES/BC_KINDS
   **就是** models._wire 的对象（import 而非复制）；
2. from_library 拟合默认值四处同源：LibraryMatSpec 字段默认 ==
   material.fit_nk 签名默认 == builder.add_from_library 签名默认 ==
   script 省略判据所用的 LIBRARY_FIT_DEFAULTS；
3. polygon 哨兵归一单一实现：builder 的 vertices 归一 ==
   models.norm_vertices_pairs（G2 起委托调用）；
4. polarization 归一跨层同义：script._norm_pol（渲染侧，宽容）对
   合法输入与 models._norm_polarization（线格式侧，严格）结果相等；
5. `studio/static/style.css` 的两条样式纪律（G73 收口后立的闸）：
   ① 同一 `@media` 上下文里，同一选择器的同一属性**只有一条声明**——
      否则就是"尾部再统一一遍"把前面那条静默吃掉（历史病灶）；
   ② 同一选择器自己的**单选择器块至多一个**——一个控件的外观只在一处说。
      逗号组（一条规则管多个控件）不算，那是横切层，允许一个选择器被
      多条横切规则捎带。
"""
from __future__ import annotations

import inspect
import math
import re
from collections import Counter
from pathlib import Path

import genie
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


# ---- 5. style.css 的两条样式纪律（G73 收口后立的闸）----------------------

def _style_css() -> str:
    return (Path(genie.__file__).resolve().parent
            / "studio" / "static" / "style.css").read_text(encoding="utf-8")


def _css_rules(text: str):
    """极简解析：只认「选择器 + { 声明 }」与 @media 嵌套。

    返回 [(上下文, 选择器列表, 属性列表, 行号)]。注释先抹成等长空白，
    于是行号可直接由偏移算出。不做 CSS 规范级别的解析——这文件里没有
    字符串里带分号的花招，够用即止。
    """
    clean = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                   text, flags=re.S)
    rules, i, n, stack = [], 0, len(clean), []
    while i < n:
        if clean[i] in " \t\n":
            i += 1
            continue
        if clean[i] == "}":
            if stack:
                stack.pop()
            i += 1
            continue
        j = clean.find("{", i)
        if j == -1:
            break
        head = clean[i:j].strip()
        if head.startswith("@"):
            stack.append(head)
            i = j + 1
            continue
        depth, k = 1, j + 1
        while k < n and depth:
            if clean[k] == "{":
                depth += 1
            elif clean[k] == "}":
                depth -= 1
            k += 1
        sels = [" ".join(s.split()) for s in head.split(",") if s.strip()]
        props = [p.split(":", 1)[0].strip().lower()
                 for p in clean[j + 1:k - 1].split(";") if ":" in p]
        rules.append((tuple(stack), sels, props, clean.count("\n", 0, i) + 1))
        i = k
    return rules


def test_css_no_shadowed_declaration():
    """① 同一上下文 + 同一选择器 + 同一属性只准一条声明。

    两条就是"后者把前者静默吃掉"：地图上写着 110px，浏览器用的是 500px。
    G73 之前这里攒了 147 条这样的死声明（含 ≤1359 三份列宽值），全部由
    人工扫出；这条闸让"再长出来"当场变红。
    """
    seen = {}
    bad = []
    for ctx, sels, props, line in _css_rules(_style_css()):
        for sel in sels:
            for p in props:
                key = (ctx, sel, p)
                if key in seen:
                    bad.append(f"  {sel}  {{{p}}}  行 {seen[key]} 与 {line}"
                               + (f"  [{ctx[-1][:40]}]" if ctx else ""))
                else:
                    seen[key] = line
    assert not bad, (
        "同一选择器的同一属性出现多次（后一条会把前一条静默覆盖）：\n"
        + "\n".join(bad[:20]))


def test_css_one_block_per_selector():
    """② 一个选择器的**单选择器块**至多一个。

    同一控件被拆到多处（基础一块、文件尾"统一节"再补一块）就是 G73 的
    病灶来源：读者要跨 1900 行拼出真实外观，且新加一轮"统一"只会再叠一层。
    逗号组是横切层（`input, textarea, code { … }` 一条管很多控件），
    不在此列——它与"一个控件被拆散"是相反方向。
    """
    singles = Counter()
    lines = {}
    for ctx, sels, props, line in _css_rules(_style_css()):
        if len(sels) != 1:
            continue
        singles[(ctx, sels[0])] += 1
        lines.setdefault((ctx, sels[0]), []).append(line)
    bad = [f"  {k[1]}  行 {lines[k]}"
           for k, v in singles.items() if v > 1]
    assert not bad, ("同一选择器有多个自己的块（应折成一块，横切用逗号组）：\n"
                     + "\n".join(bad[:20]))
