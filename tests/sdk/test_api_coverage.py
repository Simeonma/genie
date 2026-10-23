"""G70 网关路由对账锁：docs/HTTP_API.md 端点表 ↔ 服务仓实际路由双向核对。

只在私有工作区跑（需要 docs/HTTP_API.md 与 ../genie-service-live 两者；
公开仓两者皆无 → 自动 skip。表只在私有工作区被编辑，锁守的就是这里）。

分类契约（与 HTTP_API.md 表尾声明一致）：
- **网关显式路由** = 服务仓 `cloud/services/api.py` 的 @app.xxx 装饰器，
  必须与表**双向逐条**一致（方法+路径）；
- **内核代理面** = /api/jobs/*、/api/config/preflight（G78 需求预检；网格事实并入其 grid）——
  网关用 `/api/{path:path}` 全量代理到内核（锁断言该 catch-all 存在）；
- **宿主面豁免** = /api/drafts（Studio/宿主路由，不落在网关）；
- `/api/sweeps` 族已退役（G29b）：网关显式路由里不得再出现。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "HTTP_API.md"      # 曾把两段相邻字符串当路径拼接 → 锁永远 skip
SVC = ROOT.parent / "genie-service-live" / "cloud" / "services" / "api.py"

# 表中"内核代理面"的路径前缀 / 精确路径；"宿主面"豁免集
_KERNEL_PREFIXES = ("/api/jobs",)
# 内核**真实**有、且经 /api/{path} 代理过去的端点（2026-10-25 核对：
# 内核再无 /api/tools/* 与 /api/examples；网格预览并入 config/preflight）
_KERNEL_EXACT = {("POST", "/api/config/preflight")}
_HOST_SIDE = {("POST", "/api/drafts")}
_RETIRED_PREFIX = "/api/sweeps"

pytestmark = pytest.mark.skipif(
    not (DOC.is_file() and SVC.is_file()),
    reason="对账锁只在私有工作区跑（需 docs/HTTP_API.md + genie-service-live）")


def _norm(path: str) -> str:
    """路径模板归一：/api/auth/tokens/{tid} 与 {id} 是同一个端点。"""
    return re.sub(r"\{[^}]+\}", "{}", path.strip())


def _table_rows() -> set[tuple[str, str]]:
    """表行 → {(方法, 路径)}；一行里可以有多个 `METHOD /path`（如 expert 那行）。"""
    rows = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.count("|") < 2:
            continue
        first_cell = line.split("|")[1]        # 只认行首那格：正文提到退役端点不算
        for methods, path in re.findall(
                r"`([A-Z]+(?:/[A-Z]+)*)\s+(/[^`|]+)`", first_cell):
            for meth in methods.split("/"):
                rows.add((meth.strip(), _norm(path)))
    return rows


def _gateway_routes() -> tuple[set[tuple[str, str]], bool]:
    """api.py 显式路由 + 全量代理 catch-all 是否存在。"""
    src = SVC.read_text(encoding="utf-8")
    # 方法名归一到大写：文档表写 `GET`，装饰器抓到的是 `get`——不归一会全表失配
    routes = {(m.upper(), _norm(path)) for m, path in re.findall(
        r'@app\.(get|post|delete|put)\("([^"]+)"', src)}
    has_catchall = '"/api/{path:path}"' in src
    return routes, has_catchall


def test_gateway_explicit_routes_match_table_both_ways():
    table = _table_rows()
    gw, has_catchall = _gateway_routes()
    assert has_catchall, "网关必须保有 /api/{path} 全量代理（内核面的通道）"
    # 内核代理/宿主豁免之外的表行 = 应落在网关显式路由上
    table_gw = {r for r in table
                if r not in _HOST_SIDE
                and r not in _KERNEL_EXACT
                and not r[1].startswith(_KERNEL_PREFIXES)}
    missing_in_table = gw - table_gw
    missing_in_gateway = table_gw - gw
    assert not missing_in_table, (
        f"网关有路由不在 HTTP_API 表里（补行或裁决豁免）：{sorted(missing_in_table)}")
    assert not missing_in_gateway, (
        f"表里有网关不存在的路由（改正或删行）：{sorted(missing_in_gateway)}")


def test_retired_sweeps_family_gone_from_gateway():
    gw, _ = _gateway_routes()
    assert not [p for _, p in gw if p.startswith(_RETIRED_PREFIX)], (
        "/api/sweeps 族应已从网关退役（G29b）")


def test_kernel_proxied_rows_present_and_classified():
    """代理面行必须在表里且分类合法（防有人把 jobs 行误标/误删）。"""
    table = _table_rows()
    for r in _KERNEL_EXACT:
        assert r in table, f"内核代理端点 {r} 应在表中"
    jobs_rows = {r for r in table if r[1].startswith(_KERNEL_PREFIXES)}
    assert len(jobs_rows) >= 10, "jobs 族端点行不应被整段误删"
