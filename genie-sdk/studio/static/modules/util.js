/* modules/util.js — 基础工具（$ / fmtSI——全前端唯一公共依赖）
 * G5 拆分（2026-10-14）：自 app.js 机械切出，零行为变化；
 * 经典 script 按序加载，跨模块引用为运行期全局查找。 */
/* ── 基础 ──────────────────────────────────────────────────── */
const $ = (id) => document.getElementById(id);

/* v1 app.js 同款 SI 格式化（form.js:206 经 window.fmtSI 消费——
 * 组件对宿主的唯一全局依赖，原样搬运保持行为逐字节一致） */
function fmtSI(v, unit) {
  if (typeof v !== "number" || !isFinite(v)) return String(v);
  let s = v.toPrecision(4);
  if (!s.includes("e")) {
    // 只剥小数尾零（"30.00"→"30"）；无小数点的整数串不动（"2000"≠"2"）
    s = s.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  }
  return s + (unit || "");
}

/* v1 同款树元数据（GEO_TYPE_LABEL 在 previews.js） */
