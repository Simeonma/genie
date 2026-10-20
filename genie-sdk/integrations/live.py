"""SDK → Studio 实时通道（v2「外部会话」桥，2026-10）。

定位
----
用户/agent 在任意进程里用 SDK 写仿真脚本（``python my_sim.py``），
正在开着的 Studio 页面**近实时跟着变**。通道里流动的只有**脚本文本**
——GUI 收到后经本地端点 ``/api/preview`` 执行派生模型（Pyodide 已于
2026-10 阶段 ② 退役），连 cfg 都不必传（模型是脚本的投影，不是同伴
负载）。

注意（架构口径）：本通道推进的是 **drafts 环 → preview 派生模型**，
不推进 :8123 会话里的 f——Studio 的 Terminal/表单/工具条编辑走会话
执行层（``/api/exec``），与本桥是两条独立链路。

用法（脚本末尾一行，或任意位置）::

    import genie
    f = genie.connect("http://...")
    ...构建...
    genie.publish(f)          # 推给本机 Studio（默认 127.0.0.1:8777）

机制（best-effort，永不打扰主流程）：
  · ``GENIE_GUI_URL`` 改目标（缺省 ``http://127.0.0.1:8777``）；
  · ``GENIE_GUI_SYNC=0`` 显式关闭；
  · POST /api/drafts ``{label, script}``；任何失败（服务没开/旧服务
    404/网络错）静默吞——镜像面绝不影响真实调用；
  · ``Simulation._submit()`` 入口自动 publish 一次（stage=run）——
    v1 drafts 的肌肉记忆保留：提交作业的瞬间场景先落到 GUI。
    ``_PreviewSim`` 覆写了 ``_submit``，GUI 端预览不会自我回环。

脚本文本来源：``__main__.__file__``（用户屏幕上写的那份）；REPL/
notebook 场景退化为 ``None``（不推）。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

__all__ = ["publish"]

_MAX_SCRIPT = 256 * 1024   # 与服务端 413 上限一致


def _gui_url() -> str | None:
    if os.environ.get("GENIE_GUI_SYNC", "") == "0":
        return None
    return os.environ.get("GENIE_GUI_URL") or "http://127.0.0.1:8777"


def capture_main_script(limit: int = _MAX_SCRIPT) -> str | None:
    """用户主脚本全文（``python my_sim.py`` 场景；REPL 返回 None）。"""
    import sys
    path = getattr(sys.modules.get("__main__"), "__file__", None)
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_file():
            return None
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return None


def _post(url: str, payload: dict) -> bool:
    """传输层（独立函数：测试可注入替身）。失败返回 False，不抛。"""
    try:
        import requests
        r = requests.post(url.rstrip("/") + "/api/drafts", json=payload,
                          timeout=3)
        return r.status_code == 200
    except Exception:  # noqa: BLE001 —— 镜像面：任何失败吞掉
        return False


def publish(f: Any = None, *, label: str = "sdk",
            script: str | None = None) -> bool:
    """把当前脚本推给 Studio（显示同步；best-effort）。

    ``f``：可给的 Simulation（仅用于存在性判断——v2 通道不传 cfg，
    模型由 GUI 端执行脚本派生；参数保留是为了调用语义自然）。
    ``script``：缺省捕获 ``__main__`` 主脚本全文。返回是否投递成功。
    """
    url = _gui_url()
    if url is None:
        return False
    text = script if script is not None else capture_main_script()
    if not text:
        return False
    return _post(url, {"label": label, "script": text})
