"""状态同源（terminal 战役）：SessionKernel 管理器 + worker 协议测试。

锁三件事：① load_config 推进会话 f 后快照回流（SDK 推送 → GUI 可见）；
② kernel.output 的 cfg/cfg_seq 增量语义；③ 管理器 spawn/bind/exec 全链路
（真子进程 + 真 genie import——sdk 在测试环境可导入，无需网关）。
"""
from __future__ import annotations

import json
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import os

import pytest

from genie.studio.kernel_session import SessionKernel

WORKER = Path(__file__).resolve().parents[2] / "genie-sdk" / "studio" / "kernel_worker.py"
assert WORKER.is_file(), WORKER


def _spawn_and_exec(code: str, *, wait_s: float = 8.0,
                    cwd: Path | None = None, env_extra: dict | None = None):
    """直接驱动 worker 子进程跑一段代码，回收全部事件。

    cwd/env_extra 用于复现会话部署形态：工作区 = worker 启动 cwd，
    状态文件住系统空间（GENIE_STATE_FILE 另指他处）。"""
    proc = subprocess.Popen(
        [sys.executable, "-u", str(WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
        cwd=cwd,
        env={**os.environ,
             "PYTHONPATH": str(Path(__file__).resolve().parents[2]) + os.pathsep + os.environ.get("PYTHONPATH", ""),
             **(env_extra or {})})

    out_events: list[dict] = []
    done = threading.Event()

    def pump() -> None:
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            out_events.append(ev)
            if ev.get("ev") == "done":
                done.set()

    threading.Thread(target=pump, daemon=True).start()

    def send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    send({"op": "exec", "id": 1, "code": code})   # 未 bind：无 f 时纯代码照跑
    done.wait(timeout=wait_s)
    time.sleep(0.3)
    proc.kill()
    return out_events


def test_worker_exec_print_output_and_done():
    events = _spawn_and_exec("print('hello kernel')")
    kinds = [e.get("ev") for e in events]
    assert "done" in kinds
    texts = "".join(e.get("text", "") for e in events if e.get("ev") == "out")
    assert "hello kernel" in texts


def test_worker_cfg_snapshot_after_mutation():
    """纯 python 构建一段 SimConfig（零网络：无 connect，直接对象字面量
    不可行——改用 exec 里 import genie 并手动 Simulation(client=None)
    的零网络形态）。"""
    events = _spawn_and_exec(
        "from genie.core.simulate import Simulation\n"
        "f = Simulation(client=None)\n"
        "f.domain.x_range = (-1e-6, 1e-6)\n"
    )
    cfgs = [e for e in events if e.get("ev") == "cfg"]
    assert cfgs, "exec 后应有 cfg 快照"
    cfg = cfgs[-1]["cfg"]
    assert cfg["domain"]["x_range"] == [-1e-6, 1e-6]


def test_worker_startup_prunes_workspace_results_over_quota(tmp_path):
    """结果配额清理锚（2026-10-20 修 bug 反证）：worker 生在部署形态
    （cwd=工作区，GENIE_STATE_FILE 在系统空间）且工作区 genie_results
    超配额时，启动即收口——清理目标必须是**工作区**那份（结果实际由
    _auto_save_result 落 worker cwd），不是 state 目录旁（从未有结果、
    旧 bug：2.4GB 无限增长的根因）。状态空间侧的同名目录不得误删。"""
    ws = tmp_path / "scripts" / "majw"
    sysdir = tmp_path / "session" / "majw"
    ws.mkdir(parents=True)
    sysdir.mkdir(parents=True)
    # 两侧各放一个超限旧文件（quota = 0.0000001 GB ≈ 107 字节）
    stale_ws = ws / "genie_results" / "old_results.h5"
    stale_ws.parent.mkdir()
    stale_ws.write_bytes(b"x" * 65536)
    stale_sys = sysdir / "genie_results" / "old_results.h5"
    stale_sys.parent.mkdir()
    stale_sys.write_bytes(b"x" * 65536)

    events = _spawn_and_exec(
        "pass",
        wait_s=6.0,
        cwd=ws,
        env_extra={"GENIE_STATE_FILE": str(sysdir / "session_state.json"),
                   "GENIE_RESULT_QUOTA_GB": "0.0000001"})
    texts = "".join(e.get("text", "") for e in events if e.get("ev") == "out")
    assert "🧹" in texts, "工作区超配额：启动应收口并公告"
    assert not stale_ws.exists(), "工作区最旧结果应被清"
    assert stale_sys.exists(), "系统空间不是清理目标，不得误删"


def test_worker_patch_emits_snapshot():
    """状态同源核心锁：外部推送（patch）推进会话 → 快照回流（GUI 可见）。"""
    proc = subprocess.Popen(
        [sys.executable, "-u", str(WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]) + os.pathsep + os.environ.get("PYTHONPATH", "")})

    evs: list[dict] = []
    done1 = threading.Event()
    done2 = threading.Event()

    def pump2() -> None:
        for line in proc.stdout:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            evs.append(e)
            if e.get("id") == 1 and e.get("ev") == "done":
                done1.set()
            if e.get("id") == 2 and e.get("ev") == "done":
                done2.set()

    threading.Thread(target=pump2, daemon=True).start()

    def send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    send({"op": "exec", "id": 1,
          "code": "from genie.core.simulate import Simulation\n"
                  "f = Simulation(client=None)"})
    done1.wait(timeout=8)
    send({"op": "patch", "id": 2,
          "ops": [{"path": "domain.x_range", "value": [-3e-6, 3e-6]}]})
    done2.wait(timeout=8)   # patch 后的快照回流
    time.sleep(0.3)
    proc.kill()

    cfgs = [e for e in evs if e.get("ev") == "cfg"]
    assert cfgs, "外部推送后应有 cfg 快照（状态同源锁）"
    assert cfgs[-1]["cfg"]["domain"]["x_range"] == [-3e-6, 3e-6]
    assert cfgs[-1].get("origin") == "patch", cfgs[-1].get("origin")


def test_session_kernel_exec_and_cfg_seq():
    """SessionKernel 管理器：spawn + exec + cfg_seq 增量语义。"""
    k = SessionKernel()
    eid = k.submit("from genie.core.simulate import Simulation\n"
                   "f = Simulation(client=None)\n"
                   "f.domain.total_time = 6e-14\n")
    deadline = time.time() + 15
    while time.time() < deadline:
        out = k.output(0)
        if not out["busy"]:
            break
        time.sleep(0.2)
    out = k.output(0)
    assert out["busy"] is False
    assert out["cfg"] is not None and "domain" in out["cfg"]
    seq1 = out["cfg_seq"]
    # 再推一次增量 → cfg_seq 必须前进（GUI 增量拉取的依据）
    k.patch([{"path": "domain.total_time", "value": 7e-14}])
    deadline = time.time() + 10
    while time.time() < deadline:
        out = k.output(0)
        if out["cfg_seq"] > seq1:
            break
        time.sleep(0.2)
    assert out["cfg_seq"] > seq1, "patch 应推进 cfg_seq（GUI 增量语义）"


def test_submit_input_event_in_ring():
    """input 事件进环（2026-10-11 站长裁决「输入输出按时间序」收口）：
    submit 在发 worker 前写环 kind=="input" 条目——seq 先于该次全部输出，
    GUI echo 由服务端唯一负责（客户端直插 echo 刷新即丢，已废）；
    label 经 ExecIn 一路透传为环条目的 mark 字段。"""
    k = SessionKernel()
    k.submit("print('in-ring-check')", label="选中 L2-2（临时执行，不落盘）")
    deadline = time.time() + 15
    while time.time() < deadline:
        out = k.output(0)
        if not out["busy"]:
            break
        time.sleep(0.2)
    out = k.output(0)
    # 结构锁：环条目全量结构化 {seq, text, kind, origin, ts}
    for l in out["lines"]:
        assert {"seq", "text", "kind", "origin", "ts"} <= set(l), l
    inputs = [l for l in out["lines"] if l["kind"] == "input"]
    assert inputs, "submit 应在环里写 input 事件"
    first = inputs[0]
    assert first["text"] == "print('in-ring-check')"     # text 逐字原文
    assert first["origin"] == "manager"
    assert first["mark"] == "选中 L2-2（临时执行，不落盘）", "label 应透传为 mark"
    outs = [l for l in out["lines"]
            if l["kind"] == "stdout" and "in-ring-check" in l["text"]]
    assert outs, "exec 输出应进环"
    assert first["seq"] < outs[0]["seq"], "input seq 必须先于该次全部输出"


def test_failed_exec_error_displayed_once():
    """报错只显示一次（2026-10-11 站长裁决，VS Code 式终端配套）：
    失败 = worker out 流的 traceback 一次进环；管理器不再把 done.err
    二次打印成 ✗ 摘要——旧行为 traceback 末行与 ✗ 摘要一字不差两遍，
    站长所见「报错这么多还重复」的来源之一。"""
    k = SessionKernel()
    k.submit("raise ValueError('boom-display-once')")
    deadline = time.time() + 15
    while time.time() < deadline:
        out = k.output(0)
        if not out["busy"]:
            break
        time.sleep(0.2)
    out = k.output(0)
    text = "".join(l["text"] for l in out["lines"])
    assert "Traceback" in text and "ValueError: boom-display-once" in text
    assert text.count("ValueError: boom-display-once") == 1, \
        f"错误文本不得重复：\n{text}"
    assert "✗" not in text, f"done.err 摘要不得二次显示：\n{text}"


# ---- 停止（A2「长任务必须能掐」，2026-10-11 站长裁决）----

def _wait_idle(k: SessionKernel, timeout_s: float = 15.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not k.output(0)["busy"]:
            return True
        time.sleep(0.1)
    return False


def test_stop_idle_is_noop_and_worker_survives():
    """停止锚①：空闲期 stop = False（无事可停），且 SIGINT 地雷已拆——
    即使信号在空闲期到达，worker 也只提示不死亡（会话态保留，后续
    submit 照常）。走管理器公开方法（真实 send_signal 路径）。"""
    k = SessionKernel()
    k.submit("print('before-idle-stop')")
    assert _wait_idle(k)
    assert k.stop() is False, "空闲期（非忙）stop 应返回 False"
    # worker 存活证明：后续 submit 照常执行、输出进环
    k.submit("print('alive-after-idle-stop')")
    assert _wait_idle(k)
    text = "".join(l["text"] for l in k.output(0)["lines"])
    assert "alive-after-idle-stop" in text


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows 无 SIGINT 语义：stop() 改走 CTRL_BREAK_EVENT（kernel_session"
           " 已独立进程组 + kernel_worker 挂 SIGBREAK 处理器），但 CTRL_BREAK 的"
           "投递依赖真实控制台，CI/管道环境下不可靠——本用例只在 posix 验行为（G33）")
def test_stop_during_exec_interrupts_and_worker_survives():
    """停止锚②：exec `time.sleep(30)` 中 stop → 5s 内 busy=False、
    环含「已停止」、worker 存活（再 submit 一次验证）。SIGINT 冲出
    exec 被既有收尾链捕获（回滚条件/done 照发），会话不陪葬。"""
    k = SessionKernel()
    k.submit("import time\ntime.sleep(30)")
    time.sleep(1.0)   # 等 worker 真正进入 exec（避开发送窗口竞态）
    assert k.stop() is True, "exec 期 stop 应返回 True"
    deadline = time.time() + 5
    while time.time() < deadline:
        if not k.output(0)["busy"]:
            break
        time.sleep(0.1)
    out = k.output(0)
    assert out["busy"] is False, "停止后 5s 内应回到非忙（done 照发）"
    text = "".join(l["text"] for l in out["lines"])
    assert "已停止" in text, f"环应含 ⏹ 已停止提示：\n{text[-400:]}"
    # worker 存活证明：同一会话再 submit 照常
    k.submit("print('alive-after-stop')")
    assert _wait_idle(k)
    text = "".join(l["text"] for l in k.output(0)["lines"])
    assert "alive-after-stop" in text


@pytest.mark.skipif(
    os.name == "nt",
    reason="同上：本用例靠 SIGINT/CTRL_BREAK 掐断 exec，Windows 控制台投递"
           "不可靠（G33；产品侧已接 SIGBREAK 处理器，行为只能在 posix 验）")
def test_stop_cancels_orphan_backend_jobs():
    """停止锚③（孤儿作业清理）：exec 期持有已提交作业的 Simulation
    被掐断后，worker 就地调 cancel() 并回显——后端作业在独立进程组
    （start_new_session），SIGINT 传不到，同步等待断了不等于作业停了。"""
    proc = subprocess.Popen(
        [sys.executable, "-u", str(WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]) + os.pathsep + os.environ.get("PYTHONPATH", "")})
    evs: list[dict] = []
    done = threading.Event()

    def pump() -> None:
        for line in proc.stdout:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            evs.append(e)
            if e.get("ev") == "done":
                done.set()

    threading.Thread(target=pump, daemon=True).start()

    def send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    # 假 Simulation（零网络）：_job_id 非空 + cancel 可观察（print 打点）
    send({"op": "exec", "id": 1,
          "code": "class _S:\n"
                  "    _job_id = 'job-stop-orphan'\n"
                  "    def cancel(self):\n"
                  "        print('cancel-was-called')\n"
                  "f = _S()\n"
                  "import time\n"
                  "time.sleep(30)\n"})
    time.sleep(1.0)               # 等 worker 真正进入 exec
    proc.send_signal(signal.SIGINT)   # 管理器 stop() 的同款真实信号路径
    assert done.wait(timeout=8), "停止后 done 应照发"
    time.sleep(0.3)
    proc.kill()
    text = "".join(e.get("text", "") for e in evs if e.get("ev") == "out")
    assert "已停止" in text
    assert "cancel-was-called" in text, "应真调到 Simulation.cancel()"
    assert "后端作业 job-stop-orphan 已取消" in text


