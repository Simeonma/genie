"""把 import 名 genie 钉到本仓 genie-sdk/ 的引导件（conftest 与子进程锚共用）。

为什么需要它：源码目录叫 genie-sdk（分发名同名），而目录名带连字符不能作
import 名，`import genie` 无法靠 ``sys.path`` 命中；等价物是 pyproject 里那条
``[tool.setuptools] package-dir = { genie = "genie-sdk" }``——那是给安装用的，
开发/测试期由本文件提供同一映射。

只在开发与测试期使用，不进包、不随 wheel 分发。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG_DIR = ROOT / "genie-sdk"

_EDITABLE_PREFIX = "__editable___genie_"  # 同时命中旧名 genie 与新名 genie-sdk 的 editable 安装


class _LocalGenieFinder:
    """只认领顶层 ``genie``；子包交给 importlib 按父包 ``__path__`` 解析。"""

    @staticmethod
    def find_spec(fullname, path=None, target=None):
        if fullname != "genie":
            return None
        return importlib.util.spec_from_file_location(
            fullname,
            PKG_DIR / "__init__.py",
            submodule_search_locations=[str(PKG_DIR)],
        )


def bind_local_genie() -> None:
    """摘掉外部 editable 安装、清掉别处导入的 genie.*，再绑定本仓源码树。

    共享 venv 里可能装着别处的 genie（PEP 660 按精确模块名认领，实证：搬家后
    ``genie._script`` 会被解析到另一个树）；不摘则测的可能是别人的代码。
    """
    sys.meta_path[:] = [
        f for f in sys.meta_path
        if not getattr(f, "__module__", "").startswith(_EDITABLE_PREFIX)]
    for name in [m for m in sys.modules if m == "genie" or m.startswith("genie.")]:
        del sys.modules[name]
    if not any(f is _LocalGenieFinder for f in sys.meta_path):
        sys.meta_path.insert(0, _LocalGenieFinder)


def assert_bound_to_this_tree() -> None:
    """导入期护栏：已导入的 genie 必须落在本仓之下。"""
    got = getattr(sys.modules.get("genie"), "__file__", None)
    if got is not None and not got.startswith(str(ROOT)):
        raise RuntimeError(f"genie 来自错误的树：实际 {got}；期望落在 {ROOT} 之下。")
