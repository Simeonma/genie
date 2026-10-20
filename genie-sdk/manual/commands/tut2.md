# 2 · Anatomy of a simulation

> A FDTD simulation has exactly six ingredients, and the SDK exposes them
> as six namespaces on one object `f`. This page maps each namespace to the
> mathematical role it plays in the discretized problem.

The value of this mapping is that it tells you where to look when a result
is wrong. A spectrum that is off in magnitude is a `f.mat` or `f.geom`
problem; a spectrum with spurious ripples is usually a `f.domain` problem
(reflections, truncated ring-down); a completely wrong interference
pattern is often a `f.src` polarization or phase problem; and a result
that is noisy or inconsistent between runs is typically a `f.mon` sampling
problem. Six namespaces, each with a crisp mathematical contract, means
every defect in a simulation has exactly one home. This page walks the
contract for each namespace and shows how the pieces assemble into the
single configuration object the server receives.

## The computational problem

You want to solve Maxwell's equations in a finite volume `Ω` for time
`[0, T]`, given:

- a permittivity/permeability distribution `ε(r), μ(r)` — **the structure**;
- an excitation `J(r, t)` — **the source**;
- boundary conditions on `∂Ω` — **what happens at the edges**;
- and you want to measure some fields — **the monitors**.

The six namespaces are a one-to-one map of these inputs:

| Namespace | Math role | Typical questions it answers |
|---|---|---|
| `f.domain` | the volume `Ω`, the time `T`, boundary conditions on `∂Ω` | How big? How long? What happens at the edges? |
| `f.mesh` | grid spacings `Δx, Δy, Δz` and local refinement | Is the discretization fine enough? |
| `f.mat` | the material functions `ε(ω), μ(ω)` available by name | How does the medium respond to fields? |
| `f.geom` | the spatial assignment `ε(r)` from shapes, by `priority` | Where is each material? |
| `f.src` | the injection term `J(r, t)` | How do I excite the structure? |
| `f.mon` | measurement points/volumes and their DFTs | What do I record, where, at which frequencies? |

Note that the monitors are not part of the mathematical problem at all:
Maxwell's equations are solved identically whether or not anything is
watching. Monitors are pure instrumentation, which is why they can be
added, moved, and widened between runs at zero physical risk. The same is
nearly true of `f.mesh`: the grid does not change the problem being
approximated, only the accuracy and cost of the approximation. In
contrast, `f.domain`, `f.mat`, `f.geom`, and `f.src` define the problem
itself, and errors in them produce a correctly-solved simulation of the
wrong physics. That distinction — model errors versus discretization
errors — is the most useful diagnostic habit this table buys you.

The one-object design is also what makes sweeps and session editing cheap.
Because every ingredient hangs off `f`, a parameter scan is a loop that
mutates one field and resubmits, and the studio GUI's forms, tree, and 3D
view are all read-only projections of the same object. There is no second
place where the geometry lives and no sync step that can fall behind: the
config you build in a script, the config the forms edit, and the config
the server rasterizes are one serialized SimConfig JSON at every point in
its life. When in doubt about what the server will receive, that JSON is
the thing to inspect, and `f` is the only thing that produces it.

## How ε(r) is assembled

Two lists cooperate. `f.mat` registers **named material functions**; `f.geom`
assigns them to regions of space:

```python
f.mat.add_const().name('sio2').eps(2.1)          # ε = 2.1 everywhere it is placed
f.geom.add_box().material('sio2') \
    .x_range(-0.5e-6, 0.5e-6) \
    .y_range(-0.5e-6, 0.5e-6) \
    .z_range(-0.1e-6, 0.1e-6)
```

The rasterized structure is a disjoint-union construction. With
shapes `S₁…S_N` of priorities `p₁…p_N` and materials `ε₁…ε_N`:

```math
ε(r) = ε_{j(r)} ,    j(r) = argmax{ pᵢ : r ∈ Sᵢ }   (ties → larger i)
```

When shapes overlap, the larger `priority` wins (equal priority: later in
the list wins). Unassigned space is vacuum (`ε = μ = 1`). So:
adding a shape can never change points it does not cover, and a
lower-priority shape is invisible exactly where any higher-priority shape
covers it — so "override a region" is done with a higher-priority
background patch, not by deletion.

This construction has a precise consequence worth internalizing: `ε(r)` is
a pure function of the *set* of shapes, never of their order or of the
order in which materials were registered. The two chains above could be
executed in the opposite order with an identical result, which is what
makes the form-editable session `f` safe to mutate freely. The rule also
defines the debugging procedure for overlapping geometry: to know what
material the grid carries at a point, list every shape covering it and
take the highest priority, breaking ties by list position. There is no
blending and no averaging — a pixel-level interrogation of a grating made
of two overlapping boxes returns exactly one ε, decided by these rules.

The materials registry exists to keep that set of shapes honest. A
geometry node references its material by name, so a structure with a
thousand shapes of one material stores the ε function once; changing
`ε` of `sio2` in one place re-rasterizes the whole device correctly.
The name indirection also separates two concerns that otherwise tangle:
`f.mat` answers how the medium responds (a frequency-dependent `ε(ω)` for
dispersive media, a constant for the `add_const` case here), while
`f.geom` answers only where it is. A grating scan that varies pitch
touches `f.geom` alone; a contrast scan that varies index touches
`f.mat` alone. Keeping the two edits apart is the whole reason the
registry is named rather than inlined.

