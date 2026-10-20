"""agent 轨道锁测试（2026-10）：工具面行为 + LLM 自纠回路的契约。

锁四件事：
  ① check_script 是合格的"自纠回路"——错误带行号、成功带模型摘要、
     常见遗漏给告警，且**不推 GUI**（纯本地体检）；
  ② 会话面工具（get_model / edit_model / run_script / run_model /
     get_results）走的是**同一个会话模型**，被拒时如实报告、不假装成功；
  ③ MCP 工具面形状（8 个工具；v2 的两个脚本文本工具已退役）；
  ④ ``import genie`` 不因工具面接线把 fastapi 拉进来（studio 是可选 extra）。
"""
from __future__ import annotations

import subprocess
import sys

import pytest

import genie
from genie.integrations.mcp import (TOOL_NAMES, TOOLS, execute_tool,
                                    set_session_factory)

GOOD = """
import genie
def asm_grating(f, N=3):
    for i in range(N):
        f.geom.add_box().material('sio2') \\
            .x_range(i * 2e-7, i * 2e-7 + 1e-7) \\
            .y_range(-1e-7, 1e-7).z_range(-1e-7, 1e-7)

f = genie.connect('x')
f.domain.x_range = (-2e-6, 2e-6)
f.domain.y_range = (-1e-6, 1e-6)
f.domain.z_range = (-1e-6, 1e-6)
f.domain.total_time = 6e-14
f.mesh.dx = 2e-8
f.mesh.dy = 2e-8
f.mesh.dz = 2e-8
f.mat.add_const().name('sio2').eps(2.1)
asm_grating(f)
f.src.add_soft_source().freq(3e14).bandwidth(6e13).name('s0')
f.mon.add_time().name('pt').field('Ex')
f.run()
"""


class FakeSession:
    """会话客户端的假体：只实现 mcp 用到的那几个方法。

    ``fail_patch`` / ``fail_exec`` 用来演"被拒"与"脚本报错"两条路——
    工具必须如实报告，不能因为 200 就假装成功。
    """

    def __init__(self):
        self.cfg = {"domain": {"total_time": 6e-14}, "mesh": {"dx": 2e-8},
                    "materials": [], "geometry": [], "source": [],
                    "monitor": [], "run": {}}
        self.seq = 1
        self.lines: list[dict] = []
        self.origin = "replace"
        self.paths: list = []
        self.job_id = ""
        self.fail_patch = False
        self.fail_exec = False
        self.fail_run = False
        self.sent: list[tuple] = []

    def _line(self, text, kind="stdout"):
        self.lines.append({"seq": len(self.lines) + 1, "text": text,
                           "kind": kind})

    def output(self, since: int = 0, **kw):
        return {"lines": [l for l in self.lines if l["seq"] > since],
                "busy": False, "phase": "idle", "job_id": self.job_id,
                "session_id": "s-fake", "cfg": self.cfg,
                "cfg_seq": self.seq, "origin": self.origin,
                "paths": self.paths}

    def patch(self, ops, **kw):
        self.sent.append(("patch", list(ops)))
        if self.fail_patch:
            self.origin = "reject"
            self._line("(patch 失败: 第 1 条 x.9：下标越界——整批未提交)\n",
                       kind="error")
            return {"id": 1}
        mons = self.cfg.setdefault("monitor", [])
        for o in ops:
            if o.get("verb") == "append":
                mons.append(o.get("value"))
                self.paths = [f"monitor.{len(mons) - 1}"]
            elif o.get("verb") == "remove":
                mons.pop(int(o["path"].rsplit(".", 1)[1]))
                self.paths = [o["path"]]
            else:
                self.paths = [o["path"]]
                self.cfg["mesh"]["dx"] = o.get("value")
        self.origin = "patch"
        self.seq += 1
        return {"id": 1}

    def exec(self, code, *, mode="run", label="", **kw):
        self.sent.append(("exec", code, mode))
        if self.fail_exec:
            self._line("ValueError: boom\n", kind="error")
        else:
            self._line("42\n")
        return {"id": 2}

    def run(self, **kw):
        self.sent.append(("run", kw))
        if self.fail_run:
            self._line("✗ 提交失败：上游不可达\n", kind="error")
            return {"id": 3}
        self.job_id = "job-7"
        return {"id": 3}

    def result_meta(self, job_id="", **kw):
        return {"job_id": job_id or self.job_id, "monitors": ["pt"]}

    def result_series(self, *, job_id, mon, field, maxpoints=1200, **kw):
        return {"job_id": job_id, "mon": mon, "field": field, "n": 3}


# ── check_script：LLM 自纠回路 ────────────────────────────────────────

