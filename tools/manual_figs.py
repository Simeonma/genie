#!/usr/bin/env python3
"""手册插图生成器 —— 全部曲线由真实公式计算，输出 SVG 到
commands/figs/。改图重跑本脚本；产物与 HTML 同笔提交。"""
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, Ellipse

OUT = pathlib.Path(__file__).resolve().parents[1] / "genie-sdk" / \
    "manual" / "commands" / "figs"
OUT.mkdir(exist_ok=True)

plt.rcParams.update({
    "svg.fonttype": "none",          # 文本保持可选中/可搜索
    "font.size": 12,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "figure.dpi": 100,
})
BLUE, RED, GREEN, GRAY = "#24557a", "#a04030", "#3f6f52", "#77828e"


def save(fig, name):
    import os
    if os.environ.get("FIG_PNG"):
        fig.savefig(OUT / name.replace(".svg", ".png"), format="png",
                    bbox_inches="tight", dpi=110)
    else:
        fig.savefig(OUT / name, format="svg", bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


# ---- fig-yee.svg：2D Yee 交错格点 -----------------------------------------
fig, ax = plt.subplots(figsize=(5.4, 4.4))
ax.set_xlim(-0.4, 3.4); ax.set_ylim(-0.4, 3.4)
ax.set_xticks(range(4)); ax.set_yticks(range(4))
ax.set_xlabel("i·Δx"); ax.set_ylabel("j·Δy")
for i in range(4):
    for j in range(4):
        ax.plot(i, j, "o", color=BLUE, ms=13)
        ax.text(i, j, f"$E_z$", ha="center", va="center",
                color="white", fontsize=9, zorder=5)
for i in range(4):
    for j in range(3):
        ax.plot(i, j + 0.5, "s", color=RED, ms=11)
        ax.text(i, j + 0.5, f"$H_x$", ha="center", va="center",
                color="white", fontsize=8, zorder=5)
for i in range(3):
    for j in range(4):
        ax.plot(i + 0.5, j, "s", color=GREEN, ms=11)
        ax.text(i + 0.5, j, f"$H_y$", ha="center", va="center",
                color="white", fontsize=8, zorder=5)
ax.set_title("2D Yee cell: $E_z$ at integers, $H_x$/$H_y$ at half-steps",
             fontsize=11)
save(fig, "fig-yee.svg")

# ---- fig-leapfrog.svg：蛙跳时间轴 -----------------------------------------
fig, ax = plt.subplots(figsize=(6.4, 2.2))
ax.set_xlim(-0.2, 3.2); ax.set_ylim(-0.9, 0.9)
for n in range(4):
    ax.plot(n, 0.35, "o", color=BLUE, ms=12)
    ax.text(n, 0.35, f"$E^n$", ha="center", va="center", color="white",
            fontsize=9, zorder=5)
for n in range(3):
    ax.plot(n + 0.5, -0.35, "s", color=RED, ms=12)
    ax.text(n + 0.5, -0.35, "$H^{n+½}$", ha="center", va="center",
            color="white", fontsize=8, zorder=5)
for n in range(3):
    ax.annotate("", xy=(n + 0.5, -0.2), xytext=(n, 0.2),
                arrowprops=dict(arrowstyle="->", color=GRAY))
    ax.annotate("", xy=(n + 1, 0.2), xytext=(n + 0.5, -0.2),
                arrowprops=dict(arrowstyle="->", color=GRAY))
ax.axis("off")
ax.set_title("Leapfrog: E at integer steps, H at half-steps", fontsize=11)
save(fig, "fig-leapfrog.svg")

# ---- fig-gaussian.svg：脉冲 + 频谱 ----------------------------------------
fig, axs = plt.subplots(1, 2, figsize=(9.2, 3.2))
f0, bw = 300.0, 120.0                       # THz
sigma_f_THz = bw / (2 * np.sqrt(2 * np.log(2)))  # FWHM -> σ (THz)
sigma_t = 1 / (2 * np.pi * sigma_f_THz * 1e12)    # s
t = np.linspace(-6e-15, 6e-15, 800) * 1e15         # fs
env = np.exp(-t**2 / (2 * (sigma_t * 1e15) ** 2))
carrier = np.cos(2 * np.pi * f0 * 1e12 * t * 1e-15)
axs[0].plot(t, carrier * env, color=BLUE)
axs[0].plot(t, env, "--", color=GRAY, lw=1)
axs[0].set_xlabel("t (fs)"); axs[0].set_ylabel("J(t) / J$_0$")
axs[0].set_title(f"pulse: f₀ = {f0:.0f} THz, Δf_FWHM = {bw:.0f} THz",
                 fontsize=11)
f = np.linspace(0, 700, 1200)
spec = np.exp(-(f - f0) ** 2 / (2 * sigma_f_THz ** 2))
axs[1].plot(f, spec, color=RED)
axs[1].axvline(f0 - bw / 2, ls="--", color=GRAY, lw=1)
axs[1].axvline(f0 + bw / 2, ls="--", color=GRAY, lw=1)
axs[1].set_xlabel("f (THz)"); axs[1].set_ylabel("|J̃(f)|")
axs[1].set_title("spectrum: FWHM marks = bandwidth", fontsize=11)
fig.tight_layout()
save(fig, "fig-gaussian.svg")

# ---- fig-lorentz.svg：Lorentz 极点的 Re/Im ε -------------------------------
fig, ax = plt.subplots(figsize=(6.4, 3.4))
w0, g, de = 1.0, 0.12, 1.8
w = np.linspace(0.3, 2.2, 900)
eps = de * w0**2 / (w0**2 - w**2 + 1j * g * w)
ax.plot(w, eps.real, color=BLUE, label="Re ε(ω)")
ax.plot(w, eps.imag, color=RED, label="Im ε(ω)")
ax.axhline(0, color=GRAY, lw=0.8)
ax.axvline(w0, ls="--", color=GRAY, lw=0.8)
ax.annotate("ω₀", xy=(w0, 2.6), fontsize=12)
ax.set_xlabel("ω / ω₀"); ax.set_ylabel("ε(ω) − ε∞  (one pole, Δε = 1.8)")
ax.legend(frameon=False, loc="upper right")
save(fig, "fig-lorentz.svg")

# ---- fig-pml.svg：σ 斜坡与场衰减 -------------------------------------------
fig, ax = plt.subplots(figsize=(6.4, 3.2))
L = 12.0
x = np.linspace(0, L, 300)
order = 3
smax = 6.0
sigma = smax * (x / L) ** order
decay = np.exp(-np.cumsum(sigma) * (L / 300) * 0.55)
ax.plot(x, sigma / smax, color=BLUE, label="σ(x)/σ_max  (polynomial ramp)")
ax.plot(x, decay, color=RED, label="|E| inside layer (decays)")
ax.set_xlabel("depth into PML (cells)")
ax.legend(frameon=False, fontsize=10)
save(fig, "fig-pml.svg")

# ---- fig-window.svg：矩形窗 vs Hann 窗旁瓣 --------------------------------
fig, ax = plt.subplots(figsize=(6.6, 3.4))
x = np.linspace(-4.5, 4.5, 4000)
rect_db = 20 * np.log10(np.abs(np.sinc(x)) + 1e-14)
N = 256
n = np.arange(N)
hann = 0.5 * (1 - np.cos(2 * np.pi * n / N))
pad = np.zeros(16384); pad[:N] = hann
H = np.abs(np.fft.fftshift(np.fft.fft(pad)))
fw = np.fft.fftshift(np.fft.fftfreq(16384)) * N     # 单位: 1/T
hann_db = 20 * np.log10(H / H.max() + 1e-14)
m = np.abs(fw) <= 4.5
ax.plot(x, rect_db, color=BLUE, lw=1.2,
        label="rectangular window (first sidelobe −13.2 dB)")
ax.plot(fw[m], hann_db[m], color=RED, lw=1.2,
        label="Hann window (first sidelobe −31.5 dB)")
ax.set_ylim(-70, 3); ax.set_xlim(-4.5, 4.5)
ax.set_xlabel("f − f₀  (units of Δf = 1/T)"); ax.set_ylabel("window, dB")
ax.legend(frameon=False, fontsize=10, loc="upper right")
save(fig, "fig-window.svg")

# ---- fig-ringdown.svg：截断环持续 → 谱展宽 --------------------------------
fig, axs = plt.subplots(1, 2, figsize=(9.2, 3.2))
tau = 1.0
f0 = 1.6                     # ×(1/τ) 单位下的共振频率
t = np.linspace(0, 7, 4000)
full = np.exp(-t / tau) * np.sin(2 * np.pi * f0 * t)
T = 3.0
obs = full * (t <= T)
axs[0].plot(t, full, color=BLUE, lw=1, label="true field (decays to 0)")
axs[0].plot(t, obs, color=RED, lw=1.4, label=f"observed: t ≤ {T:.0f}τ")
axs[0].set_xlabel("t  (units of τ)"); axs[0].set_ylabel("E(t)")
axs[0].legend(frameon=False, fontsize=9)
axs[0].set_title("field: run truncated at t = 3τ", fontsize=11)

fgrid = np.linspace(0.4, 2.8, 2500)
def spec(sig, tmax):
    tt = t[t <= tmax]; ss = sig[t <= tmax]
    return np.array([np.abs(np.trapezoid(ss * np.exp(-2j * np.pi * f * tt), tt))
                     for f in fgrid])
axs[1].plot(fgrid, spec(full, t.max()) / spec(full, t.max()).max(),
            color=BLUE, lw=1.2, label="true: Δf ≈ 1/(πτ)")
axs[1].plot(fgrid, spec(obs, T) / spec(obs, T).max(),
            color=RED, lw=1.2, label="observed: ringing sidebands")
axs[1].set_xlabel("f  (×1/τ)"); axs[1].set_ylabel("|Ẽ(f)| (norm.)")
axs[1].legend(frameon=False, fontsize=9)
axs[1].set_title("spectrum: truncation rings at ±1/T", fontsize=11)
fig.tight_layout()
save(fig, "fig-ringdown.svg")

# ---- fig-drude.svg：Drude 型金属 Re ε --------------------------------------
fig, ax = plt.subplots(figsize=(6.4, 3.2))
w = np.linspace(0.05, 2.2, 800)
eps_inf, wp, g = 1.0, 1.37, 0.09
eps = eps_inf - wp**2 / (w**2 + 1j * g * w)
ax.plot(w, eps.real, color=BLUE, label="Re ε(ω)")
ax.axhline(0, color=GRAY, lw=0.8)
ax.axvline(wp / np.sqrt(eps_inf), ls="--", color=GRAY, lw=0.8)
ax.annotate("plasma edge\nRe ε = 0", xy=(wp, -6), fontsize=10)
ax.set_xlabel("ω / ω_p"); ax.set_ylabel("Re ε(ω)")
ax.legend(frameon=False)
save(fig, "fig-drude.svg")

print("all figures done →", OUT)

# ---- 示例库配图（解析公式计算） -------------------------------------------
# ex-ring：微环 through 谱（Lorentzian 下陷）与 drop 谱（上凸）
fig, ax = plt.subplots(figsize=(6.4, 3.2))
f = np.linspace(-3, 3, 1500)
dip = 1 - 0.9 / (1 + (f / 0.12) ** 2)
drop = 0.9 / (1 + (f / 0.12) ** 2)
ax.plot(f, dip, color=BLUE, label="through port")
ax.plot(f, drop, color=RED, label="drop port")
ax.axvline(0, ls="--", color=GRAY, lw=0.8)
ax.set_xlabel("f − f_res  (×FSR)"); ax.set_ylabel("T (norm.)")
ax.legend(frameon=False, fontsize=10)
save(fig, "ex-ring.svg")

# ex-bragg：Bragg 反射镜 stopband（耦合模近似）
fig, ax = plt.subplots(figsize=(6.4, 3.2))
f = np.linspace(-3, 3, 1500)
r = 1 / np.sqrt(1 + (f / 0.45) ** 2 * np.cosh(0) ** 0) * np.tanh(np.sqrt(0.6**2 + (f/0.45)**2*0 + 0.36)) / np.tanh(0.6)
# 用标准耦合模：R = tanh²(κL·sinc 形耦合系数窗)
kappaL = 2.0
dc = np.ones_like(f)
dc[np.abs(f) > 1] = (1 - np.sqrt(1 - (1/np.abs(f[np.abs(f) > 1]))**2)) / \
                    (1 + np.sqrt(1 - (1/np.abs(f[np.abs(f) > 1]))**2))
R = (kappaL**2 * np.sinh(np.sqrt(kappaL**2 - (np.pi*f*0)**2))**0) * np.tanh(
    np.sqrt((kappaL * np.abs(dc))**2 + (0.0)**2))**2 / 1.0
R = np.tanh(kappaL * np.abs(dc))**2
ax.plot(f, R, color=BLUE)
ax.fill_between(f, R, where=np.abs(f) <= 1, color=BLUE, alpha=0.12)
ax.set_xlabel("detuning from Bragg condition (×Δf_stopband/2)")
ax.set_ylabel("R")
ax.set_title("coupled-mode stopband: R → tanh²(κL) at center", fontsize=10)
save(fig, "ex-bragg.svg")

# ex-meta：介质超表面单胞的布洛赫角扫描透射（共振下陷随角度移动）
fig, ax = plt.subplots(figsize=(6.4, 3.2))
f = np.linspace(1.4, 1.7, 1200)
for theta, c in [(0, BLUE), (15, RED), (30, GREEN)]:
    fr = 1.55 * (1 + 0.06 * np.sin(np.deg2rad(theta)) ** 2)
    q = 25.0
    T = 1 - (1/q) ** 2 / ((f - fr) ** 2 + (1/q) ** 2) * 0.85
    ax.plot(f, T, color=c, label=f"θ = {theta}°")
ax.set_xlabel("wavelength (µm)"); ax.set_ylabel("T (norm.)")
ax.legend(frameon=False, fontsize=10, title="Bloch angle")
save(fig, "ex-meta.svg")

# ---- 配置页示意图六张 -------------------------------------------------------
def _box(ax, x, y, w, h, fc, label=None, ec=None):
    ax.add_patch(plt.Rectangle((x, y), w, h, fc=fc, ec=ec or "#666", lw=1))
    if label:
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                fontsize=9, color="white" if fc != "#e8f1fc" else "#1f62b0")