# ---- B2 会话落盘恢复（输出环 + f 跨 worker 重生/服务重启存活）----
# 落盘是恢复快照，不是第二份可编辑设计状态（铁律 1）——锚只锁「恢复」
# 语义：环 seq 续接、坏行容忍、f 重放可用，不锁任何编辑回流通道。

@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path, monkeypatch):
    """B2 落盘隔离：环/会话态文件每测一份 tmp 工作区（GENIE_SESSION_CWD
    在 kernel_session 内是调用时解析），直驱 worker 的 cwd 一并落 tmp
    ——不再写进真实 ~/data/genie/scripts/<owner>/。"""
    monkeypatch.setenv("GENIE_SESSION_CWD", str(tmp_path))
    monkeypatch.setenv("GENIE_SESSION_STATE_DIR", str(tmp_path / "sys"))
    monkeypatch.chdir(tmp_path)


def test_ring_log_semantics_across_kernel_instances(tmp_path):
    """环 log 语义锚（2026-10-13 站长裁决瘦身）：重建（=session 服务
    重启等价形态）后——①内存是干净的（历史不回放）；②seq 从文件
    最大值续接（新 emit > 旧最大，GUI 游标单调取 max 的硬约束）；
    ③文件持续追加（运行日志职责）。"""
    k = SessionKernel(owner="b2ring")
    k._emit("stdout", "第一行 hello\n", "worker")
    k._emit("input", "print('x')", "manager", mark="L2-2")
    k._emit("note", "── 便签\n", "manager")
    old_lines = k.output(0)["lines"]
    assert len(old_lines) == 3
    old_max_seq = old_lines[-1]["seq"]
    del k
    # 重建（同 owner）：历史不回放、seq 续接
    k2 = SessionKernel(owner="b2ring")
    assert k2.output(0)["lines"] == [], "重建后内存应是干净的（无历史回放）"
    k2._emit("stdout", "重启后新行\n", "worker")
    tail = k2.output(0)["lines"][-1]
    assert tail["seq"] > old_max_seq, "seq 必须从文件最大 seq 续接"
    # 权限纪律（对齐 fdtd-jobs）：目录 0700、环文件 0600
    # NTFS 没有 POSIX 权限位（Windows 一律报 0o777）→ 只在 posix 断言（G33）
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / "b2ring").stat().st_mode) == 0o700
        ring = tmp_path / "sys" / "b2ring" / "log.jsonl"
        assert stat.S_IMODE(ring.stat().st_mode) == 0o600
    ring = tmp_path / "sys" / "b2ring" / "log.jsonl"
    assert "重启后新行" in ring.read_text(encoding="utf-8"), "日志持续追加"


