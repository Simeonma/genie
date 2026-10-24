"""传输缝的锁（G80 第 1 步 + 第 4 步的本机侧）。

不装浏览器也能验的只有两件事：**分支按平台选实现**、**本机实现原样可用**。
真正的 fetch 路径由工作区 `shots/spike/` 在真 Chromium 里验（11/11 通过，
含 `run_sync(pyfetch)` 的同步 POST 打到一个真服务端）。
"""
from __future__ import annotations

import pytest

from genie.net import _transport as T


def test_default_is_requests_with_real_session():
    t = T.make_transport()
    try:
        assert isinstance(t, T.RequestsTransport)
        t.headers["X-Test"] = "1"
        assert t.headers["X-Test"] == "1"      # headers 是 Session 的（直通）
    finally:
        t.close()


def test_emscripten_selects_fetch(monkeypatch):
    """浏览器里必须选 fetch（socket 不存在）——分支在 make_transport 内部。"""
    monkeypatch.setattr(T.sys, "platform", "emscripten")
    assert isinstance(T.make_transport(), T.FetchTransport)


def test_no_requests_import_at_module_level():
    """模块顶层不得出现 requests 的导入（否则 `import genie` 在 WASM 里炸）。"""
    import ast
    import pathlib

    src = pathlib.Path(T.__file__).read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Import):
            assert all(a.name != "requests" for a in node.names), node.lineno
        if isinstance(node, ast.ImportFrom):
            assert node.module != "requests", node.lineno


def test_fetch_transport_verbs_and_unknown_attr():
    """fetch 实现在没有 pyodide 的环境里也能构造（pyodide 只在 request 时导入）。"""
    t = T.FetchTransport()
    assert callable(t.get) and callable(t.post) and callable(t.delete)
    with pytest.raises(AttributeError):
        t.nonexistent
