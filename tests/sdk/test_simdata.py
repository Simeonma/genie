"""SimData 结构体（genie-results-h5/1）锚：属性直达/下标/attrs/plot 烟雾。"""
from __future__ import annotations

import io

import h5py
import numpy as np
import pytest

from genie.core.results import SimData

pytest.importorskip("matplotlib")


def _build() -> io.BytesIO:
    buf = io.BytesIO()
    with h5py.File(buf, "w") as f:
        g = f.create_group("tr")
        g.attrs["domain"] = "f"
        g.create_dataset("freqs", data=np.linspace(2e14, 4e14, 5))
        g.create_dataset("Ex", data=np.ones((5, 3), dtype="complex128")
                         * (1 + 1j))
        f.create_group("pt").attrs["domain"] = "t"
        f.attrs["format"] = "genie-results-h5/1"
        f.attrs["executed_steps"] = 400
        f.attrs["dt"] = 6.1e-17
    buf.seek(0)
    return buf


def test_simdata_attribute_and_index_access():
    d = SimData(h5py.File(_build(), "r"), job_id="j1")
    assert d.monitors == ["pt", "tr"] or d.monitors == ["tr", "pt"]
    assert d.attrs["executed_steps"] == 400
    assert d.attrs["format"] == "genie-results-h5/1"
    assert d.tr.Ex.shape == (5, 3) and d.tr.Ex.dtype.kind == "c"
    assert d["tr"]["freqs"].shape == (5,)
    assert (d.tr.Ex[()] == d.tr.Ex[()]).all()   # 值恒定（非身份比较）


def test_simdata_missing_monitor_attributeerror():
    d = SimData(h5py.File(_build(), "r"), job_id="j1")
    with pytest.raises(AttributeError):
        d.no_such_monitor


def test_simdata_plot_smoke(monkeypatch):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    d = SimData(h5py.File(_build(), "r"), job_id="j1")
    ax = d.plot("tr", "Ex")              # 复数 → |Ex|
    assert ax.get_ylabel() == "|Ex|"
    line = ax.get_lines()[0]
    assert line.get_ydata().shape == (5,)
    assert (line.get_ydata() > 0).all()  # |1+1j| = √2
    plt.close(ax.figure)