def test_ring_tolerates_truncated_tail(tmp_path):
    """log 语义锚②：尾部半行/坏行容忍——手工追加垃圾 → 重建不炸、
    垃圾行的 seq（99）不污染基准（从合法行最大值续接）。"""
    k = SessionKernel(owner="b2half")
    k._emit("stdout", "完好行甲\n", "worker")
    k._emit("stdout", "完好行乙\n", "worker")
    del k
    ring = tmp_path / "sys" / "b2half" / "log.jsonl"
    with open(ring, "a", encoding="utf-8") as fh:
        fh.write('{"seq": 99, "text": "半截')      # 尾部半行（无换行）
        fh.write('\nnot-json-at-all\n')            # 中段坏行
    k2 = SessionKernel(owner="b2half")             # 不炸
    assert k2.output(0)["lines"] == []             # 无历史回放
    k2._emit("stdout", "续写\n", "worker")
    assert k2.output(0)["lines"][-1]["seq"] == 3, \
        "seq 从合法行最大值续接，垃圾行的 seq=99 不得污染"


def test_ring_log_capped_rotation(tmp_path):
    """log 语义锚③：限量轮换——文件超 1MB 后重启，就地截尾保整行，
    seq 基准仍从保留段最大值续接。"""
    import genie.studio.kernel_session as ks
    k = SessionKernel(owner="b2cap")
    k._emit("stdout", "x" * 200 + "\n", "worker") * 0 if False else None
    ring = tmp_path / "sys" / "b2cap" / "log.jsonl"
    # 直接灌一个超限文件（比 emit 6000 次快得多）
    with open(ring, "w", encoding="utf-8") as fh:
        for i in range(16000):
            fh.write(json.dumps({"seq": i + 1, "text": f"L{i}\n",
                                 "kind": "stdout", "origin": "worker",
                                 "ts": 0.0}) + "\n")
    assert ring.stat().st_size > ks._RING_CAP_BYTES
    del k
    k2 = SessionKernel(owner="b2cap")
    assert ring.stat().st_size <= ks._RING_CAP_BYTES + 4096, "截尾后应 ≤ 上限"
    kept = [json.loads(x) for x in
            ring.read_text(encoding="utf-8").splitlines()]
    assert kept == sorted(kept, key=lambda e: e["seq"]), "保留段仍有序"
    assert kept[0]["seq"] > 1, "头部（最旧）确实被截掉了"
    k2._emit("stdout", "新行\n", "worker")
    assert k2.output(0)["lines"][-1]["seq"] > kept[-1]["seq"], \
        "seq 从保留段最大值续接"