# fig-domain：域 + PML + 结构 + 波 + 监视器
fig, ax = plt.subplots(figsize=(6.8, 3.4))
ax.set_xlim(0, 10); ax.set_ylim(0, 4.6); ax.axis("off")
ax.add_patch(plt.Rectangle((1, 0.6), 8, 3.4, fc="#ffffff", ec="#333", lw=1.4))
for xx in (0.6, 9.0):
    ax.add_patch(plt.Rectangle((xx, 0.6), 0.4, 3.4, fc="#d7e4f5", ec="none"))
ax.text(0.8, 2.3, "P", ha="center", va="center", color="#1f62b0", rotation=90)
ax.text(9.2, 2.3, "P", ha="center", va="center", color="#1f62b0", rotation=90)
ax.text(5, 4.15, "PML on entrance/exit faces · interior is plain vacuum/structure",
        ha="center", fontsize=10, color="#57606a")
_box(ax, 4.2, 1.4, 1.6, 1.8, "#dfe4ec", "structure")
for yy in (1.2, 2.3, 3.4):
    ax.annotate("", xy=(4.0, yy), xytext=(1.6, yy),
                arrowprops=dict(arrowstyle="->", color=RED, lw=1.4))
ax.text(2.8, 3.7, "plane wave", color=RED, fontsize=10)
ax.plot([6.6, 6.6], [1.0, 3.6], color=GREEN, lw=3, alpha=0.7)
ax.text(6.85, 3.5, "freq monitor\n(transmission)", fontsize=9, color=GREEN)
ax.set_title("domain: volume Ω, PML faces, source plane, monitor plane",
             fontsize=11)
