# FAQ

> Quick answers to the most common questions, each linking to the authoritative
> page. Everything here is drawn from the reference pages and tutorials — no
> behavior beyond them.

## Setup & basics

### How do I connect to the service?

`genie.connect()` reads `GENIE_URL`/`GENIE_API_KEY` from the environment, or take them explicitly (`https://genie.example.com` for remote SDK, `http://127.0.0.1:8777` for Studio debugging). Missing both URL sources errors at the HTTP layer — see [00 · Connections](00-connect.html).

```python
import genie
f = genie.connect()   # or genie.connect("https://genie.example.com", api_key="…")
```

### Why did tweaking `f` and rerunning resend the old configuration?

A `Simulation` can only be submitted **once** — after `f.run()` the configuration is locked, and parameters passed to `run()` then raise RuntimeError. Create a fresh `genie.connect()` and rebuild via `f.to_script()` (export the script, run it on the new instance) for the next run — see [07 · Submit & lifecycle](07-run.html).

### Why are my lengths wrong by orders of magnitude?

The whole SDK is SI — meters, Hz, seconds. `f.mesh.dx = 25` (nm intended) makes the domain far smaller than the grid, and `fit_range` in nm errors the fit. Write `25e-9` — see [02 · Mesh](02-mesh.html).

### How do I check my geometry before running?

Add an index monitor (`f.mon.add_index().name('ix').field('both')`) — it returns the *built* `ε(r), μ(r)` after rasterization, where stair-casing, priority mistakes, and misplaced shapes show up. Also `f.summary()` self-checks completeness pre-submit. See [06 · Monitors](06-mon.html) and [07 · Submit](07-run.html).

## Domain, mesh & boundaries

### What does `cfl` change?

`f.domain.cfl` (default 0.9) scales the time step relative to the 3D stability limit: `Δt = cfl × Δt_max`. You normally never touch it; lowering it buys stability margin at the cost of more steps for the same `total_time` — see [01 · Domain](01-domain.html) and [Tutorial 1](tut1.html).

### How fine should my grid be?

At least ~10 cells per wavelength in the highest-index material (`dx ≈ λ/(10·n)`), finer near resonances. Set a nominal `f.mesh.dx` and use `f.mesh.refine(..., factor=k)` boxes (integers ≥ 2) around the fine structure — see [02 · Mesh](02-mesh.html).

### Why was my refine region rejected or useless?

`factor` has integer semantics — `1.5` is truncated to 1, i.e. no refinement at all; pass integers ≥ 2. Don't place the region flush against the domain edge: refining inside the PML wastes cells; leave 2–3 transition layers — see [02 · Mesh](02-mesh.html).

### Why is my oblique periodic simulation giving wrong physics?

`periodic` is valid only for **normal incidence**. Oblique incidence on a repeating structure needs `bloch` (with `k`, or `from_source=True`), otherwise the interference is silently wrong — the most common boundary mistake in metasurface work. See [Tutorial 3](tut3.html) and [01 · Domain](01-domain.html).

```python
f.domain.boundary_condition('x_min', 'bloch', from_source=True)
```

### How long should `total_time` be?

Long enough that your observable has happened: a resonance of quality factor Q at f₀ needs `total_time ≳ Q/(π·f₀)` to ring down, and spectral resolution is `Δf ≈ 1/total_time`. Check with a time monitor that fields have decayed at the end. See [Tutorial 3](tut3.html) and [Tutorial 6](tut6.html).

## Sources

### How do I choose the source bandwidth?

The Gaussian pulse's `bandwidth` (Hz) sets which spectrum is excited: it resolves features coarser than roughly `bw`, and by time–bandwidth duality the pulse lasts `~1/bw` — wide bandwidth = short pulse = short simulation. A 120 THz bandwidth pulse is ~3.7 fs FWHM. See [05 · Sources](05-src.html) and [Tutorial 5](tut5.html).

```python
f.src.add_plane_wave().freq(300e12).bandwidth(60e12).from_face('z_min')
```

### How should I set the plane-wave incidence angle?