def test_log_overwrites_on_job_submit(tmp_path):
    """log 语义锚④：提交新仿真（data.phase=submit 事件）→ log.jsonl
    覆盖前一次（站长裁决 2026-10-13）；内存滚动回放与 seq 不受影响。"""
    k = SessionKernel(owner="b2log")
    d = tmp_path / "sys" / "b2log"
    assert (d / "log.jsonl").is_file() or not (d / "log.jsonl").exists()
    k._emit("stdout", "命令输出\n", "worker")
    # 模拟 pump 收到提交事件（真实链路：worker → _pump → _begin_job_log）
    k._begin_job_log()
    k._emit("job", "⏳ 提交作业…\n", "worker",
            data={"phase": "submit"})
    k._emit("stdout", "仿真 A 输出\n", "worker")
    log = (d / "log.jsonl").read_text(encoding="utf-8")
    assert "命令输出" not in log, "提交前的会话输出不应留在本次仿真日志里"
    assert "仿真 A 输出" in log
    # 内存滚动与 seq 连续性不受覆盖影响
    lines = k.output(0)["lines"]
    assert any("命令输出" in l["text"] for l in lines), "内存回放仍在"
    assert lines[-1]["seq"] >= 3, "seq 单调继续"


def test_session_dirs_are_isolated(tmp_path):
    """O2 目录布局锚：``default`` 用平铺（升级不动存量），具名会话各占一层。

    这条同时锁住"新模型 = 新 session_id"的结构性来源：新 id 没有目录，
    就没有快照可恢复，只能从空开始。
    """
    k_def = SessionKernel(owner="b2iso")
    assert k_def._state_path == tmp_path / "sys" / "b2iso" / "session_state.json"
    k_named = SessionKernel(owner="b2iso", session_id="s-1")
    assert k_named._state_path == (tmp_path / "sys" / "b2iso" / "s-1"
                                   / "session_state.json")
    k_def._emit("stdout", "default 会话的行\n", "worker")
    assert not k_named._state_path.exists(), "两个会话的落盘互不可见"
    assert "default 会话的行" not in (
        (tmp_path / "sys" / "b2iso" / "s-1" / "log.jsonl").read_text(
            encoding="utf-8") if k_named._state_path.exists() else "")