Order of operations in the config is irrelevant to `ε(r)` — only
`priority` matters — so you can register materials and place shapes in any
order before `f.run()`.

## When is anything checked?

The SDK collects configuration without validating each line (a chain call
with a misspelled field fails immediately, but values are only checked in
bulk). Full validation — types, ranges, physical guards like `ε > 0` —
happens once, at the **submission boundary** inside `f.run()`. Errors come
back as `GenieConfigError` with a precise path. This design means partial
configurations are fine to hold in `f` while you build them up.

The design choice is deliberate. A builder-style API that validated each
statement would reject transiently inconsistent states that are perfectly
legal intermediate steps — for example, a geometry box that references a
material name you have not registered yet, registered two lines later.
Deferring validation to the submission boundary lets you construct the
config in whatever order is natural, at the cost that mistakes surface
late. The practical discipline is to validate the finished object early
and cheaply: calling `f.run()` on a deliberately truncated domain costs a
few seconds and exercises the entire validation path, so a config that
survives a smoke submission has cleared every structural check even though
the physics has not run. Errors carrying a precise path means the fix is
mechanical: the path names the namespace, the object, and the field.

What this means in practice is that the SDK's error messages are
addressed, not anecdotal. A negative `eps` on the seventh geometry node
reports as a path through `geom → node 7 → eps`, not as "invalid
configuration", because the validator walks the serialized SimConfig
tree, which has exactly those addresses. The same discipline governs the
physical guards: ranges must be min < max, frequencies positive, monitor
volumes inside the domain. All of these are cheap to state and expensive
to diagnose three GPU-minutes into a march, which is the trade the
submission-boundary design is optimizing: collect everything, then check
everything, once, where the whole object is visible.

## The grating Quickstart, counted

It is instructive to take the grating script from the
[Quickstart](quickstart.html) and inventory what the six namespaces
actually contain at submission time, because the counts are the honest
measure of simulation size.

`f.domain` carries four scalars (`x_range`, `y_range`, `z_range`,
`total_time = 20e-14` s, i.e. 200 fs) and two boundary assignments, one
call each for `x_min` and `x_max`. `f.mesh` carries three spacings,
`dx = 15 nm`, `dy = dz = 30 nm`. `f.mat` carries one material, a single
`add_const` chain naming `sio2` with `ε = 2.1`. `f.geom` carries exactly
**ten** box shapes: the `for i in range(N_TEETH)` loop executes the
`add_box` chain ten times, producing ten independent geometry nodes, each
with five fields (material name plus three ranges) — a 90 nm-wide tooth
every 180 nm of pitch starting at `x = −1.6 μm`, so the teeth span the
half-domain from `x = −1.6 μm` to `x = +0.02 μm`. `f.src` carries one
plane wave: `freq(3.3e14)` and `bandwidth(6e13)` make it a Gaussian pulse
centered at 330 THz with a 60 THz spread, injected from face `x_min`.
`f.mon` carries one frequency monitor: `field('all')` is **six** field
components (`Ex…Hz`), and `freq(3.3e14, 1.2e14, 300)` is **300** DFT
frequency samples spanning 120–330 THz, over a monitor volume of
`(0.2 × 1.2 × 1.2) μm` ≈ 13 × 40 × 40 ≈ 2.1×10⁴ grid points. The monitor
therefore accumulates `6 × 2.1×10⁴ × 300 ≈ 3.8×10⁷` DFT bins — trivial
next to the march itself, which is the point: recording everything costs
nothing, deciding to re-record after the fact costs a full rerun.

## The life of a run

```python
f.run()              # submit → queue → GPU build → march to total_time → done
```

`run()` is synchronous: it serializes `f` to a SimConfig JSON, validates,
POSTs, then polls until the job reaches a terminal state
(`defined → built → running → done`). On success the result file is
auto-downloaded next to your script. See
[07 · f — submit & lifecycle](f-submit-lifecycle.html) for `cancel`,
`timeout_s`, and multi-GPU options.

The state machine is worth knowing because each transition is a distinct
failure surface. `defined` means the config passed validation and is
queued; a stall here is load, not physics. `built` means `ε(r)` was
rasterized on the server and the job holds GPU memory; geometry errors you
somehow validated past show up here. `running` is the leapfrog march, and
`done` means monitors flushed and the result file is on its way back. The
call blocks for the whole sequence, which makes quick iteration a matter
of keeping runs small: the Quickstart's 2000 steps on a
267 × 67 × 67 cell grid (`4 × 2 × 2 μm` at 15/30/30 nm) is about
1.2×10⁶ cells × 2000 steps ≈ 2.4×10⁹ cell-updates, seconds of GPU time.
Budget your experiments against that number and you will rarely wait.

## Continue

- Exact fields and defaults per namespace: [01](f-domain-physical-domain-boundaries.html)
  · [02](f-mesh-grid-local-refinement.html) · [03](f-mat-materials-registry.html)
  · [04](f-geom-geometry.html) · [05](f-src-sources.html) · [06](f-mon-monitors.html)
- A complete working example: [Quickstart](quickstart.html)
