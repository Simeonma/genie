# 08 · sweep (f.sweep & SweepHandle)

> Submission returns a handle and **does not wait**; unlike `run()`, a sweep
> does not occupy this instance's job_id (the parent job runs on a separate
> track). All handle methods are HTTP forwarding plus thin local
> organization — no remote state is cached (every access queries live).

## `f.sweep()`

Starts a parameter sweep across the base configuration and returns a
`SweepHandle` immediately — use it to scan a parameter axis (or several)
without blocking. Axis syntax/mutual exclusion/point-count caps/parameter-name
validation are authoritative on the server (422 passed through); the same
local precheck runs before submission.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `config` | dict | no | `to_config()` | Base SimConfig JSON; defaults to the current instance's collected configuration |
| `parameters` | list | no | — | Convenient axis form: `[{"name": "dx", "linspace": [10e-9, 40e-9, 4]}, …]`; `name` must be a parameter name from the base `parameters` table; multiple axes default to `product` |
| `sweep` | dict | no | — | Fully-controlled SweepSpec dict (few users need this; can express the zip mode); mutually exclusive with `parameters` (if both given, `sweep` wins) |
| `mode` | str | no | `"product"` | `"product"` / `"zip"` — both axis forms can express either |
| `gpus_per_sim` | int | no | 1 | GPUs per point (1–8) |
| `max_parallel` | int | no | 1 | Cap on points running in parallel (1–16) |
| `on_failure` | str | no | `"continue"` | `"continue"` / `"abort"` |

**Example**

```python
f.parameters({'pitch': 180e-9})
# …chain configuration; dx etc. use {pitch} expressions…
h = f.sweep(parameters=[
    {"name": "pitch", "linspace": [140e-9, 240e-9, 6]},
], max_parallel=2)
h.wait(progress=True)
```

## SweepHandle

| Read-only | Returns | Description |
|---|---|---|
| `h.id` | str | Parent job sweep_id |
| `h.status()` | dict | Parent record + rollup + per-point summaries |
| `h.state` | str | Parent state: `queued/running/done/failed/canceled` |
| `h.rollup` | dict | Per-point counts `{succeeded, failed, canceled, …}` |
| `h.points()` | list | `[{idx, state, job_id}]` per-point summaries |
| `h.manifest()` | dict | Full manifest (axis summary + per-point md5) |

| Method | Description |
|---|---|
| `wait(timeout=None, poll=2.0, progress=None)` | Poll to a terminal state; `done` → returns the final status dict (incl. rollup), `failed`/`canceled` → raises `GenieJobError`. `timeout` is a local wait cap — on expiry GenieHTTPError is raised but **the job keeps running on the server**; re-enter `wait()` with no arguments to resume. `progress=True` for a one-line rollup progress |
| `cancel()` | Cascading cancel: parent lands on canceled, running/queued children reaped, unstarted points marked canceled. Already-terminal parent → HTTP 409 passed through |
| `child_id(idx, manifest=None)` | 0-based point index → child job id (manifest's job_id takes precedence; derived as `{sweep_id}-pNNNN`, 1-based, 4 digits, if absent) |
| `result(idx)` | That point's child-job result bytes (point not succeeded → 409 passed through) |
| `aggregate()` | Server-side aggregation table `aggregate.npz` bytes: parameter columns + per-point digest numeric-summary columns (not yet generated → 404) |
| `download(dir)` | Lands the whole set into `dir` (`manifest.json`, best-effort `aggregate.npz`, `pNNNN/result.npz`, `pNNNN/summary.json`); only `succeeded` points, existing files skipped (resumable). Returns the directory Path |

**Common pitfalls**

- Taking the `f` after `f.run()`, tweaking parameters, and sweeping — the
  `config` default pulls `to_config()`, i.e. the **current** configuration,
  which is locked after a run; don't run before sweeping.
- Assuming one failed point means total failure — under
  `on_failure="continue"` (default) the remaining points run anyway; check
  the `rollup` breakdown.