def test_legacy_state_adopted_by_first_named_session(tmp_path):
    """升级迁移锚：平铺旧布局（default 家目录）里的快照，被**第一个**具名
    会话认领一次——用户的存量模型不会因为升级而消失；搬移而非复制，
    不会二次认领。"""
    root = tmp_path / "sys" / "b2mig"
    root.mkdir(parents=True, exist_ok=True)
    (root / "session_state.json").write_text(
        json.dumps({"sims": [{"domain": {"total_time": 1e-14}}]}),
        encoding="utf-8")
    k = SessionKernel(owner="b2mig", session_id="s-new")
    assert k._state_path.exists() and k._state_path.parent.name == "s-new"
    assert not (root / "session_state.json").exists(), "搬移后旧路径不再有"


def test_f_replay_after_worker_rebirth(tmp_path):
    """B2 锚③：f 重放——真子进程 exec 建模（Simulation(client=None)
    形态，零网络）→ kill worker（模拟重生）→ 再 submit 新命令 →
    环含「已从落盘恢复 1 个仿真」且 ns["f"] 可用（print 出值）。"""
    k = SessionKernel(owner="b2replay")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.x_range = (-2e-6, 2e-6)\n")
    assert _wait_idle(k)
    # 会话态已落盘（恢复快照在 worker cwd = 工作区/<owner>/ 下，0600）
    st_path = tmp_path / "sys" / "b2replay" / "session_state.json"
    st = json.loads(st_path.read_text(encoding="utf-8"))
    assert len(st["sims"]) == 1 and st["sims"][0]["domain"]["x_range"] == [-2e-6, 2e-6]
    if os.name == "posix":          # NTFS 无 POSIX 权限位（G33）
        assert stat.S_IMODE(st_path.stat().st_mode) == 0o600
    k._proc.kill()                       # 模拟 worker 重生（崩溃/被杀）
    k._proc.wait(timeout=5)              # SIGKILL 投递异步：等内核回收再 submit
    assert _wait_idle(k)
    deadline = time.time() + 5           # 退出 note 由旧 pump 线程异步落环
    while time.time() < deadline:
        text0 = "".join(l["text"] for l in k.output(0)["lines"])
        if "输出历史保留" in text0:
            break
        time.sleep(0.1)
    assert "输出历史保留" in text0, "退出文案应换成 B2 语义（会话态已丢已废）"
    k.submit("print(f.domain.x_range)")  # 重生 + 自动重放 + 新命令
    assert _wait_idle(k)
    text = "".join(l["text"] for l in k.output(0)["lines"])
    assert "已从落盘恢复 1 个仿真" in text, f"环应含恢复 note：\n{text[-600:]}"
    assert "[-2e-06, 2e-06]" in text, f"ns['f'] 应可用（print 出值）：\n{text[-600:]}"


def test_rekey_keeps_model(tmp_path):
    """O2 锚：**换 key 不换模型、不重生进程**。

    旧语义 = bind 到新凭据就作废旧快照 + 重生 worker（模型跟着 token 的
    寿命走：改密码/7 天过期后重登会丢模型）。现在 attach 只换 Client 的
    凭据头——pid 不变、快照不删、模型原样在。要新模型请换 session_id。
    """
    k = SessionKernel(owner="b2rekey")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.total_time = 7e-14\n")
    assert _wait_idle(k)
    st_path = tmp_path / "sys" / "b2rekey" / "session_state.json"
    assert st_path.exists(), "exec 末应已落盘"
    pid = k._proc.pid

    out = k.attach("k-new")                     # token 轮换 / 改密码后重登
    assert out["key_changed"] is True
    assert k._proc.pid == pid, "换 key 不得重生 worker"
    assert st_path.exists(), "换 key 不得删快照"

    k.submit("print(f.domain.total_time)")
    assert _wait_idle(k)
    text = "".join(l["text"] for l in k.output(0)["lines"])
    assert "7e-14" in text, f"模型必须还在：\n{text[-400:]}"
    assert "凭据已更新（模型保留）" in text, "换绑要有可见提示"


