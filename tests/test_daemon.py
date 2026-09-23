from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from carpetbomber.models import Job, JobStatus
from carpetbomber.scheduler import overdue_jobs

TZ = timezone(timedelta(hours=-4))


def test_daemon_cycle_exits_when_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path))
    from carpetbomber import daemon, store

    store.save_queue([])
    with patch.object(daemon, "_log"):
        assert daemon.run_once_cycle() is False


def test_daemon_executes_overdue_and_removes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path))
    from carpetbomber import daemon, store
    from carpetbomber.gitops import GitResult

    job = Job(
        path="/repo",
        scheduled_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        requested_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
    )
    store.save_queue([job])

    with (
        patch.object(daemon, "_log"),
        patch(
            "carpetbomber.daemon.gitops.git_push",
            return_value=GitResult(ok=True, stdout="", stderr="", returncode=0),
        ),
    ):
        daemon._execute_push(job.id)

    remaining = store.load_queue()
    assert remaining == []


def test_overdue_helper_used_for_ordering():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=TZ)
    jobs = [
        Job(
            path="/b",
            scheduled_at=datetime(2026, 9, 24, 11, 0, tzinfo=TZ),
            requested_at=datetime(2026, 9, 24, 11, 0, tzinfo=TZ),
        ),
        Job(
            path="/a",
            scheduled_at=datetime(2026, 9, 24, 10, 0, tzinfo=TZ),
            requested_at=datetime(2026, 9, 24, 10, 0, tzinfo=TZ),
        ),
    ]
    assert [j.path for j in overdue_jobs(jobs, now)] == ["/a", "/b"]


def test_daemon_keeps_alive_for_pushing_only(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path))
    from carpetbomber import daemon, store

    job = Job(
        path="/repo",
        scheduled_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        requested_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        status=JobStatus.PUSHING,
    )
    store.save_queue([job])

    with patch.object(daemon, "_log"), patch.object(daemon.time, "sleep"):
        assert daemon.run_once_cycle() is True


def test_recover_stale_pushing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path))
    from carpetbomber import daemon, store

    job = Job(
        path="/repo",
        scheduled_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        requested_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        status=JobStatus.PUSHING,
    )
    store.save_queue([job])
    assert daemon.recover_stale_pushing() == 1
    remaining = store.load_queue()
    assert len(remaining) == 1
    assert remaining[0].status == JobStatus.PENDING
    assert daemon.recover_stale_pushing() == 0


def test_overdue_skips_pushing_jobs():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=TZ)
    jobs = [
        Job(
            path="/pushing",
            scheduled_at=datetime(2026, 9, 24, 10, 0, tzinfo=TZ),
            requested_at=datetime(2026, 9, 24, 10, 0, tzinfo=TZ),
            status=JobStatus.PUSHING,
        ),
        Job(
            path="/pending",
            scheduled_at=datetime(2026, 9, 24, 11, 0, tzinfo=TZ),
            requested_at=datetime(2026, 9, 24, 11, 0, tzinfo=TZ),
        ),
    ]
    assert [j.path for j in overdue_jobs(jobs, now)] == ["/pending"]