save(fig, "fig-domain.svg")

# fig-mesh：局部加密网格
fig, ax = plt.subplots(figsize=(6.8, 3.2))
ax.set_xlim(0, 10); ax.set_ylim(0, 4); ax.axis("off")
for i in range(10):
    ax.plot([i, i], [0, 4], color=GRAY, lw=0.5)
for j in range(4):
    ax.plot([0, 10], [j, j], color=GRAY, lw=0.5)
for i in np.linspace(4, 7, 13):
    ax.plot([i, i], [1, 3], color=BLUE, lw=0.7)
for j in np.linspace(1, 3, 9):
    ax.plot([4, 7], [j, j], color=BLUE, lw=0.7)
ax.add_patch(plt.Rectangle((4, 1), 3, 2, fill=False, ec=RED, lw=1.6))
ax.text(5.5, 3.25, "refine(factor=2)", color=RED, fontsize=10, ha="center")
ax.text(2, 3.25, "Δx nominal", color="#333", fontsize=10, ha="center")
ax.text(5.5, 0.6, "structure region", color=RED, fontsize=9, ha="center")
ax.set_title("mesh: nominal spacing + refined box around the structure",
             fontsize=11)
save(fig, "fig-mesh.svg")

# fig-shapes：几何形状画廊
fig, axs = plt.subplots(2, 4, figsize=(9.6, 4.4))
def _clean(ax, title):
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_xlim(-1.3, 1.3); ax.set_ylim(-1.3, 1.3)
    ax.set_title(title, fontsize=10)
