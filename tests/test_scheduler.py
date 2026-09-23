from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from carpetbomber.models import Job, JobStatus, Settings
from carpetbomber.scheduler import (
    catch_up_start_times,
    default_schedule_time,
    next_free_slot,
    overdue_jobs,
    parse_user_datetime,
)


TZ = timezone(timedelta(hours=-4))


def _dt(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def _job(path: str, scheduled: datetime, status: JobStatus = JobStatus.PENDING) -> Job:
    return Job(path=path, scheduled_at=scheduled, requested_at=scheduled, status=status)


def test_default_schedule_time_is_tomorrow_midnight():
    now = _dt(2026, 9, 23, 15, 30)
    assert default_schedule_time(now) == _dt(2026, 9, 24, 0, 0)


def test_parse_user_datetime_defaults():
    now = _dt(2026, 9, 23, 12, 0)
    assert parse_user_datetime("", "", now=now) == _dt(2026, 9, 24, 0, 0)
    assert parse_user_datetime("2026-09-25", "", now=now) == _dt(2026, 9, 25, 0, 0)
    assert parse_user_datetime("", "14:30", now=now) == _dt(2026, 9, 24, 14, 30)
    assert parse_user_datetime("2026-09-25", "08:15", now=now) == _dt(2026, 9, 25, 8, 15)


def test_next_free_slot_bumps_collisions():
    jobs = [
        _job("/a", _dt(2026, 9, 24, 0, 0)),
        _job("/b", _dt(2026, 9, 24, 0, 1)),
    ]
    assert next_free_slot(_dt(2026, 9, 24, 0, 0), jobs, spacing_minutes=1) == _dt(
        2026, 9, 24, 0, 2
    )


def test_next_free_slot_respects_spacing():
    jobs = [_job("/a", _dt(2026, 9, 24, 0, 0))]
    assert next_free_slot(_dt(2026, 9, 24, 0, 0), jobs, spacing_minutes=5) == _dt(
        2026, 9, 24, 0, 5
    )


def test_next_free_slot_exclude_id_keeps_own_slot():
    job_a = _job("/a", _dt(2026, 9, 24, 0, 0))
    job_b = _job("/b", _dt(2026, 9, 24, 0, 1))
    jobs = [job_a, job_b]
    assert next_free_slot(
        _dt(2026, 9, 24, 0, 0),
        jobs,
        spacing_minutes=1,
        exclude_id=job_a.id,
    ) == _dt(2026, 9, 24, 0, 0)
    assert next_free_slot(
        _dt(2026, 9, 24, 0, 1),
        jobs,
        spacing_minutes=1,
        exclude_id=job_a.id,
    ) == _dt(2026, 9, 24, 0, 2)


def test_overdue_jobs_ordered_by_schedule():
    now = _dt(2026, 9, 24, 1, 0)
    jobs = [
        _job("/late2", _dt(2026, 9, 24, 0, 30)),
        _job("/future", _dt(2026, 9, 24, 2, 0)),
        _job("/late1", _dt(2026, 9, 24, 0, 10)),
        _job("/done", _dt(2026, 9, 24, 0, 5), status=JobStatus.FAILED),
    ]
    overdue = overdue_jobs(jobs, now)
    assert [j.path for j in overdue] == ["/late1", "/late2"]


def test_catch_up_start_times_spaced_from_now():
    now = _dt(2026, 9, 24, 1, 0)
    overdue = [
        _job("/a", _dt(2026, 9, 24, 0, 0)),
        _job("/b", _dt(2026, 9, 24, 0, 10)),
    ]
    starts = catch_up_start_times(overdue, spacing_minutes=1, now=now)
    assert starts[0][1] == now
    assert starts[1][1] == now + timedelta(minutes=1)
    assert [j.path for j, _ in starts] == ["/a", "/b"]


def test_settings_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path))
    from carpetbomber import store

    store.save_settings(Settings(push_spacing_minutes=3))
    loaded = store.load_settings()
    assert loaded.push_spacing_minutes == 3


def test_queue_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path))
    from carpetbomber import store

    job = _job("/repo", _dt(2026, 9, 24, 0, 0))
    store.save_queue([job])
    loaded = store.load_queue()
    assert len(loaded) == 1
    assert loaded[0].path == "/repo"
    assert loaded[0].scheduled_at == job.scheduled_at
