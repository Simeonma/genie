"""同进程运行时（网页形态）的锁：`InprocRuntime` 驱动的是**同一个 `_step`**。

子进程形态靠管道喂 `kernel_worker` 的循环；这里由调用方逐条喂同一个
`_step`（`main(..., expose=…)` 交出来的）。所以这条测试的判据是
"协议回执照样出来"——证明执行逻辑没有第二份实现。
"""
from __future__ import annotations

import json

from genie.studio._runtime import InprocRuntime, make_runtime


def _rt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GENIE_STATE_FILE", str(tmp_path / "session_state.json"))
    monkeypatch.setenv("GENIE_RESULT_DIR", str(tmp_path / "genie_results"))
    # worker 起会话时会接管 genie.connect（本机形态也这样）——登记还原，
    # 否则这条全局补丁会漏到同一进程里的其它用例（真踩过：4 条红）。
    import genie
    monkeypatch.setattr(genie, "connect", genie.connect)
    lines: list[str] = []
    rt = InprocRuntime(on_line=lines.append,
                       on_err=lines.append,
                       on_exit=lambda: None)
    rt.start()
    return rt, lines


def test_inproc_runtime_answers_attach_with_ack(tmp_path, monkeypatch):
    rt, lines = _rt(tmp_path, monkeypatch)
    try:
        assert rt.alive and rt.proc is None
        assert rt.send({"op": "attach", "url": "", "key": ""}) is True
        acked = [json.loads(ln) for ln in lines if ln.strip().startswith("{")]
        assert any(e.get("ev") == "ack" for e in acked), acked
    finally:
        rt.kill()
    assert rt.alive is False
    assert rt.send({"op": "attach"}) is False     # 死了就不再假装收下


def test_inproc_runtime_patch_error_is_reported_not_swallowed(tmp_path, monkeypatch):
    """一批 op 全对或全错：错的那批要回 done{ok:false}，不能静默。"""
    rt, lines = _rt(tmp_path, monkeypatch)
    try:
        assert rt.send({"op": "patch", "id": 7, "ops": [{"path": "nope.x"}]})
        done = [json.loads(ln) for ln in lines
                if ln.strip().startswith("{") and '"done"' in ln]
        assert any(e.get("id") == 7 and e.get("ok") is False for e in done), done
    finally:
        rt.kill()


def test_platform_picks_runtime_kind(monkeypatch):
    import genie.studio._runtime as R

    kw = dict(env={}, cwd=".", on_line=lambda s: None,
              on_err=lambda s: None, on_exit=lambda: None)
    assert isinstance(R.make_runtime(["python", "-c", ""], **kw), R.PipeRuntime)
    monkeypatch.setattr(R.sys, "platform", "emscripten")
    assert isinstance(R.make_runtime([], **kw), R.InprocRuntime)
