# 3 · Boundaries and domain size

> A simulation box must end somewhere. What happens at the end decides
> whether your results are physics or reflections. This page gives the
> math behind the five boundary kinds and the rules for sizing the box.

Boundary choice and domain sizing are where most first FDTD simulations
go wrong, and they go wrong quietly. A reflecting boundary does not crash
the run; it superimposes a delayed, aliased copy of the field onto every
monitor, producing spectra with ripples that look like physics (Fabry–Perot
fringes of the computational box) and are in fact artifacts. The tell is
that the fringes move when you move the boundary and stay when you move
the structure. The discipline on this page is: choose each face's
condition deliberately, size the box against the wave, and size the time
against the slowest transient your observable depends on.

## Why the boundary matters

The grid is finite, but the wave is not: without treatment, a wave
reaching `∂Ω` reflects back with near-unity amplitude and contaminates
every monitor. The boundary condition is a model of the **exterior
world**, and you choose it per face:

```python
f.domain.boundary_condition('z_min', 'pml')
f.domain.boundary_condition('x_min', 'periodic')
```

The per-face granularity is a feature, not a bookkeeping burden. A device
that is translationally invariant along one axis needs `periodic` (or
`bloch`) on that pair of faces and absorption elsewhere; a waveguide
simulation wants PML on the propagation faces and metal or periodic on the
sides. A symmetric structure under symmetric excitation admits a symmetry
plane: replacing half the box with a `pmc` (or `pec`, for the odd
counterpart) symmetry plane and simulating the half domain halves the
computation — an explicit selection rule, not a convenience: whenever the
structure and the excitation share a mirror symmetry, `pmc`/`pec` on the
symmetry plane is the correct boundary and the half-domain simulation is
the cheaper equivalent of the full one. `pec` and `pmc` are the only kinds
with no same-axis pairing requirement; a single symmetry face is a valid
configuration. Reading the boundary list is therefore reading a compact
statement of the symmetry and radiation geometry of the problem. If you
cannot say in one sentence what the exterior world looks like on each of
the six faces, the simulation is not yet specified.

## PML — the absorbing boundary

The Perfectly Matched Layer truncates the grid with an artificial layer
that absorbs incoming waves with (in the ideal continuous case) **zero
reflection at any angle and frequency**. It works by coordinate
stretching: inside the layer, the derivative normal to the boundary is
warped as

```math
∂/∂x  →  ∂/∂x · 1/s(x),     s(x) = κ(x) + i·σ(x)/ω
```

The imaginary part `σ` makes the layer lossy with **no impedance
mismatch** at the interface; fields entering it decay as
`exp(−σ·x/(c·ε_eff))` and never come back. Discretization makes the match
slightly imperfect; reflection is exponentially small in the layer
parameters:

```math
|R| ∼ exp(−2 · σ_max · L / (c · n_eff))
```

**Why it matches.** An ordinary lossy layer has wave impedance
impedance `Z = √(μ/(ε + iσ/ω))` depends on `σ` — the impedance jumps at
the interface and reflects. In PML the coordinate stretching `s` multiplies
**both** ε and μ identically, so the ratio is untouched:

```math
Z_pml = √(μ·s / (ε·s)) = √(μ/ε) = Z_medium
```

Perfect matching is a property of the *continuous* stretching; the
discrete layer inherits it only approximately, and the residual
reflection of a ramped layer integrates to

```math
R(θ) ∝ exp( −2·(cosθ/c) · ∫₀ᴸ σ(x′) dx′ )
```

which is the precise statement of "exponentially small": to buy digits of
reflection you buy layer thickness or σ peak, exponentially. A polynomial
ramp `σ(x) = σ_max·(x/L)^order` minimizes discretization mismatch at both
ends — that is the SDK's `order` parameter (default 3).

The ramp matters because the dominant residual reflection of a discrete
PML comes from the leading edge, where the ramp is shallow but the
staircase sampling of `σ` is coarsest relative to the wavelength. A
higher `order` holds σ near zero longer, easing the field into the loss,
at the price of a steeper kick near the outer edge. Order 3 is the
standard compromise; order 4 occasionally helps for grazing incidence,
where the effective path length through the layer stretches by `1/cosθ`
and the reflection constant degrades long before the wave reaches the
outer edge.

