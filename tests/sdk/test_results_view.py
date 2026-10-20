"""results_view 纯函数守门（G13②：结果 = 会话状态）。"""
from __future__ import annotations

import numpy as np
import pytest

from genie.studio import results_view as rv


@pytest.fixture()
def h5(tmp_path):
    import h5py
    p = tmp_path / "genie_results" / "job-42_results.h5"
    p.parent.mkdir(parents=True)
    freqs = np.linspace(2.8e14, 3.2e14, 500)
    tr = 0.3 + 0.6 * np.exp(-((freqs - 3e14) ** 2) / (2 * 1e25)) \
        + 0.05j * np.sin(freqs * 1e-15)          # 复数场（|·| 取模）
    with h5py.File(p, "w") as f:
        f.attrs["dt"] = 2.5e-17
        f.attrs["executed_steps"] = 1234
        f.attrs["grid_shape"] = [32, 32, 64]
        g = f.create_group("tr")
        g.attrs["domain"] = "f"
        g.create_dataset("T", data=tr)
        g.create_dataset("freqs", data=freqs)
        # 体监视器（2D 峰值列）
        g2 = f.create_group("body")
        g2.create_dataset("Ez", data=np.arange(300).reshape(100, 3) * 1.0)
        g2.create_dataset("time", data=np.linspace(0, 1e-13, 100))
    return p


def test_result_path_whitelist(tmp_path):
    assert rv.result_path(tmp_path, "abc-123").name == "abc-123_results.h5"
    for bad in ("../x", "a/b", "", "a b", "x" * 200):
        with pytest.raises(ValueError):
            rv.result_path(tmp_path, bad)


def test_meta_shape(h5):
    m = rv.meta(h5)
    assert m["ok"] and m["job_id"] == "job-42"
    assert m["executed_steps"] == 1234 and m["dt"] == pytest.approx(2.5e-17)
    assert m["grid_shape"] == [32, 32, 64]
    tr = next(x for x in m["monitors"] if x["name"] == "tr")
    assert tr["fields"] == ["T"] and tr["axes"] == ["freqs"]


def test_series_complex_abs_and_peak(h5):
    s = rv.series(h5, "tr", "T", maxpoints=100)
    assert s["ok"] and s["x_label"] == "freqs"
    assert len(s["x"]) == len(s["y"]) <= 100          # 降采样生效
    assert s["x"][0] == pytest.approx(2.8e14)
    # 复数取模：峰值在共振处（非 sin 摆动处）
    assert s["peak"] > 0.8


def test_series_2d_body_takes_peak_column(h5):
    s = rv.series(h5, "body", "Ez", maxpoints=0)
    assert len(s["y"]) == 100                          # 时间轴全长
    assert max(s["y"]) == pytest.approx(299.0)         # 峰值格点列的极值


def test_series_missing_raises(h5):
    with pytest.raises(KeyError):
        rv.series(h5, "nope", "T")
    with pytest.raises(KeyError):
        rv.series(h5, "tr", "nope")


def test_latest_result_by_mtime(tmp_path):
    d = tmp_path / "genie_results"
    d.mkdir()
    (d / "job-42_results.h5").write_bytes(b"")
    import time
    time.sleep(0.02)
    (d / "zz-99_results.h5").write_bytes(b"")
    assert rv.latest_result(tmp_path).name == "zz-99_results.h5"
    empty = tmp_path / "empty-owner"
    empty.mkdir()
    assert rv.latest_result(empty) is None


def test_session_result_endpoints(tmp_path, monkeypatch):
    """会话结果端点（G13②）：meta（含 job_id 缺省=最近）/series 读
    owner 工作区；非法 job_id 422、缺文件 404。"""
    from fastapi.testclient import TestClient
    monkeypatch.setenv("GENIE_SCRIPTS_DIR", str(tmp_path))
    from genie.studio import session_service as ss
    c = TestClient(ss.app)
    # 尚无结果 → 404
    r = c.get("/result/meta", params={"owner": "own"})
    assert r.status_code == 404
    # 放一份结果进 owner 工作区
    import h5py, numpy as np, shutil
    d = tmp_path / "own" / "genie_results"
    d.mkdir(parents=True)
    with h5py.File(d / "job-7_results.h5", "w") as f:
        f.attrs["dt"] = 1e-17
        g = f.create_group("tr")
        g.create_dataset("T", data=np.linspace(0, 1, 50))
        g.create_dataset("freqs", data=np.linspace(3e14, 4e14, 50))
    r = c.get("/result/meta", params={"owner": "own"}).json()   # 缺省=最近
    assert r["ok"] and r["job_id"] == "job-7"
    r = c.get("/result/meta", params={"job_id": "job-7", "owner": "own"}).json()
    assert r["monitors"][0]["name"] == "tr"
    r = c.get("/result/series", params={"job_id": "job-7", "mon": "tr",
                                        "field": "T", "owner": "own"}).json()
    assert r["ok"] and len(r["y"]) == 50
    assert c.get("/result/meta",
                 params={"job_id": "../x", "owner": "own"}).status_code == 422
    assert c.get("/result/series", params={"job_id": "nope", "mon": "tr",
                                           "field": "T", "owner": "own"}
                 ).status_code == 404


def test_prune_over_quota_oldest_first(tmp_path):
    """配额锚：超限按 mtime 最旧先删到达标；未超限零动作；缺目录安全。"""
    import time
    d = tmp_path / "genie_results"
    d.mkdir()
    for name, mb in (("old.h5", 2), ("mid.h5", 2), ("new.h5", 2)):
        (d / name).write_bytes(b"q" * (mb * 1024 * 1024))
        time.sleep(0.02)
    # 未超限（6MB ≤ 8MB）
    assert rv.prune_over_quota(d, 8 * 1024 * 1024) == []
    # 超限（6MB > 3MB）：old 走（4MB 仍超）→ mid 也走（2MB ≤ 3 停）
    gone = rv.prune_over_quota(d, 3 * 1024 * 1024)
    assert gone == ["old.h5", "mid.h5"]
    assert [p.name for p in d.iterdir()] == ["new.h5"]
    # 缺目录
    assert rv.prune_over_quota(tmp_path / "nope", 100) == []
