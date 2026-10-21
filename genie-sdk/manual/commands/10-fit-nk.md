# 10 · genie.material — n-k fitting & library

> Three module-level functions. For day-to-day work prefer
> [`f.mat.add_from_library`](#f-mat-materials-registry) (an automation wrapper over the same
> workflow); reach for these directly only when you have your own n-k data
> or need to fine-tune a fit.

## Model-selection ladder

When a material model is needed, the selection order is: a **constant ε**
first, then a **hand-written pole** set, and only then a **library fit**.
The rule is to use the simplest model that describes the physics
correctly: a constant is free in memory and runtime, each hand-written
pole buys one resonance at known cost, and a fit is reserved for when
tabulated n-k data must actually be reproduced.

## genie.material.fit_nk()

Fit n-k data into a Drude-Lorentz pole set (the only dispersive form the
kernel accepts); requires scipy (ImportError → `pip install scipy`).
Returns: dict `{converged, eps_inf, n_poles, poles, quality,
material_node, warnings}` — `material_node` is a `lorentz` node that goes
straight into a SimConfig (None = no usable node); for multi-component
inputs everything except warnings is a dict keyed by component.
Failure semantics differ by surface: over the HTTP interface a
non-converged fit or `eps_inf ≤ 0` returns `material_node = null` plus
the `warnings` list, while the SDK surface raises `ValueError` for the
same conditions.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `nk` | 3-tuple / 7-tuple / dict | yes | — | `(wl, n, k)`: single-component iso fit (wl in m); `(wl, nx, kx, ny, ky, nz, kz)`: anisotropic xx/yy/zz; `{component name: (wl, n, k)}`: arbitrarily named components |
| `fit_range` | (lo, hi) m | no | (400e-9, 800e-9) | Fitting wavelength window; < 3 points inside → ValueError |
| `n_drude` / `n_lorentz` | int | no | 0 / 2 | Number of Drude / Lorentz poles |
| `maxfev` | int | no | 5000 | Iteration cap for curve_fit |
| `name` | str | no | None | Name of the resulting material_node |

**Example**

```python
import genie
wl, n, k = my_refractiveindex_data()          # SI: m / dimensionless
res = genie.material.fit_nk((wl, n, k), fit_range=(500e-9, 900e-9))
res["converged"] and res["material_node"]
# merge via chained API: rebuild the fitted material as pole chains (see 03 · f.mat)
m = f.mat.add_lorentz().name(res["material_node"]["name"]).eps_inf(res["material_node"]["eps_inf"])
for p in res["material_node"]["poles"]:   # Drude and Lorentz poles alike
    m.add_eps_lorentz_pole(**p)           # or m.add_eps_drude_pole(...) per pole type
```

**Common pitfalls**

- Passing wavelengths in nm — both `fit_range` and the data must be in
  meters.
- Reversed `fit_range` (lo ≥ hi) — ValueError.

## The fit_range → eps_inf → cfl divergence chain

`fit_range` does not just select where the fit is judged; it moves
`eps_inf`, and `eps_inf` feeds the Courant stability margin. Narrow the
window and the fitter trades background offset for in-band accuracy, and
the resulting `eps_inf` can drop below 1 — an n < 1 effective background
that tightens the CFL bound in ways the default `cfl` no longer covers.

Measured chain (Au, default pole counts):

| fit_range | eps_inf | cfl = 0.9 | cfl = 0.5 / 0.3 |
|---|---|---|---|
| 400–800 nm (default) | ≈ 7.6 | stable | stable |
| 500–600 nm | ≈ 0.20 (n < 1) | NaN divergence within ~1000 steps | stable |

Mitigations, in order of cost: probe with a short `total_time` trial run
before committing to a campaign; lower `cfl`; widen `fit_range` so the
fitter recovers a physical background; and when a narrow-band fit is
unavoidable, trust only in-band results and treat the stability margin
as part of the fit's price.

## genie.material.load_library_nk() / list_library_materials()

`load_library_nk(name, base_url=None, api_key=None, username=None, …)`
returns `(wl, n, k)` of a library material — prefers the built-in local
library (works offline), falls back to the server by default. Feed it to
`fit_nk` or plot it yourself. `list_library_materials()` lists all names
(37 entries, e.g. `Au`, `Ag`, `Si`…).

```python
wl, n, k = genie.material.load_library_nk('Au')
genie.material.list_library_materials()
```

See also　[add_from_library](#f-mat-materials-registry) = an automation wrapper over
load_library_nk + fit_nk + registration.
