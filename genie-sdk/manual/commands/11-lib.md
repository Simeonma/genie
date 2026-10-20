# 11 · genie.lib — parametric device library

> One-shot wrappers for common structures: one call generates a whole set
> of geometry nodes. Pass your current Simulation instance as `f`;
> materials must be **registered first** (the preflight check rejects any
> reference to an undefined material at submission).

## genie.lib.grating()

An x-oriented grating of `n` line periods — a for loop of add_box in one
parameter-driven call (handy when sweeping pitch). Returns None; `duty`
outside (0,1) or `n < 1` → immediate ValueError.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `material` | str | yes | — | Name of a registered material |
| `x_range` | (m, m) | yes | — | Start and nominal end (`pitch * n` should ≈ end − start; a leftover half-period is your physical call) |
| `y_range` / `z_range` | (m, m) | yes | — | Cross-section extent of the lines (identical for all) |
| `n` | int | yes | — | Number of periods (lines, ≥ 1) |
| `pitch` | float, m | yes | — | Period |
| `duty` | float | no | 0.5 | Duty cycle, open interval (0,1); line width = `pitch * duty` |
| `priority` | int | no | 0 | Same value for all lines |

## genie.lib.ring()

A ring/disk — parametric wrapper over `add_ring_z`; `inner_radius=0` gives
a solid disk. Returns None.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `material` | str | yes | — | Name of a registered material |
| `outer_radius` / `height` | float, m | yes | — | Outer radius and height (> 0) |
| `inner_radius` | float, m | no | 0.0 | 0 = solid disk; must be < `outer_radius` |
| `center` | (x, y, z) m | no | (0, 0, 0) | Ring center |
| `priority` | int | no | 0 | — |

**Example**

```python
from genie.lib import grating, ring
f.mat.add_const().name('sio2').eps(2.1)
f.parameters({'pitch': 180e-9})
grating(f, material='sio2',
        x_range=(-1.6e-6, 1.6e-6),
        y_range=(-5e-7, 5e-7), z_range=(-1e-7, 1e-7),
        n=18, pitch=180e-9, duty=0.5)
ring(f, material='sio2', outer_radius=300e-9,
     inner_radius=100e-9, height=220e-9)
```

See also　Underlying shapes [add_box](#f-geom-geometry) / [add_ring_z](#f-geom-geometry);
sweeping `pitch`/radii with [f.sweep](#sweep-f-sweep-sweephandle) is the typical usage.