a = axs[0, 0]
a.add_patch(plt.Rectangle((-1, -0.7), 2, 1.4, fc="#dfe4ec", ec="#333"))
_clean(a, "box: x/y/z_range")
a = axs[0, 1]
a.add_patch(Circle((0, 0), 0.85, fc="#dfe4ec", ec="#333"))
_clean(a, "sphere: center+radius")
a = axs[0, 2]
a.add_patch(plt.Rectangle((-0.45, -1), 0.9, 2, fc="#dfe4ec", ec="#333"))
_clean(a, "cylinder: radius+height (axis z)")
a = axs[0, 3]
th = np.linspace(0, 2 * np.pi, 7)
a.add_patch(plt.Polygon(np.c_[np.cos(th), np.sin(th)], fc="#dfe4ec", ec="#333"))
_clean(a, "ngon_z: n_sides+circumradius")
a = axs[1, 0]
a.add_patch(Ellipse((0, 0), 2, 1.2, fc="#dfe4ec", ec="#333"))
_clean(a, "ellipse_z: rx, ry")
a = axs[1, 1]
a.add_patch(Circle((0, 0), 0.9, fc="#dfe4ec", ec="#333"))
a.add_patch(Circle((0, 0), 0.4, fc="white", ec="#333"))
_clean(a, "ring_z: inner 0 = solid disk")
a = axs[1, 2]
a.add_patch(plt.Polygon([(-1, -0.8), (-0.2, -0.8), (-0.2, 0.8), (0.6, 0.8),
                          (0.6, -0.8), (1, -0.8), (1, -1), (-1, -1)],
                         closed=True, fc="#dfe4ec", ec="#333"))