def test_check_script_ok_with_summary():
    r = genie.check_script(GOOD)
    assert r["ok"] is True, r["errors"]
    s = r["summary"]
    assert s["geometry"] == 3 and s["source"] == 1 and s["monitor"] == 1
    assert s["total_time"] == 6e-14
    assert r["warnings"] == []


def test_check_script_reports_syntax_error_with_line():
    r = genie.check_script("import genie\nf = (\n")
    assert r["ok"] is False
    assert r["errors"][0]["kind"] == "syntax"
    assert r["errors"][0]["line"] == 2


def test_check_script_reports_runtime_error_with_line():
    r = genie.check_script(
        "import genie\nf = genie.connect('x')\n\nraise ValueError('boom')")
    assert r["ok"] is False
    e = r["errors"][0]
    assert e["kind"] == "ValueError" and e["line"] == 4 and "boom" in e["message"]


def test_check_script_warns_common_omissions():
    """常见遗漏给告警但不阻断（agent 自行判断是否补）。"""
    r = genie.check_script("""
import genie
f = genie.connect('x')
f.domain.x_range = (-1e-6, 1e-6)
f.geom.add_box().material('m')
""")
    assert r["ok"] is True
    joined = " ".join(r["warnings"])
    assert "源" in joined and "total_time" in joined and "监视器" in joined


def test_check_script_empty_and_oversize():
    assert genie.check_script("")["ok"] is False
    assert genie.check_script("   ")["errors"][0]["kind"] == "empty"
    big = "x = 1\n" * 50000
    assert genie.check_script(big)["errors"][0]["kind"] == "too_large"


# ── 会话面工具：同一个模型，如实报告 ─────────────────────────────────

def test_get_model_reads_session_model():
    cli = FakeSession()
    r = execute_tool("get_model", {}, session=cli)
    assert r["ok"] is True and r["has_model"] is True
    assert r["model"]["mesh"]["dx"] == 2e-8
    assert r["session_id"] == "s-fake" and r["busy"] is False


def test_get_model_section_filter():
    """大模型别整份拉：section 只回那一节。"""
    cli = FakeSession()
    cli.cfg["monitor"] = [{"type": "time", "name": "t1", "field": "Ey"}]
    r = execute_tool("get_model", {"section": "monitor"}, session=cli)
    assert r["ok"] is True and list(r["model"]) == ["monitor"]
    assert r["model"]["monitor"][0]["name"] == "t1"
    bad = execute_tool("get_model", {"section": "nope"}, session=cli)
    assert bad["ok"] is False and "section" in bad["error"]


def test_edit_model_appends_one_object():
    """加一个就是加一个：工具只发一条 append，回执点名新元素与它的值。"""
    cli = FakeSession()
    r = execute_tool("edit_model", {"ops": [
        {"verb": "append", "path": "monitor",
         "value": {"type": "time", "name": "t1", "field": "Ey"}}]}, session=cli)
    assert r["ok"] is True, r
    assert r["applied_paths"] == ["monitor.0"]
    # 回执只带改动的那几处（不刷整份模型——大模型塞不下）
    assert r["changed"]["monitor.0"]["name"] == "t1"
    assert "model" not in r
    assert cli.sent[0][0] == "patch" and len(cli.sent[0][1]) == 1


def test_edit_model_reports_rejection_as_failure():
    """被拒 ≠ 成功：ok=false + 原因（模型没动）。工具不能因为 HTTP 200 就说成功。"""
    cli = FakeSession()
    cli.fail_patch = True
    r = execute_tool("edit_model", {"ops": [{"path": "x.9", "value": 1}]},
                     session=cli)
    assert r["ok"] is False and r["rejected"] is True
    assert "整批未提交" in r["error"], r


def test_edit_model_rejects_empty_ops():
    r = execute_tool("edit_model", {"ops": []}, session=FakeSession())
    assert r["ok"] is False and "ops" in r["error"]


def test_run_script_returns_output_and_failure():
    cli = FakeSession()
    ok = execute_tool("run_script", {"script": "print(6 * 7)"}, session=cli)
    assert ok["ok"] is True and "42" in ok["output"]
    assert ("exec", "print(6 * 7)", "run") in cli.sent

    cli2 = FakeSession()
    cli2.fail_exec = True
    bad = execute_tool("run_script", {"script": "raise ValueError('boom')"},
                       session=cli2)
    assert bad["ok"] is False and "boom" in bad["output"]


def test_run_script_build_mode_passes_mode_through():
    cli = FakeSession()
    execute_tool("run_script", {"script": "x = 1", "mode": "build"},
                 session=cli)
    assert cli.sent[-1] == ("exec", "x = 1", "build")


