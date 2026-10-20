/* modules/api.js — 会话身份 + 统一的失败措辞（M2/O2）
 *
 * 三件事在这里，且只在这里：
 *  1. **三生命周期分开存**：token（能不能提交）/ session_id（哪一份模型）/
 *     用户名（隔离到哪个目录）。旧代码把三者压在 token 上，于是"改密码"
 *     或"7 天过期"会连带模型消失。
 *  2. **一个失败出口**：`apiFailText()` 把 401/503/502 翻成人话，
 *     `apiNotice()` 做去重提示。旧代码有 6 处各自处理"会话不可用"，
 *     用户能看到 4 种不同表现（静默/一行红字/503/兜底）。
 *  3. **请求头统一注入**：X-API-Key 与 X-Session-Id 由 boot.js 的 fetch
 *     包装统一加，调用点不再手写（手写就会漏）。
 */
"use strict";

const SESSION_SID_KEY = "genie_v2_session_id";     /* 哪一份模型 */
const SESSION_USER_KEY = "genie_v2_session_user";  /* session 属于谁 */
const SESSION_TOKEN_KEY = "genie_v2_api_key";      /* 能不能提交 */

function genieToken() {
  try { return localStorage.getItem(SESSION_TOKEN_KEY) || ""; } catch { return ""; }
}

function genieSid() {
  try { return localStorage.getItem(SESSION_SID_KEY) || "default"; } catch { return "default"; }
}

/** 新建一个会话 id（= 新模型）。只生成，不落盘——由调用方决定去留。 */
function genieNewSid() {
  const c = (typeof crypto !== "undefined" && crypto.randomUUID)
    ? crypto.randomUUID() : (Date.now().toString(36) + Math.random().toString(36).slice(2));
  return String(c).replace(/[^\w\-]/g, "").slice(0, 64) || "default";
}

/**
 * 登录成功后确定本浏览器的 session_id。
 *
 * 规则（O2 的三生命周期正交）：
 *  - 没有 id，或**换了账号** → 新 id（新模型）；
 *  - 同一个账号再次登录（改密码、token 过期、手滑退出又登回）→ **沿用**
 *    id，模型保住；
 *  - 显式"退出登录"会把 id 删掉 → 下次登录必然是新的。
 */
function genieClaimSession(username) {
  let sid = "";
  try { sid = localStorage.getItem(SESSION_SID_KEY) || ""; } catch {}
  let owner = "";
  try { owner = localStorage.getItem(SESSION_USER_KEY) || ""; } catch {}
  if (!sid || (owner && username && owner !== username)) {
    sid = genieNewSid();
  }
  try {
    localStorage.setItem(SESSION_SID_KEY, sid);
    if (username) localStorage.setItem(SESSION_USER_KEY, username);
  } catch {}
  return sid;
}

/** 退出登录：模型身份一并作废（下次登录 = 新模型）。 */
function genieDropSession() {
  try {
    localStorage.removeItem(SESSION_SID_KEY);
    localStorage.removeItem(SESSION_USER_KEY);
  } catch {}
}

/** token 失效（401/吊销/过期）：只清凭据，**保留 session_id**——
 *  重新登录同一个账号应当回到同一个模型。 */
function genieDropToken() {
  try {
    localStorage.removeItem(SESSION_TOKEN_KEY);
    localStorage.removeItem("genie_v2_username");
  } catch {}
}

/** 失败原因 → 一句人话（唯一实现）。 */
function apiFailText(r, j) {
  const d = (j && (j.detail || j.message)) || "";
  if (r && r.status === 401) {
    return "登录已失效或用完了——请重新登录（右上角账号钮）";
  }
  if (r && r.status === 503) {
    return "会话进程不可用（本机内核没起来或已退出）——重启 Studio 后重试";
  }
  if (r && r.status === 502) {
    return d || "上游服务不可达";
  }
  if (d) return d;
  return r ? ("HTTP " + r.status) : "网络错误";
}

/* 同一句话 6 秒内只提示一次（轮询/连点不刷屏） */
let _apiNoticeAt = 0;
let _apiNoticeMsg = "";

function apiNotice(msg, kind) {
  const now = Date.now();
  if (msg === _apiNoticeMsg && now - _apiNoticeAt < 6000) return;
  _apiNoticeMsg = msg;
  _apiNoticeAt = now;
  try { toast(msg, kind || "err"); } catch { /* toast 未就绪不拦 */ }
}

/** 一次失败的统一处理：翻译 + 去重提示。返回那句人话（调用方可直接写终端）。 */
function apiFailed(where, r, j) {
  const text = apiFailText(r, j);
  if (r && r.status === 401) {
    /* 凭据死了：清 token（保留 session），按钮回「Connect」 */
    genieDropToken();
    const b = document.getElementById("login-toggle");
    if (b) { b.textContent = "Connect"; b.classList.remove("on"); b.classList.add("err"); }
  }
  apiNotice((where ? where + "：" : "") + text, "err");
  return text;
}
