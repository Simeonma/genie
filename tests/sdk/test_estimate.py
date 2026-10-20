"""守卫：估算单一真源（`genie.models.estimate`）+ preview estimate 节。

锚：与内核守卫同一把尺子（base：1µm³ @25nm = 40³=64000 cells；步数
√3·c₀·T/(cfl·min_cell)，60fs@2e-8、cfl0.9 ≈ 1733）。"""
from __future__ import annotations

import math

import pytest

from genie.models._wire import DomainSpec, MeshSpec
from genie.models.estimate import (estimate_cells_domain_mesh,
                                   estimate_steps_domain_mesh,
                                   mesh_preview_stats)

_D = dict(x_range=(-1e-6, 1e-6), y_range=(-1e-6, 1e-6),
          z_range=(-1e-6, 1e-6), total_time=6e-14)
_M = {"dx": 2.5e-8}


def test_cells_base_grid():
    d, m = DomainSpec(**_D), MeshSpec(**_M)
    assert estimate_cells_domain_mesh(d, m) == 80 ** 3


def test_steps_formula():
    d, m = DomainSpec(**_D), MeshSpec(**_M)
    expect = math.ceil(math.sqrt(3) * 299792458.0 * 6e-14
                       / (0.9 * 2.5e-8))
    assert estimate_steps_domain_mesh(d, m) == expect


def test_refine_inflates_cells():
    m = dict(_M, refine=[{"x_range": [0, 5e-7], "y_range": [-1e-6, 1e-6],
                          "z_range": [-1e-6, 1e-6], "factor": 2}])
    d, mm = DomainSpec(**_D), MeshSpec(**m)
    base = estimate_cells_domain_mesh(d, MeshSpec(**_M))
    assert estimate_cells_domain_mesh(d, mm) > base


def test_mesh_preview_stats_shape():
    st = mesh_preview_stats(DomainSpec(**_D), MeshSpec(**_M))
    assert st["cells"] == 80 ** 3 and st["n_steps_est"] > 0
    assert st["dt_est"] == pytest.approx(0.9 * 2.5e-8
                                         / (math.sqrt(3) * 299792458.0))
    assert st["spacing"] == {"dx": 2.5e-8, "dy": 2.5e-8, "dz": 2.5e-8}


def test_preview_attaches_estimate():
    import genie
    src = ("import genie\n"
           "f = genie.connect('x')\n"
           "f.domain.x_range = (-1e-6, 1e-6)\n"
           "f.domain.y_range = (-1e-6, 1e-6)\n"
           "f.domain.z_range = (-1e-6, 1e-6)\n"
           "f.domain.total_time = 6e-14\n"
           "f.mesh.dx = 2.5e-8\n")
    r = genie.preview_script(src)
    assert r["ok"] is True
    est = r.get("estimate")
    assert est and est["cells"] == 80 ** 3 and est["n_steps_est"] > 0


def test_preview_partial_no_estimate():
    import genie
    r = genie.preview_script("import genie\nf = genie.connect('x')\n")
    assert r["ok"] is True and "estimate" not in r
