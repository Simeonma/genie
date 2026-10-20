# 03 · f.mat — materials registry

> Two manual material types (const / lorentz) + one library-fit wrapper
> (from_library) + five management methods. **Geometries reference materials
> by `name`** — register first, then reference. All eps/mu entries: finite,
> > 0; tensors symmetric with positive main diagonal — violations return 422
> at the submit boundary. Duplicate names: later write wins (`remove_model`
> deletes every entry with that name).

## `f.mat.add_const()`

Registers a constant (non-dispersive) material; eps/mu accept a scalar (isotropic), a 3-element diagonal, or a 3×3 symmetric tensor.

| Chain method | Description |
|---|---|
| `.name(s)` | Registration name (required; geometries reference by it) |
| `.eps(v)` | Relative permittivity, dimensionless, > 0 (negative constant ε diverges numerically — use pole/library fits for metals) |
| `.mu(v)` | Relative permeability, dimensionless, > 0, default 1.0 |

```python
f.mat.add_const().name('sio2').eps(2.1)                 # iso
f.mat.add_const().name('quartz').eps([2.25, 2.25, 2.31])  # uniaxial
```

## `f.mat.add_lorentz()`

Registers a Drude-Lorentz dispersive material (`eps_inf` + pole list); the kernel is pole-only, so all dispersive metals/media are expressed as poles.

| Chain method | Description |
|---|---|
| `.name(s)` | Registration name (required) |
| `.eps_inf(v)` / `.mu_inf(v)` | High-frequency-limit ε/μ, same forms as const eps (scalar/diagonal/tensor, > 0), default 1.0 |
| `.add_eps_lorentz_pole(omega_0, gamma, delta_eps=1.0, *, alpha=None, beta=None)` | Adds one Lorentz pole; omega_0/gamma in rad/s, omega_0 > 0 |
| `.add_eps_drude_pole(omega_p, gamma, *, alpha=None, beta=None)` | Adds one Drude pole (the ω₀=0 case); omega_p > 0 |
| `.add_mu_lorentz_pole(...)` / `.add_mu_drude_pole(...)` | Magnetic poles, same parameters as above |

Pole forms (settled 2026-09; 3-element shorthand removed): **iso** — omit `alpha`/`beta` → isotropic on all axes; **rank-1** — `alpha=[x,y,z]` (required) ± `beta` (defaults to alpha) → anisotropic along one direction (auto-normalized, zero vectors rejected). Per-axis independence = stack poles. Gain = negative oscillator strength (`omega_p²<0` / negative Δε) is accepted; `gamma < 0` is rejected (not a gain channel).

```python
f.mat.add_lorentz().name('au_fit') \
    .eps_inf(1.0) \
    .add_eps_drude_pole(1.35e16, 1.05e14) \
    .add_eps_lorentz_pole(4.5e15, 1.3e15, 2.5)
```

**Common pitfalls**

- Passing a 3-element list to a pole — removed, SDK raises TypeError immediately (use iso scalar or rank-1 alpha/beta); wanting ω₀=0 with a lorentz pole is likewise rejected — Drude is the ω₀=0 case.
- Fitting hand-written nk data — use `add_from_library` below or `genie.material.fit_nk` (the kernel only consumes poles).

## `f.mat.add_from_library()`

Takes data from the built-in n-k material library (bundled locally, works offline, 37 materials) → fits on the client → registers a lorentz pole material node. Computed immediately (not a lazy setter): the config carries the poles themselves, identical locally and in the cloud. Returns: the registered pole material node.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `library` | str | ✓ | — | Library name, e.g. `'Au'`; `genie.material.list_library_materials()` lists all |
| `name` | str | — | library name | Registration name |
| `fit_range` | (lo, hi) m | — | (400nm, 800nm) | Fit wavelength window; < 3 points in the window raises an error |
| `n_drude` | int | — | 0 | Number of Drude poles |
| `n_lorentz` | int | — | 2 | Number of Lorentz poles |
| `maxfev` | int | — | 5000 | Iteration cap for scipy curve_fit |

```python
f.mat.add_from_library('Au', fit_range=(500e-9, 900e-9), n_lorentz=3)
f.geom.add_box().material('Au').x_range(...)…
```

**Common pitfalls**

- Passing `fit_range` in nm — the unit is meters (`(500e-9, 900e-9)`).
- Fitting requires scipy; missing → `ImportError` pointing to `pip install scipy` (no silent fallback). A fit producing no usable node → `ValueError` with a list of warnings. Expecting a `from_library` node in the config — the server rejects that node type; this is sugar that expands to lorentz.

## Management methods (five)

| Command | Returns | Description |
|---|---|---|
| `list_models()` | `list[str \| None]` | All material names (unnamed ones are None) |
| `has_model(name)` | `bool` | Whether that name is registered |
| `count_models` | `int` (property) | Number of materials |
| `remove_model(name)` | `bool` | Removes **all** entries with that name; True ⇔ the name actually disappeared |
| `clear_models()` | `None` | Clears the material table |
