"""sdk/genie/studio/kernel_session — 会话 kernel 的管理器（库模块，非入口）。

持有常驻 worker 进程（kernel_worker.py）：spawn/重生、凭据换绑、exec
提交、输出环缓冲（GUI 按 since 增量拉）、最新 cfg 快照。

**三生命周期正交（M2/O2，2026-10-22）**——这是本模块最重要的一条纪律：

- ``owner``      → 工作目录与结果隔离（``workspace 根/<owner>/``，0700）；
- ``key``        → 能不能提交（``attach()`` 幂等换绑，**换 key 不换模型**）；
- ``session_id`` → 哪一份模型（``session/<owner>/<session_id>/``）。

于是：刷新页面（同 session_id、同 key）保留模型；**改密码 / token 过期重登
（同 session_id、换 key）也保留模型**（只是重新授权）；重新登录生成新
session_id 才是新模型。旧实现在 ``bind()`` 里比对凭据并删快照
（``_drop_stale_state``）——那让 token 的寿命决定了模型的寿命，已删。

B1 按人隔离：注册表在上层 session_service，一 (owner, session_id) 一实例
一环。线程模型：读 worker stdout 的 pump 线程 + 提交走锁——FastAPI 侧
永不阻塞。

B2 会话落盘：输出环全量追加流（log.jsonl，本类写/读）与会话 f 快照
（session_state.json，worker 写）按 (owner, session_id) 落系统空间——
worker 重生 / 服务重启不再「世界消失」。**落盘不含任何凭据**（见下）。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from genie.studio.session_client import DEFAULT_SESSION

_WORKER = Path(__file__).with_name("kernel_worker.py").resolve()
MAX_LINES = 4000          # 输出环上限（超出丢最旧——terminal 滚动语义）
_RING_CAP_BYTES = 1 << 20  # 环文件（=运行日志）限量：1MB，重启时截尾
_KEEP_SESSIONS = 8         # 每 owner 保留的会话目录数（GC 上限）
_GC_MIN_AGE_S = 7 * 86400  # 且只清 7 天以前创建的（新会话不动）


def workspace_root() -> Path:
    """脚本/产物工作区根（B1 按人隔离：其下再按 owner 分一层）。

    解析链与 session 服务落位一致：GENIE_SESSION_CWD → GENIE_SCRIPTS_DIR
    → 缺省 ~/data/genie/scripts。

    **唯一一份**（M2）：此前 studio 侧另有一份 ``GENIE_SCRIPTS_DIR`` 解析，
    只设 ``GENIE_SESSION_CWD`` 时两处得出不同根目录——"文件面板看不到脚本"
    的根源。现在双方都调本函数。
    """
    return Path(os.environ.get("GENIE_SESSION_CWD")
                or os.environ.get("GENIE_SCRIPTS_DIR")
                or Path.home() / "data/genie/scripts")


def _session_root() -> Path:
    """系统空间根（2026-10-13 站长裁决搬家）：会话恢复快照与运行日志
    住这里，**不进用户工作区**（scripts/<owner>/ 只剩用户自己的文件——
    文件面板所见即所得，无需过滤规则）。解析：GENIE_SESSION_STATE_DIR
    → 缺省 ~/data/genie/session。"""
    return Path(os.environ.get("GENIE_SESSION_STATE_DIR")
                or Path.home() / "data/genie/session")


def backend() -> str:
    """提交上游（**部署环境的属性，不是请求的属性**）。

    客户端从不在请求里指定后端：会话自己知道，worker 据此建 Client。
    这条把"哪个后端"从每条请求里删掉了。
    """
    return (os.environ.get("GENIE_BACKEND")
            or os.environ.get("GENIE_INTERNAL_BACKEND")
            or "http://127.0.0.1:9100").rstrip("/")


def _session_dir(owner: str, session_id: str) -> Path:
    """会话目录：``session/<owner>/<session_id>/``。

    **兼容例外**（O2）：``session_id == "default"`` 用平铺的
    ``session/<owner>/``——这是 O2 之前唯一的布局，也是云宿主/旧客户端的
    缺省会话。于是"升级不动存量"：存量模型原地被 default 会话继续用，
    GUI 的具名会话则各占一层目录。
    """
    root = _session_root() / owner
    return root if session_id in ("", DEFAULT_SESSION) else root / session_id


def _owner_dir(owner: str) -> Path:
    """per-owner 工作目录（worker cwd = 脚本 savefig/open 相对路径产物
    的落点）：根/<owner>/，0700——按登录身份隔离工作区。

    **跨会话共享**（用户自己的文件在换模型后还在）：只有结果按会话分层。
    """
    d = workspace_root() / owner
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)      # mkdir 的 mode 受 umask 影响，落位后显式收紧
    return d


def results_dir(owner: str, session_id: str) -> Path:
    """本会话的结果目录（= worker 的 GENIE_RESULT_DIR，也是 GUI 读取点）。

    同样有 default 例外（平铺），理由同 ``_session_dir``。
    """
    d = _owner_dir(owner) / "genie_results"
    return d if session_id in ("", DEFAULT_SESSION) else d / session_id


class SessionKernel:
    """一 (owner, session_id) 一份会话管理器（spawn/重生 worker、输出环、凭据）。

    B2 落盘边界（铁律 1）：**落盘是恢复快照，不是第二份可编辑设计状态**
    ——唯一可编辑真源永远是会话进程内的 f；log.jsonl / session_state.json
    只服务「worker 重生 / 服务重启」后的自动恢复，从不回流编辑（v1 病灶 =
    静默双中心同步，任何复刻一律拒绝）。
    """

    def __init__(self, owner: str = "local",
                 session_id: str = "default") -> None:
        self._owner = owner    # 归属身份（目录名用，白名单由上层把关）
        self._session_id = session_id
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()          # 保护 lines/cfg/busy/seq
        self._wlock = threading.Lock()         # 串行化 stdin 写（提交/绑定）
        self._lines: list[dict] = []           # [{seq, text, kind, origin, ts}]
        # 环条目结构化（2026-10-11 站长裁决「输入输出按时间序/报错一次/
        # VS Code 形态」收口）：kind ∈ input/stdout/stderr/error/note
        # /job/job-done/job-progress/state（完整动词表 = session_client
        # 模块头注——job 族由 worker 发射，非预留）；origin ∈
        # worker/manager；ts 由 _emit 统一打。
        # text 逐字保留原文——kind 只是注解，不改一字。
        self._seq = 0
        self._cfg: dict | None = None
        self._cfg_seq = 0
        self._busy = False
        # 生命周期现值（2026-10 站长裁决「状态监测架构收敛」）：worker 的
        # state 事件驱动，output() 随响应回快照——GUI 刷新第一拍即对表，
        # 按钮/进度条零旁证（不重放历史、不猜文本）。
        self._phase = "idle"
        self._job_id = ""
        self._key = ""          # 授权凭据（可空）：换绑只改这一格
        self._next_id = 1
        # B2 会话落盘（目录 0700，文件 0600 各写点收紧）：
        #   log.jsonl          —— 输出环 JSONL 追加流（本类写，构造时读回）
        #   session_state.json —— 会话 f 快照（worker 原子写，不含凭据）
        _d = _owner_dir(owner)
        _s = _session_dir(owner, session_id)
        _s.mkdir(parents=True, exist_ok=True)
        os.chmod(_s, 0o700)
        self._ring_path = _s / "log.jsonl"
        self._state_path = _s / "session_state.json"
        self._migrate_legacy()
        self._gc_sessions()
        self._ring_fh = None                   # 常开追加句柄（首条 emit 打开）
        self._restore_ring()                   # seq 续接：起点 = 文件最大 seq

    # ---- 身份 ----

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def session_id(self) -> str:
        return self._session_id

    # ---- 对宿主端点的接口 ----

    def attach(self, key: str = "") -> dict:
        """凭据换绑（幂等）——**换 key 不换模型、不重生进程**。

        这是 O2 的核心动作：token 轮换、改密码、过期后重新登录，都只走这里。
        首次调用（进程还没起）建空模型（域/网格/材料全空，无任何默认值）；
        之后只把新 key 交给 worker 更新各实例的 Client 头——进程、目录、
        快照一律不动。**要新模型请换 session_id**（上层注册表按 session
        分支，那是另一个 SessionKernel）。
        """
        key = key or ""
        if not key and self._key:
            # 空凭据的绑定请求**不得降级**已绑定的会话（console 没有 token，
            # 它 attach 时不该把会话的钥匙拔掉）。要换掉凭据请显式给新 key。
            return {"session_id": self._session_id, "key_changed": False,
                    "alive": self._alive}
        changed = key != self._key
        self._key = key
        if not self._alive:
            self._respawn()          # 首次：spawn 时顺带挂 key
        elif changed:
            self._send({"op": "attach", "url": backend(), "key": key})
        return {"session_id": self._session_id, "key_changed": changed,
                "alive": self._alive}

    def _begin(self) -> None:
        """一次执行的公共前置（忙/相位）。exec id 由调用方取号。"""
        self._set_busy(True)
        with self._lock:
            self._phase = "exec"

    def submit(self, code: str, *, mode: str = "run",
               label: str = "") -> int:
        """整段代码提交到会话 exec → exec id（输出走 output(since) 增量拉）。

        ``mode``（M3）：
          - ``run``  —— 在**当前命名空间**里执行（终端语义：f 常驻、状态累积）；
          - ``build`` —— 在**新命名空间**里执行，成功才原子替换当前模型
            （脚本语义：结果只由脚本内容决定；失败零副作用，无回滚）。

        发 worker 前先把 input 事件写环（mark=label 透传执行来源标注）：
        seq 天然先于该次全部输出——GUI echo 由服务端唯一负责，输入输出
        按时间序（客户端直插 echo 刷新即丢，已废）。"""
        self._ensure()
        eid = self._next_id
        self._next_id += 1
        self._emit("input", code, "manager", mark=label)
        self._begin()
        self._send({"op": "exec", "id": eid, "code": code,
                    "mode": mode if mode in ("run", "build") else "run",
                    "url": backend(), "key": self._key})
        return eid

    def run(self, *, gpu: int | None = None,
            timeout_s: int | None = None) -> int:
        """提交**当前模型**（= 工具栏 Run / terminal 的 run_model()）。

        **不改模型**：模型没变，所以没有改名、没有重建、没有对象替换。
        旧实现是"往终端里打一行 f.run()"，于是按钮的语义取决于终端命名
        空间里恰好有个没被换掉的 f——那是把意图写成了文本。
        """
        self._ensure()
        eid = self._next_id
        self._next_id += 1
        self._begin()
        self._send({"op": "run", "id": eid, "gpu": gpu,
                    "timeout_s": timeout_s,
                    "url": backend(), "key": self._key})
        return eid

    def patch(self, ops: list) -> int:
        """模型**路径级增量**（M3b）：表单/树/工具条的一次改动。

        客户端只发它改了什么（不再发整份文档）——服务端是权威，回声带
        origin=patch 与已应用路径，前端据此跳过整面板重渲染。"""
        self._ensure()
        eid = self._next_id
        self._next_id += 1
        self._begin()
        self._send({"op": "patch", "id": eid, "ops": list(ops or []),
                    "url": backend(), "key": self._key})
        return eid

    def replace(self, model: dict) -> int:
        """整份模型替换（.gensim 导入 / 搬运）。"""
        self._ensure()
        eid = self._next_id
        self._next_id += 1
        self._begin()
        self._send({"op": "replace", "id": eid, "model": model,
                    "url": backend(), "key": self._key})
        return eid

    def stop(self) -> bool:
        """停止当前执行（A2「长任务必须能掐」）：向 worker 发 SIGINT。

        worker 侧状态感知：exec 期 → StopExec 掐断 + 孤儿作业清理；
        空闲期 → 忽略（worker 永不因 SIGINT 死亡）。非忙/进程已死
        返回 False（无事可停）；信号发不出去（OSError）同样 False。"""
        if not (self._alive and self._busy):
            return False
        try:
            if os.name == "nt":
                # Windows 不支持 send_signal(SIGINT)（ValueError: Unsupported
                # signal）。worker 起在独立进程组里，发 CTRL_BREAK_EVENT →
                # 子进程 SIGBREAK → kernel_worker 里同一处理器掐断（G33）。
                self._proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self._proc.send_signal(signal.SIGINT)
        except (OSError, ValueError):
            return False
        return True

    def output(self, since: int) -> dict:
        """读取会话快照（**纯读**，不唤起——唤起是产品策略，见 ``ensure()``）。"""
        with self._lock:
            lines = [l for l in self._lines if l["seq"] > since]
            return {"lines": lines, "busy": self._busy,
                    "phase": self._phase, "job_id": self._job_id,
                    "session_id": self._session_id,
                    "cfg": (self._cfg or {}).get("cfg") if self._cfg else None,
                    "resolved": (self._cfg or {}).get("resolved") if self._cfg else None,
                    "cfg_seq": self._cfg_seq,
                    "origin": (self._cfg or {}).get("origin") if self._cfg else None,
                    "paths": (self._cfg or {}).get("paths") if self._cfg else []}

    # ---- 内部 ----

    @property
    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ensure(self) -> None:
        """确保会话活着（**读即唤起**的产品策略入口）。

        为什么要它：Studio 与它会话同进程，Studio 重启 = 会话对象没了；而
        已经开着的页面只会轮询 ``/api/exec/output``，不会重新 attach。若轮询
        不唤起，页面会一直看到"空模型"——看起来像模型丢了，其实只是没人把
        它叫醒。轮询方要的本来就是"这个会话现在是什么样"，所以读 = 确保活着。

        唤起后 worker 会从快照重放并**主动回流一次 cfg**（见
        kernel_worker.replay_state），因此下一拍轮询就能拿到模型。
        """
        self._ensure()

    def _ensure(self) -> None:
        if not self._alive:
            self._respawn()

    # ---- 目录生命周期（O2：一 session 一目录）----

    def _migrate_legacy(self) -> None:
        """把平铺旧布局（``session/<owner>/session_state.json``）搬进**第一个**
        具名会话目录。

        只对具名会话（非 default）生效：default 会话本身就住在平铺路径上，
        搬它等于自己搬自己。升级后用户第一次登录会建立具名会话，它认领
        升级前的模型——不会凭空消失；搬移（``replace``）而非复制，防二次
        认领。
        """
        if self._session_id in ("", DEFAULT_SESSION):
            return
        legacy = _session_root() / self._owner
        if not legacy.is_dir() or self._state_path.exists():
            return
        for name in ("session_state.json", "log.jsonl"):
            src = legacy / name
            if not src.is_file():
                continue
            try:
                src.replace(_session_dir(self._owner, self._session_id) / name)
            except OSError:
                pass

    def _gc_sessions(self) -> None:
        """每 owner 保留最近的 _KEEP_SESSIONS 个会话目录，且只清 7 天前的。

        best-effort：清不掉（占用/权限）就不清，绝不拦住会话启动。
        """
        root = _session_root() / self._owner
        try:
            dirs = sorted((p for p in root.iterdir() if p.is_dir()),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return
        now = time.time()
        for i, p in enumerate(dirs):
            if i < _KEEP_SESSIONS:
                continue
            try:
                if now - p.stat().st_mtime < _GC_MIN_AGE_S:
                    continue
                for f in p.iterdir():
                    if f.is_file():
                        f.unlink()
                p.rmdir()
            except OSError:
                continue

    def _restore_ring(self) -> None:
        """环文件恢复（构造时一次；2026-10-13 站长裁决瘦身为 **log 语义**）：

        - 文件 = 仿真运行日志（崩溃审计）+ seq 基准，**不再回放历史进
          内存**——服务重启后终端是干净的（历史回放无价值：重启完没人
          回头看旧滚屏；已开页面 DOM 里的旧内容仍在，视觉不断）。
        - **seq 续接仍是核心**：GUI 游标单调取 max（term.js SessionSync），
          重启后新行 seq 若小于客户端游标 = 输出对已开页面永久隐身——
          起点 = 文件最大合法 seq。
        - **限量轮换**：超过 _RING_CAP_BYTES 就地截断保尾部（治无限
          追加的 wart）；尾部半行/坏行跳过不炸、其 seq 不污染基准。
        """
        try:
            raw = self._ring_path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return                     # 无环文件 = 全新会话
        if len(raw.encode("utf-8")) > _RING_CAP_BYTES:
            head = raw[-_RING_CAP_BYTES:]
            cut = head.find("\n")      # 从整行边界开始保留
            raw = head[cut + 1:] if cut >= 0 else head
            try:
                # newline="" = 不做换行翻译：上面按 UTF-8 字节数算上限，若落盘
                # 时被转成 CRLF，每行多 1 字节，截尾后文件仍超上限（G33 Windows）。
                self._ring_path.write_text(raw, encoding="utf-8", newline="")
            except OSError:
                pass                   # 截断失败不拦启动
        max_seq = 0
        for ln in raw.splitlines():
            try:
                e = json.loads(ln)
            except ValueError:
                continue               # 半行/垃圾行：跳过
            if isinstance(e, dict) and isinstance(e.get("seq"), int):
                max_seq = max(max_seq, e["seq"])
        with self._lock:
            self._seq = max_seq

    def _begin_job_log(self) -> None:
        """新仿真提交 → 日志覆盖前一次（2026-10-13 站长裁决：log.jsonl
        = 最近一次仿真的运行日志，不跨仿真追加）。内存环与 seq 不动
        （开着的页面滚动回放不受影响；seq 单调继续，文件从本条重新起记，
        重启时的基准 = 本文件最大 seq，仍然一致）。"""
        with self._lock:
            try:
                if self._ring_fh is not None:
                    self._ring_fh.close()
                self._ring_path.write_text("", encoding="utf-8")
                self._ring_fh = None
            except OSError:
                pass

    def _ring_append(self, entry: dict) -> None:
        """环条目落盘（B2，调用方持 _lock）：同步追加一行 JSONL——常开
        句柄 + 每条 write+flush，不 fsync（断电最多丢尾部，读回时半行
        容忍）。文件 0600。异常全吞：盘故障不得拖垮会话输出。"""
        try:
            if self._ring_fh is None:
                self._ring_fh = self._ring_path.open("a", encoding="utf-8", newline="")
                os.chmod(self._ring_path, 0o600)   # open 的 mode 受 umask 影响
            self._ring_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._ring_fh.flush()
        except OSError:
            self._ring_fh = None       # 句柄失效（盘满/被删）：下条重开再试

    def _respawn(self) -> None:
        with self._lock:
            # B2：环与 _seq 不再清——输出历史跨 worker 重生保留（清了就
            # 回不到 seq 续接，理由见 _restore_ring）；重生的全部语义 =
            # 杀旧进程、起新进程（f 由 worker 读 session_state.json 重放）。
            self._busy = False
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except OSError:
                pass
        sdk_root = str(_WORKER.parent.parent.parent)   # …/sdk（dev checkout 子进程也能 import genie）
        env = {**os.environ, "PYTHONPATH": sdk_root + os.pathsep +
               os.environ.get("PYTHONPATH", ""),
               # 系统文件搬家配套：state 绝对路径显式传递（worker 的
               # cwd 是用户工作区，不再从 cwd 猜系统路径）
               "GENIE_STATE_FILE": str(self._state_path),
               # O2：结果按会话分层（两个模型的结果不互相污染 latest）
               "GENIE_RESULT_DIR": str(results_dir(self._owner, self._session_id)),
               # 后端是部署属性：worker 从环境读，不从请求读
               "GENIE_BACKEND": backend()}
        # cwd = 本 owner 的脚本工作区（workspace 根/<owner>/，spawn 时落
        # 位 0700）——脚本内 savefig/open 的相对路径产物与 .py 同处一区
        cwd = _owner_dir(self._owner)
        # Windows：独立进程组 → stop() 才能发 CTRL_BREAK_EVENT（G33）
        _flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self._proc = subprocess.Popen(
            [sys.executable, "-u", str(_WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            bufsize=1, env=env,
            cwd=str(cwd),
            creationflags=_flags,
        )
        self._note("会话进程已启动"
                   + ("（凭据已挂）" if self._key else "（未登录——只能编辑）"))
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._pump_err, daemon=True).start()
        if self._key:
            self._send({"op": "attach", "url": backend(), "key": self._key})

    def _send(self, obj: dict) -> None:
        if not self._alive or self._proc.stdin is None:
            return
        try:
            with self._wlock:
                self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self._set_busy(False)

    def _emit(self, kind: str, text: str, origin: str, *, mark: str = "",
              data: dict | None = None) -> None:
        """环唯一写入口：统一打 ts（worker 不带时间，归一化在这里）。
        mark 仅 input 条目带（执行来源标注）；data 为结构化载荷
        （事件契约：job-done 带 {job_id}——G13②）。"""
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, "text": text, "kind": kind,
                     "origin": origin, "ts": time.time()}
            if mark:
                entry["mark"] = mark
            if data is not None:
                entry["data"] = data
            self._lines.append(entry)
            if len(self._lines) > MAX_LINES:
                del self._lines[: len(self._lines) - MAX_LINES]
            self._ring_append(entry)   # B2：append 环后同步落盘一行

    def _set_busy(self, v: bool) -> None:
        with self._lock:
            self._busy = v

    def _note(self, text: str) -> None:
        self._emit("note", f"── {text}\n", "manager")

    def _pump(self) -> None:
        """worker stdout：一行一个 JSON 事件 → 输出环 / cfg 快照 / done。"""
        proc = self._proc
        assert proc and proc.stdout
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                # 非 JSON 输出原样进 terminal（worker stdout 裸奔帧）
                self._emit("stdout", line + "\n", "worker")
                continue
            kind = ev.get("ev")
            if kind == "out":
                data = ev.get("data")
                # 生命周期 state 事件 → 现值跟踪（output 快照的数据源）
                if isinstance(data, dict) and data.get("phase"):
                    with self._lock:
                        self._phase = data["phase"]
                        if data.get("job_id"):
                            self._job_id = data["job_id"]
                        elif data["phase"] == "idle":
                            self._job_id = ""
                if isinstance(data, dict) and data.get("phase") == "submit":
                    self._begin_job_log()   # 新仿真 = 覆盖旧日志（站长裁决）
                # kind 透传（worker 语义发射点带 note/error/job-done）；
                # 缺省 = 纯 stdout chunk（_Out 捕获）。text 逐字透传不改
                # 一字；data 结构化载荷随事件（G13② 事件契约）。
                self._emit(ev.get("kind") or "stdout",
                           ev.get("text", ""), "worker",
                           data=data)
            elif kind == "cfg":
                with self._lock:
                    self._cfg = {"cfg": ev.get("cfg"),
                                 "resolved": ev.get("resolved"),
                                 # M3 来源标记：客户端据此区分"我的写回来了"
                                 # 与"别人改了模型"（不再靠内容猜）
                                 "origin": ev.get("origin") or "exec",
                                 "paths": ev.get("paths") or []}
                    self._cfg_seq += 1
            elif kind == "done":
                # done.err 仍在协议里（API/agent 消费用）；terminal 显示由
                # worker 的 out 流唯一负责——traceback/⏱/回滚提示已在环里，
                # 不再二次打印（2026-10-11 站长裁决：报错只显示一次，
                # VS Code 式单面终端）。
                self._set_busy(False)
                with self._lock:
                    self._phase = "idle"    # done 兜底（worker state idle
                                            # 已先行，此处防事件丢失）
        # stdout EOF = worker 退出（B2：不再有「会话态已丢」——输出历史
        # 在环落盘里，会话 f 由 worker 重生时读 session_state.json 重放）
        self._note("会话进程退出——下次执行自动重生（输出历史保留，会话 f 由落盘恢复）")
        self._set_busy(False)

    def _pump_err(self) -> None:
        proc = self._proc
        assert proc and proc.stderr
        for line in proc.stderr:
            if line.strip():
                self._emit("stderr", "[err] " + line, "manager")