def test_attach_is_idempotent(tmp_path):
    """同 key 重复 attach（刷新页面的常态）→ 进程不动、环不新增凭据提示。"""
    k = SessionKernel(owner="b2idem")
    k.attach("k1")
    pid = k._proc.pid
    out = k.attach("k1")
    assert out["key_changed"] is False
    assert k._proc.pid == pid
    text = "".join(l["text"] for l in k.output(0)["lines"])
    assert "凭据已更新" not in text


def test_output_revives_dead_session(tmp_path):
    """读即唤起：Studio 重启后，**已经开着的页面**只靠轮询就该恢复。

    同进程形态下 Studio 重启 = 会话对象没了；页面不会重新 attach。若轮询
    不唤起、唤起后不回流快照，页面会一直看着空模型（像模型丢了）。
    """
    from genie.studio import session_service as ss

    k = SessionKernel(owner="b2revive")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.total_time = 9e-14\n")
    assert _wait_idle(k)
    # 模拟"Studio 重启后的新对象"：注册表清空，同一目录重建
    ss._kernels.clear()
    deadline = time.time() + 15
    cfg = None
    while time.time() < deadline:
        cfg = ss.output(0, "b2revive", "default").get("cfg")
        if cfg is not None:
            break
        time.sleep(0.2)
    assert cfg is not None, "轮询应把会话叫醒并回流快照"
    assert (cfg.get("domain") or {}).get("total_time") == 9e-14


def test_attach_with_empty_key_does_not_degrade(tmp_path):
    """空凭据的 attach **不得拔掉**已绑定的钥匙。

    `genie console` 没有 token，接进来时若把会话的凭据清空，模型立刻
    变成"只能建模不能提交"——而且没有任何报错。"""
    k = SessionKernel(owner="b2nokey")
    k.attach("k-real")
    pid = k._proc.pid
    out = k.attach("")                       # console 形态
    assert out["key_changed"] is False
    assert k._key == "k-real"
    assert k._proc.pid == pid
    # 未绑定时空 attach 也是纯 no-op（不凭空 spawn 也不改状态）
    k2 = SessionKernel(owner="b2nokey2")
    assert k2.attach("")["key_changed"] is False
    assert k2._key == ""


def test_f_replay_survives_attach_after_rebirth(tmp_path):
    """B2 配套锚（服务重启主路径）：带凭据的会话 kill 重生后，重生
    worker 先重放、再收到 manager 的 attach op——attach 不得另立空 f 顶掉
    恢复态（「f 还在」靠这条成立）。凭据与落盘无关（盘上无凭据，O2）→
    重放仍旧生效。genie.connect 零网络，假 url 即可离线锁协议。

    等待判据用落盘文件/环内证据而非裸 busy：attach op 的 done(id=-1)
    会提前清 busy（既有协议行为），裸等会在 persist 前 kill。"""
    k = SessionKernel(owner="b2rebind")
    k.attach("k-e2e")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.total_time = 6e-14\n")
    st_path = tmp_path / "sys" / "b2rebind" / "session_state.json"
    deadline = time.time() + 20
    while time.time() < deadline and not st_path.exists():
        time.sleep(0.1)
    assert st_path.exists(), "exec 末应已落盘"
    if os.name != "nt":
        import stat as _stat
        assert _stat.S_IMODE(st_path.stat().st_mode) == 0o600
    # O2：盘上不许有凭据（拷走一个 json 也泄露不了 token）
    st = json.loads(st_path.read_text(encoding="utf-8"))
    assert set(st) == {"sims"}, f"快照只应含模型：{sorted(st)}"
    k._proc.kill()
    k._proc.wait(timeout=5)              # SIGKILL 投递异步：等内核回收再 submit
    deadline = time.time() + 20
    while time.time() < deadline and k._proc.poll() is None:
        time.sleep(0.05)
    k.submit("print(f.domain.total_time)")
    # 等第二次 exec 的环内证据（精确到 stdout 行——「6e-14」也出现在
    # exec1 的输入回显里，子串匹配会提前误判）
    lines: list = []
    outs: list = []
    deadline = time.time() + 20
    while time.time() < deadline:
        lines = k.output(0)["lines"]
        outs = [l for l in lines
                if l["kind"] == "stdout" and l["text"].strip() == "6e-14"]
        if outs or any("落盘恢复失败" in l["text"] for l in lines):
            break
        time.sleep(0.1)
    text = "".join(l["text"] for l in lines)
    # 2 个 = attach 时代实例 + 脚本直建 f（会话实例全集本就二者都在环）
    assert "已从落盘恢复 2 个仿真" in text, f"环应含恢复 note：\n{text[-600:]}"
    assert outs, f"attach op 不得顶掉恢复的 f：\n{text[-600:]}"