Worked number. For an `order = 3` ramp the integral of σ over the layer
is `σ_max·L/4` (the average of `(x/L)³` is ¼), so at normal incidence the
reflection amplitude is `R ≈ exp(−σ_max·L/(2c))`. To hit −40 dB
(`|R| ≤ 10⁻²`) you need `σ_max·L ≥ 2c·ln(100) = 2.76×10⁹`. With the
Quickstart grid (`dx = 15 nm`) and the default `layers = 12`, the layer is
`L = 180 nm` thick, which requires `σ_max ≥ 1.5×10¹⁰ s⁻¹`. That is a
modest demand and the default meets it; the case that does not is a beam
arriving at 85° incidence, where `cosθ = 0.09` inflates the required
`σ_max·L` by a factor of 11 and the honest fix is more layers, not a
bigger σ peak (which aggravates the discretization mismatch the ramp was
chosen to suppress). For evanescent tails — a resonator's near field
decaying into the boundary — κ stretching (`kappa_max`) does the work,
since an evanescent wave decays in the layer only through the real
stretch.

The three knobs in the SDK map directly: `layers` = layer thickness `L`
(default 12), `kappa_max` = peak real stretch `κ` (default 1.0), `order` =
polynomial order of the σ ramp (default 3). Layer-count practice: 12–16
layers for accuracy runs, 8 layers for quick iterations; the parameter
constraint `layers ≥ 2` is enforced by the parameter table and is a
validity floor, not a recommendation. Increase `layers` for
grazing-incidence or highly evanescent fields.

## Periodic and Bloch boundaries

`periodic` ties opposite faces: the field satisfies

```math
E(r + a·x̂) = E(r)
```

valid only for **normal incidence** on a repeating structure. For oblique
incidence the phase advance between unit cells must be represented — that
is the `bloch` condition:

```math
E(r + a·x̂) = E(r) · e^{i·k_x·a}
```

with `k = (kx, ky, kz)` in rad/m, or `from_source=True` to take `k` from
the plane wave you already placed. For a plane wave of vacuum wavelength
`λ₀` at incidence angle `θ` in a background index `n`:

```math
|k| = 2π·n/λ₀ ,    k_x = |k|·sinθ ,    a·k_x = 2π · (a/λ) · sinθ
```

**The `k` protocol.** The Bloch wave vector is passed as the full vector
`k = [kx, ky, kz]` in rad/m, the same vector on both faces of the axis,
and each face uses only its own axis component. `k = [0, 0, 0]` makes
`bloch` degenerate to `periodic` face by face — a usable sanity check
that a `bloch` setup reproduces the `periodic` result at zero phase
advance.

The period enters only as the phase advance per cell — a Bloch sweep
is a scan of `a·k_x`, which is why oblique periodic simulations with a
`periodic` boundary instead silently compute normal-incidence physics. Using `periodic` where Bloch is needed
silently computes the wrong interference — this is the single most common
boundary mistake in periodic metasurface work.

The failure mode deserves its emphasis because nothing breaks. With
`periodic` faces and an oblique plane-wave source, the source injects a
wave with the correct angle and the boundary immediately contradicts it:
the field arriving at `x_max` with phase advance `e^{i·k_x·a}` is wrapped
to `x_min` with phase 1, and the mismatch acts as a fictitious scatterer
at the boundary. The run completes, the monitors report smooth spectra,
and the answer is the interference pattern of your device plus a
spurious grating of period `2π/Δk_x`. `from_source=True` removes the
arithmetic: the solver reads the in-plane wavevector off the source
definition. One worked value: the Quickstart source at `f = 330 THz`
(`λ₀ = 0.91 μm`) striking a grating of period `a = 180 nm` at θ = 30° in
vacuum carries `a·k_x = 2π·(0.18/0.91)·0.5 = 0.62 rad` of phase advance
per cell; that number, not the angle, is the physical input, and it is
what a Bloch sweep of angle actually varies.

**`from_source` precedence.** When `from_source=True` is passed together
with an explicit `k`, `from_source` takes precedence unconditionally and
`k` is silently ignored (ruling A1, 2026-09-07; the kernel `calibrate`
logic — "psi=90 gives e_hat=-x̂" — is of the same family: source-derived
quantities override the supplied value). `from_source=True` requires a
plane-wave or Gaussian-beam source to exist; otherwise the job fails.

