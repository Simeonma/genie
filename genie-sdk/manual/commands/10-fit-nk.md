# 10 · genie.material — n-k fitting & library

> Three module-level functions. For day-to-day work prefer
> [`f.mat.add_from_library`](#f-mat-materials-registry) (an automation wrapper over the same
> workflow); reach for these directly only when you have your own n-k data
> or need to fine-tune a fit.

## genie.material.fit_nk()

Fit n-k data into a Drude-Lorentz pole set (the only dispersive form the
kernel accepts); requires scipy (ImportError → `pip install scipy`).
Returns: dict `{converged, eps_inf, n_poles, poles, quality,
material_node, warnings}` — `material_node` is a `lorentz` node that goes
straight into a SimConfig (None = no usable node); for multi-component
inputs everything except warnings is a dict keyed by component.

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
