#!/usr/bin/env python3
"""commands 手册构建器 —— manual/commands/*.md → 多页静态文档站。

零外部依赖（不用 markdown 包/CDN）：渲染器只支持手册模板用到的语法
子集（标题/表格/围栏代码/粗体/行内码/链接/列表/引用），并对手册的
「**标签**　内容」段落做结构化排版（kv overline 行）。

站点结构（Sphinx/RTD 风）：
- index.html            落地页（分组卡片 + 快速开始入口）
- <doc-id>.html         每篇一个页面；侧栏分组导航 + 页底 Prev/Next
- 真源 = 同目录 *.md；改 md 后重跑本脚本（护栏测试
  tests/sdk/test_manual_build.py 会重跑并断言无 diff）。
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC_DIR = REPO / "genie-sdk" / "manual" / "commands"

# 页序与分组（Sphinx 风侧栏分组；显示用，文件名不动）
GROUPS = [
    ("Tutorials — physics of the method", [
        "tut1",
        "tut2",
    ]),
    ("Component guides", [
        "tut3",
        "tut4",
        "tut5",
        "tut6",
    ]),
    ("Reference", [
        "00-connect",
        "01-domain",
        "02-mesh",
        "03-mat",
        "04-geom",
        "05-src",
        "06-mon",
        "07-run",
        "08-sweep",
        "09-results",
    ]),
    ("Advanced", [
        "10-fit-nk",
        "11-lib",
    ]),
    ("Examples", [
        "quickstart",
        "walkthrough",
        "examples",
    ]),
    ("FAQ", [
        "faq",
        "troubleshooting",
    ]),
]

# ---------------------------------------------------------------------------
# 极简 Markdown 渲染
# ---------------------------------------------------------------------------

_KEYWORDS = {
    "import", "from", "as", "def", "return", "for", "in", "if", "elif",
    "else", "while", "None", "True", "False", "not", "and", "or", "is",
    "with", "try", "except", "raise", "lambda", "class", "pass", "break",
    "continue"}

_TOK = re.compile(
    r'("[^"\n]*"|\'[^\'\n]*\'|#[^\n<]*|'
    r'\b(?:import|from|as|def|return|for|in|if|elif|else|while|None|True|False|'
    r'not|and|or|is|with|try|except|raise|lambda|class|pass|break|continue)\b|'
    r'\b[A-Za-z_][A-Za-z0-9_]*(?=\s*\()|'
    r'\b\d+\.?\d*(?:e-?\d+)?\b)')


def _hl(code: str) -> str:
    out, last = [], 0
    for m in _TOK.finditer(code):
        out.append(html.escape(code[last:m.start()]))
        t = m.group(1)
        if t[0] in "\"'":
            cls = "str"
        elif t.startswith("#"):
            cls = "cm"
        elif t[0].isdigit():
            cls = "num"
        elif t.isidentifier() and t not in _KEYWORDS:
            cls = "fn"
        else:
            cls = "kw"
        out.append(f'<span class="{cls}">{html.escape(t)}</span>')
        last = m.end()
    out.append(html.escape(code[last:]))
    return "".join(out)


# 行内"数学味"判定：含希腊字母/算符/上下标记号 → 按行内数学排版
_MATHISH = re.compile(r"[\u0391-\u03c9\u2202\u2207\u221d\u2192\u2190\u2260"
                      u"\u2264\u2265\u2248\u2211\u221a\u00d7\u00b1\u00b2\u00b3"
                      u"\u1ebc\u0303]")


_SIMPLE_VAR = re.compile(
    r"^([A-Za-z\u0391-\u03c9])([+\u2212-]([A-Za-z0-9]|[\u00bc-\u00be]"
    r"[\u2032-\u2037]?|[\u2150-\u215e]))?$")


def _code_span(m: re.Match) -> str:
    t = m.group(1)                 # _inline 外层已 html 转义，勿二次转义
    if _MATHISH.search(t):         # 行内数学：LaTeX 风
        return f'<span class="mathi">{_math_typeset(_subsup(_math_space(t)))}</span>'
    if _SIMPLE_VAR.match(t):       # 单字母（含 n+½ 简式）：变量斜体
        vec = t[0] in _MATH_VEC
        return f'<span class="mathi">{_math_typeset(t, vec=vec)}</span>'
    return f"<code>{t}</code>"


def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)',
               r'<img src="\2" alt="\1" loading="lazy">', s)
    s = re.sub(r'`([^`]+)`', _code_span, s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'\*(\S(?:[^*\n]*\S)?)\*', r'<em>\1</em>', s)
    s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', s)
    return s



# 正文裸排的场/矢量单字母（词级），排版为带箭头矢量；跳过代码/公式/已斜体区
_PROSE_VEC = re.compile(r"(?<![\w#&])([EHJDBM])(?![\w;])")
_PROSE_SKIP = ("code", "pre", "script", "style", "i", "em")
_PROSE_SPAN = re.compile(r'class="[^"]*\bmathi\b')


def _prose_math(h: str) -> str:
    """正文裸排的场/矢量单字母（词级）→ 带箭头矢量。

    栈式跳过 code/pre/script/style/i/em 与 mathi/vec span 内部。"""
    out, stack = [], []
    for seg in re.split(r"(<[^>]+>)", h):
        if seg.startswith("<"):
            m = re.match(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)", seg)
            if m:
                close, tag = m.groups()
                tag = tag.lower()
                hit = tag in _PROSE_SKIP or (
                    tag == "span" and _PROSE_SPAN.search(seg))
                if hit:
                    if close:
                        if stack and stack[-1] == tag:
                            stack.pop()
                    else:
                        stack.append(tag)
            out.append(seg)
            continue
        if not stack:
            seg = _PROSE_VEC.sub(
                r'<span class="vec"><i>\1</i></span>', seg)
        out.append(seg)
    return "".join(out)


def _anchor(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-",
                  text.lower()).strip("-")


_FRAC = {"½": ("1", "2"), "¼": ("1", "4"), "¾": ("3", "4"),
         "⅓": ("1", "3"), "⅔": ("2", "3"), "⅙": ("1", "6"),
         "⅚": ("5", "6"), "⅛": ("1", "8")}


def _subsup(esc: str) -> str:
    """^{...}/_{...}/裸 _xx → <sup>/<sub>；分数堆叠；- 归一为 −。"""
    for ch, (a, b) in _FRAC.items():
        esc = esc.replace(ch, f"<sup>{a}</sup>⁄<sub>{b}</sub>")
    fix = lambda c: c.replace("-", "\u2212")
    s = re.sub(r"\^\{([^}]*)\}", lambda m: "<sup>" + fix(m.group(1)) + "</sup>", esc)
    s = re.sub(r"_\{([^}]*)\}", lambda m: "<sub>" + fix(m.group(1)) + "</sub>", s)
    return re.sub(r"_([A-Za-z0-9]+)", lambda m: "<sub>" + fix(m.group(1)) + "</sub>", s)


# 函数名/单位：多字母，正体（ISO 80000：量斜体、单位正体）
_MATH_UP = ("sin|cos|tan|exp|ln|log|argmax|argmin|min|max|Re|Im|Re|"
            "fs|ps|ns|ms|nm|um|mm|cm|km|Hz|kHz|MHz|GHz|THz|dB|rad|SI")
# 单字母变量（希腊+拉丁）；(?<![\w.]) 排除多字母词与 2e-9 尾数
_MATH_VAR = re.compile(
    r"@([A-Za-z\u0391-\u03c9])"          # @x = 张量记号（上划线）
    r"|\b(?:" + _MATH_UP + r")\b"
    r"|(?<![\w.])([A-Za-z\u0391-\u03c9])(?![\w'’])")
# 矢量字母集：电/磁场、电流、通量密度与位矢/波矢（FDTD 惯例）
_MATH_VEC = set("EHJDBr")


def _math_space(t: str) -> str:
    """公式文本段（无标签）的算符间距归一（AMS/期刊惯例）。"""
    t = re.sub(r"[ \t]*([=≤≥∝·])[ \t]*", r" \1 ", t)
    out, i, n = [], 0, len(t)
    while i < n:
        ch = t[i]
        if ch in "+−":
            j = len(out) - 1
            while j >= 0 and out[j] == " ":
                j -= 1
            last = out[j] if j >= 0 else "\n"
            unary = last in "(=[,·+−" or last == "\n"
            while out and out[-1] == " ":
                out.pop()
            if unary:
                if out and out[-1] not in "([":
                    out.append(" ")
                out.append(ch)
            else:
                if out and out[-1] != " ":
                    out.append(" ")
                out.extend([ch, " "])
            i += 1
            while i < n and t[i] == " ":
                i += 1          # 算符后的空格由我们统一给
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _math_typeset(esc: str, vec: bool = False) -> str:
    """变量斜体、矢量箭头；全串扫描并跳过标签区间（跨标签前瞻正确）。"""
    tag_spans = [m.span() for m in re.finditer(r"<[^>]+>", esc)]

    def intag(pos: int) -> bool:
        return any(a <= pos < b for a, b in tag_spans)

    out, last = [], 0
    for m in _MATH_VAR.finditer(esc):
        a, b = m.span()
        if intag(a):
            continue
        out.append(esc[last:a])
        g = m.group(2)
        nxt = esc[b:b + 1]
        if m.group(1):                     # 张量：上划线，正体
            out.append(f'<span class="tns">{m.group(1)}</span>')
        elif g is None:                    # 函数/单位：保持正体
            out.append(m.group(0))
        elif vec and g in _MATH_VEC and nxt not in ("<^_"):
            out.append(f'<span class="vec"><i>{g}</i></span>')
        else:
            out.append(f"<i>{g}</i>")
        last = b
    out.append(esc[last:])
    return "".join(out)


def _math_html(code: str) -> str:
    """轻量公式排版：间距 → 上下标/分数 → 变量斜体 + 矢量箭头。"""
    s = _math_space(html.escape(code))
    s = _math_typeset(_subsup(s), vec=True)
    return f'<pre class="math">{s}</pre>'


def _code_html(code: str, lang: str = "") -> str:
    if lang == "math":
        return _math_html(code)
    return f'<pre class="code"><code>{_hl(code)}</code></pre>'


def _table(lines: list[str]) -> str:
    rows = [[c.strip().replace("\\|", "|") for c in
             re.split(r"(?<!\\)\|", r.strip().strip("|"))]
            for r in lines]
    out = ['<div class="tblwrap"><table>']
    out.append("<thead><tr>" + "".join(
        f"<th>{_inline(c)}</th>" for c in rows[0]) + "</tr></thead><tbody>")
    for r in rows[2:]:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r)
                   + "</tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def render(md: str) -> str:
    out: list[str] = []
    lines = md.splitlines()
    i, in_code, code_buf, code_lang = 0, False, [], ""
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            if in_code:
                out.append(_code_html("\n".join(code_buf), code_lang))
                in_code = False
            else:
                in_code, code_buf, code_lang = True, [], ln[3:].strip()
            i += 1
            continue
        if in_code:
            code_buf.append(ln)
            i += 1
            continue
        if ln.startswith("|"):
            blk = []
            while i < len(lines) and lines[i].startswith("|"):
                blk.append(lines[i])
                i += 1
            out.append(_table(blk))
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            lvl = len(m.group(1))
            text = m.group(2).strip()
            anchor = _anchor(re.sub(r"`", "", text).lower())
            if lvl == 2:
                out.append(
                    f'<h2 id="{anchor}"><a class="anchor" href="#{anchor}"'
                    f' aria-label="Link to this section">#</a>'
                    f'{_inline(text)}</h2>')
            else:
                out.append(f'<h{lvl} id="{anchor}">{_inline(text)}</h{lvl}>')
            i += 1
            continue
        if re.match(r"^\s*[-*]\s+", ln):
            blk = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                item = re.sub(r"^\s*[-*]\s+", "", lines[i])
                i += 1
                while i < len(lines) and lines[i].strip() \
                        and not re.match(r"^\s*[-*]\s+", lines[i]) \
                        and not lines[i].startswith(("#", "|", ">", "```")):
                    item += " " + lines[i].strip()   # 懒续行
                    i += 1
                blk.append(item)
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>"
                                        for x in blk) + "</ul>")
            continue
        if ln.startswith(">"):
            blk = []
            while i < len(lines) and lines[i].startswith(">"):
                blk.append(lines[i].lstrip("> "))
                i += 1
            out.append(f'<div class="intro">{_inline(" ".join(blk))}</div>')
            continue
        if not ln.strip():
            i += 1
            continue
        blk = []
        while i < len(lines) and lines[i].strip() \
                and not lines[i].startswith(("#", "|", ">", "```")) \
                and not re.match(r"^\s*[-*]\s+", lines[i]):
            blk.append(lines[i])
            i += 1
        para = " ".join(blk)
        km = re.match(r"^\*\*([^*]{1,24}?)\*\*\s*(.*)$", para)
        if km:
            label, rest = km.group(1), km.group(2)
            sig = " sig" if label.lower() == "signature" else ""
            out.append(f'<div class="kv"><span class="kv-k">{label}</span>'
                       f'<span class="kv-v{sig}">'
                       f'{_inline(rest) if rest else ""}</span></div>')
        else:
            out.append(f"<p>{_inline(para)}</p>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 页面骨架
# ---------------------------------------------------------------------------

CSS = """:root{
--bg:#fbfbfc;--panel:#fff;--fg:#1b2027;--muted:#4b5560;--faint:#67727e;
--line:#e2e6ea;--soft:#f4f5f7;--brand:#24557a;--brand2:#35699a;
--cur-bg:#e9edf1;--r-sm:4px;--r-md:5px;
--code-bg:#f6f7f8;--sig-bg:#f1f4f6;--sig-line:#d8dee4;
--kw:#0b4a8f;--str:#116329;--cm:#6e7781;--num:#953800}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:24px}
body{margin:0;font:16px/1.65 -apple-system,"Segoe UI","PingFang SC",
"Hiragino Sans GB","Noto Sans SC","Microsoft YaHei",sans-serif;
color:var(--fg);background:var(--bg)}
#side{position:fixed;top:0;left:0;bottom:0;width:292px;overflow-y:auto;
padding:20px 14px 40px;border-right:1px solid var(--line);background:var(--panel)}
#side .brand{font-weight:700;font-size:15px;padding:2px 8px 14px}
#side .brand a{color:var(--fg);text-decoration:none}
#side .brand .dot{color:var(--brand)}
#side input{width:100%;padding:8px 12px;border:1px solid var(--line);
border-radius:var(--r-sm);font-size:13.5px;margin:0 0 10px;background:var(--soft)}
#side input:focus{outline:2px solid var(--brand2);outline-offset:-1px;
border-color:var(--brand2)}
#side details.grp{margin:0}
#side details.grp>summary{list-style:none;cursor:pointer;display:flex;
align-items:center;gap:6px;font-size:11px;font-weight:700;
text-transform:uppercase;letter-spacing:.1em;color:var(--faint);
padding:12px 8px 4px;border-radius:var(--r-sm)}
#side details.grp>summary:hover{color:var(--muted);background:transparent}
#side details.grp>summary::after{content:"";flex:none;width:6px;height:6px;
margin-left:auto;margin-right:2px;border-right:1.5px solid currentColor;
border-bottom:1.5px solid currentColor;transform:rotate(-45deg);
transition:transform .15s ease}
#side details.grp[open]>summary::after{transform:rotate(45deg)}
#side details.doc{margin:1px 0 1px 16px}
#side details.doc>summary::after{content:"";flex:none;width:6px;height:6px;
margin-left:auto;border-right:1.5px solid currentColor;
border-bottom:1.5px solid currentColor;transform:rotate(-45deg);
transition:transform .15s ease}
#side details.doc[open]>summary::after{transform:rotate(45deg)}
#side details.doc>summary .t{flex:1;min-width:0}
#side details.doc>summary{list-style:none;cursor:pointer;font-weight:600;
font-size:13px;padding:6px 8px;border-radius:var(--r-sm);color:var(--fg);
line-height:1.45;display:flex;gap:8px;align-items:baseline}
#side details.doc>summary:hover{background:var(--soft)}
#side details.doc>summary .no{flex:none;min-width:22px;color:var(--brand);
font-variant-numeric:tabular-nums}
#side details.doc>summary .t{flex:1;min-width:0}
#side details.doc.cur>summary{background:var(--cur-bg);color:var(--brand)}
#side nav a.cmd{display:block;padding:2.5px 8px 2.5px 44px;color:var(--muted);
text-decoration:none;font-size:12.3px;border-radius:var(--r-sm);font-family:
ui-monospace,SFMono-Regular,Consolas,monospace;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
#side nav a.cmd:hover{background:var(--soft);color:var(--fg)}
#side nav a.cmd.active{background:var(--cur-bg);color:var(--brand);font-weight:600}
#side a.pg{display:block;padding:6px 8px 6px 28px;color:var(--fg);
text-decoration:none;font-size:13px;font-weight:500;
border-radius:var(--r-sm)}
#side a.pg:hover{background:var(--soft)}
#side a.pg.cur{background:var(--cur-bg);color:var(--brand);font-weight:600}
#side a.pg .no{display:inline-block;min-width:22px;color:var(--brand);
font-variant-numeric:tabular-nums}
#main{margin-left:292px;padding:0 0 60px}
.docwrap{max-width:820px;margin:0 auto;padding:36px 48px 0}
.crumbs{font-size:12.5px;color:var(--faint);margin-bottom:18px}
.crumbs a{color:var(--muted)}
.crumbs a:hover{color:var(--brand)}
.crumbs .src{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
font-size:11px;color:var(--faint);border:1px solid var(--line);
border-radius:3px;padding:1px 6px}
.crumbs .src:hover{color:var(--fg);border-color:var(--faint);
text-decoration:none}
#topbar{display:none}
#navmask{display:none}
.landing{padding:40px 0 8px;line-height:1.65}
.landing h1{font-size:32px;margin:0 0 16px;font-weight:650;
letter-spacing:-.01em}
.landing .lede{font-size:17px;color:var(--fg);margin:0 0 8px}
.landing p{color:var(--muted);max-width:62ch}
.cta{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 4px}
.btn{display:inline-block;padding:9px 18px;border:1px solid var(--line);
border-radius:var(--r-sm);background:var(--panel);color:var(--fg);font-weight:600;
font-size:14px;text-decoration:none;transition:border-color .15s,
background .15s}
.btn:hover{text-decoration:none;border-color:var(--brand2);color:var(--brand)}
.btn.primary{background:var(--brand);border-color:var(--brand);color:#fff}
.btn.primary:hover{background:#1d4666;border-color:#1d4666}
.toc{margin:8px 0 6px}
.toc h2{border:none;background:none;padding:0;margin:30px 0 10px;
font-size:12.5px;font-weight:700;text-transform:uppercase;
letter-spacing:.09em;color:var(--faint)}
.toc ul{list-style:none;margin:0;padding:0;display:grid;
grid-template-columns:1fr 1fr;gap:10px}
.toc li{margin:0;padding:13px 16px;border:1px solid var(--line);
border-radius:6px;background:var(--panel);position:relative;
transition:border-color .15s}
.toc a{font-weight:600;font-size:14.5px;text-decoration:none;display:block}
.toc a:hover{text-decoration:none;color:var(--brand)}
.toc a::after{content:"";position:absolute;inset:0}
.toc .d{display:block;color:var(--muted);font-size:13px;font-weight:400;
line-height:1.55;margin-top:4px}
h1{font-size:30px;margin:0 0 8px;font-weight:650;letter-spacing:-.01em}
h1 .no{color:var(--brand);margin-right:12px;
font-variant-numeric:tabular-nums}
.intro{background:var(--soft);border-left:3px solid var(--faint);
border-radius:0 var(--r-md) var(--r-md) 0;padding:14px 20px;color:var(--muted);
font-size:16.5px;line-height:1.6;margin:16px 0 8px}
h2{font-size:21px;margin:2.4em 0 .8em;padding:0 0 8px;position:relative;
border-bottom:1px solid var(--line)}
h2:target{animation:tfade 1.6s ease}
@keyframes tfade{0%{background:#e9eef4}100%{background:transparent}}
h2 .anchor{position:absolute;left:-1.3em;color:var(--faint);font-weight:400;
text-decoration:none;opacity:0;font-weight:400}
h2:hover .anchor{opacity:1}
h3{font-size:17px;margin:1.8em 0 .5em}
h2 code{background:none;padding:0;font-size:.95em;color:var(--fg)}
code{background:var(--code-bg);padding:.1em .35em;
border-radius:3px;font-size:.88em;font-family:ui-monospace,SFMono-Regular,
Consolas,"Liberation Mono",monospace}
pre.code{background:var(--code-bg);border:1px solid var(--line);
border-radius:var(--r-md);padding:14px 18px;overflow-x:auto;font-size:13px;
line-height:1.6;margin:.8em 0 1.2em;position:relative}
.btn,.toc li,.pagenav a,#side details.doc>summary,#side a.pg,
#side nav a.cmd,.cpy{transition:background .12s ease,border-color .12s ease,
color .12s ease}
.cpy{position:absolute;top:6px;right:6px;border:1px solid var(--line);
background:var(--panel);color:var(--faint);font-size:11px;
border-radius:var(--r-sm);padding:1px 7px;cursor:pointer}
.cpy:hover{color:var(--fg);border-color:var(--faint)}
pre.code code{background:none;border:none;padding:0}
pre.math{font-family:Georgia,"Times New Roman",serif;font-size:16.5px;
text-align:center;background:var(--panel);border:1px solid var(--line);
border-radius:var(--r-md);padding:14px 18px;margin:.8em 0 1.2em;overflow-x:auto;
white-space:pre;font-style:normal;line-height:1.9;color:var(--fg)}
pre.math i,.mathi i{font-style:italic}
.vec{position:relative;display:inline-block;font-style:italic;
margin:0 .06em}
.vec::after{content:"\\2192";position:absolute;left:50%;top:-.5em;
font-size:.82em;font-style:normal;transform:translateX(-50%);
pointer-events:none}
.tns{position:relative;display:inline-block;font-style:normal;
margin:0 .06em}
.tns::after{content:"\\7e";position:absolute;left:50%;top:-.5em;
font-size:.82em;transform:translateX(-50%);pointer-events:none}
.mathi{font-family:Georgia,"Times New Roman",serif;font-size:1.05em;
white-space:nowrap}
pre.math .math-op{font-style:normal}
pre.math sup,pre.math sub{font-size:.72em;font-style:normal;
line-height:0;position:relative;vertical-align:baseline}
pre.math sup{top:-.45em}pre.math sub{top:.35em}
.kw{color:var(--kw);font-weight:600}.str{color:var(--str)}
.fn{color:#6847a8}
.cm{color:var(--cm);font-style:italic}.num{color:var(--num)}
.kv{display:block;margin:1.2em 0 .2em}
.kv-k{display:block;font-weight:700;font-size:11.5px;color:var(--muted);
text-transform:uppercase;letter-spacing:.09em;margin-bottom:4px}
.kv-v{display:block;min-width:0}
.kv-v.sig>code{display:inline-block;background:var(--sig-bg);
border:1px solid var(--sig-line);border-radius:var(--r-md);padding:8px 12px;
font-size:12.8px;line-height:1.7;word-break:break-all;margin:2px 6px 6px 0}
.tblwrap{overflow-x:auto;margin:.9em 0 1.3em}
pre.code,#side,.tblwrap{scrollbar-width:thin;
scrollbar-color:var(--line) transparent}
pre.code::-webkit-scrollbar,.tblwrap::-webkit-scrollbar{height:8px}
#side::-webkit-scrollbar{width:8px}
pre.code::-webkit-scrollbar-thumb,.tblwrap::-webkit-scrollbar-thumb,
#side::-webkit-scrollbar-thumb{background:var(--line);border-radius:4px}
pre.code::-webkit-scrollbar-thumb:hover,.tblwrap::-webkit-scrollbar-thumb:hover,
#side::-webkit-scrollbar-thumb:hover{background:var(--faint)}
pre.code::-webkit-scrollbar-track,.tblwrap::-webkit-scrollbar-track,
#side::-webkit-scrollbar-track{background:transparent}
table{border-collapse:collapse;width:100%;font-size:13.8px;line-height:1.6;
font-variant-numeric:tabular-nums;
background:var(--panel);border:1px solid var(--line);border-radius:var(--r-md);
overflow:hidden}
th,td{padding:9px 14px;text-align:left;vertical-align:top;
border-bottom:1px solid var(--line)}
th{background:var(--soft);font-weight:600;font-size:13px;color:var(--muted);
white-space:nowrap}
th:first-child{width:1%}
td:first-child{min-width:130px}
td:nth-child(4){min-width:144px}   /* Default 列 */
td:nth-child(2){min-width:64px}   /* Type 列 */
th:first-child:nth-last-child(2){width:auto}
td:first-child:nth-last-child(2){min-width:300px}
td code{word-break:break-word}
tbody tr:last-child td{border-bottom:none}
img{max-width:100%;display:block;margin:14px auto;
border:1px solid var(--line);border-radius:var(--r-md);background:var(--panel)}
ul{margin:.5em 0 1em;padding-left:1.3em}
li{margin:.35em 0}
li::marker{color:var(--faint)}
p{margin:1em 0}
a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline;text-underline-offset:2px;text-decoration-thickness:1px}
:focus-visible{outline:2px solid var(--brand2);outline-offset:2px;
border-radius:2px}
::selection{background:#d4e0ec}
h1,h2,h3{text-wrap:balance}
p,li{text-wrap:pretty}
strong{color:var(--fg);font-weight:600}
.pagenav{display:flex;justify-content:space-between;gap:16px;
max-width:820px;margin:34px auto 0;padding:18px 48px 40px}
.pagenav a{flex:1;border:1px solid var(--line);border-radius:6px;
padding:12px 16px;text-decoration:none;background:var(--panel)}
.pagenav a:hover{border-color:var(--brand2);text-decoration:none}
.pagenav .dir{font-size:11px;color:var(--faint);text-transform:uppercase;
letter-spacing:.08em}
.pagenav .tt{font-weight:600;color:var(--brand);font-size:14px}
.pagenav a.next{text-align:right}
#sres a.pg{display:flex;flex-direction:column;gap:0;padding:7px 8px}
#sres .pgname{font-weight:400;font-size:11px;color:var(--faint)}
#sres .nohit{color:var(--faint);font-size:12.5px;padding:8px}
@media(max-width:1100px){
#topbar{display:flex;position:fixed;top:0;left:0;right:0;height:48px;
align-items:center;gap:10px;padding:0 12px;background:var(--panel);
border-bottom:1px solid var(--line);z-index:30}
#topbar .brand{font-weight:700;font-size:14.5px;flex:1;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#topbar .brand a{color:var(--fg);text-decoration:none}
#topbar .brand .dot{color:var(--brand)}
#menu{flex:none;width:36px;height:36px;border:1px solid var(--line);
border-radius:8px;background:var(--panel);cursor:pointer;
display:flex;align-items:center;justify-content:center;padding:0}
#menu svg{display:block}
#side{transform:translateX(-100%);transition:transform .2s ease;
z-index:40;box-shadow:0 0 24px rgba(20,35,60,.15)}
body.nav-open #side{transform:none}
body.nav-open #navmask{display:block;position:fixed;inset:48px 0 0 0;
background:rgba(20,35,60,.35);z-index:35}
#main{margin-left:0;padding-top:48px}
.docwrap,.pagenav{padding-left:20px;padding-right:20px}
#side input{font-size:16px}
h2 .anchor{display:none}}
@media(max-width:720px){
pre.math{font-size:13px;text-align:left;white-space:pre-wrap}
.toc ul{grid-template-columns:1fr}
.pagenav{flex-direction:column;gap:10px}
.pagenav a.next{text-align:right}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}
*{transition:none!important;animation:none!important}}
@media print{#side,.pagenav,#topbar,#navmask{display:none}
#main{margin:0;padding-top:0}
.docwrap{max-width:none;padding:0}
body{background:#fff;color:#000;font-size:12px;line-height:1.55}
h1{font-size:22px}h2{font-size:16px;break-after:avoid}
h3{font-size:13.5px}
pre.code{white-space:pre-wrap;word-break:break-word;break-inside:avoid}
pre.code .cpy{display:none}
pre.math,img,.tblwrap{break-inside:avoid}
img{border:none}
a{color:#000;text-decoration:none}
.docwrap a[href^="http"]::after{content:" (" attr(href) ")";
font-size:10px;color:#444;word-break:break-all}
.intro,.kv-v.sig>code{background:#f3f4f6}
table{font-size:10.5px}
.crumbs .src{display:none}}
"""

JS_NAV = """<script>
const q=document.getElementById("q");
const nl=document.getElementById("navlist");
const sr=document.getElementById("sres");
if(q)q.addEventListener("input",()=>{const f=q.value.trim().toLowerCase();
if(!f){sr.style.display="none";nl.style.display="";return;}
const hits=SEARCH.filter(e=>e.c.toLowerCase().includes(f)
  ||e.dt.toLowerCase().includes(f));
sr.innerHTML=hits.map(e=>
  `<a class="pg" href="${e.d}.html#${e.c.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"")}">`
  +`${e.c}<span class="pgname">${e.dt}</span></a>`).join("")
  ||`<div class="nohit">No matches</div>`;
nl.style.display="none";sr.style.display="";});
document.querySelectorAll("pre.code").forEach(pre=>{
const b=document.createElement("button");b.className="cpy";
b.textContent="Copy";
b.onclick=()=>{navigator.clipboard.writeText(pre.textContent)
  .then(()=>{b.textContent="Copied";
    setTimeout(()=>b.textContent="Copy",1200);});};
pre.appendChild(b);});
const links=()=>[...document.querySelectorAll("#side a.cmd")];
let tick=false;addEventListener("scroll",()=>{if(tick)return;tick=true;
requestAnimationFrame(()=>{tick=false;
let cur=null;for(const h of document.querySelectorAll("h2[id]"))
if(h.getBoundingClientRect().top<120)cur=h.id;
for(const a of links())a.classList.toggle("active",a.dataset.h===cur);});
},{passive:true});
const mb=document.getElementById("menu");
if(mb)mb.onclick=()=>document.body.classList.toggle("nav-open");
const nm=document.getElementById("navmask");
if(nm)nm.onclick=()=>document.body.classList.remove("nav-open");
addEventListener("keydown",e=>{if(e.key==="Escape")
document.body.classList.remove("nav-open");});
document.querySelectorAll("#side a").forEach(a=>
a.addEventListener("click",()=>document.body.classList.remove("nav-open")));
</script>"""


def _sidebar(cur: str, docs: dict) -> str:
    data = [{"c": c, "d": did, "dt": docs[did]["title"]}
            for did in docs for c in docs[did]["cmds"]]
    parts = ['<aside id="side" aria-label="Docs navigation">',
             '<div class="brand"><a href="index.html">GENIE'
             '<span class="dot"> ·</span> SDK Docs</a></div>',
             '<input id="q" type="search" aria-label="Search all commands" '
             'placeholder="Search all commands…">',
             f'<script>const SEARCH={json.dumps(data, ensure_ascii=False)};'
             '</script>',
             '<div id="sres" style="display:none"></div>']
    parts.append('<div id="navlist">')
    for grp, ids in GROUPS:
        # 组 = 可折叠 details：当前页所在组展开，其余收起（落地面全收）
        grp_open = " open" if cur in ids else ""
        parts.append(f'<details class="grp"{grp_open}>'
                     f'<summary><span class="gt">{html.escape(grp)}</span>'
                     f'</summary>')
        for did in ids:
            d = docs[did]
            if did == cur:
                det = ['<details class="doc cur" open>',
                       f'<summary><span class="t">{html.escape(d["title"])}</span></summary>',
                       '<nav>']
                for c in d["cmds"]:
                    anch = _anchor(c.lower())
                    det.append(f'<a class="cmd" data-h="{anch}" '
                               f'href="{did}.html#{anch}">'
                               f'{html.escape(c)}</a>')
                det.append('</nav></details>')
                parts += det
            else:
                parts.append(
                    f'<a class="pg" href="{did}.html">'
                    f'{html.escape(d["title"])}</a>')
        parts.append('</details>')
    parts.append('</div>')
    parts.append("</aside>")
    return "\n".join(parts)


def _trim_blurb(s: str, limit: int = 160) -> str:
    """句子边界优先截断：整句装得下就取整句，否则在词边界收尾加 …。"""
    if len(s) <= limit:
        return s
    cut = s[:limit]
    m = re.search(r"^(.+?[.!?])(\s|$)", cut)      # 最后一个完整句
    if m and len(m.group(1)) >= limit * 0.5:
        return m.group(1)
    tail = cut[:cut.rfind(" ")] if " " in cut else cut
    return tail + "…"


def _page(title: str, body: str, sidebar: str, prev_, next_,
          src: str | None = None, desc: str = "") -> str:
    if src:
        body = (f'<div class="crumbs"><a href="index.html">Docs</a>'
                f' › {html.escape(title)} · '
                f'<a class="src" href="{src}" title="Markdown source">.md</a></div>'
                + body)
    nav = ""
    if prev_ or next_:
        l = (f'<a href="{prev_[0]}.html"><div class="dir">← Previous</div>'
             f'<div class="tt">{html.escape(prev_[1])}</div></a>'
             if prev_ else "<span></span>")
        r = (f'<a class="next" href="{next_[0]}.html">'
             f'<div class="dir">Next →</div>'
             f'<div class="tt">{html.escape(next_[1])}</div></a>'
             if next_ else "")
        nav = f'<div class="pagenav">{l}{r}</div>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{html.escape(title)} · GENIE SDK</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%2324557a'/%3E%3Ctext x='16' y='22' font-family='ui-monospace,monospace' font-size='17' font-weight='700' fill='%23fff' text-anchor='middle'%3EG%3C/text%3E%3C/svg%3E">
<meta property="og:type" content="article">
<meta property="og:site_name" content="GENIE SDK Docs">
<meta property="og:title" content="{html.escape(title)}">
{f'<meta property="og:description" content="{html.escape(desc, quote=True)}">'
 if desc else ""}
<style>{CSS}</style>
</head>
<body>
<div id="topbar"><button id="menu" aria-label="Toggle navigation"
aria-controls="side"><svg width="18" height="18" viewBox="0 0 18 18"
fill="none" stroke="#24292f" stroke-width="2"
stroke-linecap="round"><path d="M2 4.5h14M2 9h14M2 13.5h14"/></svg></button>
<div class="brand"><a href="index.html">GENIE<span class="dot"> ·</span>
SDK Docs</a></div></div>
{sidebar}
<div id="navmask"></div>
<main id="main">
<div class="docwrap">{body}</div>
{nav}
</main>
{JS_NAV}
</body>
</html>
"""


def _landing(docs: dict, order: list) -> str:
    total = sum(len(d["cmds"]) for d in docs.values())
    toc = []
    for grp, ids in GROUPS:
        items = "".join(
            f'<li><a href="{did}.html">{html.escape(docs[did]["title"])}</a>'
            f'<span class="d">{html.escape(docs[did].get("blurb", ""))}'
            f"</span></li>"
            for did in ids)
        toc.append(f'<div class="toc"><h2>{html.escape(grp)}</h2>'
                   f"<ul>{items}</ul></div>")
    body = f"""
<div class="landing">
<h1>GENIE SDK Documentation</h1>
<p class="lede">GENIE is a cloud FDTD solver driven by a small Python SDK:
assemble a simulation on one object, submit it with
<code>f.run()</code>, and read the fields back as arrays.</p>
<p>The manual documents all {total} commands, the physics behind each
solver setting, worked examples, and answers to common problems.</p>
<div class="cta"><a class="btn primary" href="quickstart.html">Quickstart
→</a><a class="btn" href="00-connect.html">API Reference</a></div>
{''.join(toc)}
</div>"""
    return _page("GENIE SDK Documentation", body,
                 _sidebar("__index", docs), None,
                 ("quickstart", docs["quickstart"]["title"]),
                 desc="GENIE SDK manual: GPU FDTD solver for photonics "
                      f"and nanooptics — all {total} commands, the physics "
                      "behind each setting, worked examples, and FAQ.")


def build(check: bool = False) -> int:
    mds = sorted(SRC_DIR.glob("*.md"))
    if not mds:
        print(f"[build_manual] no md sources in {SRC_DIR}", file=sys.stderr)
        return 1

    # pass 1: 解析每篇（title/doc_id/cmds/blurb）
    docs, order = {}, []
    for p in mds:
        md = p.read_text(encoding="utf-8")
        m = re.match(r"^#\s+(.+)$", md, re.M)
        title = m.group(1).strip() if m else p.stem
        # 组装顺序已由侧栏 GROUPS 表达，真源 h1 里的章号（"1 ·"/"09 ·"）
        # 不进侧栏导航与 <title>——正文 h1 的同款剥离已有，此处对齐
        title = re.sub(r"^\d+\s*·\s*", "", title).strip()
        did = p.stem          # 页面 id = 文件名（稳定，不随标题漂移）
        blurb = ""
        bline = next((n for n, l in enumerate(md.splitlines())
                      if l.startswith(">")), None)
        if bline is not None:
            blk = []
            for ln in md.splitlines()[bline:]:
                if not ln.startswith(">"):
                    break
                blk.append(ln.lstrip("> ").strip())
            plain = " ".join(blk)
            plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", plain)
            plain = re.sub(r"\*\*([^*]+)\*\*", r"\1", plain)
            blurb = re.sub(r"`([^`]*)`", r"\1", plain)
            blurb = _trim_blurb(blurb, 160)
        docs[did] = {"title": title, "cmds": [
            mm.group(1).strip() for mm in
            re.finditer(r"^##\s+`?([^\n`]+)`?\s*$", md, re.M)],
            "blurb": blurb, "md": md, "path": p}
        order.append(did)

    grouped = {d for _, ids in GROUPS for d in ids}
    missing = set(order) - grouped
    if missing:
        print(f"[build_manual] pages not in GROUPS: {sorted(missing)}",
              file=sys.stderr)
        return 1

    # pass 2: 渲染 + 跨页链接重写（#doc-id → doc-id.html；#h2 → 归属页）
    h2_owner: dict[str, str] = {}
    for did in order:
        h2_owner[did] = did
        for c in docs[did]["cmds"]:
            h2_owner[_anchor(c.lower())] = did

    doc_ids = set(order)

    def fix_links(body: str, cur: str) -> str:
        def repl(m):
            tgt = m.group(1)
            if tgt in doc_ids:                      # 篇级链接 → 落到页首
                return f'href="{tgt}.html"' if tgt != cur else 'href="#top"'
            if tgt in h2_owner:
                page = h2_owner[tgt]
                return f'href="{page}.html#{tgt}"' if page != cur \
                    else f'href="#{tgt}"'
            return m.group(0)
        return re.sub(r'href="#([^"]+)"', repl, body)

    outputs: dict[str, str] = {}
    for idx, did in enumerate(order):
        d = docs[did]
        body = render(d["md"])
        body = re.sub(r"^<h1([^>]*)>(?:\d+ · )?", r"<h1\1>", body, count=1)
        body = fix_links(body, did)
        body = _prose_math(body)
        prev_ = (order[idx - 1], docs[order[idx - 1]]["title"]) if idx else None
        next_ = (order[idx + 1], docs[order[idx + 1]]["title"]) \
            if idx + 1 < len(order) else None
        blurb_d = (d.get("blurb", "") or "")[:200]
        outputs[did] = _page(d["title"], body,
                             _sidebar(did, docs), prev_, next_,
                             src=d["path"].name, desc=blurb_d)
    outputs["index"] = _landing(docs, order)

    if check:
        for did, page in outputs.items():
            f = SRC_DIR / f"{did}.html"
            cur = f.read_text(encoding="utf-8") if f.exists() else ""
            if cur != page:
                print(f"[build_manual] {f.name} is stale — run "
                      "python tools/build_manual.py", file=sys.stderr)
                return 1
        print("[build_manual] all pages up to date")
        return 0

    # 清理孤儿 html（旧 id 命名 / 已删除页）
    keep = {f"{did}.html" for did in outputs}
    for f in SRC_DIR.glob("*.html"):
        if f.name not in keep:
            f.unlink()
            print("[build_manual] removed orphan", f.name)
    for did, page in outputs.items():
        (SRC_DIR / f"{did}.html").write_text(page, encoding="utf-8")
    print(f"[build_manual] {len(order)} pages + index → {SRC_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build(check="--check" in sys.argv))
