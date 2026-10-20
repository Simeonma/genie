/* modules/mobile.js — 移动模式状态首页（<768px 显形；桌面隐藏）。
 *
 * 定位（2026-10 站长裁决）：移动端 = 会话的纯投影监控端——
 * 状态英雄区（phase/进度）+ 结果卡片流 + 终端流 + Run/Stop，
 * 编辑走「编辑」页（Tree+Inspector 同屏）。数据源 = 会话事件流
 * （term.js ingest 转喂 __mobilePhase/__mobileProgress/
 * __mobileJobDone）+ /api/result/meta。零本地权威，铁律 1 合身。 */
"use strict";

(function () {
  const PHASE_LABEL = {
    submit: "提交作业中…", queue: "云端排队中…", run: "计算中",
    download: "取回结果中…", exec: "执行中",
  };
  const KEYH = () => ({ "X-API-Key": localStorage.getItem("genie_v2_api_key") || "" });
  const $id = (id) => document.getElementById(id);

  let jobId = "", jobLabel = "";
  /* 作业激活态：最近 __mobilePhase 落在关键路径 phase 集合内。
   * 与 badge「未连接」解耦——badge 文本陈旧不等于作业没在跑。 */
  const ACTIVE_PHASES = { submit: 1, queue: 1, run: 1, download: 1 };
  let lastPhase = "";                            /* 最近一次 __mobilePhase 的 phase */
  function termBusy() {
    try { return !!(window.__termState && window.__termState().busy); } catch (e) { return false; }
  }
  function jobActive() { return !!ACTIVE_PHASES[lastPhase]; }
  /* r4②：badge 文本与作业激活态解耦——作业激活期间强制
   * CTA 隐藏、去掉红色警示；badge 降为中性灰（.m-stale，
   * 文本保留）。作业结束（lastPhase 退出激活集）恢复 badge 权威。 */
  function applyConnVisual() {
    const badge = $id("status-badge");
    const active = jobActive();
    const off = badgeOff && !active;
    if (badge) {
      badge.classList.toggle("m-disconnected", off);
      badge.classList.toggle("m-stale", badgeOff && active);
    }
       /* Run 看 busy；Stop 看 busy 或作业激活（与连接态无关） */
    /* r5③：CTA 扩展为「状态页 + 编辑页」两处——按类统一显隐 */
    document.querySelectorAll(".m-connect-cta").forEach((c) => { c.hidden = !off; });
    /* r6b⑥：有历史结果（__lastJobId）时 CTA 降级——
     * 全宽钮隐藏，英雄区尾部一行小链接接手（.m-cta-link）。 */
    const hasHistory = !!window.__lastJobId;
    /* r17：作业激活期（submit/queue/run/download）一律隐藏行内连接胶囊——
     * jobActive 优先于 badge 文本，避免作业跑着还显示「未连接 · 点此连接」。 */
    const mini = off && hasHistory && !jobActive();
    document.querySelectorAll(".m-connect-cta").forEach((c) => {
      c.classList.toggle("m-cta-mini", mini);
      if (mini) c.hidden = true;
    });
    const ctaLink = document.querySelector("#m-scene-status .m-cta-link");
    if (ctaLink) ctaLink.hidden = !mini;
    updateHeroIdle();
    sync3dEmpty();   /* r10：连接态翻转时复评 3D 空态 */
  }
  window.__mobileConnVisual = applyConnVisual;   /* phase 翻转与作业收尾都复评 */
  let heroBusy = false;                          /* 英雄区忙碌态（.m-idle 中性化用） */
  /* r6b：英雄区异常态机 —— "normal" | "err"（作业失败）| "stopped"（用户停止）。
   * 新作业 phase 进入激活集 / 成功收尾 → 回 normal。 */
  let heroMode = "normal";
  let wasActive = false;                         /* r6b：激活→空闲翻转探测（脚本级失败兜底） */
  let lastErrText = "";                          /* 最后一条 error/stderr 行（错误态判据） */
  /* r7①：错误态副文案取材候选——traceback 首行无信息量，缓存最近
   * 数条错误行，优先挑含 Error/错误/失败 的最后一条。 */
  const errLines = [];
  function pickErrText() {
    for (let i = errLines.length - 1; i >= 0; i--) {
      if (/Error|错误|失败/.test(errLines[i])) return errLines[i];
    }
    return errLines.length ? errLines[errLines.length - 1] : lastErrText;
  }
  let badgeOff = false;                          /* #status-badge 当前是否「未连接」 */
  let lastStep = 0, lastTot = 0, samples = [];   /* [{t, step}] ETA 滑窗 */
  /* r16b①：排队段已耗时——phase=queue 首次落地记起始时间戳，
   * 同一作业排队期间持续刷新；离开 queue（run/收尾）即清零。 */
  let queueSince = 0;
  function fmtElapsed(sec) {
    sec = Math.max(0, Math.floor(sec));
    const m = Math.floor(sec / 60), s = sec % 60;
    return "已耗时 " + m + ":" + String(s).padStart(2, "0");
  }
  function queueMeta() {
    setBar(null, "已提交，等待空闲卡",
           queueSince ? fmtElapsed(Date.now() / 1000 - queueSince) : "");
  }

  function fmtEta(sec) {
    if (!isFinite(sec) || sec <= 0) return "";
    return sec >= 90 ? "剩 " + Math.round(sec / 60) + " 分" : "剩 " + Math.round(sec) + " 秒";
  }
  function setBar(pct, l, r) {
    const f = $id("m-bar-fill");
    if (f && pct != null) f.style.width = Math.max(0, Math.min(100, pct)) + "%";
    const L = $id("m-meta-l"), R = $id("m-meta-r");
    if (L && l != null) L.textContent = l;
    if (R && r != null) R.textContent = r;
  }
  /* ⑤ 空态英雄区中性化：未连接或空闲无作业时降级为浅灰虚线框 */
  function updateHeroIdle() {
    const hero = document.querySelector("#m-scene-status .m-hero");
    if (!hero) return;
    if (heroMode !== "normal") {          /* r6b：err/stopped 态不做 idle 中性化 */
      hero.classList.remove("m-idle");
      return;
    }
    const off = !!badgeOff && !jobActive();
    hero.classList.remove("m-err", "m-stopped");   /* normal 态兜底清异常类（progress 路径等） */
    hero.classList.toggle("m-idle", off || (!heroBusy && !jobId));
  }
  /* r6b①②：err/stopped 英雄区 —— 类切换 + 文案 + 按钮行（延迟构建） */
  function setHeroButtons(hero, mode) {
    let row = hero.querySelector(".m-hero-btns");
    if (mode === "normal") { if (row) row.remove(); return; }
    if (!row) {
      row = document.createElement("div");
      row.className = "m-hero-btns";
      hero.appendChild(row);
    }
    row.innerHTML = "";
    const mk = (label, fn) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "m-hero-btn"; b.textContent = label;
      b.addEventListener("click", fn);
      row.appendChild(b);
    };
    if (mode === "err") {
      mk("查看终端", () => { if (window.Dock) Dock.activatePanel("term-dock"); });
      mk("回编辑", () => { if (window.Dock) Dock.activatePanel("json-panel"); });
    } else {
      mk("重新 Run", () => { if (typeof runScript === "function") runScript(); });
    }
  }
  function applyHeroMode() {
    const hero = document.querySelector("#m-scene-status .m-hero");
    if (!hero) return;
    const st = $id("m-state"), ph = $id("m-phase");
    hero.classList.toggle("m-err", heroMode === "err");
    hero.classList.toggle("m-stopped", heroMode === "stopped");
    if (heroMode === "err") {
      if (st) st.textContent = "运行失败";
      if (ph) ph.textContent = (pickErrText() || "作业执行失败").slice(0, 60);
    } else if (heroMode === "stopped") {
      if (st) st.textContent = "已停止";
      if (ph) ph.textContent = "会话仍在，可重新 Run";
    }
    setHeroButtons(hero, heroMode);
    updateHeroIdle();
  }
  function setHero(state, phase) {
    heroBusy = state === "busy";
    if (phase) lastPhase = phase;   /* 记录最近 phase，驱动 jobActive/Stop 可用性 */
                      /* phase 翻转 → Stop/Run 立即降级/恢复 */
    if (typeof window.__mobileConnVisual === "function") window.__mobileConnVisual();
    updateHeroIdle();
    const st = $id("m-state"), ph = $id("m-phase");
    if (!st || !ph) return;
    if (state === "busy" || jobActive()) {   /* 作业激活期按忙碌显示（会话 busy 抖动不回写「空闲」） */
      st.textContent = PHASE_LABEL[phase] || "执行中";
      if (phase !== "run") setBar(null, "", "");   /* 非计算段：不定宽条姿态 */
    } else {
      st.textContent = "空闲";
      ph.textContent = "等待作业——桌面 Run 或此处开始";
      setBar(0, "", "");
    }
  }

  /* ── 事件转喂入口（term.js ingest 调用）────────────────────── */
  /* Run 只因会话 busy 执行中禁用（termBusy 语义，boot.js __termState）。
   * 首次 exec 即自动连接（worker 用服务端 keys 绑定），未连接 ≠ 不能跑
   * ——此前按「未连接」badge 禁用造成死锁（移动端永远无法开始），已修。
 */
  window.__mobilePhase = function (d) {
    if (!d) return;
    if (d.job_id && d.job_id !== jobId) { jobId = d.job_id; samples = []; }
    if (d.job_id) jobId = d.job_id;
    /* r6b：新作业激活（尤其 phase=submit）→ 清 err/stopped 英雄区；
     * 脚本级失败（无 sim.run 就 raise，不产 job-done）用「激活→空闲
     * 翻转 + 终端含错误」兜底进错误态。 */
    const act = !!(d.phase && ACTIVE_PHASES[d.phase]);
    if (act) {
      if (d.phase === "submit") { lastErrText = ""; errLines.length = 0; }
      heroMode = "normal";
      wasActive = true;
    } else if (!d.busy && wasActive && heroMode === "normal" && lastErrText) {
      heroMode = "err";
      wasActive = false;
    } else if (!d.busy) {
      wasActive = false;
    }
    const ph = $id("m-phase");
    if (ph && d.job_id) ph.textContent = "作业 " + d.job_id + (jobLabel ? " · " + jobLabel : "");
    /* r16b①：排队段 meta 填真实信息（左=已提交等待空闲卡，右=已耗时 mm:ss）；
     * 离开 queue（run/download/收尾）清零起始戳。 */
    if (d.phase === "queue") {
      if (!queueSince) queueSince = Date.now() / 1000;
    } else if (d.phase) {
      queueSince = 0;
    }
    setHero(d.busy ? "busy" : "idle", d.phase);   
    applyHeroMode();                              /* r6b：异常态类/文案兜底覆写 */
    if (d.phase === "queue") queueMeta();         /* r16b①：setHero 清 meta 后补排队信息 */
  };
  window.__mobileProgress = function (d) {
    heroBusy = true; lastPhase = "run"; queueSince = 0; 
    if (heroMode !== "normal") heroMode = "normal";   /* 计算中 = 异常态翻篇 */
    if (typeof window.__mobileConnVisual === "function") window.__mobileConnVisual();
    updateHeroIdle();
    const st = $id("m-state");
    if (st) st.textContent = "计算中";
    const step = Number(d && d.step), nTot = Number(d && d.n_steps);
    if (!isFinite(step) || !isFinite(nTot) || nTot <= 0) return;
    if (d.job_id && d.job_id !== jobId) { jobId = d.job_id; samples = []; }
    const now = Date.now() / 1000;
    samples.push({ t: now, step });
    if (samples.length > 40) samples.shift();
    const pct = Math.round(step / nTot * 100);
    let eta = "";
    const s0 = samples[0];
    if (samples.length >= 2 && now - s0.t >= 5) {
      const rate = (step - s0.step) / (now - s0.t);
      eta = fmtEta(rate > 0 ? (nTot - step) / rate : NaN);
    }
    setBar(pct, "step " + step + " / " + nTot, eta);
  };
  window.__mobileJobDone = function (d) {
    if (d && d.job_id) { jobId = d.job_id; }
    queueSince = 0;
    const st = $id("m-state");
    /* r6b①：ok===false 且终端里确有错误行 → 错误态英雄区；成功/无凭据回 normal */
    heroMode = (d && d.ok === false && lastErrText) ? "err" : "normal";
    if (heroMode === "normal") { lastErrText = ""; errLines.length = 0; }   /* 成功收尾清错误凭据 */
    if (st) st.textContent = heroMode === "err" ? "运行失败" : "作业完成";
    setBar(100, "", "");
    lastPhase = "";                    /* 退出激活集：连接警示恢复 badge 权威 */
    if (typeof window.__mobileConnVisual === "function") window.__mobileConnVisual();
    else 
    applyHeroMode();
  };

  /* r10：3D 页未连接空态——mobile 模式、**确实无场景内容**时显示
   * .m-3d-empty 覆盖层（提示 + 「连接服务」代理 #login-toggle）。
   * r12 判定修正：不再按 #status-badge 文本猜（未连接但会话有恢复
   * 数据时旧判定误伤——覆盖层挡住真场景）。改看会话配置本身：
   * window.getCfg() 返回非空对象 = 会话有恢复/当前配置 = 有场景，
   * 无论连接态徽标如何一律放行；未连接且无 cfg 才显示。桌面零改动。 */
  function sceneHasCfg() {
    try {
      const c = (typeof window.getCfg === "function") ? window.getCfg() : null;
      return !!c && typeof c === "object" && Object.keys(c).length > 0;
    } catch (e) { return false; }
  }
  function sync3dEmpty() {
    const c = $id("three-container");
    if (!c || !document.body.classList.contains("mobile-mode")) return;
    let ov = c.querySelector(".m-3d-empty");
    const hasContent = sceneHasCfg();
    if (hasContent) { if (ov) ov.remove(); return; }
    if (ov) return;
    ov = document.createElement("div");
    ov.className = "m-3d-empty";
    const msg = document.createElement("div");
    msg.className = "m-3d-empty-msg";
    msg.textContent = "连接后此处显示 3D 场景";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "m-3d-empty-btn";
    btn.textContent = "连接服务";
    btn.addEventListener("click", () => {
      const lt = $id("login-toggle");
      if (lt) lt.click();
    });
    ov.appendChild(msg); ov.appendChild(btn);
    c.appendChild(ov);
  }
  window.__mobileSync3dEmpty = sync3dEmpty;
  window.__mobilePageActive = function (panelId) {
    /* 状态卡页已取消（2026-10 裁决）*/
    /* r10：进 3D 页即评空态；并挂一次性 MutationObserver 盯 canvas 出现/移除 */
    if (panelId === "scene-panel" && document.body.classList.contains("mobile-mode")) {
      sync3dEmpty();
      const c = $id("three-container");
      if (c && !c.__m3dObs) {
        c.__m3dObs = new MutationObserver(sync3dEmpty);
        c.__m3dObs.observe(c, { childList: true, subtree: true });
      }
    }
    /* r6b⑤：首次进入 3D 页 → 一次性手势提示条（localStorage 记已示），3 秒淡出 */
    if (panelId === "scene-panel" && document.body.classList.contains("mobile-mode")
        && !localStorage.getItem("genie_v2_m3d_hint")) {
      localStorage.setItem("genie_v2_m3d_hint", "1");
      const tip = document.createElement("div");
      tip.className = "m-gesture-hint";
      tip.textContent = "单指旋转 · 双指缩放";
      document.body.appendChild(tip);
      setTimeout(() => tip.classList.add("m-fade"), 2500);
      setTimeout(() => tip.remove(), 3100);
    }
  };

  /* ── 操作条 ── */
  document.addEventListener("DOMContentLoaded", () => {
    /* r6b③ + r12：终端流「↓ 最新」悬浮回底钮——从 .m-term 泛化为
     * attachJumpBtn(scroller, host)：scroll 监听、离开底部（>24px）显示、
     * 点击回底。复用于 #term-out（运行页 Terminal，host = #term-card）。 */
    function attachJumpBtn(scroller, host) {
      if (!scroller || !host || scroller.__mJump) return;
      scroller.__mJump = true;
      if (getComputedStyle(host).position === "static") host.style.position = "relative";
      const jump = document.createElement("button");
      jump.type = "button";
      jump.className = "m-term-jump";
      jump.hidden = true;
      jump.setAttribute("aria-label", "回到底部");
      jump.textContent = "↓ 最新";
      host.appendChild(jump);
      const atBottom = () =>
        scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 24;
      scroller.addEventListener("scroll", () => { jump.hidden = atBottom(); });
      jump.addEventListener("click", () => {
        scroller.scrollTop = scroller.scrollHeight;
        jump.hidden = true;
      });
    }
    const tout = $id("term-out");
    if (tout) attachJumpBtn(tout, $id("term-card") || tout.parentNode);

    /* ④ 未连接 CTA：英雄区下方全宽「连接服务」次级行动条（移动媒体块才显形）。
     * 点击 = 代理 #login-toggle（连接对话框原件，桌面零改动）。 */
    const hero = document.querySelector("#m-scene-status .m-hero");
    if (hero && !$id("m-connect-cta")) {
      const cta = document.createElement("button");
      cta.type = "button";
      cta.id = "m-connect-cta";
      cta.className = "m-connect-cta";
      cta.hidden = true;   /* 初始隐藏，applyBadge 按连接态接管 */
      cta.textContent = "连接服务";
      cta.addEventListener("click", () => {
        const lt = $id("login-toggle");
        if (lt) lt.click();
      });
      hero.after(cta);
    }

    /* r6b⑥：CTA 降级形态——英雄区尾部一行小链接（有历史结果时替换全宽钮） */
    if (hero && !hero.querySelector(".m-cta-link")) {
      const link = document.createElement("button");
      link.type = "button";
      link.className = "m-cta-link";
      link.hidden = true;   /* applyConnVisual 按连接态 + 历史结果接管 */
      link.textContent = "未连接 · 点此连接";
      link.addEventListener("click", () => {
        const lt = $id("login-toggle");
        if (lt) lt.click();
      });
      hero.appendChild(link);
    }

    /* r5③ 树页 CTA 已删（M1 裁决）：桌面树顶常驻「连接服务」与
     * 顶栏登录按钮职责重复——登录入口只留 #login-toggle 一处。 */

    updateHeroIdle();
    sync3dEmpty();   /* r10：初始加载也评一次（mobile 模式下 scene 页空态） */

    /* ── r5①：Inspector 折叠分组移动端默认全展开 ──
     * 机制（views/form.js _sec/_msec）：.sec-head.collapsed + body.style.display=none。
     * 移动模式下渲染钩子后把折叠组全部置开；用 MutationObserver 兜
     * renderInspector 的任意重渲染（选树节点/改对象），class 变更不触发
     * childList observer，无回环。 */
    function expandMobileSections() {
      if (!document.body.classList.contains("mobile-mode")) return;
      document.querySelectorAll("#config-panel .sec-head.collapsed").forEach((h) => {
        const body = h.nextElementSibling;
        h.classList.remove("collapsed");
        if (body) body.style.display = "";
        h.setAttribute("aria-expanded", "true");
      });
    }
    const cfgContent = $id("config-content");
    if (cfgContent) {
      new MutationObserver(expandMobileSections)
        .observe(cfgContent, { childList: true, subtree: true });
    }
    const cfgPanel = $id("config-panel");
    if (cfgPanel) {
      /* 面板收养/换页也会换入内容——面板级 observer 兜底 */
      new MutationObserver(expandMobileSections)
        .observe(cfgPanel, { childList: true });
      expandMobileSections();
    }

    /* ── r5④：结果页空态可操作——「去编辑页添加监视器」按钮 ──
     * 只在移动媒体块显形（base display:none，桌面零改动）。 */
    const ve = $id("viz-empty");
    if (ve && !ve.querySelector(".m-viz-goedit")) {
      const go = document.createElement("button");
      go.type = "button";
      go.className = "m-viz-goedit";
      go.textContent = "去编辑页添加监视器";
      go.addEventListener("click", () => {
        if (window.Dock && typeof Dock.activatePanel === "function")
          Dock.activatePanel("struct-panel");
      });
      ve.appendChild(go);
    }

    /* 连接态判据（M1）：登录 token 在否（#status-badge 已删——静态
     * 「未连接」纯误导）。boot.js 在登录态翻转时派发 genie-login
     * 事件；此处初始评一次 + 监听翻转。
     * ③ 同一回调同步 Run/Stop 降级；④ 同步「连接服务」CTA 显隐；
     * ⑤ 同步英雄区 .m-idle 中性化。 */
    const applyLogin = () => {
      badgeOff = !localStorage.getItem("genie_v2_api_key");
      applyConnVisual();
    };
    window.addEventListener("genie-login", applyLogin);
    applyLogin();
  });
})();

  /* ── R22 类别 chip 工具条：点类别 → 按钮面板挂 .m-pop-host（条外
   * 宿主，不被横滑容器裁剪）；面板外点击/桌面模式 → 归还原位。 ── */
  const MQT = window.matchMedia("(max-width: 767px)");
  const wsBar = document.getElementById("workspace-bar");
  let popBtns = null, popHome = null, popBox = null;
  function closeToolsPop() {
    if (!popBtns || !popHome) return;
    /* 归还原盒（dataset.homeIndex）——此前还到 workspace-bar 直下，
     * 导致盒子丢按钮 + 同类别再点找不到按钮永不收起（站长实测缺陷） */
    const idx = Number(popBtns.dataset.homeIndex ?? -1);
    const boxes = [...document.querySelectorAll("#workspace-bar .obj-toolbar > .tb-box")];
    const home = boxes[idx];
    if (home) home.appendChild(popBtns);
    else popHome.parentNode.insertBefore(popBtns, popHome);
    document.querySelectorAll("#workspace-bar .tb-box.m-open").forEach((b) => b.classList.remove("m-open"));
    popBtns = null; popHome = null; popBox = null;
  }
  function toolsChipToggle(titleEl) {
    const box = titleEl.closest(".tb-box");
    const isOpen = popBox === box;
    closeToolsPop();
    if (isOpen) return;
    const btns = box.querySelector(".tb-box-btns");
    if (!btns) return;
    const boxIdx = [...wsBar.querySelectorAll(".obj-toolbar > .tb-box")].indexOf(box);
    btns.dataset.homeIndex = String(boxIdx);
    const host = wsBar.querySelector(".m-pop-host");
    host.appendChild(btns);
    popBtns = btns; popHome = host; popBox = box;
    box.classList.add("m-open");
  }
  function toolsSetup() {
    const bar = document.getElementById("workspace-bar");
    if (!bar || bar.querySelector(".m-pop-host")) return;
    const host = document.createElement("div");
    host.className = "m-pop-host";
    bar.appendChild(host);
    /* 触屏 tap 激活层（R23）：横滑条带内抖动会被判成滚动、吃掉
     * click——统一 pointerdown/up 阈值判定（8px），未移动的抬起
     * = tap。桌面鼠标不受影响（pointerType=mouse 走原生 click）。 */
    let ptr = null, moved = false, suppressUntil = 0, inProgram = false;
    bar.addEventListener("pointerdown", (e) => {
      /* 仅移动模式激活（桌面走原生 click）；全指针类型统一走阈值层
       * （窄窗 + 鼠标的移动模式同样需要 chip 激活） */
      if (!document.body.classList.contains("mobile-mode")) return;
      ptr = { x: e.clientX, y: e.clientY, target: e.target, type: e.pointerType };
      moved = false;
      suppressUntil = performance.now() + 800; /* 触摸手势期压原生 click */
    });
    bar.addEventListener("pointermove", (e) => {
      if (!ptr) return;
      if (Math.hypot(e.clientX - ptr.x, e.clientY - ptr.y) > 8) moved = true;
    });
    bar.addEventListener("pointerup", (e) => {
      if (!ptr) return;
      const t = ptr; ptr = null;
      if (t.moved) return;                     /* 滑动：交给原生滚动 */
      const title = t.target.closest(".tb-box-title");
      if (title) { toolsChipToggle(title); return; }
      const act = t.target.closest(".tb-box-btns .tb-btn, #run-mount .run-btn");
      if (act) {
        inProgram = true;
        try { act.click(); } finally { inProgram = false; }
        suppressUntil = performance.now() + 450;
      }
    });
    /* 捕获期抑制：触摸手势后的原生 click 在抑制窗内被吃掉（防双触发） */
    bar.addEventListener("click", (e) => {
      if (inProgram) return;
      if (performance.now() < suppressUntil) { e.stopPropagation(); }
    }, true);
    document.addEventListener("click", (e) => {
      if (!document.body.classList.contains("mobile-mode")) return;
      if (e.target.closest("#workspace-bar")) return;
      closeToolsPop();
    });
  }
  function toolsTeardown() { closeToolsPop(); }
  toolsSetup();
  MQT.addEventListener("change", () => { MQT.matches ? toolsSetup() : toolsTeardown(); });