def test_worker_publish_disabled(monkeypatch):
    """G13① 锚：会话 worker 禁用 publish——drafts 镜像属本地 SDK 批
    处理展示通道（决策档案 §4）；worker 里它抓 __main__ 会抓到自身
    源码（2026-10-13 实证 17KB 泄漏进 GUI 编辑器并触发 reset 重放）。
    禁用后：publish 返回 False、零 HTTP 外发。"""
    import http.server

    captured: list[bytes] = []

    class _H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            captured.append(self.rfile.read(n))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("GENIE_GUI_URL",
                       f"http://127.0.0.1:{srv.server_port}")

    events = _spawn_and_exec(
        "from genie.integrations.live import publish\n"
        "print('PUB>', publish(label='run'))")
    out = "".join(e.get("text", "") for e in events if e.get("ev") == "out")
    assert "PUB> False" in out, "worker 内 publish 应被禁用（返回 False）"
    assert not captured, "禁用态不得外发任何 draft"


def test_second_run_is_an_explicit_error():
    """M3 锚：对**已提交实例**再 `f.run()` → 明确报错，不再偷偷重建。

    旧行为是"从当前配置重建一个新实例换掉 f"——用户手里的对象与别名
    静默失效，而且"改完没生效"会变成无声事故。会话语义里"再跑当前
    模型"是 run 原语（工具栏 Run / run_model()），它不动 f。
    """
    events = _spawn_and_exec(
        "import genie\n"
        "f = genie.Simulation(client=None)\n"
        "f.domain.x_range = (-1e-6, 1e-6)\n"
        "f._job_id = 'fake-submitted'\n"       # 模拟已提交（不真跑作业）
        "f.run()\n")
    out = "".join(e.get("text", "") for e in events if e.get("ev") == "out")
    assert "已经提交过" in out, out[-400:]
    assert "run_model()" in out, "报错要给一条能照做的出路"
    assert "重跑：已从当前配置重建" not in out, "不得再偷偷重建"


def test_patch_applies_path_and_tags_origin(tmp_path):
    """M3b 锚：patch 只动给定路径，快照带 origin=patch + 已应用路径。

    客户端不再发整份文档——服务端是模型权威，回声告诉前端"哪些路径变了"，
    前端据此跳过整面板重渲染（这是"敲字段被重建面板"的根治点）。
    """
    k = SessionKernel(owner="b3patch")
    k.attach("k1")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.total_time = 6e-14\n")
    assert _wait_idle(k)
    before = k.output(0)["cfg"]
    eid = k.patch([{"path": "domain.cfl", "value": 0.5},
                   {"path": "mesh.dx", "value": 2e-8}])
    assert _wait_idle(k)
    d = k.output(0)
    assert (d.get("cfg") or {}).get("domain", {}).get("cfl") == 0.5
    assert (d.get("cfg") or {}).get("mesh", {}).get("dx") == 2e-8
    assert d.get("origin") == "patch", d.get("origin")
    assert d.get("paths") == ["domain.cfl", "mesh.dx"], d.get("paths")
    # 没被点名的字段原样保留（增量语义）
    assert (d.get("cfg") or {}).get("domain", {}).get("total_time") == \
        before["domain"]["total_time"]
    assert eid >= 1


def test_patch_batch_is_all_or_nothing(tmp_path):
    """一批 op **全对或全错**（M4）：半落地会让调用方以为整批成了。

    被拒的一批：模型一个字节不动，回声 ``origin=reject``——前端据此把本地
    那份改回服务端。少了这条回声，那个非法值会一直留在表单里，之后每次
    提交都带上它、每次都整批失败（表单从此一个字也存不进去）。
    """
    k = SessionKernel(owner="b3patchbad")
    k.attach("k1")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.total_time = 7e-14\n")
    assert _wait_idle(k)
    before = k.output(0)["cfg"]
    k.patch([{"path": "domain.cfl", "value": 0.5},        # 这一条本来是好的
             {"path": "materials.99.name", "value": "x"}])
    assert _wait_idle(k)
    d = k.output(0)
    text = "".join(l["text"] for l in d["lines"])
    assert "整批未提交" in text, text[-300:]
    assert "第 2 条 materials.99.name" in text, "报错要说清是哪一条坏的"
    assert (d["cfg"] or {}) == before, "整批拒了，好那条也不该落地"
    assert d.get("origin") == "reject", d.get("origin")


