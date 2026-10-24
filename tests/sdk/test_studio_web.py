"""网页入口的锁（G80 第 4c 步）：ASGI 直调同一份 `create_app`，不经过网络。

浏览器里唯一多出来的东西就是"请求怎么送进 app"——没有 uvicorn，改用
`web.dispatch()` 直调 ASGI。这条测试在本机就把它钉住：一口 `GET
/api/health` 必须回 200 JSON，且回包内容与 `genie studio` 同源（同一个
`create_app`）。
"""
from __future__ import annotations

import json

from genie.studio import web


def _isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GENIE_STATE_FILE", str(tmp_path / "session_state.json"))
    monkeypatch.setenv("GENIE_RESULT_DIR", str(tmp_path / "genie_results"))
    monkeypatch.setenv("GENIE_STUDIO_OPEN", "1")     # 免登录形态：不起登录闸


def test_dispatch_health_over_asgi(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    app = web.serve()
    status, ctype, body = web.dispatch(app, "GET", "/api/health")
    assert status == 200, (status, body[:200])
    assert "json" in ctype
    data = json.loads(body)
    assert isinstance(data, dict) and data


def test_dispatch_serves_the_gui_shell(tmp_path, monkeypatch):
    """静态壳也由同一个 app 发——网页形态不需要第二个静态服务器。"""
    _isolate(tmp_path, monkeypatch)
    app = web.serve()
    status, ctype, body = web.dispatch(app, "GET", "/")
    assert status == 200
    assert b"<html" in body.lower() or b"<!doctype" in body.lower()


def test_mount_to_js_without_pyodide_returns_api(tmp_path, monkeypatch):
    """本机没有 `js` 模块：挂载函数要原样返回 api（不假装成功）。"""
    _isolate(tmp_path, monkeypatch)
    api = web.mount_to_js()
    assert set(api) >= {"dispatch", "app"}
    payload = json.loads(api["dispatch"]("GET", "/api/health"))
    assert payload["status"] == 200
