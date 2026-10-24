"""分层契约守卫（G1 定案的常驻执行面，DISCIPLINE §5）。

2026-10-11 core 分层重构定案：分层不是自觉，是测试锁死的产品性质——
违反即本文件红，与 pytest 同跑、无人工步骤。

契约（genie 包内）：

| 层 | 允许依赖 | 禁止 |
|---|---|---|
| models | stdlib / pydantic / genie_protocol（2026-10-27 起为兼容壳，真源=protocol/genie_protocol，独立分发包） | 任何 genie 兄弟层、fdtd |
| core | models / stdlib / numpy（交互与传输能力经组合根 hooks 注入，见 genie/__init__「组合根」） | net / integrations / studio / host / services / fdtd |
| net / integrations | core / models（向下） | studio / host / services / fdtd |
| studio | 整个 genie 包（它是组合层） | host / services / fdtd |
| 任意 | — | fdtd（零内核纪律）、cloud/host/services（反向依赖禁令） |

（2026-10-18 拆包：cloud 已独立于本仓；方向由两侧夹住——本文件守
"genie 不向服务层伸手"，服务仓 `tests/cloud/test_layering.py` 守
"服务层不 import fdtd"。）
判据 = AST 静态扫描（Import/ImportFrom 全量，含函数体内的 lazy import）。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SDK = Path(__file__).resolve().parents[2] / "genie-sdk"   # 目录名；包名仍是 genie

# 层 → 允许的 genie 内兄弟层（None = 不允许任何兄弟层）
_ALLOWED = {
    "models": set(),          # 叶子层
    "core": {"models"},
    "net": {"core", "models"},
    "integrations": {"core", "models", "net"},
    "lib": {"models"},
    "studio": {"core", "models", "net", "integrations", "lib"},
}

# 服务层顶名（genie-service 仓的 cloud/host/services）：genie 包永不得 import
_SERVICE_LAYERS = frozenset({"cloud", "host", "services"})


def _iter_modules():
    """扫描范围 = 库代码。`examples/` 是随包分发的用户脚本，本来就该用
    公开 API（`import genie`），不是分层契约的当事人。"""
    for p in sorted(SDK.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        if "examples" in p.relative_to(SDK).parts:
            continue
        yield p


def _layer_of(dotted: str) -> str | None:
    """genie 内模块点名的顶层层名（genie.core.simulate → core；
    genie 本体 → None（组合根，允许一切）。"""
    parts = dotted.split(".")
    if len(parts) < 2:
        return None
    return parts[1]


def _imports_of(path: Path, pkg_chain: list[str]) -> set[str]:
    """文件全量 import 的顶层目标点名（genie 内部模块记 genie.<层>…，
    外部包记原名；相对 import 按 pkg_chain 解析）。

    包 ``__init__.py`` 的 pkg_chain 已经去掉了文件名，所以 ``level=1``
    指向"自身这个包"，少减一层；普通模块则按 `chain[:-level]`。
    """
    is_pkg = path.name == "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                root = (node.module or "").split(".")[0]
                if node.module:
                    out.add(node.module if node.module.startswith("genie")
                            else root)
                # `from x import y` 无 module（level 0 不存在此形态）
            else:
                cut = node.level - 1 if is_pkg else node.level
                base = pkg_chain[: len(pkg_chain) - cut]
                mod_parts = [m for m in (node.module or "").split(".") if m]
                if mod_parts:
                    out.add(".".join(base + mod_parts))
                else:
                    # `from . import a, b`：真目标是 base.a / base.b，
                    # 不是 base 本身（旧写法把它当成"导入父包"，会误报）。
                    for a in node.names:
                        out.add(".".join(base + [a.name]))
    return out


def _module_chain(path: Path) -> list[str]:
    rel = path.relative_to(SDK.parent)          # genie-sdk/core/simulate.py
    # 目录名 genie-sdk → 包名 genie（下面的判据全按包名说话）
    parts = ["genie"] + list(rel.with_suffix("").parts[1:])
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return parts


@pytest.mark.parametrize("path", _iter_modules(), ids=lambda p: str(p.relative_to(SDK)))
def test_layering_contract(path: Path):
    chain = _module_chain(path)
    mod = ".".join(chain)
    own = _layer_of(mod)
    for target in _imports_of(path, chain):
        if target == "fdtd" or target.startswith("fdtd."):
            pytest.fail(f"{mod}: 零内核纪律——import fdtd 禁止")
        if target.split(".")[0] in _SERVICE_LAYERS:
            pytest.fail(
                f"{mod}: 反向依赖禁令——genie 不得 import {target}（服务层"
                f"在 genie-service 仓；两边只经 HTTP 说话）")
        if not (target == "genie" or target.startswith("genie.")):
            continue                            # 外部依赖（含基础包 genie_protocol）不在分层契约内
        # 组合根 `genie`（包 __init__）不是"无层"，是**最上层**：只有 studio
        # 这个组合层可以直接用它；其余层要用上层能力一律走 hooks 注入
        # （2026-10-21：core/preview 曾 `import genie` 换 connect，被旧判据
        # 的 `layer is None → continue` 静默放过）。
        if target == "genie":
            if own is not None and own != "studio":
                pytest.fail(
                    f"{mod}: 分层契约违规——{own} 层不得 import 组合根 `genie`"
                    f"（能力走组合根 hooks 注入，见 genie/__init__._wire_core_hooks）")
            continue
        layer = _layer_of(target)
        if layer is None or layer == own:
            continue                            # 组合根 / 同层
        allowed = _ALLOWED.get(own)
        if allowed is not None and layer not in allowed:
            pytest.fail(
                f"{mod}: 分层契约违规——{_ALLOWED and own} 层不得依赖 "
                f"{layer} 层（{own} 允许: {sorted(allowed) or '仅外部依赖'}；"
                f"交互/传输能力走组合根 hooks，见 genie/__init__）")


def test_protocol_layer_is_leaf():
    """genie_protocol（protocol/ 子目录，独立分发包 genie-protocol）= 纯叶子：
    零 genie 依赖、零 fdtd/cloud——内核与网关只装它一个也能用（2026-10-27
    拆分定案的新契约面；本守卫防它悄悄长回对 SDK 的依赖）。"""
    PROTO = SDK.parent / "protocol" / "genie_protocol"
    offenders = []
    for p in sorted(PROTO.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    offenders.append((p.name, node.lineno, a.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    offenders.append((p.name, node.lineno, node.module))
    bad = [f"{f}:{ln} -> {t}" for f, ln, t in offenders
           if t.split(".")[0] in ("genie", "fdtd", "cloud", "host", "services")]
    assert not bad, ("genie_protocol 必须零 genie/fdtd/cloud 依赖（它是三方"
                     "共享的协议叶子）：\n" + "\n".join(bad))


def test_low_layers_use_relative_imports():
    """下层（models / core）**不得用绝对 `genie.*` 导入**。

    绝对导入会先导入根包 `genie/__init__`，而那个文件要 import 本层——
    等于把"下层可独立使用"这个性质悄悄废掉（也是隐性循环依赖的来源）。
    上层（studio / `__main__`）本来就是入口，允许绝对导入。
    """
    offenders = []
    for p in _iter_modules():
        rel = p.relative_to(SDK)
        if rel.parts[0] not in ("models", "core"):
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and not n.level \
                    and (n.module or "").startswith("genie."):
                offenders.append(f"{rel}:{n.lineno} from {n.module}")
    assert not offenders, (
        "下层出现绝对 genie 导入（改用相对 `from ..x import y`）：\n"
        + "\n".join(offenders))


def test_composition_root_wires_core():
    """组合根接线完整性：import genie 后 core/model hooks 全部就位
    （缺一 = 某条产品面静默退化为离线态）。"""
    import genie  # noqa: F401
    from genie.core import material, simulate

    for key in ("expert_factory",):
        assert key in simulate.hooks, f"组合根漏接 simulate.hooks[{key!r}]"
    # 2026-10-27 G19b 翻转：material 的 remote_nk_fetch hook 已随材质库
    # 本地化退役（material.hooks 面删除）——此处不再断言。
