"""``genie console`` 终端客户端的进程级守门（G12 终局形态）。

子进程喂 stdin 脚本 → 验证：① exec 输出回流；②多行块整段执行；
③ exit 干净退出且外部会话存活（console 只是客户端，不拥有会话）。

M2/O1 起会话地址不再靠 ``GENIE_SESSION_URL`` 猜：console 读本机门牌
（``GENIE_RENDEZVOUS``）或显式 ``--attach``。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

_REPO = os.path.join(os.path.dirname(__file__), "..", "..")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def console_run():
    with tempfile.TemporaryDirectory(prefix="genie-console-test-") as td:
        env = {**os.environ,
               "GENIE_SCRIPTS_DIR": os.path.join(td, "scripts"),
               # 门牌指向不存在的位置：不许连到开发机上真开着的 Studio
               "GENIE_RENDEZVOUS": os.path.join(td, "absent.json")}
        for k in ("GENIE_SESSION_URL", "GENIE_SESSION_PORT",
                  "GENIE_SESSION_TOKEN"):
            env.pop(k, None)

        def _run(feed: str, timeout: float = 60, extra: list | None = None,
                 env_extra: dict | None = None) -> str:
            p = subprocess.run(
                [sys.executable, "-m", "genie", "console"] + (extra or []),
                cwd=_REPO, env={**env, **(env_extra or {})}, input=feed,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout)
            assert p.returncode == 0, p.stderr[-1500:]
            return p.stdout

        yield _run


def test_console_exec_and_exit(console_run):
    out = console_run("print(6 * 7)\nexit\n")
    assert "42" in out


def test_console_multiline_block(console_run):
    feed = ("def sq(x):\n    return x * x\n\n"   # 空行闭合块
            "print(sq(9))\n"
            "exit\n")
    out = console_run(feed)
    assert "81" in out


def test_console_client_only_leaves_external_session_alive(tmp_path):
    """连外部 session 的 console 是纯客户端：退出不杀会话。"""
    import json
    sess_port = _free_port()
    env = {**os.environ,
           "GENIE_SCRIPTS_DIR": str(tmp_path / "scripts"),
           "GENIE_RENDEZVOUS": str(tmp_path / "absent.json")}
    for k in ("GENIE_SESSION_URL", "GENIE_SESSION_PORT",
              "GENIE_SESSION_TOKEN"):
        env.pop(k, None)
    srv = subprocess.Popen(
        [sys.executable, "-c",
         f"import uvicorn; from genie.studio.session_service import app; "
         f"uvicorn.run(app, host='127.0.0.1', port={sess_port})"],
        cwd=_REPO, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{sess_port}"
    try:
        for _ in range(100):              # 等服务就绪 ≤10s
            try:
                urllib.request.urlopen(
                    base + "/output?owner=local", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        p = subprocess.run(
            [sys.executable, "-m", "genie", "console", "--attach", base],
            cwd=_REPO, env=env, input="print('bye')\nexit\n",
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60)
        assert p.returncode == 0 and "bye" in p.stdout
        # console 退出，外部 session 仍活且可继续 exec
        req = urllib.request.Request(
            base + "/exec",
            data=json.dumps({"code": "print(7 * 3)",
                             "owner": "local"}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
        time.sleep(2)
        with urllib.request.urlopen(
                base + "/output?owner=local&since=0", timeout=5) as r:
            body = r.read().decode()
        assert "21" in body
    finally:
        srv.terminate()