_clean(a, "polygon_z: vertices (+sentinel holes)")
a = axs[1, 3]
a.add_patch(plt.Polygon([(-1, -0.7), (0.3, -0.7), (1, 0.7), (-0.3, 0.7)],
                         closed=True, fc="#dfe4ec", ec="#333"))
a.annotate("", xy=(0.6, 1.05), xytext=(-0.7, -0.95),
           arrowprops=dict(arrowstyle="->", color=RED))
_clean(a, "polygon_swept: vertices + tilt")
fig.suptitle("geometry factories — overlap resolved by priority (larger wins)", fontsize=11)
fig.tight_layout()
save(fig, "fig-shapes.svg")

# fig-sources：三类光源
fig, axs = plt.subplots(1, 3, figsize=(9.8, 3.0))
a = axs[0]; a.set_xlim(0, 10); a.set_ylim(0, 6); a.axis("off")
for x0 in (2, 3.2, 4.4, 5.6):
    a.plot([x0, x0], [0.5, 5.5], color=RED, lw=1.1)
a.text(7.6, 3, "plane_wave\n(from_face / theta)", fontsize=10, ha="center", color="#333")
a = axs[1]; a.set_xlim(0, 10); a.set_ylim(0, 6); a.axis("off")
yy = np.linspace(0.5, 5.5, 200)
for x0, w in [(2, 2.2), (3.4, 1.7), (4.8, 1.1)]:
    a.errorbar(x0, 3, yerr=w, fmt="none", ecolor=RED, elinewidth=1.6,
               capsize=3)
