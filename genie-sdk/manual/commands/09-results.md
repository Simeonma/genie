# 09 · results (get_* & SimData)

> Three ways to retrieve results: `get_time/get_freq/get_index` (raw data,
> cached), `results()` (full h5 view + plotting), and `digest()` (numeric
> summary, see [Submit & lifecycle](#f-submit-lifecycle)). Prerequisite: the job state must be
> `done`.

## f.get_time() / get_freq() / get_index()

Fetch the raw result object by monitor name; name omitted = first monitor
of that type. Cached — repeated calls cost no extra downloads.

| Command | Returns |
|---|---|
| `f.get_time(name=None)` | `TimeResult` from a time monitor |
| `f.get_freq(name=None)` | `FreqResult` from a frequency monitor |
| `f.get_index(name=None)` | `IndexResult` from an index monitor |

```python
fr = f.get_freq('tr')          # frequency monitor tr
fr.freqs                       # frequency array (Hz)
fr.fields                      # {field name: ndarray}
```

**Common pitfalls**

- Job not `done` → RuntimeError with the job log tail; wrong monitor name →
  `KeyError` with a name hint.

## The three Result objects

Shared surface: `.comps` (component list), `.keys()` (all data keys),
`.dict()` → `{key: np.ndarray}` for custom post-processing.

| Class | From | Extra attributes |
|---|---|---|
| `TimeResult` | time monitor | `.time` (time axis, s) |
| `FreqResult` | freq monitor | `.freqs` (frequency axis, Hz); fields are complex ndarrays |
| `IndexResult` | index monitor | eps/mu distribution (real) |

## f.results()

Returns: `SimData`, a wrapper over the h5 file. The grouped view it
exposes (`data.tr.Ex` — see below) is a convenience surface; the
underlying file layout follows the flat-key protocol described in
[The h5 key protocol](#the-h5-key-protocol) below. Prefers the file run() saved locally, otherwise
fetches on the spot; `job_id` omitted = this instance's latest job (any
historical job can be revisited).

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `job_id` | str | no | latest job | Job whose results to pull |

| Access | Gives |
|---|---|
| `data.monitors` | list of monitor names, e.g. `['tr', 'pt', …]` |
| `data.attrs` | root attributes: executed_steps / dt / grid_shape / format |
| `data.tr.Ex` | attribute access → complex ndarray (lazy h5py read) |
| `data["tr"]["Ex"]` | subscripting, same effect |
| `data.tr.keys()` | all dataset names for that monitor |

```python
data = f.results()
ax = data.plot("tr", "Ex")
data.plot("tr", "Ey", ax=ax)         # overlay
```

`data.plot(mon, field, ax=None)` returns a matplotlib Axes (optional
dependency — install `genie-sdk[plot]`); for volume monitors it plots the
peak grid point curve by default.

**Common pitfalls**

- Slice lazy h5py reads wherever possible (`data.tr.Ex[:, 0]`) instead of
  pulling the full array first.
- Comparing result files across parameter sweeps — use `digest()` (see
  page 07).

See also　Monitor definitions: [Monitors](#f-mon-monitors); auto-save paths: [f.run](#f-submit-lifecycle).

## The h5 key protocol

On disk the result file
uses **flat keys** — `<prefix>@<monitor>.<field>` — not nested groups:

| Prefix | Keys | Meaning |
|---|---|---|
| `t@` | `t@名.time`, `t@名.<comp>`, `t@名.x/y/z` | time-domain axis, field components, position axes (point monitors: **no** `x/y/z` arrays) |
| `f@` | `f@名.freqs`, `f@名.<comp>`, `f@名.x/y/z` | frequency axis, **complex DFT amplitudes**, position axes |
| `i@` | `i@名.eps`, `i@名.mu`, `i@名.x/y/z` | permittivity / permeability, per-cell coordinates |

The grouped access the SDK offers (`data.tr.Ex`, `get_freq('tr').fields`)
is a wrapped convenience view over these flat keys. Where older pages
describe the file as "one group per monitor, one dataset per field",
that describes the wrapper, not the wire format — this section is
authoritative when the two accounts coexist.

**Index-monitor data shape.** `i@名.eps` / `i@名.mu` is a **flat
per-cell list** (1-D, one value per grid cell) accompanied by
equal-length per-cell coordinate arrays `x`, `y`, `z` — not axis
ticks. To reconstruct a 3-D array, take `np.unique` on each
coordinate array and reshape: the unique counts give the grid
dimensions. Sanity anchors from a real run: vacuum n = 1.0000, SiO₂
n = 1.449 = √2.10.

**Axis-order pitfall (a common mistake).** The packed eps cube is
laid out in `(z, y, x)` order while the coordinate arrays are listed
as `x, y, z`. A reshape that assumes the coordinate order silently
transposes the structure — a correct build then *reads back as
wrong*, which is worse than a crash. Avoid by querying cells by
nearest-neighbor coordinate lookup, or by pinning the axis order
explicitly before any reshape.

**Time vs freq consistency.** On a healthy run the two routes agree to
within ~1%; a larger discrepancy points at monitor configuration
(sampling window, position mismatch) first, not the solver.
