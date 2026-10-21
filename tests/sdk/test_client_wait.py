"""net.client 的 wait() 终态判定（G24）。

janitor 会把老作业标成 ``archived``——那是终态（产物挪去 archive_path），
不是"还在跑"。旧实现只把 failed/killed 当坏终态，``archived`` 会被无限
轮询下去。
"""
from __future__ import annotations

import pytest

from genie.models.errors import GenieJobError
from genie.net import client as C


class _FakeClient:
    """只替换 job_status，其余走真实 wait() 逻辑。"""

    def __init__(self, states):
        self._states = list(states)
        self.calls = 0

    def job_status(self, job_id):
        self.calls += 1
        st = self._states[min(self.calls - 1, len(self._states) - 1)]
        return st


def _wait(fake):
    return C.Client.wait(fake, "job-1", poll_interval=0)


def test_archived_is_terminal_not_endless_poll():
    fake = _FakeClient([{"state": "running"}, {"state": "archived",
                                               "archive_path": "/arc/job-1"}])
    with pytest.raises(GenieJobError) as ei:
        _wait(fake)
    assert "archived" in str(ei.value)
    assert fake.calls == 2, "archived 应立即结束等待，不再轮询"


def test_archived_message_points_at_archive():
    fake = _FakeClient([{"state": "archived", "archive_path": "/arc/job-9"}])
    with pytest.raises(GenieJobError) as ei:
        _wait(fake)
    assert "/arc/job-9" in str(ei.value), "归档作业要指出产物位置"


def test_succeeded_still_returns_status():
    fake = _FakeClient([{"state": "running"}, {"state": "succeeded"}])
    st = _wait(fake)
    assert st["state"] == "succeeded"
