# Quickstart

> A complete guided-mode-free starter: one grating transmission simulation,
> from `connect()` to a plot, in about 30 lines. Every step links to the
> full reference.

## The whole script

This is a real, runnable simulation — a 10-period dielectric grating with a
plane-wave source and a frequency-domain transmission monitor:

```python
import genie

f = genie.connect("https://genie.example.com", api_key="…")   # or env vars

# 1 · physical domain (SI units throughout)
f.domain.x_range = (-2e-6, 2e-6)
f.domain.y_range = (-1e-6, 1e-6)
f.domain.z_range = (-1e-6, 1e-6)
f.domain.total_time = 20e-14
f.domain.boundary_condition('x_min', 'pml')
f.domain.boundary_condition('x_max', 'pml')

# 2 · grid
f.mesh.dx = 15e-9
f.mesh.dy = 30e-9
f.mesh.dz = 30e-9

# 3 · material
f.mat.add_const().name('sio2').eps(2.1)

# 4 · geometry: 10 grating teeth
N_TEETH, PITCH = 10, 180e-9
for i in range(N_TEETH):
    x = -1.6e-6 + i * PITCH
    f.geom.add_box().material('sio2') \
        .x_range(x, x + 90e-9) \
        .y_range(-5e-7, 5e-7) \
        .z_range(-1e-7, 1e-7)

# 5 · source
f.src.add_plane_wave().freq(3.3e14).bandwidth(6e13) \
    .from_face('x_min').name('pw')

# 6 · monitor
f.mon.add_freq().name('tr') \
    .center(1.7e-6, 0, 0).size(2e-7, 1.2e-6, 1.2e-6) \
    .field('all').freq(3.3e14, 1.2e14, 300)

# 7 · submit and wait
f.run()
```

## What each step does

| Step | Page | In one line |
|---|---|---|
| domain + PML | [01 · f.domain](01-domain.html) | Simulation box, total time, absorbing boundaries on x_min/x_max |
| mesh | [02 · f.mesh](02-mesh.html) | 15 nm fine axis along the grating, 30 nm elsewhere |
| material | [03 · f.mat](03-mat.html) | Register `sio2` (ε=2.1) — geometry references it by name |
| geometry | [04 · f.geom](04-geom.html) | A `for` loop stamps out N boxes — N executions, N nodes |
| source | [05 · f.src](05-src.html) | Plane wave from face `x_min`, centered 330 THz |
| monitor | [06 · f.mon](06-mon.html) | Frequency monitor `tr` behind the grating, 300 points |
| run | [07 · f — submit & lifecycle](07-run.html) | Submit + poll; results auto-download on success |

## Read the results

`f.run()` returns after the job reaches a terminal state and the result file
has been auto-downloaded. Three ways in:

```python
fr = f.get_freq('tr')        # raw arrays: fr.freqs (Hz), fr.fields
T  = abs(fr.fields['Ex'])**2 # do your own normalization/plotting

data = f.results()           # full h5 view: data.tr.Ex, data.attrs
data.plot('tr', 'Ex')        # quick matplotlib plot (optional dependency)

print(f.digest())            # numeric summary (server-computed, zero-GPU)
```

See [09 · results](09-results.html) for the full data surface.

## Where to go next

- Parameterize the pitch and scan it: [08 · sweep](08-sweep.html)
- Metals and dispersion: [03 · f.mat](03-mat.html)
  (`add_lorentz`, `add_from_library`)
- Ready-made structures (gratings, rings): [11 · genie.lib](11-lib.html)
