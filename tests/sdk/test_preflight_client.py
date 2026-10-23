"""``Client.preflight`` 锚（G78）：需求预检的调用面与降级语义。

三件事：
1. 打的是 ``POST /api/config/preflight``、体是 ``{"cfg": <配置>}``（与
   ``POST /api/jobs`` 同源同形，网关侧决策用的是同一份口径）；
2. 200 → 原样透出 ``demand`` 曲线 + ``grid``，并标 ``available: true``；
3. **老内核 404 → ``{"available": False}``**，不抛异常——调用方要把
   "未知"与"装不下"分开处理（装不下是 422）。
"""
from __future__ import annotations

import json

from genie.net.client import Client


class _Resp:
    def __init__(self, code: int, payload: dict):
        self.status_code = code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _Sess:
    """最小假传输层：记录请求、回一份固定响应。"""

    def __init__(self, code: int, payload: dict):
        self.headers: dict = {}
        self.calls: list = []
        self._r = _Resp(code, payload)

    def request(self, method, url, json=None, timeout=None):  # noqa: A002
        self.calls.append((method, url, json))
        return self._r


def _client(code: int, payload: dict):
    c = Client("http://kernel.test", api_key="k-test")
    c._s = _Sess(code, payload)
    return c


_CFG = {"domain": {"x_range": [-1e-6, 1e-6]}, "run": {"timeout_s": 60}}


def test_preflight_posts_config_and_returns_demand():
    curve = {"1": [7399], "2": [3790, 3788]}
    c = _client(200, {"cap": 2, "caliber": "x", "demand": curve,
                      "grid": {"n_tot": [300, 300, 324], "axes": [[], [], []]}})
    got = c.preflight(_CFG)
    assert got["available"] is True
    assert got["demand"] == curve
    assert got["grid"]["n_tot"] == [300, 300, 324]
    method, url, body = c._s.calls[0]
    assert (method, url) == ("POST", "http://kernel.test/api/config/preflight")
    assert body == {"cfg": _CFG}          # 与 /api/jobs 同源同形


def test_preflight_old_kernel_degrades_to_unavailable():
    """老内核没这个端点 → 404 不当错误，返回 available=False。"""
    c = _client(404, {"detail": "Not Found"})
    assert c.preflight(_CFG) == {"available": False}


def test_preflight_config_error_still_raises():
    """配置被内核拒（422）→ 照旧抛 GenieHTTPError（不是静默降级）。"""
    import pytest

    from genie import GenieHTTPError

    c = _client(422, {"detail": "run.gpu 须为整数"})
    with pytest.raises(GenieHTTPError) as ei:
        c.preflight(_CFG)
    assert ei.value.status == 422
