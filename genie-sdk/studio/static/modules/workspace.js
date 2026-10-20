/* modules/workspace.js — 工作区文件面板（B3/B4：列/看/传/下）
 * G5 拆分（2026-10-14）：自 app.js 机械切出，零行为变化；
 * 经典 script 按序加载，跨模块引用为运行期全局查找。 */
/* ══ 工作区文件面板（B3/B4）：脚本 + savefig 图片 + 数据文件统一列、
 * 看、传、下。col3「文件」标签卡；.py 编辑仍走 col4 脚本工作流——
 * 这里只管文件本体。上传 = multipart 流式（/api/workspace/upload）；
 * 图片点行内联预览（/api/workspace/raw media_type 直出）；删除用户
 * 全权（服务端无脑执行，GUI 只 confirm 一声）。 */
const FILE_KIND_GLYPH = { script: "PY", image: "IMG", data: "DAT", other: "•" };

function fmtFileSize(n) {
  if (n == null) return "";
  const u = ["B", "KB", "MB", "GB"];
  let v = n, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (i === 0 ? v : v.toFixed(1)) + " " + u[i];
}

async function loadWorkspaceFiles() {
  const tb = $("files-tbody");
  if (!tb) return;
  const KEYH = { "X-API-Key": localStorage.getItem("genie_v2_api_key") || "" };
  let files = [];
  try {
    const r = await fetch("/api/workspace/files", { headers: KEYH });
    if (r.ok) files = ((await r.json()).files) || [];
  } catch { return; }        /* 未登录态静默——同「我的脚本」口径 */
  tb.innerHTML = "";
  const empty = $("files-empty");
  if (empty) empty.classList.toggle("hidden", files.length > 0);
  for (const f of files) {
    const tr = document.createElement("tr");
    tr.className = "files-row kind-" + f.kind;
    const tdK = document.createElement("td");
    tdK.className = "files-kind"; tdK.textContent = FILE_KIND_GLYPH[f.kind] || "•";
    tdK.title = f.kind;
    const tdN = document.createElement("td");
    tdN.className = "files-name"; tdN.textContent = f.name;
    const tdS = document.createElement("td");
    tdS.className = "files-size"; tdS.textContent = fmtFileSize(f.size);
    const tdD = document.createElement("td");
    const dl = document.createElement("a");
    dl.className = "files-dl";
    dl.href = "/api/workspace/raw?name=" + encodeURIComponent(f.name);
    dl.download = f.name;
    dl.textContent = "⬇"; dl.title = "下载 " + f.name;
    tdD.appendChild(dl);
    const tdX = document.createElement("td");
    const del = document.createElement("button");
    del.className = "mini files-del"; del.type = "button";
    del.textContent = "删"; del.title = "删除 " + f.name + "（不可恢复）";
    del.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!window.confirm("删除 " + f.name + "？（不可恢复）")) return;
      const r = await fetch("/api/workspace/delete", { method: "POST",
        headers: { "Content-Type": "application/json", ...KEYH },
        body: JSON.stringify({ name: f.name }) });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        toast("删除失败：" + (d.detail || ("HTTP " + r.status)), "err");
        return;
      }
      toast("已删除 " + f.name, "ok");
      loadWorkspaceFiles();
    });
    tdX.appendChild(del);
    /* 脚本：点行载入编辑器（工作区旧脚本的入口，G14 前置裁决：
     * 「我的脚本」下拉退役后收敛到此）；图片：点行内联预览 */
    if (f.kind === "script") {
      tr.classList.add("previewable");
      tr.title = "Click to load " + f.name + " into the editor";
      tr.addEventListener("click", async () => {
        const rd = await (await fetch("/api/scripts/read?name=" +
          encodeURIComponent(f.name), { headers: KEYH })).json();
        if (!rd || !rd.text) { toast("Read failed: " + f.name, "err"); return; }
        const ed = $("code-editor");
        ed.value = rd.text;
        ed.dispatchEvent(new Event("input", { bubbles: true }));
        toast("Loaded " + rd.name, "info");
      });
    }
    if (f.kind === "image") {
      tr.classList.add("previewable");
      tr.title = "点击预览 " + f.name;
      tr.addEventListener("click", () => showFilePreview(f.name));
    }
    tr.append(tdK, tdN, tdS, tdD, tdX);
    tb.appendChild(tr);
  }
}

function showFilePreview(name) {
  const pv = $("files-preview");
  if (!pv) return;
  pv.classList.remove("hidden");
  pv.innerHTML = "";
  const head = document.createElement("div");
  head.className = "files-preview-head";
  const ttl = document.createElement("span");
  ttl.className = "files-preview-name"; ttl.textContent = name;
  const x = document.createElement("button");
  x.className = "mini"; x.type = "button"; x.textContent = "×";
  x.title = "关闭预览";
  x.addEventListener("click", () => pv.classList.add("hidden"));
  head.append(ttl, x);
  const img = document.createElement("img");
  img.src = "/api/workspace/raw?name=" + encodeURIComponent(name);
  img.alt = name;
  pv.append(head, img);
}

/* 上传：钮 → 隐藏 input[file] → change → FormData POST（流式，进度
 * 由服务端分块落盘；本地小文件直接等结果）。同一文件可重复选（value 先清）。 */
(() => {
  const btn = $("files-upload"), inp = $("files-file");
  if (!btn || !inp) return;
  btn.addEventListener("click", () => inp.click());
  inp.addEventListener("change", async () => {
    const f = inp.files && inp.files[0];
    inp.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f, f.name);
    const KEYH = { "X-API-Key": localStorage.getItem("genie_v2_api_key") || "" };
    toast("上传中：" + f.name + "…", "info");
    try {
      const r = await fetch("/api/workspace/upload",
        { method: "POST", headers: KEYH, body: fd });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        toast("上传失败：" + (d.detail || ("HTTP " + r.status)), "err");
        return;
      }
      toast("已上传 " + d.name + "（" + fmtFileSize(d.size) + "）", "ok");
      loadWorkspaceFiles();

    } catch (e) { toast("上传失败：" + e, "err"); }
  });
})();
(() => {
  const rb = $("files-refresh");
  if (rb) rb.addEventListener("click", loadWorkspaceFiles);
})();
