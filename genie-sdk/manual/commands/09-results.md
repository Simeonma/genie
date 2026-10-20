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
`.dict()` → `{key: np.ndarray}` for your own post-processing.

| Class | From | Extra attributes |
|---|---|---|
| `TimeResult` | time monitor | `.time` (time axis, s) |
| `FreqResult` | freq monitor | `.freqs` (frequency axis, Hz); fields are complex ndarrays |
| `IndexResult` | index monitor | eps/mu distribution (real) |

## f.results()

Returns: `SimData`, a wrapper over the h5 file (groups = monitors,
datasets = fields/axes). Prefers the file run() saved locally, otherwise
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
dependency — install `genie[plot]`); for volume monitors it plots the
peak grid point curve by default.

**Common pitfalls**

- Slice lazy h5py reads whenever you can (`data.tr.Ex[:, 0]`) instead of
  pulling the full array first.
- Comparing result files across parameter sweeps — use `digest()` (see
  page 07).

See also　Monitor definitions: [Monitors](#f-mon-monitors); auto-save paths: [f.run](#f-submit-lifecycle).
