"""设备授权登录（G72b，RFC 8628 风格）——`genie login` 的机制层。

流程（与网关契约 2026-10-23 定稿一致）::

    POST /api/auth/device            → 201 {device_code, user_code,
                                            verification_url, expires_in, interval}
    POST /api/auth/device/approve    → {user_code, username, password}（或 X-API-Key）
    POST /api/auth/device/token      → 轮询：
        200 pending / 400 slow_down / 200 approved(+token, 单次烧毁)
        403 denied（终态即烧码）→ 其后 410 / 404 无效或过期（合并防枚举，
        含 poll-cap 击杀）

分层：net（IO 层）。密码只在本模块过手一次，**绝不落盘**——config.json
最终只存 token（作为 api_key 走既有优先级链）。
"""
from __future__ import annotations

import time
from typing import Any, Callable

import requests

from ..models.errors import GenieConfigError

Post = Callable[..., requests.Response]


def _default_post(url: str, *, json: dict, timeout: float,
                  headers: dict | None = None) -> requests.Response:
    return requests.post(url, json=json, timeout=timeout, headers=headers)


def _raise_ctx(status: int, detail: Any) -> None:  # pragma: no cover - 辅助
    raise GenieConfigError(f"网关返回 {status}：{detail}")


def create_device(base_url: str, *, post: Post = _default_post,
                  timeout: float = 10.0) -> dict:
    """第一步：创建 pending 授权。返回网关 201 体（含 interval/expires_in）。"""
    r = post(f"{base_url}/api/auth/device", json={}, timeout=timeout)
    if r.status_code == 429:
        raise GenieConfigError("创建设备码被限流（10 次/小时）——稍后再试")
    if r.status_code != 201:
        raise GenieConfigError(f"创建设备码失败（{r.status_code}）：{r.text[:200]}")
    return r.json()


def approve_device(base_url: str, user_code: str, *, username: str,
                   password: str, api_key: str | None = None,
                   post: Post = _default_post,
                   timeout: float = 10.0) -> None:
    """第二步：批准（密码或既有 key 二选一）。401 = 凭据错（泛化防枚举）。"""
    body: dict = {"user_code": user_code, "username": username,
                  "password": password}
    headers = {"X-API-Key": api_key} if api_key else {}
    r = post(f"{base_url}/api/auth/device/approve", json=body, timeout=timeout,
             headers=headers)
    if r.status_code == 401:
        raise GenieConfigError("用户名或密码错误（设备码未被消耗，可重试）")
    if r.status_code == 404:
        raise GenieConfigError("设备码不存在或已过期——重新运行 genie login")
    if r.status_code == 409:
        raise GenieConfigError("该设备码已被处理——重新运行 genie login")
    if r.status_code != 200:
        raise GenieConfigError(f"批准失败（{r.status_code}）：{r.text[:200]}")


def poll_token(base_url: str, device_code: str, *, post: Post = _default_post,
               timeout: float = 10.0) -> tuple[str, dict | None]:
    """轮询一次。返回 ``(state, payload)``：

    ``("pending"|"slow_down", None)`` 继续等；``("approved", {token,…})``
    成功（payload 里的 token 只出现这一次）；终态用
    ``("denied"|"burned"|"gone", None)``——分别对应用户拒绝 / 已被使用
    （含 deny 烧毁后的 410）/ 无效或过期（404 合并防枚举）。
    """
    r = post(f"{base_url}/api/auth/device/token",
             json={"device_code": device_code}, timeout=timeout)
    if r.status_code == 200:
        j = r.json()
        return ("approved", j) if j.get("status") == "approved" else ("pending", None)
    if r.status_code == 400:
        return ("slow_down", None)
    if r.status_code == 403:
        return ("denied", None)
    if r.status_code == 410:
        return ("burned", None)
    if r.status_code == 404:
        return ("gone", None)
    raise GenieConfigError(f"轮询收到意外状态 {r.status_code}：{r.text[:200]}")


def login(base_url: str, *, username: str, password: str,
          sleep: Callable[[float], None] = time.sleep,
          post: Post = _default_post, open_browser: bool = False,
          clock: Callable[[], float] = time.monotonic) -> dict:
    """完整流程：建码 →（可选开浏览器）→ 凭据批准 → 轮询到 token。

    返回 ``{"token", "username", "gateway"}``。轮询严格守 interval、
    slow_down 指数退避、总时长以 expires_in 为上限（对齐网关 15 分钟）。
    ``sleep``/``clock`` 可注入（测试用，不真等）。
    """
    dev = create_device(base_url, post=post)
    interval = max(1.0, float(dev.get("interval") or 2))
    deadline = clock() + max(60.0, float(dev.get("expires_in") or 900))
    if open_browser and dev.get("verification_url"):
        import webbrowser
        webbrowser.open(dev["verification_url"])
    approve_device(base_url, dev["user_code"], username=username,
                   password=password, post=post)
    backoff = interval
    while clock() < deadline:
        state, payload = poll_token(base_url, dev["device_code"], post=post)
        if state == "approved":
            return {"token": payload["token"], "username": payload.get("username", ""),
                    "gateway": base_url}
        if state == "slow_down":
            backoff = min(backoff * 2, 30.0)       # 指数退避，封顶 30s
            sleep(backoff)
            continue
        if state == "pending":
            backoff = interval                     # 恢复正常节拍
            sleep(interval)
            continue
        if state == "denied":
            raise GenieConfigError(
                "设备码被拒绝（另一处输入了 Deny）——重新运行 genie login 可再生成")
        if state == "burned":
            raise GenieConfigError(
                "该设备码已被使用——每个码只发一次 token，请重新运行 genie login")
        raise GenieConfigError(
            "设备码无效或已过期——重新运行 genie login（本机配置未改动）")
    raise GenieConfigError(
        "设备授权超时（超过网关有效期）——重新运行 genie login，这次"
        "批准动作要在有效期内完成")
