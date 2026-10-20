"""``genie`` 命令行入口——软件的一键形态（G12/G8，2026-10-13 定案）。

- ``genie studio``：本地拉起整套软件——一个持有 f 的会话（含干活子
  进程 worker）+ 浏览器 GUI；
- ``genie console``：你 shell 里的终端客户端——与 GUI terminal 平等
  的键盘（Jupyter console 语义）。

**拓扑（M2/O1+O3，2026-10-22）：两个进程，一个端口。**

    genie studio
      ① 会话对象与 GUI **同进程**（零 HTTP 跳、零第二个端口）
      ② 模型住在 worker 子进程里（故障域隔离 + 可中断 + 独立 cwd）
      ③ 跨进程客户端（console/外部工具）走 GUI 端口的 ``/session``，
         口令写在门牌 ~/.genie/studio.json；指纹之外一律不认
      ④ 全局唯一网络出口 = 会话（``/gw`` 白名单）

于是：关掉再开 = 一个干净的会话（模型靠快照恢复，不靠进程常驻）；
``--attach URL`` 显式连外部会话（跨机/云端调试，此时 Studio 退化成纯客户端）。
"""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import threading
import webbrowser


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) != 0


def _next_free_port(host: str, start: int) -> int:
    port = start
    while port < start + 50:
        if _port_free(host, port):
            return port
        port += 1
    raise SystemExit(f"端口 {start}~{start + 49} 均被占用——用 --port 指定")


def _start_local_session() -> tuple[object, str, str]:
    """起本地会话（OS 分配端口 + 本机口令）→ (server, url, token)。

    **不做存活探测、不复用**：复用会把上一个后端/上一个凭据的旧会话
    带进来，正是"模型莫名其妙存在/消失"的根源（M2/O1）。
    """
    try:
        from genie.studio.session_service import serve
    except ImportError:  # pragma: no cover —— 指路不裸栈
        raise SystemExit('缺 server extra：pip install "genie[server]"')
    token = secrets.token_urlsafe(24)
    try:
        server, port = serve(0, token=token)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"✗ 本地会话启动失败：{e}")
    return server, f"http://127.0.0.1:{port}", token


def cmd_studio(args: argparse.Namespace) -> int:
    import uvicorn

    from genie.studio import rendezvous as rv
    from genie.studio import session_service as ss
    from genie.studio.server import create_app
    from genie.studio.session_client import SessionClient
    from genie.studio.session_local import LocalSessionHost

    attach = (args.attach or "").rstrip("/")
    gui_port = args.port if args.port else _next_free_port("127.0.0.1", 8777)
    gui_url = f"http://127.0.0.1:{gui_port}"
    require_auth = not (args.open
                        or os.environ.get("GENIE_STUDIO_OPEN") == "1")

    def _on_attach(owner: str, session_id: str) -> None:
        """把"当前活跃会话"记进门牌（console 据此接上同一个模型）。"""
        rv.update(session_id=session_id, owner=owner)

    if attach:
        # 外部会话（跨机/云端调试）：Studio 只是个客户端，不持有会话
        token = os.environ.get("GENIE_SESSION_TOKEN", "")
        host, share = SessionClient(attach, token=token), False
        print(f"· 使用外部会话（{attach}）")
    else:
        # 同进程：会话对象与 GUI 在同一个进程里，**没有 HTTP 跳、没有第二个
        # 端口**（O3）。给跨进程客户端（console）留的门 = /session，带口令。
        token = secrets.token_urlsafe(24)
        ss.set_token(token)
        host, share = LocalSessionHost(), True
        rv.write(url=gui_url + "/session", token=token)
        print(f"· 会话与 GUI 同进程（跨进程客户端见 {gui_url}/session）")

    print(f"· GENIE 启动中 → {gui_url}   （Ctrl-C 退出）")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(gui_url)).daemon = True
        print("  提示：未登录不能做任何操作——先在启动页用账号密码登录"
              "（--open 或 env GENIE_STUDIO_OPEN=1 可退回本机免登录形态）")

    app = create_app(session=host,
                     mount_session=True,
                     share_session=share,
                     require_auth=require_auth,
                     on_attach=_on_attach)
    try:
        uvicorn.run(app, host="127.0.0.1", port=gui_port, log_level="warning")
    finally:
        if share:
            rv.clear()
    return 0


def cmd_console(args: argparse.Namespace) -> int:
    from genie.studio import rendezvous as rv
    from genie.studio.console import run_console
    from genie.studio.session_client import SessionClient

    url = (args.attach or "").rstrip("/")
    token = os.environ.get("GENIE_SESSION_TOKEN", "")
    sid = (args.session or "").strip()
    server = None
    cli = None
    if not url:
        cli = SessionClient.discover()      # 读门牌：GUI 正在用的那个会话
    if cli is None and url:
        cli = SessionClient(url, token=token)
    if cli is not None:
        print(f"· 连接会话（{cli.base_url}）"
              + (f" · session={cli.session_id or 'default'}"))
    else:
        server, url, token = _start_local_session()
        rv.write(url=url, token=token)
        cli = SessionClient(url, token=token)
        print(f"· 本机会话已启动（{url}）")
    try:
        return run_console(
            cli,
            session_id=(sid or cli.session_id or "default"),
            owner=(os.environ.get("GENIE_SCRIPTS_OWNER") or cli.owner
                   or "local"))
    finally:
        if server is not None:
            rv.clear()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="genie", description="GENIE——GPU 电磁仿真软件"
        "（界面+配置器+后处理器；内核在服务端）")
    sub = ap.add_subparsers(dest="cmd")   # 裸敲 genie = studio（一键形态）
    st = sub.add_parser("studio", help="本地拉起整套软件（会话 + GUI）")
    st.add_argument("--no-browser", action="store_true",
                    help="不自动打开浏览器")
    st.add_argument("--port", type=int, default=None,
                    help="GUI 端口（缺省 8777，被占自动顺延）")
    st.add_argument("--attach", default="",
                    help="连一个已在跑的会话（http://host:port），不自己起")
    st.add_argument("--open", action="store_true",
                    help="本机免登录形态（调试用；等价 GENIE_STUDIO_OPEN=1）")
    st.set_defaults(fn=cmd_studio)
    co = sub.add_parser("console", help="shell 里的终端客户端（与 GUI 平等）")
    co.add_argument("--attach", default="",
                    help="连一个已在跑的会话（缺省读本机门牌）")
    co.add_argument("--session", default="",
                    help="会话 id（缺省读门牌里 GUI 正在用的那个）")
    co.set_defaults(fn=cmd_console)
    ns = ap.parse_args(argv)
    if ns.cmd is None:                  # 裸敲 genie = studio（一键形态）
        ns.cmd = "studio"
        ns.fn = cmd_studio
        ns.no_browser = False
        ns.port = None
        ns.attach = ""
        ns.open = False
    return ns.fn(ns)


if __name__ == "__main__":
    raise SystemExit(main())
