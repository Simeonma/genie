/* modules/inspector.js — 检查器（FormPanel 只读驱动 + 参数面板 + 选中路由）
 * G5 拆分（2026-10-14）：自 app.js 机械切出，零行为变化；
 * 经典 script 按序加载，跨模块引用为运行期全局查找。 */
function renderInspector() {
  let k = inspectorSel.kind, i = inspectorSel.i;
  if (k === "params") { renderParamsPane(); return; }
  if (i != null && !((cfg[k] || [])[i])) i = null;
  inspectorSel = { kind: k, i };
  if (!cfg) {
    const c = $("config-content");
    c.textContent = "";
    const body = document.createElement("div");
    body.className = "pane-body";
    const es = document.createElement("div");
    es.className = "empty-state pane-empty-state";
    const ic = document.createElement("span");
    ic.className = "empty-ic";
    try { ic.appendChild(previewEl("domain")); } catch { /* 图标缺失忽略 */ }
    es.appendChild(ic);
    const t = document.createElement("div");
    t.className = "empty-title";
    t.textContent = "还没有模型";
    es.appendChild(t);
    const h = document.createElement("div");
    h.className = "empty-hint";
    h.textContent = "写一段脚本（或载入示例），按 Run / Ctrl+Enter 预览——"
      + "树、表单与 3D 会一起出现。";
    es.appendChild(h);
    body.appendChild(es);
    c.appendChild(body);
    return;
  }
  if (i == null) FormPanel.show(k);
  else {
    FormPanel.showInstance(k, i);
    if (k === "mon" || k === "monitor")
      /* 结果标签卡入口（监视器专属）——仅结果态渲染（2026-10-14
       * 站长裁决：编辑态 monitor 不携带数据、不提供新建 Plot；
       * 已画的 Plot 标签卡跨模式保留）。 */
      if (window.__resultMode) addMonitorPlotCta(i);
  }
}

/* 参数页（只读简化版：name/值 两列）
 * 2026-10-21：与其他面板对齐——不再有 22px 预览图标 + 大标题，改成一行
 * 小字说明（"只读 · 由脚本 # parameters 捕获"）+ 两列读数。 */
function renderParamsPane() {
  const c = $("config-content");
  c.textContent = "";
  const body = document.createElement("div");
  body.className = "pane-body";
  c.appendChild(body);
  const note = document.createElement("div");
  note.className = "pane-note";
  note.textContent = "只读 · 由脚本 # parameters 捕获";
  body.appendChild(note);
  const params = (cfg && cfg.parameters) || {};
  const keys = Object.keys(params);
  if (!keys.length) {
    const empty = document.createElement("div");
    empty.className = "pane-empty";
    empty.textContent = "脚本未声明参数。";
    body.appendChild(empty);
    return;
  }
  for (const k of keys) {
    const row = document.createElement("div");
    row.className = "frow";
    const l = document.createElement("label");
    l.className = "flabel";
    l.textContent = k;
    row.appendChild(l);
    const v = document.createElement("div");
    v.className = "small";
    v.style.wordBreak = "break-all";
    v.style.paddingTop = "5px";
    v.textContent = String(params[k]);
    row.appendChild(v);
    body.appendChild(row);
  }
}

function selectObj(kind, i) {
  treeSel = i == null ? { kind } : { kind, i: +i };
  renderTree();
  inspectorSel = { kind, i: i == null ? null : +i };
  renderInspector();
  /* 3D 联动高亮（2026-10-21 用户需求）：选中什么，3D 里就圈出什么。
   * 组/单例面板（domain/mesh/run/params）没有 3D 对象 → 清掉高亮。 */
  if (typeof scene !== "undefined" && scene && scene.highlightSelection) {
    const OBJ_KINDS = ["geometry", "source", "monitor", "materials"];
    if (i != null && OBJ_KINDS.indexOf(kind) >= 0) scene.highlightSelection(kind, i);
    else scene.clearHighlight();
  }
}

/* ══ 3D（v1 initScene 同款：WebGL→2D 降级 + 显示工具钮接线） ══ */
