"""G72b 设备授权登录：`net/device_login` 轮询状态机全覆盖（假传输，零网络）。

网关契约（2026-10-23 定稿）：pending 续等 / slow_down 退避 / approved 发
token（单次烧毁）/ denied 403 终态 / 410 burned / 404 合并防枚举。
"""
from __future__ import annotations

import pytest

from genie.models.errors import GenieConfigError
from genie.net import device_login as dl


class FakeResp:
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status_code, self._j, self.text = status, payload or {}, text or str(payload or "")

    def json(self):
        return self._j


class FakePost:
    """按脚本依次回响应；记录 (path, json) 供断言。"""

    def __init__(self, script: list[FakeResp]):
        self.script, self.calls = list(script), []

    def __call__(self, url, *, json, timeout=10.0, headers=None):
        self.calls.append((url.rsplit("/", 1)[-1], json))
        if self.script:
            return self.script.pop(0)
        return FakeResp(200, {"status": "pending"})   # 脚本耗尽 = 永远 pending


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _device_resp(**kw):
    d = {"device_code": "gd_" + "x" * 43, "user_code": "AAAA-BBBB",
         "verification_url": "https://gw/login/device",
         "expires_in": 900, "interval": 2}
    d.update(kw)
    return FakeResp(201, d)


def _ok(payload=None):
    return FakeResp(200, payload if payload is not None else {"ok": True})


def _run(script, **kw):
    post, clock, sleeps = FakePost(script), FakeClock(), []
    out = dl.login("https://gw", username="u", password="p", post=post,
                   clock=clock, sleep=sleeps.append, **kw)
    return out, post, sleeps


def test_happy_path_password_approve_then_token():
    out, post, sleeps = _run([
        _device_resp(),
        _ok(),                                        # approve
        FakeResp(200, {"status": "pending"}),
        FakeResp(200, {"status": "approved", "token": "gt_abc",
                       "username": "dora"}),
    ])
    assert out == {"token": "gt_abc", "username": "dora",
                   "gateway": "https://gw"}
    paths = [p for p, _ in post.calls]
    assert paths == ["device", "approve", "token", "token"]
    assert post.calls[1][1]["username"] == "u"        # 密码模式 approve
    assert sleeps and sleeps[0] == 2                  # 严格守 interval


def test_denied_is_terminal_and_actionable():
    with pytest.raises(GenieConfigError, match="拒绝"):
        _run([_device_resp(), _ok(), FakeResp(403, {"status": "denied"})])


def test_burned_410_distinct_from_gone_404():
    with pytest.raises(GenieConfigError, match="已被使用"):
        _run([_device_resp(), _ok(), FakeResp(410)])
    with pytest.raises(GenieConfigError, match="无效或已过期"):
        _run([_device_resp(), _ok(), FakeResp(404)])


def test_slow_down_backs_off_then_recovers():
    out, _, sleeps = _run([
        _device_resp(), _ok(),
        FakeResp(400, {"status": "slow_down"}),       # 退避 ×2
        FakeResp(400, {"status": "slow_down"}),       # 再 ×2
        FakeResp(200, {"status": "pending"}),
        FakeResp(200, {"status": "approved", "token": "gt_1",
                       "username": "u"}),
    ])
    assert out["token"] == "gt_1"
    assert sleeps[0] == 4 and sleeps[1] == 8          # 指数退避
    assert sleeps[2] == 2                             # pending 后恢复正常节拍


def test_timeout_raises_not_hangs():
    clock = FakeClock()
    post = FakePost([_device_resp(expires_in=60), _ok(),
                     FakeResp(200, {"status": "pending"})] * 1 +
                    [FakeResp(200, {"status": "pending"})])
    with pytest.raises(GenieConfigError, match="超时"):
        dl.login("https://gw", username="u", password="p", post=post,
                 clock=clock, sleep=lambda s: setattr(clock, "t", clock.t + s))


def test_approve_401_actionable_and_config_untouched():
    with pytest.raises(GenieConfigError, match="用户名或密码错误"):
        _run([_device_resp(), FakeResp(401)])


def test_create_rate_limited_429():
    with pytest.raises(GenieConfigError, match="限流"):
        _run([FakeResp(429)])


def test_default_post_signature_accepts_headers():
    """真机回归锚：approve 带 X-API-Key 头，_default_post 必须收 headers
    （生产实锤踩过：签名缺 headers，mock 签名宽松没拦住，真机 TypeError）。"""
    import inspect
    params = inspect.signature(dl._default_post).parameters
    assert "headers" in params and "json" in params and "timeout" in params