def test_patch_append_and_remove_array_items(tmp_path):
    """append/remove（M4）：**加一个就是加一个**。

    只有 set 的话，"加一个源"在客户端就是 读→改→写（两个客户端同时加会
    丢一个），而且它得先把整张表读下来。有了这两个动词，数组上的增量写入
    和标量一样是"只说我改了什么"。
    """
    k = SessionKernel(owner="b4append")
    k.attach("k1")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.total_time = 6e-14\n")
    assert _wait_idle(k)
    k.replace({"domain": {"total_time": 6e-14}, "mesh": {"dx": 3e-8},
               "materials": [], "geometry": [], "source": [],
               "monitor": [], "run": {}})
    assert _wait_idle(k)

    k.patch([{"verb": "append", "path": "monitor",
              "value": {"type": "time", "name": "t1", "field": "Ey"}}])
    assert _wait_idle(k)
    d = k.output(0)
    assert [m.get("name") for m in d["cfg"]["monitor"]] == ["t1"]
    assert d.get("paths") == ["monitor.0"], d.get("paths")

    k.patch([{"verb": "append", "path": "monitor",
              "value": {"type": "time", "name": "t2", "field": "Ex"}}])
    assert _wait_idle(k)
    d = k.output(0)
    assert [m.get("name") for m in d["cfg"]["monitor"]] == ["t1", "t2"]
    assert d.get("paths") == ["monitor.1"], d.get("paths")

    k.patch([{"verb": "remove", "path": "monitor.0"}])
    assert _wait_idle(k)
    d = k.output(0)
    assert [m.get("name") for m in d["cfg"]["monitor"]] == ["t2"]


def test_patch_path_accepts_object_name(tmp_path):
    """数组那一段可以写**名字**（不是只有下标）。

    按下标改/删是"读→算→写"：别人刚插一个，你删掉的就是别人的。名字是对象
    自己的身份，说"删掉叫 grating 的那个"不会因为下标错位而删错东西。
    """
    k = SessionKernel(owner="b4name")
    k.attach("k1")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.total_time = 6e-14\n")
    assert _wait_idle(k)
    k.replace({"domain": {"total_time": 6e-14}, "mesh": {"dx": 3e-8},
               "materials": [], "geometry": [], "source": [],
               "monitor": [{"type": "time", "name": "t1", "field": "Ey"},
                           {"type": "time", "name": "t2", "field": "Ex"}],
               "run": {}})
    assert _wait_idle(k)

    k.patch([{"verb": "remove", "path": "monitor.t1"}])
    assert _wait_idle(k)
    names = [m.get("name") for m in k.output(0)["cfg"]["monitor"]]
    assert names == ["t2"], names

    # 名字对仍在下标 0 的那个对象同样有效（名字不是下标别名）
    k.patch([{"path": "monitor.t2.field", "value": "Ez"}])
    assert _wait_idle(k)
    assert k.output(0)["cfg"]["monitor"][0]["field"] == "Ez"

    # 查无此名：报错要能自纠（把有的名字列出来）
    before = k.output(0)["cfg"]
    k.patch([{"verb": "remove", "path": "monitor.nope"}])
    assert _wait_idle(k)
    text = "".join(l["text"] for l in k.output(0)["lines"])
    assert "不在这个数组里" in text and "t2" in text, text[-300:]
    assert k.output(0)["cfg"] == before, "查无此名不该改动模型"


def test_patch_rejects_unknown_verb_and_bad_remove(tmp_path):
    """动词只认三个；写错动词/删越界都是整批失败，且说清原因。"""
    k = SessionKernel(owner="b4verb")
    k.attach("k1")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.total_time = 6e-14\n")
    assert _wait_idle(k)
    before = k.output(0)["cfg"]

    k.patch([{"verb": "insert", "path": "monitor", "value": {}}])
    assert _wait_idle(k)
    text = "".join(l["text"] for l in k.output(0)["lines"])
    assert "未知 verb" in text, text[-300:]

    k.patch([{"verb": "remove", "path": "monitor.7"}])
    assert _wait_idle(k)
    text = "".join(l["text"] for l in k.output(0)["lines"])
    assert "下标越界" in text, text[-300:]
    assert (k.output(0)["cfg"] or {}) == before, "两次都该整批拒、模型不动"


def test_replace_swaps_whole_model(tmp_path):
    """replace：整份模型换掉（.gensim 导入那条路）。"""
    k = SessionKernel(owner="b3replace")
    k.attach("k1")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.total_time = 6e-14\n")
    assert _wait_idle(k)
    new = {"domain": {"total_time": 1.5e-13},
           "mesh": {"dx": 3e-8}, "materials": [], "geometry": [],
           "source": [], "monitor": [], "run": {}}
    k.replace(new)
    assert _wait_idle(k)
    d = k.output(0)
    assert (d.get("cfg") or {}).get("domain", {}).get("total_time") == 1.5e-13
    assert d.get("origin") == "replace"


def test_run_submits_current_model_without_changing_it(tmp_path):
    """M3 锚：`op=run` 提交当前模型，**不改模型**（f 与实例列表原样）。

    真子进程跑：先建模型 → 发 run op（后端不可达 → 报错）→ 模型必须
    一字不动，且实例数不增加。
    """
    k = SessionKernel(owner="b3run")
    k.submit("from genie.core.simulate import Simulation\n"
             "f = Simulation(client=None)\n"
             "f.domain.total_time = 5e-14\n")
    assert _wait_idle(k)
    before = k.output(0)["cfg"]
    eid = k.run()
    assert eid >= 1
    assert _wait_idle(k)
    after = k.output(0)["cfg"]
    assert after == before, "run 不得改模型"
    text = "".join(l["text"] for l in k.output(0)["lines"])
    assert "⏳ 提交作业" in text, "run 要走真提交那条路（哪怕后端不可达）"
