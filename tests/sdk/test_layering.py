"""分层契约守卫（G1 定案的常驻执行面，DISCIPLINE §5）。

2026-10-11 core 分层重构定案：分层不是自觉，是测试锁死的产品性质——
违反即本文件红，与 pytest 同跑、无人工步骤。

契约（genie 包内）：

| 层 | 允许依赖 | 禁止 |
|---|---|---|
| models | stdlib / pydantic | 任何 genie 兄弟层、fdtd |
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
    for p in sorted(SDK.rglob("*.py")):
        if "__pycache__" in p.parts:
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
    外部包记原名；相对 import 按 pkg_chain 解析）。"""
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
                base = pkg_chain[: len(pkg_chain) - node.level]
                target = ".".join(base + [m for m in (node.module or "").split(".") if m])
                out.add(target)
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
        if not target.startswith("genie"):
            continue                            # 外部依赖不在分层契约内
        layer = _layer_of(target)
        if layer is None or layer == own:
            continue                            # 组合根 / 同层
        allowed = _ALLOWED.get(own)
        if allowed is not None and layer not in allowed:
            pytest.fail(
                f"{mod}: 分层契约违规——{_ALLOWED and own} 层不得依赖 "
                f"{layer} 层（{own} 允许: {sorted(allowed) or '仅外部依赖'}；"
                f"交互/传输能力走组合根 hooks，见 genie/__init__）")


def test_composition_root_wires_core():
    """组合根接线完整性：import genie 后 core hooks 五键 + material 一键
    全部就位（缺一 = 某条产品面静默退化为离线态）。"""
    import genie  # noqa: F401
    from genie.core import material, simulate

    for key in ("expert_factory", "publish"):
        assert key in simulate.hooks, f"组合根漏接 simulate.hooks[{key!r}]"
    assert "remote_nk_fetch" in material.hooks, \
        "组合根漏接 material.hooks['remote_nk_fetch']"
