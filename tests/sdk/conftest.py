"""pytest 全局夹具（tests/sdk）。

`GENIE_STUDIO_OPEN=1` 把本地 Studio 退回"本机免登录"形态：生产默认是
**未登录什么都不给做**（server 模块级 app 带 require_auth=True），而绝大多数
单测直接 `from genie.studio.server import app` 打本地能力接口（preview/
validate/scripts/workspace/drafts），不该为每个用例造登录态。

登录闸本身由 `test_studio_server.py::test_require_auth_*` 用
`create_app(require_auth=True)` 单独覆盖——也就是说：**闸有测试，其余用例
走免登录形态**。必须在 import genie.studio.server 之前设好（conftest 先于
测试模块导入执行）。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("GENIE_STUDIO_OPEN", "1")


@pytest.fixture(autouse=True)
def _reset_session_token(monkeypatch):
    """会话端口口令是**进程级**的（一个进程一个会话，生产如此）。

    测试里 ``serve(token=…)`` 会把它留在模块全局上，污染后续用例的
    ``TestClient(ss.app)``（凭空 401）。每个用例前清空——需要口令的用例
    自己再设。
    """
    import genie.studio.session_service as _ss
    monkeypatch.setattr(_ss, "_TOKEN", "")

