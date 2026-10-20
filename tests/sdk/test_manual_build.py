"""commands 手册构建护栏 —— md 真源与 index.html 不允许漂移。

改了 manual/commands/*.md 之后必须重跑 ``python tools/build_manual.py``
并同笔提交 HTML（人看网页、agent 读 md，同一真源两投影——见
tools/build_manual.py 模块头）。
"""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "build_manual", Path(__file__).resolve().parents[2] / "tools"
    / "build_manual.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules["build_manual"] = _mod
_spec.loader.exec_module(_mod)

build = _mod.build


def test_manual_html_up_to_date():
    assert build(check=True) == 0, (
        "manual/commands/index.html 落后于 md 源——请运行 "
        "python tools/build_manual.py 并提交产物")
