"""``genie studio`` 一键拉起的进程级冒烟（G12 第 1 批守门；M2/O1 改写）。

真起子进程（python -m genie studio）→ 轮询就绪 → 四验证：
① GUI health（studio 路由活着、会话报活、upstream 由会话上报）；
② **门牌**能拿到会话地址（O1：端口由 OS 给，不猜不复用）；
③ 会话端口有口令（缺口令 401）；
④ exec → 输出环回流（worker 子进程在真跑代码）。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def studio_proc():
    gui_port = _free_port()
    # 不用 TemporaryDirectory：Windows 下子进程树（studio → session worker）
    # 终止后句柄仍有残余，rmtree 会抛 WinError 32/5（G33）。改成手工建目录
    # + 尽力删除，测试结果不因"临时目录删不掉"而变红。
    td = tempfile.mkdtemp(prefix="genie-cli-test-")
    rv = os.path.join(td, "studio.json")
    env = {**os.environ,
           "GENIE_SCRIPTS_DIR": os.path.join(td, "scripts"),
           "GENIE_SESSION_STATE_DIR": os.path.join(td, "state"),
           "GENIE_RENDEZVOUS": rv}
    # 干净环境：不许从宿主机环境继承"连到某个已有会话"的线索
    for k in ("GENIE_SESSION_URL", "GENIE_SESSION_PORT",
              "GENIE_SESSION_TOKEN"):
        env.pop(k, None)
    p = subprocess.Popen(
        [sys.executable, "-m", "genie", "studio",
         "--no-browser", "--open", "--port", str(gui_port)],
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    base = f"http://127.0.0.1:{gui_port}"
    up = False
    for _ in range(150):                     # ≤15s 等起
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=1) as r:
                if r.status == 200:
                    up = True
                    break
        except Exception:
            time.sleep(0.1)
    if not up:
        p.kill()
        out = p.stdout.read() if p.stdout else ""
        shutil.rmtree(td, ignore_errors=True)
        pytest.fail(f"genie studio 未就绪:\n{out[-2000:]}")
    try:
        yield base, rv
    finally:
        # 只 terminate 父进程在 Windows 会留下子进程占着 scripts/local → 用
        # taskkill /T 整棵树；POSIX 上 terminate 就够。
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           capture_output=True, check=False)
        else:
            p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        shutil.rmtree(td, ignore_errors=True)


def _card(rv_path: str) -> tuple[str, str]:
    """读门牌 → (会话地址, 口令)。O1 的发现机制就是它。"""
    for _ in range(100):
        try:
            with open(rv_path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("url"):
                return d["url"].rstrip("/"), d.get("token", "")
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise AssertionError(f"门牌没写出来：{rv_path}")


def _get(url: str, token: str = ""):
    hdr = {"X-Session-Token": token} if token else {}
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def _post(url: str, body: dict, token: str = ""):
    hdr = {"Content-Type": "application/json"}
    if token:
        hdr["X-Session-Token"] = token
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=hdr, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def test_studio_health_reports_session(studio_proc):
    base, _ = studio_proc
    h = _get(base + "/api/health")
    assert h["ok"] is True and h["service"] == "genie-studio"
    assert h["session"] is True, "Studio 必须知道自己的会话活着"
    assert h["upstream"], "上游地址由会话上报（Studio 不持有后端配置）"


def test_rendezvous_publishes_session(studio_proc):
    """门牌 = 会话地址的**唯一**发现机制（不猜 8123、不复用旧进程）。"""
    _, rv = studio_proc
    url, token = _card(rv)
    assert url.startswith("http://127.0.0.1:")
    assert token, "本机会话端口必须带口令"
    assert _get(url + "/health").get("ok") is True


def test_session_port_requires_token(studio_proc):
    """会话端口不再裸奔：缺口令 401（云宿主未设 GENIE_SESSION_TOKEN 时不校验，
    那条兼容路径由 test_session_service 覆盖）。"""
    _, rv = studio_proc
    url, _ = _card(rv)
    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(url + "/output?owner=local")
    assert ei.value.code == 401


def test_exec_roundtrip(studio_proc):
    _, rv = studio_proc
    url, token = _card(rv)
    _post(url + "/exec", {"code": "print(40 + 2)", "owner": "local"}, token)
    seen = ""
    for _ in range(80):                          # ≤8s 等 done
        out = _get(url + "/output?owner=local&since=0", token)
        seen = "".join(l["text"] for l in out["lines"])
        if out["busy"] is False and "42" in seen:
            break
        time.sleep(0.1)
    assert "42" in seen, f"exec 输出未回流: {seen!r}"


def test_local_session_never_reuses():
    """O1 核心：两次启动 = 两个会话 = 两个端口两个口令。

    旧实现会"探测 :8123 并复用"——复用会把上一个后端/上一个凭据的旧会话
    带进来（模型莫名其妙存在/消失的根源）。这条断言就是防它回来。
    """
    from genie.__main__ import _start_local_session
    s1, u1, t1 = _start_local_session()
    s2, u2, t2 = _start_local_session()
    try:
        assert u1 != u2, "两次启动不得共用一个会话"
        assert t1 and t2 and t1 != t2, "每次启动一个新口令"
    finally:
        s1.should_exit = True
        s2.should_exit = True


def test_session_client_discovers_rendezvous_card(tmp_path, monkeypatch):
    """跨进程客户端的唯一入口：读门牌 → 客户端自带 owner/session_id。

    agent 脚本要接上"人正在看的那个模型"，只需要 ``SessionClient.discover()``
    ——不用猜端口，也不用重抄 owner/session_id。
    """
    from genie.studio import rendezvous as rv
    from genie.studio.session_client import SessionClient

    monkeypatch.setenv("GENIE_RENDEZVOUS", str(tmp_path / "card.json"))
    assert SessionClient.discover() is None, "没门牌就不猜端口（O1）"

    rv.write(url="http://127.0.0.1:9/session", token="t0k",
             session_id="s-7", owner="alice")
    cli = SessionClient.discover()
    assert cli.base_url == "http://127.0.0.1:9/session"
    assert cli.token == "t0k"
    assert (cli.owner, cli.session_id) == ("alice", "s-7"), \
        "门牌要带出身份——否则连上的是别人的空模型"


def test_session_client_owner_required_without_discovery():
    """没有 discover、也没显式给 owner → 422（而不是悄悄写到别的目录）。"""
    from fastapi import HTTPException

    from genie.studio.session_client import SessionClient

    with pytest.raises(HTTPException) as ei:
        SessionClient("http://127.0.0.1:9").patch([{"path": "mesh.dx",
                                                    "value": 1e-8}])
    assert ei.value.status_code == 422