**Oblique incidence, complete recipe.** Fix the angle `θ` on the source;
set transverse `bloch` faces with `k` equal to the transverse wave vector
at the center frequency (`k_x = |k(f₀)|·sinθ`, with `|k| = n·2πf₀/c`);
set `pml` on the propagation (longitudinal) faces. The Bloch phase is
exact only at `f₀`; over a broadband run the off-center frequencies carry
the wrong phase advance and accuracy degrades as the bandwidth widens.
The shortcut is `from_source=True`, which reads the transverse wave
vector off the source definition.

## Sizing the box

Sizing must satisfy two independent requirements:

**Room for the structure.** Between any scatterer and a PML face
leave several cells of background (and never put a monitor inside the
PML). Fields decay there; monitors inside the layer measure garbage.

**Runout for the physics.** The total time must be long enough that
the observable (a pulse, a resonance ring-down) has happened. A resonance
with quality factor `Q` at frequency `f₀` decays as

```math
E(t) ∝ e^{−π·f₀·t/Q}
```

so you need roughly `total_time ≳ Q/(π·f₀)` to capture the ring-down —
too short a time truncates it and produces spectral artifacts (that is
what `apodize` on freq monitors mitigates, not cures).

The two requirements fail in opposite directions and are cheap to check
separately. Spatial runout fails as reflections: the rule of thumb is a
background gap of order λ/4 to λ/2 between the last scatterer and a PML
face, enough that the near field (which decays fast) has become a
propagating field (which the PML absorbs at specification) before the
truncation. Temporal runout fails as spectral leakage: truncating a
ring-down in time convolves the true spectrum with a sinc of width
`1/T`, so a resonance that still has amplitude at `t = T` appears
broadened and shifted. The apodization window trades that sinc for a
Gaussian blur; it is first aid, not a substitute for a long enough `T`.

`domain.total_time` (seconds, > 0) is the single definition of the time
budget; the step count is derived from it at build (`n_steps ≈
total_time/Δt`) and is a read-only value in `summary`/`results` — there is
no `run.n_steps` to set.

## A worked domain-sizing decision

Here is the full sizing computation for the Quickstart grating, as you
would redo it for your own device. The structure spans
`x ∈ [−1.6, 0.02] μm`, so a box of `x ∈ [−2, 2] μm` leaves a 0.4 μm gap
between the last tooth and the `x_max` PML — about 0.44 vacuum wavelengths
at the 330 THz center frequency (`λ₀ = 0.91 μm`), comfortably above the
λ/4 rule. The transverse extent of ±1 μm against a grating that is 1 μm
wide leaves 0.5 μm of background on each side; with PML on `x_min/x_max`
only and the default (periodic or metal, per the config) on the transverse
faces, the monitor at `x = 1.7 μm` with a 1.2 μm aperture captures the
beam without clipping.

The grid at `dx = 15 nm` gives `4 μm/15 nm ≈ 267` cells along x and
`2 μm/30 nm ≈ 67` along y and z, about `1.2×10⁶` cells total, of which
the twelve PML layers per x-face (`180 nm`, λ₀/5) are a modest overhead.
The CFL limit for this anisotropic grid is
`Δt_max = 1/(c·√(1/dx² + 1/dy² + 1/dz²)) = 4.08×10⁻¹⁷ s`, so at
`cfl = 0.9` the solver steps at `Δt ≈ 3.7×10⁻¹⁷ s`. The requested
`total_time = 200 fs` therefore corresponds to `200/0.0367 ≈ 5450` steps,
and since the job marches to the grid's time capacity, all `200 fs` of
simulated time are delivered.
Is that enough? The light must cross the `3.7 μm` from source face to
monitor, about `12.5 fs`, and the grating is a weak, non-resonant
scatterer with an effective `Q` of order 10, whose stored energy decays in
`Q/(π f₀) ≈ 10 fs`. A budget of `200 fs` covers a dozen transit times
plus full decay, with margin for the low-frequency tail of the 60 THz
pulse. Had this been a high-Q resonator instead — say `Q = 1000` at
`f₀ = 193 THz`, needing `Q/(π f₀) ≈ 1.65 ps` — the same arithmetic says
the run needs `≈ 45 000` steps, and stopping at `200 fs` would smear every
spectral feature by more than `1/T ≈ 14 GHz` — set a larger `total_time`
instead. One repeatable lesson: the
time budget is decided by `λ/(n·dx)` and `Q/(π f₀)` together, and both
are known before the first run.

## Continue

- Exact parameter tables: [01 · f.domain](01-domain.html)
  and [02 · f.mesh](02-mesh.html)
- Putting it together: [Quickstart](quickstart.html)
