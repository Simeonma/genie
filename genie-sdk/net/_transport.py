"""HTTP 传输缝——唯一一处知道"网络长什么样"的代码。

上层（``net.client``）只认两件事：``request(...)`` 与一个
``TransportError``。本机实现 = requests（socket）；网页实现 = Pyodide 的
fetch（浏览器没有 socket）——见 `LEDGER.md` G80 第 4 步。

**为什么 requests 不能放在模块顶层**：``import requests`` 连带
``socket`` / ``ssl``，浏览器（Pyodide/WASM）里直接 ImportError，于是
``import genie`` 在入口就炸。所以 requests 只在
``RequestsTransport.__init__`` 里按需导入。

``requests.Session`` 的其余表面（``headers`` / ``post`` / ``delete`` /
``close`` …）经 ``__getattr__`` 直通——调用方与测试替身都不用改。
"""
from __future__ import annotations

import sys
from typing import Any


class TransportError(Exception):
    """传输层失败（连不上 / 超时 / 被中断）——不是 HTTP 状态错误。

    ``Client._req`` 把它翻成"网络错误 …（网络瞬断可重试该操作）"；这层
    与具体库无关，所以浏览器实现抛的是同一个异常。
    """


class _FetchResponse:
    """fetch 回包的最小 ``requests.Response`` 替身（只实现调用方用到的）。"""

    def __init__(self, status: int, content: bytes, headers: dict) -> None:
        self.status_code = status
        self.content = content
        self.headers = headers

    def json(self) -> Any:
        import json
        return json.loads(self.content.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


class FetchTransport:
    """网页实现（Pyodide）：浏览器没有 socket，只有 fetch。

    ``pyfetch`` 是 async，而 SDK 的 API 是同步的——用
    ``pyodide.ffi.run_sync`` 在 Worker 里把它同步掉（spike 实测同步 POST
    200 OK，见 LEDGER G80）。``timeout`` 由浏览器 fetch 自己管，这里忽略。
    """

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}

    def request(self, method: str, url: str, **kw: Any) -> _FetchResponse:
        from pyodide.ffi import run_sync          # 只在浏览器里存在
        from pyodide.http import pyfetch

        hdrs = dict(self.headers)
        body = None
        js = kw.get("json")
        data = kw.get("data")
        if js is not None:
            import json
            body = json.dumps(js).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        elif data is not None:
            body = data.encode("utf-8") if isinstance(data, str) else data

        async def _do() -> tuple[int, bytes]:
            r = await pyfetch(url, method=method, headers=hdrs, body=body)
            return r.status, await r.bytes()

        try:
            status, raw = run_sync(_do())
        except Exception as e:                    # noqa: BLE001 —— 归一成缝的异常
            raise TransportError(str(e)) from e
        return _FetchResponse(status, raw, hdrs)

    def __getattr__(self, name: str) -> Any:
        """``get`` / ``post`` / ``delete`` … 直通到 ``request``。"""
        if name in ("get", "post", "put", "delete", "patch"):
            return lambda url, **kw: self.request(name.upper(), url, **kw)
        raise AttributeError(name)


class RequestsTransport:
    """本机实现：requests.Session + 异常归一。"""

    def __init__(self) -> None:
        import requests                     # 延迟：浏览器里没有它
        self._rq = requests
        self._session = requests.Session()

    # ---- 缝的两件事 ----

    def request(self, method: str, url: str, **kw: Any) -> Any:
        try:
            return self._session.request(method, url, **kw)
        except self._rq.RequestException as e:
            raise TransportError(str(e)) from e

    # ---- 其余表面直通（headers / post / delete / close …）----

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):            # 防 __init__ 期自引用递归
            raise AttributeError(name)
        return getattr(self._session, name)


def make_transport() -> Any:
    """按运行环境选实现（**分支在这里，不在调用方**）。

    浏览器（Pyodide/WASM）里 ``sys.platform == "emscripten"``；那里没有
    socket，只能用 fetch。其余环境一律 requests。
    """
    if sys.platform == "emscripten":
        return FetchTransport()
    return RequestsTransport()
