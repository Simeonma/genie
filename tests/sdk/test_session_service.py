"""会话唯一家：session_service 壳层契约（kernel 打桩——壳层只测转发与
校验，worker/环行为由 test_kernel_session 锁）。

锁七件事：/exec 校验+attach+转发、/output 透传、/load_config 转发、
code 空校验 422、/stop 转发（A2）、**owner 按人隔离**（B1）、
**session_id 按会话隔离**（O2）+ /gw 白名单与唯一错误翻译。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import genie.studio.kernel_session as kernel_session_module
import genie.studio.session_service as ss


class _FakeKernel:
    def __init__(self):
        self.calls: list[tuple] = []
        self._n = 0

    def attach(self, key=""):
        self.calls.append(("attach", key))
        return {"session_id": "default", "key_changed": bool(key),
                "alive": True}

    def submit(self, code, mode="run", **kw):
        self.calls.append(("submit", code, mode))
        self._n += 1
        return self._n

    def run(self, **kw):
        self.calls.append(("run", kw.get("gpu"), kw.get("timeout_s")))
        self._n += 1
        return self._n

    def patch(self, ops):
        self.calls.append(("patch", ops))
        self._n += 1
        return self._n

    def replace(self, model):
        self.calls.append(("replace", model))
        self._n += 1
        return self._n

    def load_config(self, cfg):
        self.calls.append(("load_config", cfg))

    def ensure(self):
        pass

    def output(self, since=0):
        self.calls.append(("output", since))
        return {"lines": [{"seq": 1, "text": "hi"}], "busy": False,
                "cfg": {"a": 1}, "resolved": None, "cfg_seq": 1}

    def stop(self):
        self.calls.append(("stop",))
        return True


def test_session_service_contract(monkeypatch):
    fake = _FakeKernel()
    monkeypatch.setattr(ss, "get_kernel",
                        lambda owner="user", session_id="default": fake)
    c = TestClient(ss.app)

    # /exec：attach(key) + submit 转发，id 回传（reset 是 mode=build 的旧名）
    r = c.post("/exec", json={"code": "print(1)", "reset": True,
                              "url": "http://gw", "key": "k1"})
    assert r.status_code == 200 and r.json() == {"id": 1}
    assert ("attach", "k1") in fake.calls
    assert ("submit", "print(1)", "build") in fake.calls

    # /run：提交当前模型（不改模型）
    r = c.post("/run", json={"gpu": 2})
    assert r.status_code == 200 and r.json()["id"] >= 1
    assert ("run", 2, None) in fake.calls

    # mode 缺省 = run（终端语义）
    assert c.post("/exec", json={"code": "x = 1"}).status_code == 200
    assert ("submit", "x = 1", "run") in fake.calls

    # /model/patch：路径级增量（空 ops 422）
    r = c.post("/model/patch",
               json={"ops": [{"path": "domain.cfl", "value": 0.5}]})
    assert r.status_code == 200 and r.json()["id"] >= 1
    assert ("patch", [{"path": "domain.cfl", "value": 0.5}]) in fake.calls
    assert c.post("/model/patch", json={"ops": []}).status_code == 422

    # /model/replace：整份替换（空 model 422）
    r = c.post("/model/replace", json={"model": {"domain": {}}})
    assert r.status_code == 200
    assert ("replace", {"domain": {}}) in fake.calls
    assert c.post("/model/replace", json={"model": {}}).status_code == 422

    # /output：透传管理器增量结构
    r = c.get("/output", params={"since": 0})
    assert r.status_code == 200
    assert r.json()["lines"][0]["text"] == "hi"
    assert ("output", 0) in fake.calls

    # /load_config：旧名（整份推送）→ 现在转发到 replace 原语
    r = c.post("/load_config", json={"cfg": {"domain": {}}})
    assert r.json() == {"ok": True}
    assert ("replace", {"domain": {}}) in fake.calls

    # /stop：转发管理器（A2「长任务必须能掐」；即时动作、无 body）
    r = c.post("/stop")
    assert r.status_code == 200 and r.json() == {"stopped": True}
    assert ("stop",) in fake.calls

    # 空 code 422（与客户端契约一致）
    assert c.post("/exec", json={"code": "  "}).status_code == 422


def test_attach_endpoint_and_legacy_bind(monkeypatch):
    """O2：/attach 是正名（幂等换绑），/bind 留一版兼容旧前端。"""
    fake = _FakeKernel()
    monkeypatch.setattr(ss, "get_kernel",
                        lambda owner="user", session_id="default": fake)
    c = TestClient(ss.app)
    r = c.post("/attach", json={"key": "k2", "owner": "u1",
                                "session_id": "s1"})
    assert r.status_code == 200 and r.json()["key_changed"] is True
    assert ("attach", "k2") in fake.calls
    r = c.post("/bind", json={"key": "k3"})
    assert r.status_code == 200
    assert ("attach", "k3") in fake.calls


def test_health_reports_upstream(monkeypatch):
    """health 是 Studio 的 /api/health 的数据源（Studio 不再持有后端配置）。"""
    c = TestClient(ss.app)
    j = c.get("/health").json()
    assert j["ok"] is True and j["service"] == "genie-session"
    assert j["upstream"].startswith("http")


class _OwnerKernel:
    """按 owner 独立计数的最小 kernel 桩（隔离锚用：cfg_seq = 自身
    submit 次数——环互串立刻现形）。"""

    def __init__(self, owner: str = "user", session_id: str = "default"):
        self.owner = owner
        self.session_id = session_id
        self.n = 0

    def attach(self, key=""):
        return {"session_id": self.session_id}

    def submit(self, code, mode="run", label=""):
        self.n += 1
        return self.n

    def run(self, **kw):
        self.n += 1
        return self.n

    def ensure(self):
        pass

    def output(self, since=0):
        return {"lines": [], "busy": False, "cfg": None,
                "resolved": None, "cfg_seq": self.n, "owner": self.owner}


    def stop(self):
        return True


def test_owner_isolation(monkeypatch):
    """B1 按人隔离锚：ownerA/ownerB 各 exec → 各自独立环，互不可见；
    非法 owner（路径穿越形态）422 拒收（owner 会用作目录名）。"""
    monkeypatch.setattr(kernel_session_module, "SessionKernel", _OwnerKernel)
    monkeypatch.setattr(ss, "_kernels", {})          # 注册表清空，从零验
    c = TestClient(ss.app)

    assert c.post("/exec", json={"code": "print('a')",
                                 "owner": "ownerA"}).status_code == 200
    assert c.post("/exec", json={"code": "print('b')",
                                 "owner": "ownerB"}).status_code == 200
    assert set(ss._kernels) == {("ownerA", "default"),       # 一 owner 一实例
                                ("ownerB", "default")}

    outA = c.get("/output", params={"owner": "ownerA"}).json()
    outB = c.get("/output", params={"owner": "ownerB"}).json()
    assert outA["cfg_seq"] == 1 and outB["cfg_seq"] == 1

    # ownerA 再 exec：只推进 ownerA 的环，ownerB 的不动
    c.post("/exec", json={"code": "print('a2')", "owner": "ownerA"})
    assert c.get("/output", params={"owner": "ownerA"}).json()["cfg_seq"] == 2
    assert c.get("/output", params={"owner": "ownerB"}).json()["cfg_seq"] == 1
    # /stop 同样按 owner 路由（互不误伤）
    assert c.post("/stop", params={"owner": "ownerB"}).json() == \
        {"stopped": True}

    # 非法 owner（路径穿越形态）422
    assert c.post("/exec", json={"code": "x",
                                 "owner": "../evil"}).status_code == 422
    assert c.get("/output",
                 params={"owner": "../evil"}).status_code == 422


def test_session_isolation(monkeypatch):
    """O2 按会话隔离锚：同 owner 两个 session_id → 两个 kernel、两套环。

    "重新登录 = 新模型"由此结构性成立（新 session_id = 新目录 = 无快照），
    不再依赖"每次登录签发新 token"这种隐式前提。
    """
    monkeypatch.setattr(kernel_session_module, "SessionKernel", _OwnerKernel)
    monkeypatch.setattr(ss, "_kernels", {})
    c = TestClient(ss.app)
    c.post("/exec", json={"code": "1", "owner": "u", "session_id": "s1"})
    c.post("/exec", json={"code": "2", "owner": "u", "session_id": "s2"})
    assert set(ss._kernels) == {("u", "s1"), ("u", "s2")}
    assert c.get("/output", params={"owner": "u", "session_id": "s1"}
                 ).json()["cfg_seq"] == 1
    assert c.get("/output", params={"owner": "u", "session_id": "s2"}
                 ).json()["cfg_seq"] == 1
    # 非法 session_id（会当目录名）422
    assert c.get("/output", params={"owner": "u",
                                    "session_id": "../x"}).status_code == 422


def test_gateway_whitelist_and_translation(monkeypatch):
    """/gw 是**唯一**网关出口：白名单外的路径 403；上游不可达只有一种措辞。"""
    import requests
    seen = {}

    class _R:
        status_code = 200
        content = b'{"ok": true}'
        headers = {"content-type": "application/json"}

    def fake_request(method, url, data=None, params=None, headers=None,
                     timeout=None):
        seen.update({"method": method, "url": url, "data": data,
                     "params": params, "headers": headers})
        return _R()

    monkeypatch.setattr(requests, "request", fake_request)
    c = TestClient(ss.app)

    r = c.post("/gw/api/auth/login", content=b'{"username":"a"}',
               headers={"X-Upstream-Key": "k1",
                        "Content-Type": "application/json"})
    assert r.status_code == 200
    assert seen["url"].endswith("/api/auth/login")
    assert seen["data"] == b'{"username":"a"}'
    assert seen["headers"] == {"X-API-Key": "k1"}

    # 白名单外 403（不做通用代理）
    assert c.get("/gw/admin/secret").status_code == 403

    # 上游不可达 → 502 + 人话（唯一一份实现，原来在 server.py）
    def boom(*a, **kw):
        raise requests.exceptions.ConnectionError(
            "Max retries exceeded with url: /api/auth/login "
            "(Caused by NewConnectionError(...))")

    monkeypatch.setattr(requests, "request", boom)
    r = c.get("/gw/whoami")
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "上游不可达" in detail and "没有响应" in detail
    assert "Caused by" not in detail, "原始多层括号要截掉，否则更难读"