a.text(7.6, 3, "gaussian_beam\n(radius = aperture)", fontsize=10, ha="center", color="#333")
a = axs[2]; a.set_xlim(0, 10); a.set_ylim(0, 6); a.axis("off")
a.add_patch(plt.Rectangle((3.6, 2.6), 2.8, 0.9, fc="#dfe4ec", ec=RED))
for r, al in [(1.2, 0.5), (2.0, 0.3), (2.8, 0.18)]:
    a.add_patch(Circle((5, 3.05), r, fc=RED, alpha=al*0.25, ec="none"))
a.text(7.6, 3, "soft_source\n(local J volume)", fontsize=10, ha="center", color="#333")
fig.suptitle("source types — all share freq / bandwidth / delay / phase", fontsize=11)
fig.tight_layout()
save(fig, "fig-sources.svg")

# fig-monitors：监视器布置
fig, ax = plt.subplots(figsize=(6.8, 3.4))
ax.set_xlim(0, 10); ax.set_ylim(0, 4.6); ax.axis("off")
ax.add_patch(plt.Rectangle((1, 0.6), 8, 3.4, fc="#ffffff", ec="#333", lw=1.2))
for xx in (0.6, 9.0):
    ax.add_patch(plt.Rectangle((xx, 0.6), 0.4, 3.4, fc="#d7e4ec", ec="none"))
_box(ax, 4.2, 1.5, 1.6, 1.6, "#dfe4ec", "structure")
ax.plot([6.8, 6.8], [1.0, 3.6], color=GREEN, lw=3, alpha=0.75)
ax.text(7.0, 3.55, "freq monitor (face) → T(f)", fontsize=9, color=GREEN)
ax.plot(2.6, 3.2, "o", color=RED, ms=9)
ax.text(2.75, 3.35, "time monitor (point)", fontsize=9, color=RED)
ax.add_patch(plt.Rectangle((3.0, 0.9), 4.0, 2.8, fill=False, ec="#953800", lw=1.3, ls="--"))
ax.text(5.0, 0.65, "index monitor (volume) → built ε(r)", fontsize=9,
        color="#953800", ha="center")
ax.set_title("monitors: face for spectra, point for waveforms, volume for ε(r)",
             fontsize=11)
save(fig, "fig-monitors.svg")

# fig-lifecycle：状态机
fig, ax = plt.subplots(figsize=(7.6, 2.2))
ax.set_xlim(0, 10); ax.set_ylim(0, 3); ax.axis("off")
states = [("defined", 1.1), ("built", 3.5), ("running", 6.0), ("done", 8.6)]
for name, x in states:
    ax.add_patch(Circle((x, 1.7), 0.62, fc="#e8f1fc", ec=BLUE, lw=1.4))
    ax.text(x, 1.7, name, ha="center", va="center", fontsize=9, color=BLUE)
for (n1, x1), (n2, x2) in zip(states[:-1], states[1:]):
    ax.annotate("", xy=(x2 - 0.72, 1.7), xytext=(x1 + 0.72, 1.7),
                arrowprops=dict(arrowstyle="->", color="#333"))
ax.text(2.3, 2.15, "run()", fontsize=9, ha="center")
ax.text(4.75, 2.15, "server build", fontsize=9, ha="center")
ax.text(7.3, 2.15, "march steps", fontsize=9, ha="center")
ax.annotate("failed / killed", xy=(6.0, 0.7), fontsize=9, color=RED, ha="center")
ax.annotate("", xy=(6.0, 1.02), xytext=(6.0, 0.62),
            arrowprops=dict(arrowstyle="->", color=RED))
ax.set_title("simulation lifecycle (run() raises GenieJobError on failure)",
             fontsize=11)
save(fig, "fig-lifecycle.svg")
