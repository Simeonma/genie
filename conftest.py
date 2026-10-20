"""测试树护栏（genie SDK 仓）：`genie` 必须解析到本仓根下的 genie-sdk/ 源码树。

映射逻辑在 _tree.py（conftest 与子进程锚共用同一份）：目录名 genie-sdk 带
连字符、不能作包名，单靠把 ROOT 塞进 sys.path 无法命中 `import genie`。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT))

import _tree  # noqa: E402  （必须在 ROOT 入 path 之后）

collect_ignore_glob = ["genie-sdk/core/nkdata/*", "genie-sdk/studio/static/vendor/*"]

_tree.bind_local_genie()
_tree.assert_bound_to_this_tree()


def pytest_collection_finish(session):
    _tree.assert_bound_to_this_tree()
