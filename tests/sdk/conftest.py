"""pytest 全局夹具（tests/sdk）。

`GENIE_STUDIO_OPEN=1` 把本地 Studio 退回"本机免登录"形态：生产默认是
**未登录什么都不给做**（server 模块级 app 带 require_auth=True），而绝大多数
单测直接 `from genie.studio.server import app` 打本地能力接口（preview/
validate/scripts/workspace/drafts），不该为每个用例造登录态。

登录闸本身由 `test_studio_server.py::test_require_auth_*` 用
`create_app(require_auth=True)` 单独覆盖——也就是说：**闸有测试，其余用例
走免登录形态**。必须在 import genie.studio.server 之前设好（conftest 先于
测试模块导入执行）。

G72 会话代持轨的三条隔离（同样 import 前设好）：

- ``GENIE_SESSION_AUTOSTART=0``：裸 ``connect()`` 不许在测试里自起会话
  （想测自起的用例自己 monkeypatch 回 "1"）；
- ``GENIE_RENDEZVOUS`` 指向不存在的文件：绝不读到开发机真门牌、绝不
  连到用户正在用的真 Studio 会话；
- 凭据仓（``~/.genie/credentials.json``）钉到 tmp：登录截获等写盘
  测试不碰真实凭据。
"""
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("GENIE_STUDIO_OPEN", "1")
os.environ.setdefault(
    "GENIE_SESSION_AUTOSTART", "0")
os.environ.setdefault(
    "GENIE_RENDEZVOUS",
    os.path.join(tempfile.gettempdir(), "genie-sdk-test-no-rendezvous.json"))


@pytest.fixture(autouse=True)
def _pin_session_state(tmp_path, monkeypatch):
    """每用例：会话口令清空 + 凭据仓/代持缓存钉 tmp（进程级全局态隔离）。

    钉 ``_store_dir`` 而非 ``config_path``：迁移逻辑（config.json →
    credentials.json）在真实 ``config_path`` 代码里跑，测试可见。
    """
    import genie.studio.session_service as _ss
    from genie.net import config as _nc
    monkeypatch.setattr(_ss, "_TOKEN", "")
    monkeypatch.setattr(_ss, "_CRED", None)
    monkeypatch.setattr(_ss, "_CRED_BROKER", False)
    monkeypatch.setattr(_nc, "_store_dir", lambda: tmp_path / "genie-home")