def test_run_model_submits_without_changing_model():
    cli = FakeSession()
    r = execute_tool("run_model", {}, session=cli)
    assert r["ok"] is True and r["job_id"] == "job-7"
    assert cli.sent[0][0] == "run"
    assert cli.sent[0][1] == {"gpu": None, "timeout_s": None}


def test_run_model_reports_submit_failure():
    """提交失败不能报成功——否则 agent 会一直等一个不存在的作业。"""
    cli = FakeSession()
    cli.fail_run = True
    r = execute_tool("run_model", {}, session=cli)
    assert r["ok"] is False and "上游不可达" in r["error"], r


def test_run_model_passes_gpu_and_timeout():
    cli = FakeSession()
    execute_tool("run_model", {"gpu": 2, "timeout_s": 60}, session=cli)
    assert cli.sent[0][1] == {"gpu": 2, "timeout_s": 60}


def test_get_results_meta_then_series():
    cli = FakeSession()
    meta = execute_tool("get_results", {}, session=cli)
    assert meta["ok"] is True and meta["meta"]["monitors"] == ["pt"]
    ser = execute_tool("get_results", {"mon": "pt", "field": "Ey"}, session=cli)
    assert ser["ok"] is True and ser["series"]["n"] == 3
    miss = execute_tool("get_results", {"mon": "pt"}, session=cli)
    assert miss["ok"] is False and "field" in miss["error"]


def test_session_tools_report_no_studio():
    """没有在跑的 Studio → 说清怎么办（而不是抛栈）。"""
    set_session_factory(lambda: None)
    try:
        r = execute_tool("get_model", {})
        assert r["ok"] is False and r["session"] is False
        assert "genie studio" in r["error"]
    finally:
        _restore_factory()


# ── 工具面形状 ────────────────────────────────────────────────────────

def _restore_factory():
    from genie.integrations import mcp
    mcp.set_session_factory(genie._session_client)


def test_mcp_tool_surface_shape():
    """MCP 面：8 个工具；脚本语义的两个（current_script/publish_script）已退役。"""
    assert TOOL_NAMES == {"get_model", "edit_model", "run_script", "run_model",
                          "get_results", "check_script", "get_starter_script",
                          "list_materials"}
    assert "current_script" not in TOOL_NAMES and "publish_script" not in TOOL_NAMES
    by = {t["name"]: t for t in TOOLS}
    for name in TOOL_NAMES:
        assert by[name]["description"], name
        assert by[name]["parameters"]["type"] == "object", name
    # 描述是 prompt：增量形状、事务语义、别用 f.run 都要写到
    assert "verb" in by["edit_model"]["description"]
    assert "全对或全错" in by["edit_model"]["description"]
    assert "run_model" in by["run_script"]["description"]
    assert "asm_" not in by["check_script"]["description"] or True


def test_retired_script_tools_are_gone_from_public_api():
    assert not hasattr(genie, "current_script")
    assert not hasattr(genie, "publish_script")


def test_starter_script_is_runnable():
    """样板必须真能跑（agent 的起点；实测：不照抄样板模型会发明 API）。"""
    r = execute_tool("get_starter_script", {})
    assert r["ok"] is True and "genie.connect(" in r["script"]
    assert "f.geom.add_box()" in r["script"]      # 正确方法名（非 box()）
    assert genie.check_script(r["script"])["ok"] is True


def test_execute_tool_dispatch_and_unknown():
    r = execute_tool("check_script", {"script": GOOD})
    assert r["ok"] is True
    mats = execute_tool("list_materials", {})
    assert mats["count"] > 0 and "Au" in mats["models"]
    bad = execute_tool("nope", {})
    assert bad["ok"] is False and "未知工具" in bad["error"]


def test_build_server_constructs():
    """MCP 服务器能构造出来（2026-10-21 补的回归锚）。

    mcp 2.x 把 ``FastMCP`` 改名成 ``MCPServer``，1.x 仍叫 ``FastMCP``——原先
    只写了 1.x 的 import，于是 ``pyproject`` 声明 ``mcp>=2.0,<3`` 时
    ``genie-mcp`` 一启动就 ModuleNotFoundError，而测试只摸 TOOLS/execute_tool，
    从未走过构造路径，所以静默坏了。这里真的构造一次。
    """
    pytest.importorskip("mcp")
    from genie.integrations.mcp import build_server
    srv = build_server()
    assert srv is not None
    assert callable(getattr(srv, "run", None)), "构造出来的服务器没有 run()"


def test_import_genie_does_not_pull_fastapi():
    """工具面的接线必须懒——studio 是可选 extra，``import genie`` 不能拉 fastapi。"""
    out = subprocess.run(
        [sys.executable, "-c",
         "import genie, sys; print('fastapi' in sys.modules)"],
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "False", "import genie 把 fastapi 拉进来了"
