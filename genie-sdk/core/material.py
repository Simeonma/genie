"""genie.material — client-side Drude-Lorentz n-k → pole config fitting.

Ports the kernel's pure-numerical fitting (REFERENCE ONLY, never import the
kernel)::

    genie-fdtd/fdtd/_material/_fit.py                 — fit_drude_lorentz,
                                                       _params_to_poles
    genie-fdtd/fdtd/_material/_evaluate_dispersion.py — evaluate_dispersion
    v100/backend/tools_runner.py:49-160            — the API wrapper shape,
                                                       _pole_to_node, _quality_table

The deliverable is ``genie.material.fit_nk(nk, ...)`` — a thin pure function
that maps n-k data to *config* pole data (``materials[].poles``). Like the
rest of the SDK it stays dependency-light: ``import genie`` pulls only numpy;
scipy's ``curve_fit`` is imported lazily the first time ``fit_nk`` actually
fits, so the browser mirror can ``import genie`` without scipy until the fit
is invoked.  numpy is expected.

The returned dict matches ``tools_runner.material_fit`` for the single-component
(3-tuple) input so the UI can consume it unchanged.  For multi-component input
(dict / 7-tuple) the per-component quantities become dicts keyed by component
name (mirroring the kernel's ``MultiFitResult``), and ``warnings`` is folded
into one list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

# Speed of light in vacuum [m/s] — matches the kernel's C0_PHYS constant.
_C0_SI = 299792458.0
# Quality-table point cap before sampling (mirrors tools_runner.QUALITY_TABLE_CAP).
QUALITY_TABLE_CAP = 1000

from ..models import LIBRARY_FIT_DEFAULTS   # 拟合默认值正典（G2 归一）

__all__ = ["fit_nk", "load_library_nk", "list_library_materials"]

# ── 组合根注入点（G1 分层契约，2026-10-11 定案）──────────────────────
# core 只依赖 models/本地数据：load_library_nk 的 HTTP 回退实现在上层
# （net.client.fetch_nk_payload），由 ``genie/__init__`` 组合根在
# import 时注入。缺省 = 报"回退未接线"（产品面不可达——import genie
# 即接线）。分层守卫 = tests/sdk/test_layering.py。
hooks: dict = {}


def _wire(**impl) -> None:
    """组合根注册通道（genie/__init__ 专用；幂等覆盖）。"""
    hooks.update(impl)


# ═══════════════════════════════════════════════════════════════════════════
# Dispersion evaluation (pure numpy)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class _DispersionResult:
    """Result of dispersion evaluation from Drude-Lorentz pole tuples.

    eps : complex permittivity eps(omega); omega : angular frequencies [rad/s];
    n / k : refractive index real / extinction coefficient (Re/Im of sqrt(eps)).
    """
    eps: np.ndarray
    omega: np.ndarray
    n: np.ndarray
    k: np.ndarray


def _evaluate_dispersion(eps_inf, poles, omega):
    """eps(ω) = eps_inf + Σ ωp² / (ω0² − ω² − j·γ·ω)  (pure numpy).

    ``poles`` is a list of (omega_0, gamma, omega_p_sq) SI tuples — the same
    unified convention the kernel uses.  Returns a ``_DispersionResult``.
    """
    eps = np.full_like(omega, float(eps_inf), dtype=complex)
    w2 = omega * omega
    for w0, gm, omega_p_sq in poles:
        eps += omega_p_sq / (w0**2 - w2 - 1j * gm * omega)
    sq = np.sqrt(eps)
    return _DispersionResult(eps=eps, omega=omega, n=sq.real, k=sq.imag)


# ═══════════════════════════════════════════════════════════════════════════
# Drude-Lorentz fitting (log10-parameter space)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class _ComponentFit:
    """Single-component fit result: eps_inf, poles (ω0, γ, ωp²) SI tuples,
    converged."""
    eps_inf: float
    poles: list
    converged: bool


def _params_to_poles(params, n_drude, n_lorentz):
    """Unpack log10-space fit params → (ω0, γ, ωp²) SI pole tuples.

    Sole source of the parameter layout, shared by the residual and the result
    assembly (a second bit-identical copy in the kernel is exactly how the
    historical abs(ωp²) sign bug diverged — keep them in lockstep).
    """
    poles = []
    idx = 0
    for _ in range(n_drude):
        wp = 10.0 ** float(params[idx]); idx += 1
        gd = 10.0 ** float(params[idx]); idx += 1
        poles.append((0.0, gd, wp * wp))
    for _ in range(n_lorentz):
        de = 10.0 ** float(params[idx]); idx += 1
        w0 = 10.0 ** float(params[idx]); idx += 1
        g = 10.0 ** float(params[idx]); idx += 1
        poles.append((w0, g, de * w0 * w0))  # ωp² = Δε·ω0²
    return poles


def _dl_residual(omega, eps_inf, n_drude, n_lorentz, *params):
    """Residual for curve_fit (real+imag stacked) using evaluate_dispersion."""
    r = _evaluate_dispersion(eps_inf, _params_to_poles(params, n_drude, n_lorentz),
                             omega)
    return np.concatenate([r.n, r.k])


def _fit_drude_lorentz(wavelengths, n, k, n_drude=0, n_lorentz=2,
                       maxfev=5000):
    """Fit a single component's n-k data (already windowed) to Drude-Lorentz.

    Faithful port of the kernel's ``fit_drude_lorentz``: log10-space params,
    the frequency search box, the eps_inf high-frequency guess (argsort on the
    shortest wavelengths), the Drude low-frequency guess, the Lorentz peak-scan
    (suppress found peaks), clamping of p0 into bounds, and ``curve_fit`` with
    ``bounds``/``maxfev``.  On failure ``popt`` falls back to ``p0`` and
    ``converged`` is False (never raises for non-convergence).

    scipy is imported lazily here — the first time a fit actually runs.
    A missing scipy raises an ImportError with an explicit pointer
    (fit needs scipy; no silent degradation — F1 2026-09 ruling).

    2026-09 audit 批 α：删除了死的 ``eps_inf_guess=None`` 参数——全仓
    零调用方传它（fit_nk 不透传），留着是幽灵 API（反证：grep
    eps_inf_guess 全仓仅签名与分支两处）。
    """
    try:
        from scipy.optimize import curve_fit  # lazy: import genie stays scipy-free
    except ImportError as exc:
        raise ImportError(
            "拟合需要 scipy（curve_fit）——请安装: pip install scipy"
        ) from exc

    wavelengths = np.asarray(wavelengths, dtype=float).ravel()
    n = np.asarray(n, dtype=float).ravel()
    k = np.asarray(k, dtype=float).ravel()
    if wavelengths.size == 0:
        raise ValueError("wavelengths must be non-empty")
    if not np.all(np.isfinite(wavelengths)) or np.any(wavelengths <= 0):
        raise ValueError(
            f"wavelengths must be finite and > 0 [m]; got "
            f"min={np.min(wavelengths):.4g}, max={np.max(wavelengths):.4g}")

    omega = 2 * np.pi * _C0_SI / wavelengths

    # Frequency search box: only the LOWER bound adapts to the data span (so
    # sub-16 THz resonances are fittable); the ceiling stays at the historical
    # constants — a higher damping ceiling let the Au 1-Drude fit collapse into
    # a degenerate γ ≈ 4.6e17 pole that the ADE γ·dt guard rejects at build time.
    w_min = float(np.min(omega))
    w_max = float(np.max(omega))
    freq_lo = min(1e10, w_min * 1e-2)
    freq_hi = 1e17
    gamma_hi = 1e16

    high_idx = len(omega) // 8
    if high_idx <= 0:
        high_idx = 1
    # eps_inf is the HIGH-frequency limit: sample the shortest wavelengths
    # (argsort — input order agnostic). The static value eps(0) >= eps_inf,
    # so a low-frequency guess biases eps_inf high.
    order = np.argsort(wavelengths)
    hi_f_idx = order[:high_idx]
    eps_inf_0 = float(np.mean(n[hi_f_idx]**2 - k[hi_f_idx]**2))
    eps_inf_0 = max(eps_inf_0, 1.0)

    p0 = [eps_inf_0]
    bounds_low = [0.1]
    bounds_high = [100.0]
    # curve_fit/least_squares rejects any initial guess outside its bounds, so
    # extend the eps_inf box to contain the guess (the generic clamp below then
    # covers every parameter uniformly).
    if p0[0] > bounds_high[0]:
        bounds_high[0] = max(bounds_high[0], p0[0] * 1.1)
    elif p0[0] < bounds_low[0]:
        bounds_low[0] = min(bounds_low[0], p0[0] * 0.9)

    if n_drude > 0:
        # omega = 2πc/λ is DESCENDING for ascending wavelengths: the LAST
        # quarter holds the lowest frequencies (Drude tail), not the first.
        # eps_low must be sampled from the same low-frequency point.
        low_idx = int(np.argmax(wavelengths))
        w_low = omega[low_idx]
        eps_low = (n[low_idx] + 1j * k[low_idx]) ** 2
        wp_est = np.sqrt(max(-float(eps_low.real), 1.0)) * w_low
        p0 += [np.log10(wp_est), np.log10(1e14)]
        bounds_low += [np.log10(freq_lo), np.log10(min(1e11, freq_lo))]
        bounds_high += [np.log10(freq_hi), np.log10(gamma_hi)]

    eps_complex = (n + 1j * k) ** 2
    eps_imag = np.abs(eps_complex.imag)   # ufunc → fresh array, safe to mute
    for _ in range(n_lorentz):
        peak_idx = np.argmax(eps_imag)
        w0_est = omega[peak_idx]
        de_est = max(np.abs(eps_complex.imag[peak_idx]) * 2, 0.1)
        g_est = w0_est * 0.1
        p0 += [np.log10(de_est), np.log10(w0_est), np.log10(g_est)]
        bounds_low += [np.log10(1e-3), np.log10(freq_lo),
                       np.log10(min(1e10, freq_lo))]
        bounds_high += [np.log10(1e4), np.log10(freq_hi), np.log10(gamma_hi)]
        # Suppress this peak so the next iteration finds a different one.
        half_width = max(int(len(omega) * 0.05), 3)
        lo = max(0, peak_idx - half_width)
        hi = min(len(eps_imag), peak_idx + half_width + 1)
        eps_imag[lo:hi] = 0.0

    ydata = np.concatenate([n, k])

    # Clamp every initial guess into the search box: curve_fit rejects any p0
    # outside its bounds (eps_inf is a linear parameter; the log10-space pole
    # guesses hit the same trap whenever the data's resonances sit outside the
    # default optical band, e.g. THz data).
    p0 = [min(max(v, lo), hi)
          for v, lo, hi in zip(p0, bounds_low, bounds_high)]

    try:
        popt, _ = curve_fit(
            lambda w, *p: _dl_residual(w, p[0], n_drude, n_lorentz, *p[1:]),
            omega, ydata, p0=p0,
            bounds=(bounds_low, bounds_high), maxfev=maxfev)
        fit_converged = True
    except (RuntimeError, ValueError):
        popt = np.array(p0)
        fit_converged = False

    eps_inf = float(popt[0])
    ade_poles = _params_to_poles(popt[1:], n_drude, n_lorentz)
    return _ComponentFit(eps_inf=eps_inf, poles=ade_poles, converged=fit_converged)


# ═══════════════════════════════════════════════════════════════════════════
# Config-node assembly (pure)
# ═══════════════════════════════════════════════════════════════════════════

def _pole_to_node(w0, gamma, omega_p_sq):
    """(ω0, γ, ωp²) SI pole tuple → config PoleSpec node.

    Lorentz: ωp² = Δε·ω0² → delta_eps = ωp²/ω0²; Drude: ω0 == 0 (the kernel's
    unified convention, ``_params_to_poles`` produces exactly 0.0) → omega_p =
    √ωp².
    """
    if w0 == 0.0:
        return {"kind": "drude", "omega_p": float(omega_p_sq) ** 0.5,
                "gamma": float(gamma)}
    return {"kind": "lorentz", "omega_0": float(w0), "gamma": float(gamma),
            "delta_eps": float(omega_p_sq) / float(w0) ** 2}


def _sanity_check_lorentz_node(node):
    """Light stand-in for the kernel's pydantic ``LorentzMatSpec`` / ``PoleSpec``
    validation (the SDK must never import pydantic or the kernel).

    Re-checks the invariants the config consumer relies on, mirroring the
    kernel's guards: type == 'lorentz', non-empty name, eps_inf finite & > 0
    (``_check_finite_pos``), and per-pole gamma present, kind valid, and
    omega_0 / omega_p > 0 (``_check_pos`` — no finiteness guard on poles, and
    negative gamma = gain is accepted, matching the kernel).

    ``node`` is returned on success; ``ValueError`` is raised on any violation.
    """
    if not isinstance(node, dict):
        raise ValueError("material node must be a dict")
    if node.get("type") != "lorentz":
        raise ValueError(f"material node type must be 'lorentz', got {node.get('type')!r}")
    name = node.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("material node needs a non-empty 'name'")
    eps_inf = node.get("eps_inf")
    if eps_inf is None or not (np.isfinite(eps_inf) and eps_inf > 0):
        raise ValueError(f"eps_inf must be finite and > 0, got {eps_inf!r}")
    poles = node.get("poles")
    if not isinstance(poles, list):
        raise ValueError("material node 'poles' must be a list")
    for i, p in enumerate(poles):
        if not isinstance(p, dict):
            raise ValueError(f"pole {i} must be a dict")
        kind = p.get("kind")
        if kind not in ("lorentz", "drude"):
            raise ValueError(f"pole {i} kind must be 'lorentz' or 'drude', got {kind!r}")
        if p.get("gamma") is None:
            raise ValueError(f"pole {i} needs gamma")
        if kind == "lorentz":
            w0 = p.get("omega_0")
            if w0 is None or not (w0 > 0):
                raise ValueError(f"lorentz pole {i} needs omega_0 > 0")
        else:  # drude
            wp = p.get("omega_p")
            if wp is None or not (wp > 0):
                raise ValueError(f"drude pole {i} needs omega_p > 0")
    return node


def _quality_table(w, n_data, k_data, n_fit, k_fit):
    """Fit-quality summary: RMSE / max-abs-error plus per-wavelength tables.

    Mirrors ``tools_runner._quality_table``; subsamples the per-wavelength
    arrays above ``QUALITY_TABLE_CAP`` points (RMSE is still computed over the
    full set).
    """
    n = len(w)
    idx = (np.arange(n) if n <= QUALITY_TABLE_CAP
           else np.linspace(0, n - 1, QUALITY_TABLE_CAP).astype(int))
    return {
        "n_points": int(n),
        "subsampled": bool(n > QUALITY_TABLE_CAP),
        "rmse_n": float(np.sqrt(np.mean((n_fit - n_data) ** 2))),
        "rmse_k": float(np.sqrt(np.mean((k_fit - k_data) ** 2))),
        "max_abs_err_n": float(np.max(np.abs(n_fit - n_data))),
        "max_abs_err_k": float(np.max(np.abs(k_fit - k_data))),
        "wavelength_m": [float(v) for v in w[idx]],
        "n_data": [float(v) for v in n_data[idx]],
        "n_fit": [float(v) for v in n_fit[idx]],
        "k_data": [float(v) for v in k_data[idx]],
        "k_fit": [float(v) for v in k_fit[idx]],
    }


# ═══════════════════════════════════════════════════════════════════════════
# Public entry point
# ═══════════════════════════════════════════════════════════════════════════

def _fit_range_bounds(fit_range):
    """Unpack + validate ``fit_range`` (lo < hi) — a reversed range used to
    surface late as a misleading "Only 0 data points" error, so it fails here
    at the cause with the actual bounds."""
    lo, hi = fit_range
    if not lo < hi:
        raise ValueError(
            f"fit_range must satisfy lo < hi [m]; got ({lo!r}, {hi!r}) — "
            "a reversed range selects zero data points (the fit would "
            "otherwise fail later as 'Only 0 data points', far from the "
            "cause)")
    return lo, hi


def _scalar_result(fit, w, n_data, k_data, default_name):
    """Assemble the single-component tools_runner result dict.

    ``fit`` is a ``_ComponentFit``; ``w``/``n_data``/``k_data`` are the masked
    in-window arrays.  The config ``material_node`` is built only when the fit
    converged AND eps_inf > 0.
    """
    omega = 2.0 * np.pi * _C0_SI / w
    d = _evaluate_dispersion(fit.eps_inf, fit.poles, omega)
    n_fit = np.asarray(d.n)
    k_fit = np.asarray(d.k)

    warnings: list[str] = []
    if not fit.converged:
        warnings.append(
            "拟合未收敛（curve_fit 达到初始猜测/迭代上限）——极点是当前最优"
            "尝试而非可信解；建议缩窄 fit_range、减少极点数或加大 maxfev")
    if not (fit.eps_inf > 0):
        warnings.append(
            f"eps_inf={fit.eps_inf!r} ≤ 0，无法转成合法配置节点"
            "（lorentz 材料要求 eps_inf > 0）")

    poles = [_pole_to_node(*p) for p in fit.poles]
    node = None
    if fit.converged and fit.eps_inf > 0:
        node = {"type": "lorentz",
                "name": default_name,
                "eps_inf": float(fit.eps_inf),
                "poles": poles}
        try:
            _sanity_check_lorentz_node(node)
        except ValueError as e:
            node = None
            warnings.append(f"拟合结果转配置节点未通过校验: {e}")

    return {
        "converged": bool(fit.converged),
        "eps_inf": float(fit.eps_inf),
        "n_poles": len(poles),
        "poles": poles,                      # SI 角频率 rad/s（delta_eps 无量纲）
        "quality": _quality_table(w, n_data, k_data, n_fit, k_fit),
        "material_node": node,               # 可直接粘进配置 materials 数组
        "warnings": warnings,
    }


def fit_nk(nk, fit_range=LIBRARY_FIT_DEFAULTS["fit_range"],
           n_drude=LIBRARY_FIT_DEFAULTS["n_drude"],
           n_lorentz=LIBRARY_FIT_DEFAULTS["n_lorentz"],
           maxfev=LIBRARY_FIT_DEFAULTS["maxfev"], name=None):
    """Fit n-k data to a Drude-Lorentz model → poles config.

    Parameters
    ----------
    nk : (wavelengths_m, n, k) | dict of component -> (wl, n, k)
         | 7-tuple (wl, nx, kx, ny, ky, nz, kz)
        n-k data in SI [m, dimensionless, dimensionless].  A 3-tuple is a
        single-component isotropic fit; a 7-tuple is an anisotropic xx/yy/zz
        fit; a dict fits arbitrary named components.
    fit_range : tuple[float, float]
        Wavelength window [m].  Must satisfy lo < hi; each component's data is
        masked to (wl >= lo) & (wl <= hi) before fitting, and fewer than 3
        in-window points raises ValueError.
    n_drude : int
        Number of Drude poles (default 0).
    n_lorentz : int
        Number of Lorentz poles (default 2).
    maxfev : int
        Max function evaluations for scipy ``curve_fit``.
    name : str | None
        Name for the config ``material_node`` (defaults to "fitted" for a
        3-tuple, or the component key for multi-component input).

    Returns
    -------
    dict
        ``{converged, eps_inf, n_poles, poles, quality, material_node,
        warnings}``.  For single-component input these match
        ``tools_runner.material_fit`` so the UI can consume them unchanged —
        ``poles`` is a list of config poles (``{kind, omega_p|omega_0, gamma,
        delta_eps?}``) and ``material_node`` is a config ``lorentz`` node or
        None.  For dict / 7-tuple input, ``converged``/``eps_inf``/``n_poles``/
        ``poles``/``quality``/``material_node`` are dicts keyed by component
        (mirroring the kernel's ``MultiFitResult``) and ``warnings`` is one
        aggregated list.

    Raises
    ------
    ValueError
        If ``fit_range`` is reversed (lo >= hi), ``nk`` is not a recognized
        shape, a component is not a (wl, n, k) 3-tuple, or fewer than 3 points
        fall inside the fit window.
    """
    lo, hi = _fit_range_bounds(fit_range)
    # Normalize every input shape to {component: (wl, n, k)}; the scalar-vs-dict
    # result shape follows the INPUT TYPE (a user dict containing '' must stay
    # dict-shaped, hence the isinstance guard).
    is_scalar = not isinstance(nk, dict) and len(nk) == 3
    if isinstance(nk, dict):
        comps = dict(nk)
    elif is_scalar:
        comps = {'': nk}
    elif len(nk) == 7:
        wl_m, nx, kx, ny, ky, nz, kz = nk
        comps = {'xx': (wl_m, nx, kx), 'yy': (wl_m, ny, ky), 'zz': (wl_m, nz, kz)}
    else:
        raise ValueError(
            "nk must be 3-tuple, 7-tuple, or dict of component -> (wl, n, k)")

    fits: dict = {}
    fit_data: dict = {}
    for comp, comp_data in comps.items():
        try:
            wl, n_arr, k_arr = comp_data
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"nk component {comp!r} must be a (wl, n, k) 3-tuple, got "
                f"{type(comp_data).__name__}: {exc}") from exc
        wl = np.asarray(wl, dtype=float)
        n_arr = np.asarray(n_arr, dtype=float)
        k_arr = np.asarray(k_arr, dtype=float)
        mask = (wl >= lo) & (wl <= hi)
        n_in = int(mask.sum())
        if n_in < 3:
            raise ValueError(
                f"Only {n_in} data points in fit range "
                f"{lo * 1e9:.0f}-{hi * 1e9:.0f} nm for nk component "
                f"{comp!r} — widen fit_range or supply more data inside "
                f"the window")
        fits[comp] = _fit_drude_lorentz(
            wl[mask], n_arr[mask], k_arr[mask],
            n_drude=n_drude, n_lorentz=n_lorentz, maxfev=maxfev)
        fit_data[comp] = (wl[mask], n_arr[mask], k_arr[mask])

    if is_scalar:
        w, nd, kd = fit_data['']
        return _scalar_result(fits[''], w, nd, kd, name or "fitted")

    out = {c: _scalar_result(fits[c], *fit_data[c], name or c)
           for c in comps}
    return {
        "converged": {c: o["converged"] for c, o in out.items()},
        "eps_inf": {c: o["eps_inf"] for c, o in out.items()},
        "n_poles": {c: o["n_poles"] for c, o in out.items()},
        "poles": {c: o["poles"] for c, o in out.items()},
        "quality": {c: o["quality"] for c, o in out.items()},
        "material_node": {c: o["material_node"] for c, o in out.items()},
        "warnings": [warn for o in out.values() for warn in o["warnings"]],
    }


def load_library_nk(name, base_url=None, api_key=None, username=None,
                    *, timeout=30.0, allow_remote=True):
    """取材质库某名的原始 n-k 数据 → (wl_m, n, k)。

    F1 起 n-k 库随 fit 能力迁入服务仓：SDK 包内自带全部 yml
    （``genie/nkdata/``，迁移时与内核库逐字节一致），本函数**优先读
    本地打包数据**（离线可用，浏览器除外——Pyodide 无本地文件，继续
    走 HTTP）；本地无该库名时才回退 HTTP 端点
    ``GET /api/tools/nk_library?name=<name>``（后端读的也是同一份
    随迁库，本地/云端同构）。永不 import fdtd。

    Parameters
    ----------
    name : str
        库名（如 ``'Au'``）。base_url / api_key / username 缺省读环境
        变量 ``GENIE_URL`` / ``GENIE_API_KEY`` / ``GENIE_USERNAME``。
    allow_remote : bool
        本地无该库名时是否允许 HTTP 回退（默认 True；False 则本地
        未命中直接报错——纯离线断言用）。

    Returns
    -------
    (wl_m, n, k) : tuple[np.ndarray, np.ndarray, np.ndarray]
        波长（米）、折射率实部 n、消光系数 k（与 ``fit_nk`` 的 3-tuple
        输入约定一致；本地路径波长 µm→m 已换算）。

    Raises
    ------
    ValueError
        库名为空/含路径分隔符；本地未命中且（缺 base_url 或
        allow_remote=False）；后端返回意外格式；或三列不等长/非法。
    """
    from .nkdata import load_nk_data

    if not isinstance(name, str) or not name:
        raise ValueError("load_library_nk(name) 需要非空字符串库名")
    data = load_nk_data(name)
    if data is not None:
        wl_um, n, k = data
        return (np.asarray(wl_um, dtype=float) * 1e-6,
                np.asarray(n, dtype=float), np.asarray(k, dtype=float))
    if not allow_remote:
        raise ValueError(
            f"本地材质库无库名 {name!r}（离线模式不回退 HTTP；"
            "genie.material.list_library_materials() 可列本地全部库名）")
    url = base_url or os.environ.get("GENIE_URL")   # 可能为 None——组合根
    # 的 hook（G72 会话代持）还会沿 凭据仓>缺省 链补；这里不预拦。
    fetch = hooks.get("remote_nk_fetch")
    if fetch is None:
        if not url:
            raise ValueError(
                "load_library_nk 需要 base_url（或设置环境变量 GENIE_URL）——"
                "无法连接材质库；请先用 genie.connect(...) 指定服务器")
        raise RuntimeError(
            "材质库 HTTP 回退未接线——组合根（genie/__init__）负责注入；"
            "正常 ``import genie`` 即完成接线")
    key = api_key if api_key is not None else os.environ.get("GENIE_API_KEY")
    user = username if username is not None else os.environ.get("GENIE_USERNAME")
    payload = fetch(name, url, key, user, timeout)
    if (not isinstance(payload, dict) or "wavelength_m" not in payload
            or "n" not in payload or "k" not in payload):
        raise ValueError(
            f"材质库接口对 {name!r} 返回了意外格式: {str(payload)[:200]!r}——"
            "请确认后端 /api/tools/nk_library 支持 ?name= 返回三列数据")
    wl = np.asarray(payload["wavelength_m"], dtype=float)
    n = np.asarray(payload["n"], dtype=float)
    k = np.asarray(payload["k"], dtype=float)
    if not (len(wl) == len(n) == len(k)):
        raise ValueError(
            f"材质库 {name!r} 三列不等长: wavelength_m={len(wl)}, "
            f"n={len(n)}, k={len(k)}")
    return (wl, n, k)


def list_library_materials():
    """列出本地打包 n-k 库的全部库名（sorted，F1 随迁后离线可用）。"""
    from .nkdata import available_materials

    return available_materials()