Prefer `.from_face('x_min' …)` — normal incidence, simplest and most reliable. For oblique incidence set `theta`/`phi` (don't combine with `from_face`, which is sugar for normal incidence), and use `bloch` boundaries with a matching `size` window. See [05 · Sources](05-src.html).

### For a Gaussian beam, what does `radius` mean?

It is the **aperture radius** on the source plane, not the beam width: the 1/e² spot is `w ≈ 0.47·radius`, so set `radius ≈ 2.12·w` for a desired `w`. See [05 · Sources](05-src.html).

### Why do my monitors near the source show garbage?

Inside the TFSF source window (or just at the source plane) monitors mix incident + scattered fields; keep monitors a few cells away, face monitors between structure and PML. Never place a monitor inside the PML — those fields have no physical meaning. See [05 · Sources](05-src.html) and [Tutorial 6](tut6.html).

## Monitors & results

### How do I request frequency points on a freq monitor?

Only the three-argument form `.freq(center, bw, n)` works — points `linspace` over `[center−bw/2, center+bw/2]`; a single value or list is rejected. See [06 · Monitors](06-mon.html).

```python
f.mon.add_freq().name('tr').center(0, 0, 500e-9).size(1e-6, 1e-6, 0) \
    .field('all').freq(300e12, 120e12, 200)
```

### Why is my transmission not between 0 and 1?

Raw `|Ẽ|²` is not transmission — it must be normalized by the incident flux. Only server-computed numbers in `f.digest()` marked `normalized=true` are physical T, and only for **plane** monitors (point monitors have no area integral and carry no T). If R+T+A > 1, suspect a too-small box or a truncated resonance. See [Tutorial 5](tut5.html) and [Tutorial 6](tut6.html).

### My spectrum has ringing/sidelobes around a sharp peak. Why?

A finite record of length T convolves your spectrum with a sinc (−13.2 dB first sidelobe) — a truncated ring-down. Run longer (`total_time ≳ 3τ`) or apply `.apodize('both', …)` (Hann window, −31.5 dB sidelobes, at 2× resolution cost). See [Tutorial 5](tut5.html) and [06 · Monitors](06-mon.html).

### How do I read the results?

Three paths into the same auto-downloaded h5: `f.get_freq('tr')` (cached raw arrays), `f.results()` (whole-file view + `.plot()`), `f.digest()` (server-side numeric summary, no file). The job must be `done`; a wrong name raises `KeyError` with a hint. See [09 · Results](09-results.html) and [Tutorial 6](tut6.html).

```python
fr = f.get_freq('tr');  spec = abs(fr.fields['Ex'])**2
```

## Materials

### How do I fit gold (or any metal)?

Register a library fit: `f.mat.add_from_library('Au', fit_range=(500e-9, 900e-9))` loads bundled n-k data and fits Drude-Lorentz poles client-side (37 materials, works offline; needs scipy). Note `fit_range` is in **meters**. See [03 · Materials](03-mat.html) and [10 · genie.material](10-fit-nk.html).

```python
f.mat.add_from_library('Au', fit_range=(500e-9, 900e-9), n_lorentz=3)
```

### Why can't I just set a negative constant ε for a metal?

A negative constant ε is rejected at submission — it is nondispersive and numerically divergent. The kernel is pole-only: metals must be Drude/Lorentz poles (`add_lorentz` + `add_eps_drude_pole`). See [03 · Materials](03-mat.html) and [Tutorial 4](tut4.html).

### How do I express gain in a material?

Not with negative damping — `gamma < 0` is rejected. The gain channel is a **negative oscillator strength** (`Δε < 0`, equivalently `ωp² < 0`), which the kernel accepts as a bounded pump model. See [Tutorial 4](tut4.html).

### How do geometries decide which material wins where?

Shapes overlap by `priority` — larger wins; equal priority: later in list order wins. Unassigned space is vacuum. "Punch a hole" with a higher-priority background-material patch, not deletion. See [04 · Geometry](04-geom.html) and [Tutorial 2](tut2.html).

## Running & sweeps

### How do I scan a parameter without blocking?

Put the quantity behind a named parameter (`f.parameters({'pitch': 180e-9})`, referenced as `'{pitch}'` in numeric slots), then `f.sweep(parameters=[{"name": "pitch", "linspace": [...]}])` returns a `SweepHandle` immediately. See [08 · Sweep](08-sweep.html).

```python
h = f.sweep(parameters=[{"name": "pitch", "linspace": [140e-9, 240e-9, 6]}],
            max_parallel=2)
h.wait(progress=True)
```

### How do I scan two parameters together (zip)?

Two ways: `mode="zip"` pairs axis points element-wise, or pass a fully-controlled `sweep` SweepSpec dict (which wins if both `sweep` and `parameters` are given). Default `mode="product"` scans the Cartesian product. See [08 · Sweep](08-sweep.html).

### Why was my sweep point skipped / marked failed?

Under the default `on_failure="continue"` the remaining points run anyway — check `h.rollup` for the `{succeeded, failed, canceled}` breakdown and `h.points()` per point; failed points return 409 from `h.result(idx)`. See [08 · Sweep](08-sweep.html).

### Why can't I sweep after `f.run()`?

The sweep's base config defaults to `to_config()` — the **current** configuration, which is locked after a run. Build the parameterized configuration and sweep it without running first. Also note sweep axes can only vary **parameter names**, not literals like a `dx` value. See [08 · Sweep](08-sweep.html) and [07 · Submit](07-run.html).

### How do I rerun with a changed parameter?

You cannot mutate a submitted instance. Either export `f.to_script()`, tweak the script, and run it on a fresh `genie.connect()`, or make the quantity a named parameter and use `f.sweep()` with a single-point axis. See [07 · Submit](07-run.html) and [08 · Sweep](08-sweep.html).

## Units & expressions

### Can I write `"d/4"` instead of a number?

Yes — every numeric slot accepts an expression string evaluated **server-side**, referencing the global parameter table set by `f.parameters()` (repeated calls merge). Use bare parameter names (`'d/4'`, not `'{d}/4'` — braces are a Python set literal and get rejected); unit suffixes like `'50[nm]'` also work. Referencing an undefined parameter is rejected at the submission boundary, not locally. See [07 · Submit](07-run.html) and [00 · Connections](00-connect.html).

```python
f.parameters({'d': 1e-6, 'gap': 'd / 10'})
f.mesh.dx = 'd / 40'
```

### How do I build common structures quickly?

`genie.lib.grating(f, …)` and `genie.lib.ring(f, …)` generate whole geometry node sets in one parameter-driven call (register materials first; `duty` ∈ (0,1) open interval, `n ≥ 1` — violations raise ValueError immediately). See [11 · genie.lib](11-lib.html).
