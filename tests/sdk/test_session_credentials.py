"""G72 ①②：会话代持凭据 + connect 双轨。

覆盖：代拨注入（调用方无凭据 → 会话持有的 token 代发）、登录截获
（gateway_forward 单一咽喉点）、迁移（config.json → credentials.json）、
裸 connect 的会话轨/指路错误/直连回退。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import genie
from genie.models.errors import GenieConfigError
from genie.net import config as ncfg
from genie.studio import session_service as ss


class _Resp:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._p = payload
        self.content = content or json.dumps(payload or {}).encode()
        self.headers = {}

    def json(self):
        return self._p if self._p is not None else json.loads(self.content)


@pytest.fixture()
def fake_rq(monkeypatch):
    """截获 gateway_forward 内部的 requests.request 调用。"""
    import requests
    calls: list[dict] = []

    def _fake(method, url, **kw):
        calls.append({"method": method, "url": url, **kw})
        return _Resp()

    monkeypatch.setattr(requests, "request", _fake)
    return calls


# ── 代拨注入 ────────────────────────────────────────────────────────

def test_gateway_forward_injects_stored_cred(fake_rq, monkeypatch):
    monkeypatch.setattr(ss, "_CRED",
                        {"api_key": "gt_stored", "username": "dora"})
    ss.gateway_forward("GET", "api/jobs")
    h = fake_rq[0]["headers"]
    assert h["X-API-Key"] == "gt_stored" and h["X-Username"] == "dora"


def test_caller_key_wins_over_stored(fake_rq, monkeypatch):
    monkeypatch.setattr(ss, "_CRED", {"api_key": "gt_stored"})
    ss.gateway_forward("GET", "api/jobs", key="gt_caller")
    assert fake_rq[0]["headers"]["X-API-Key"] == "gt_caller"


def test_no_cred_no_header(fake_rq, monkeypatch):
    monkeypatch.setattr(ss, "_CRED", {})
    ss.gateway_forward("GET", "api/health")
    assert not fake_rq[0]["headers"]


# ── 登录截获（单一咽喉点）──────────────────────────────────────────

def test_login_success_captured(fake_rq, monkeypatch):
    import requests
    monkeypatch.setattr(
        requests, "request",
        lambda *a, **k: _Resp(payload={"token": "gt_new"}))
    ss.gateway_forward(
        "POST", "api/auth/login",
        data=json.dumps({"username": "dora", "password": "x"}).encode())
    cfg = ncfg.load_config()
    assert cfg["api_key"] == "gt_new" and cfg["username"] == "dora"
    assert ss._CRED == {"api_key": "gt_new", "username": "dora"}


def test_login_failure_not_captured(fake_rq, monkeypatch):
    import requests
    monkeypatch.setattr(
        requests, "request",
        lambda *a, **k: _Resp(status=401, payload={"detail": "bad"}))
    ss.gateway_forward(
        "POST", "api/auth/login",
        data=json.dumps({"username": "dora", "password": "x"}).encode())
    assert "api_key" not in ncfg.load_config()


def test_capture_bad_payload_never_crashes(monkeypatch):
    import requests
    monkeypatch.setattr(
        requests, "request",
        lambda *a, **k: _Resp(content=b"not-json"))
    ss.gateway_forward("POST", "api/auth/login", data=b"\xff\xfe")
    assert ss._CRED is None or "api_key" not in (ss._CRED or {})


# ── 迁移：config.json → credentials.json ───────────────────────────

def test_old_config_adopted_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(ncfg, "_store_dir", lambda: tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps({"gateway": "https://gw", "api_key": "k"}), encoding="utf-8")
    p = ncfg.config_path()
    assert p.name == "credentials.json" and p.exists()
    assert not (tmp_path / "config.json").exists()
    assert ncfg.load_config()["gateway"] == "https://gw"


# ── connect 双轨 ───────────────────────────────────────────────────

def test_bare_connect_via_alive_session_card(tmp_path, monkeypatch):
    from genie.studio import rendezvous as rv
    rv_path = tmp_path / "rv.json"
    monkeypatch.setenv("GENIE_RENDEZVOUS", str(rv_path))
    rv.write(url="http://127.0.0.1:9999/session", token="door-token")
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: _Resp())   # _alive → 200
    s = genie.connect()
    assert s._client.base_url == "http://127.0.0.1:9999/session/gw"
    assert s._client._s.headers["X-Session-Token"] == "door-token"
    # 零凭据：会话轨的 Client 不带任何网关 key
    assert "X-API-Key" not in s._client._s.headers


def test_bare_connect_no_credentials_actionable(monkeypatch):
    monkeypatch.setenv("GENIE_SESSION_AUTOSTART", "1")
    monkeypatch.delenv("GENIE_API_KEY", raising=False)
    with pytest.raises(GenieConfigError, match="genie login"):
        genie.connect()


def test_bare_connect_autostart_off_falls_direct(monkeypatch):
    monkeypatch.setenv("GENIE_SESSION_AUTOSTART", "0")
    ncfg.save_config(gateway="https://cfg-gw")
    s = genie.connect()
    assert s._client.base_url == "https://cfg-gw"


def test_client_sends_upstream_timeout_header(monkeypatch):
    import requests
    seen = {}

    def _fake(self, method, url, **kw):
        seen.update(self.headers)
        return _Resp()

    monkeypatch.setattr(requests.Session, "request", _fake)
    from genie.net.client import Client
    Client("https://gw", timeout=7)._req("GET", "/api/health")
    assert seen["X-Upstream-Timeout"] == "7.0" or seen["X-Upstream-Timeout"] == "7"
