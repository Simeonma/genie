#!/usr/bin/env bash
# publish.sh — SDK 发版（单仓流程：本仓即 SDK 源码仓，2026-10-18 拆包后）
#
# 用法:  bash tools/publish.sh <版本号，如 2.0.1>
# 前提:  pyproject.toml 与 genie-sdk/__init__.py 版本号已同步。工作树除这两处
#       版本号外必须干净——第 ⓿ 步会拒绝任何其它在途改动（多 session 共写
#       纪律：禁止把别 session 的工作随发布一起快照入库）。
#       注：源码目录名 genie-sdk，包名仍是 genie（pyproject 的 package-dir 映射）；
#       脚本里凡读「源树」的路径写 genie-sdk/，凡读「wheel 内」的路径仍写 genie/。
#
# 流程:
#   ⓿ 工作树校验（只允许版本号两处在途）
#   ① 版本双处一致性校验
#   ② 清构建中间物 → 构建 wheel
#   ③ 发布门：index 引用逐条命中 / 产物与源树逐字节 / 无内部文档 / 无数据
#   ④ 提交并推 main（源码）
#   ⑤ 换 dist 孤儿分支（wheel，-f 绕过 .gitignore）
#   ⑥ GitHub Release（tag=v<版本>）
set -euo pipefail

VER="${1:?用法: publish.sh <版本号>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "── ⓿ 工作树校验（只允许版本号两处在途）"
DIRTY="$(git status --porcelain)"
STRAY="$(printf '%s\n' "$DIRTY" \
  | grep -vE '^( M|M |MM|A |AM) (pyproject\.toml|genie-sdk/__init__\.py)$' \
  | grep -v '^$' || true)"
if [ -n "$STRAY" ]; then
  echo "!! 工作树含版本号以外的改动，拒绝发布——先提交或 stash 它们："
  printf '%s\n' "$STRAY"
  exit 1
fi
echo "   ok"

echo "── ① 版本校验"
grep -q "version = \"$VER\"" pyproject.toml || { echo "!! pyproject 版本不是 $VER"; exit 1; }
grep -q "__version__ = \"$VER\"" genie-sdk/__init__.py || { echo "!! __init__ 版本不是 $VER"; exit 1; }

echo "── ② 构建 wheel"
rm -rf build dist ./*.egg-info
"$HOME/venvs/gpufdtd/bin/python" -m pip wheel . -w dist --no-deps -q
WHL="$(ls "$ROOT"/dist/*.whl)"
WHL_NAME="$(basename "$WHL")"
cp "$WHL" /tmp/"$WHL_NAME"

echo "── ③ 发布门"
python3 - "$WHL" "$ROOT" <<'PY'
import hashlib, re, sys, zipfile
whl, root = sys.argv[1], sys.argv[2]
zf = zipfile.ZipFile(whl); names = zf.namelist()
assert any('genie/models/' in n for n in names), "缺 models"
assert any('genie/manual/' in n for n in names), "缺 manual"
assert any('genie/examples/' in n for n in names), "缺 examples"
assert any('/static/modules/' in n for n in names), "缺前端 modules"
assert any('/static/views/' in n for n in names), "缺前端 views"
assert not any('genie_results' in n for n in names), "数据残留!"
assert not any('proposals/' in n for n in names), "内部提案混入!"
idx = next(n for n in names if n.endswith('studio/static/index.html'))
html = zf.read(idx).decode()
refs = re.findall(r'(?:src|href)="(/[^"]+)"', html)
# 绝对 URL 引用按命名空间落到各自的内容根：manual/examples 已移出
# studio/static（2026-10 拆分），但对外 URL 不变。
ROOTS = (('/manual/', 'genie/manual/'), ('/examples/', 'genie/examples/'))
def target(ref):
    for url, pkgpath in ROOTS:
        if ref.startswith(url):
            return pkgpath + ref[len(url):]
    return 'genie/studio/static' + ref
missing = [r for r in refs
           if not any(n.endswith(target(r)) for n in names)]
assert not missing, f"index 引用缺失 {len(missing)} 条: {missing}"
# 手册插图：页面引用的 figs/* 必须都在产物里。2026-10-21 拆分时实测的坑——
# 旧规则 static/manual/commands/* 不跨目录，figs/ 下 34 个文件从未进过
# wheel，发出去的手册全是碎图而门禁没抓（当时只查 index.html 的引用）。
pages = [n for n in names
         if n.startswith('genie/manual/commands/') and n.endswith('.html')]
bad_figs = [(p, r) for p in pages
            for r in re.findall(r'src="(figs/[^"]+)"', zf.read(p).decode('utf-8', 'ignore'))
            if not any(n.endswith('genie/manual/commands/' + r) for n in names)]
assert not bad_figs, f"手册插图缺失 {len(bad_figs)} 条: {bad_figs[:5]}"
src = open(f"{root}/genie-sdk/studio/static/index.html", 'rb').read()
assert hashlib.sha256(zf.read(idx)).digest() == hashlib.sha256(src).digest(), \
    "产物 index.html 与源树不一致（陈旧副本）"
print(f"   发布门通过: {len(names)} 文件 / {len(refs)} 条引用全命中 / index 字节一致")
PY

echo "── ④ 提交并推 main"
git add -A
git diff --cached --quiet || git commit -q -m "release: genie SDK $VER"
git push -q origin main

echo "── ⑤ dist 分支换 wheel"
git checkout -q --orphan dist-tmp
git rm -rq --cached .
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
mkdir -p dist && cp /tmp/"$WHL_NAME" dist/
git add -f dist/*
git commit -q -m "wheel: genie $VER"
git push -q --force origin dist-tmp:dist
git checkout -q main
git branch -D dist-tmp -q

echo "── ⑥ GitHub Release v$VER"
python3 - "$VER" <<'PY'
import json, subprocess, sys, urllib.request
ver = sys.argv[1]
token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
body = f"""genie SDK {ver}。

```bash
# GitHub 直连（若 raw.githubusercontent.com 可达）
pip install https://github.com/Simeonma/genie-sdk/raw/dist/dist/genie-{ver}-py3-none-any.whl
# CDN 镜像（国内网络推荐：raw.githubusercontent 常不可达）
pip install https://cdn.jsdelivr.net/gh/Simeonma/genie-sdk@dist/dist/genie-{ver}-py3-none-any.whl
```

源码：本仓 main（Apache-2.0）。wheel 亦在 `dist` 分支。"""
req = urllib.request.Request(
    "https://api.github.com/repos/Simeonma/genie-sdk/releases",
    data=json.dumps({"tag_name": f"v{ver}", "name": f"genie SDK {ver}",
                     "body": body, "prerelease": "a" in ver}).encode(),
    method="POST",
    headers={"Authorization": f"token {token}", "Content-Type": "application/json"})
print("   release:", json.load(urllib.request.urlopen(req))["html_url"])
PY

echo "── 完成。 $VER"
