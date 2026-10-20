"""``python -m genie.studio`` — 只起 Studio 网页门（不自己起会话）。

用法::

    python -m genie.studio [port]        # 缺省 8777，绑定 127.0.0.1

**推荐入口是 ``genie studio``**：它自己起会话（OS 分配端口 + 本机口令）并把
地址显式注入工厂。本模块是传统形态——会话地址从 ``GENIE_SESSION_URL``
（缺省 127.0.0.1:8123）取；没有会话服务时界面能开但所有执行类接口会报
"会话服务不可达"（诚实的失败，不是假装能跑）。

需要 server extra（fastapi/uvicorn）：``pip install "genie[server]"``。
"""
from __future__ import annotations

import sys


def main() -> None:
    try:
        import uvicorn
    except ImportError:  # pragma: no cover —— 指路不裸栈
        sys.exit("缺 uvicorn——本地 Studio 需要 server extra："
                 'pip install "genie[server]"')
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
    uvicorn.run("genie.studio.server:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
