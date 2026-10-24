#!/usr/bin/env python3
"""publish.py — SDK 发版（单仓流程：本仓即 SDK 源码仓）。

用法:
    python tools/publish.py <版本号>              # 完整发版
    python tools/publish.py <版本号> --dry-run    # 只跑到发布门，不提交不推送

前提：pyproject.toml 与 genie-sdk/__init__.py 的版本号已同步为该版本；
      工作树除这两处版本号外必须干净（第 ⓿ 步会拒绝其它在途改动——
      多 session 共写纪律：禁止把别 session 的工作随发布一起快照入库）。

流程:
    ⓿ 工作树校验（只允许版本号两处在途）
    ① 版本双处一致性校验
    ② 清构建中间物 → 构建 wheel
    ③ 发布门（产物级）
    ④ 提交并推 main（源码）
    ⑤ 重建 dist 孤儿分支（wheel）
    ⑥ GitHub Release（tag=v<版本>）

为什么不是 bash：原 publish.sh 写死了 ``$HOME/venvs/.../python`` 与 ``python3``，
在 Windows 上跑不了；且它用 ``git checkout --orphan`` + 清空工作树来造孤儿分支，
中途失败会把工作树留在半毁状态。这里改成 git 底层管道（hash-object / mktree /
commit-tree）直接造提交，**不碰工作树**，任何一步失败都能安全重来。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "genie-sdk"
PYPROJECT = ROOT / "pyproject.toml"
INIT = PKG / "__init__.py"
WHL_DIR = ROOT / "dist"

VERSION_FILES = ("pyproject.toml", "genie-sdk/__init__.py")


def _p(*args: object, file=None) -> None:
    # file kwarg 透传 print（2026-10-27：历史上 _fail/_run/_git 的失败路径
    # 都传了 file= 而本函数不收——任何报错先 TypeError，真错误信息从没打出来过）
    print(*args, file=file, flush=True)


def _run(cmd: list[str], *, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        _p(f"!! 命令失败 ({r.returncode}): {' '.join(cmd)}")
        if r.stdout.strip():
            _p(r.stdout.strip())
        if r.stderr.strip():
            _p(r.stderr.strip(), file=sys.stderr)
        raise SystemExit(1)
    return r


def _git(*args: str, check: bool = True, stdin: str | None = None) -> str:
    """跑 git 并返回 stdout。

    stdin 必须以 **bytes** 传入：Windows 的 subprocess 在文本模式下会把 ``\\n``
    自动翻成 CRLF，喂给 ``git mktree`` 会变成文件名里的 ``\\r``（踩过）。
    """
    if stdin is None:
        return _run(["git", *args], check=check).stdout
    r = subprocess.run(["git", *args], cwd=str(ROOT),
                       input=stdin.encode("utf-8"), capture_output=True)
    if check and r.returncode != 0:
        _p(f"!! git {' '.join(args)} 失败", file=sys.stderr)
        _p(r.stderr.decode("utf-8", "replace").strip(), file=sys.stderr)
        raise SystemExit(1)
    return r.stdout.decode("utf-8", "replace")


def _fail(msg: str) -> None:
    _p(f"!! {msg}", file=sys.stderr)
    raise SystemExit(1)


# ── ⓿ 工作树校验 ──────────────────────────────────────────────────────────
def step0_worktree() -> None:
    _p("── ⓿ 工作树校验（只允许版本号两处在途）")
    if not (ROOT / ".git").exists():
        _fail(f"{ROOT} 不是 git 仓——发版要在公开仓里跑")
    porcelain = _git("status", "--porcelain")
    stray = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if path not in VERSION_FILES:
            stray.append(line)
    if stray:
        _p("!! 工作树含版本号以外的改动，拒绝发布——先提交或 stash 它们：")
        for s in stray:
            _p("   " + s)
        raise SystemExit(1)
    _p("   ok")


# ── ① 版本校验 ────────────────────────────────────────────────────────────
def step1_version(ver: str) -> None:
    _p("── ① 版本校验")
    py = PYPROJECT.read_text(encoding="utf-8")
    if not re.search(rf'^version\s*=\s*"{re.escape(ver)}"', py, re.M):
        _fail(f"pyproject.toml 的 version 不是 {ver}")
    ini = INIT.read_text(encoding="utf-8")
    if not re.search(rf'__version__\s*=\s*"{re.escape(ver)}"', ini):
        _fail(f"genie-sdk/__init__.py 的 __version__ 不是 {ver}")
    _p(f"   ok（ pyproject.toml / genie-sdk/__init__.py 均为 {ver} ）")


# ── ② 构建 wheel（SDK + protocol 双产物，2026-10-27 起）───────────────────
def step2_build() -> list[Path]:
    _p("── ② 构建 wheel（SDK + protocol）")
    for p in (ROOT / "build", WHL_DIR):
        if p.exists():
            shutil.rmtree(p)
    for p in ROOT.glob("*.egg-info"):
        shutil.rmtree(p, ignore_errors=True)
    for target in (".", "protocol"):
        r = _run([sys.executable, "-m", "pip", "wheel", target, "-w", str(WHL_DIR),
                  "--no-deps", "--no-build-isolation", "-q"], check=False)
        if r.returncode != 0:
            _p(r.stdout.strip())
            print(r.stderr.strip(), file=sys.stderr)
            _fail(f"wheel 构建失败（{target}；若缺 setuptools：python -m pip install setuptools）")
    whls = sorted(WHL_DIR.glob("*.whl"))
    names = [w.name for w in whls]
    ok = (len(whls) == 2
          and any(n.startswith("genie_sdk-") for n in names)
          and any(n.startswith("genie_protocol-") for n in names))
    if not ok:
        _fail(f"dist/ 里应当恰好两个 wheel（genie_sdk + genie_protocol），实际 {names}")
    for w in whls:
        _p(f"   {w.name}  ({w.stat().st_size / 1024 / 1024:.2f} MB)")
    return whls


# ── ③ 发布门（产物级）─────────────────────────────────────────────────────
def step3_gate(whl: Path) -> None:
    _p("── ③ 发布门")
    zf = zipfile.ZipFile(whl)
    names = zf.namelist()

    def need(cond: bool, label: str) -> None:
        _p(("   ✓ " if cond else "   ✗ ") + label)
        if not cond:
            raise SystemExit(1)

    need(any("genie/models/" in n for n in names), "必备面 models")
    need(any("genie/manual/" in n for n in names), "必备面 manual")
    need(any("genie/examples/" in n for n in names), "必备面 examples")
    need(any("/static/modules/" in n for n in names), "必备面 前端 modules")
    need(any("/static/views/" in n for n in names), "必备面 前端 views")
    need(not any("genie_results" in n for n in names), "无结果数据残留")
    need(not any("proposals/" in n for n in names), "无内部提案混入")

    idx = next(n for n in names if n.endswith("studio/static/index.html"))
    html = zf.read(idx).decode("utf-8", "ignore")
    refs = re.findall(r'(?:src|href)="(/[^"]+)"', html)
    roots = (("/manual/", "genie/manual/"), ("/examples/", "genie/examples/"))

    def target(ref: str) -> str:
        for url, pkgpath in roots:
            if ref.startswith(url):
                return pkgpath + ref[len(url):]
        return "genie/studio/static" + ref

    missing = [r for r in refs if not any(n.endswith(target(r)) for n in names)]
    need(not missing, f"index.html 的 {len(refs)} 条绝对引用全部命中"
                      + (f"（缺 {missing}）" if missing else ""))

    src = (PKG / "studio" / "static" / "index.html").read_bytes()
    need(hashlib.sha256(zf.read(idx)).digest() == hashlib.sha256(src).digest(),
         "产物 index.html 与源树字节一致")

    pages = [n for n in names
             if n.startswith("genie/manual/commands/") and n.endswith(".html")]
    bad = [(p, r) for p in pages
           for r in re.findall(r'src="(figs/[^"]+)"', zf.read(p).decode("utf-8", "ignore"))
           if not any(n.endswith("genie/manual/commands/" + r) for n in names)]
    need(not bad, f"手册 {len(pages)} 页引用的插图全部命中"
                  + (f"（缺 {bad[:3]}）" if bad else ""))
    _p(f"   发布门通过：{len(names)} 文件 / {len(refs)} 条引用 / {len(pages)} 页手册")


# ── ④ 提交并推 main ───────────────────────────────────────────────────────
def step4_push_main(ver: str) -> None:
    _p("── ④ 提交并推 main")
    _git("add", "-A")
    staged = _run(["git", "diff", "--cached", "--quiet"], check=False).returncode
    if staged == 0:
        _p("   无改动（版本号已提交过），跳过提交")
    else:
        _git("commit", "-q", "-m", f"release: genie SDK {ver}")
        _p("   " + _git("log", "-1", "--pretty=%h %s").strip())
    _git("push", "-q", "origin", "main")
    _p("   已推送 main")


# ── ⑤ dist 孤儿分支（纯管道，不碰工作树；双轮子，2026-10-27 起）──────────
def step5_dist(whls: list[Path], ver: str) -> None:
    _p("── ⑤ 重建 dist 孤儿分支")
    # git mktree 不接受带斜杠的路径：先造 dist 子树，再套根树。
    entries = "".join(
        f"100644 blob {_git('hash-object', '-w', str(w)).strip()}\t{w.name}\n"
        for w in whls)
    sub = _git("mktree", stdin=entries).strip()
    tree = _git("mktree", stdin=f"040000 tree {sub}\tdist\n").strip()
    commit = _git("commit-tree", tree, "-m", f"wheel: genie {ver}").strip()
    _git("push", "-q", "--force", "origin", f"{commit}:refs/heads/dist")
    _p(f"   dist 分支 → {commit[:7]}（{len(whls)} 个 wheel）")


# ── ⑥ GitHub Release ──────────────────────────────────────────────────────
def _repo_slug() -> str:
    url = _git("remote", "get-url", "origin").strip()
    m = re.search(r"github\.com[:/](?P<slug>[\w.\-]+/[\w.\-]+?)(?:\.git)?$", url)
    return m.group("slug") if m else "Simeonma/genie-sdk"


def step6_release(whls: list[Path], ver: str) -> None:
    _p("── ⑥ GitHub Release")
    slug = _repo_slug()
    tag = f"v{ver}"
    exists = _run(["gh", "release", "view", tag, "--repo", slug],
                  check=False).returncode == 0
    if exists:
        _p(f"   {tag} 已存在，跳过创建（附件仍会补传/覆盖）")
    body = (
        f"genie SDK {ver}。\n\n"
        "```bash\n"
        "# GitHub 直连（若 raw.githubusercontent.com 可达）\n"
        f"pip install https://github.com/{slug}/raw/dist/dist/{whl.name}\n"
        "# CDN 镜像（国内网络推荐：raw.githubusercontent 常不可达）\n"
        f"pip install https://cdn.jsdelivr.net/gh/{slug}@dist/dist/{whl.name}\n"
        "```\n\n"
        f"源码：本仓 main。wheel 亦在 `dist` 分支。"
    )
    cmd = ["gh", "release", "create", tag, "--repo", slug,
           "--title", f"genie SDK {ver}", "--notes", body]
    if "a" in ver:
        cmd.append("--prerelease")
    out = _run(cmd, check=False)
    if out.returncode != 0:
        _p(out.stdout.strip())
        print(out.stderr.strip(), file=sys.stderr)
        _fail("Release 创建失败（若是 gh 未登录：gh auth login -h github.com --web）")
    _p("   " + out.stdout.strip())
    # 附件双轮子（2026-10-27 起）：已存在则 --clobber 覆盖补传
    up = _run(["gh", "release", "upload", tag, "--repo", slug, "--clobber",
               *[str(w) for w in whls]], check=False)
    if up.returncode != 0:
        _p(up.stdout.strip())
        print(up.stderr.strip(), file=sys.stderr)
        _fail("Release 附件上传失败")
    _p("   附件：" + "、".join(w.name for w in whls))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="genie SDK 发版")
    ap.add_argument("version", help="版本号，如 2.0.0a5 / 2.0.1")
    ap.add_argument("--dry-run", action="store_true",
                    help="只跑到发布门（不提交、不推送、不建 Release）")
    args = ap.parse_args(argv)
    ver = args.version

    _p(f"发版 {ver}   仓：{ROOT}")
    step0_worktree()
    step1_version(ver)
    whls = step2_build()
    sdk_whl = next(w for w in whls if w.name.startswith("genie_sdk-"))
    step3_gate(sdk_whl)
    if args.dry_run:
        _p("\n--dry-run：止于发布门，未提交、未推送、未建 Release。")
        return 0
    step4_push_main(ver)
    step5_dist(whls, ver)
    step6_release(whls, ver)
    _p(f"\n── 完成：{ver}（源码 main / wheel dist / Release v{ver}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
