from __future__ import annotations

from datetime import datetime, timedelta

from carpetbomber.models import Job, JobStatus


def default_schedule_time(now: datetime | None = None) -> datetime:
    """Next calendar day at 00:00 local time."""
    now = now or datetime.now().astimezone()
    tomorrow = (now + timedelta(days=1)).date()
    return datetime(
        tomorrow.year,
        tomorrow.month,
        tomorrow.day,
        0,
        0,
        0,
        tzinfo=now.tzinfo,
    )


def parse_user_datetime(
    date_str: str,
    time_str: str,
    now: datetime | None = None,
) -> datetime:
    """Parse date (YYYY-MM-DD) and time (HH:MM). Empty fields use defaults."""
    now = now or datetime.now().astimezone()
    default = default_schedule_time(now)

    date_str = (date_str or "").strip()
    time_str = (time_str or "").strip()

    if not date_str and not time_str:
        return default

    if date_str:
        year, month, day = (int(x) for x in date_str.split("-", 2))
    else:
        year, month, day = default.year, default.month, default.day

    if time_str:
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    else:
        hour, minute = 0, 0

    return datetime(year, month, day, hour, minute, 0, tzinfo=now.tzinfo)


def occupied_slots(jobs: list[Job], *, exclude_id: str | None = None) -> set[datetime]:
    slots: set[datetime] = set()
    for job in jobs:
        if job.status != JobStatus.PENDING:
            continue
        if exclude_id and job.id == exclude_id:
            continue
        # Normalize to minute precision for collision checks
        slots.add(job.scheduled_at.replace(second=0, microsecond=0))
    return slots


def next_free_slot(
    requested: datetime,
    jobs: list[Job],
    spacing_minutes: int = 1,
    *,
    exclude_id: str | None = None,
) -> datetime:
    """Find the next open minute slot starting at requested, stepped by spacing."""
    spacing = max(1, int(spacing_minutes))
    step = timedelta(minutes=spacing)
    candidate = requested.replace(second=0, microsecond=0)
    taken = occupied_slots(jobs, exclude_id=exclude_id)
    while candidate in taken:
        candidate = candidate + step
    return candidate


def pending_jobs(jobs: list[Job]) -> list[Job]:
    return [j for j in jobs if j.status == JobStatus.PENDING]


def pushing_jobs(jobs: list[Job]) -> list[Job]:
    return [j for j in jobs if j.status == JobStatus.PUSHING]


def active_jobs(jobs: list[Job]) -> list[Job]:
    """Jobs that keep the daemon alive: pending (not yet run) or pushing (in flight)."""
    return [j for j in jobs if j.status in (JobStatus.PENDING, JobStatus.PUSHING)]


def overdue_jobs(jobs: list[Job], now: datetime | None = None) -> list[Job]:
    now = now or datetime.now().astimezone()
    overdue = [j for j in pending_jobs(jobs) if j.scheduled_at <= now]
    return sorted(overdue, key=lambda j: (j.scheduled_at, j.created_at))


def next_due_job(jobs: list[Job], now: datetime | None = None) -> Job | None:
    now = now or datetime.now().astimezone()
    future = [j for j in pending_jobs(jobs) if j.scheduled_at > now]
    if not future:
        return None
    return min(future, key=lambda j: (j.scheduled_at, j.created_at))


def catch_up_start_times(
    overdue: list[Job],
    spacing_minutes: int,
    now: datetime | None = None,
) -> list[tuple[Job, datetime]]:
    """Assign execution start times for overdue jobs spaced apart from now."""
    now = now or datetime.now().astimezone()
    spacing = max(1, int(spacing_minutes))
    step = timedelta(minutes=spacing)
    ordered = sorted(overdue, key=lambda j: (j.scheduled_at, j.created_at))
    result: list[tuple[Job, datetime]] = []
    cursor = now
    for job in ordered:
        result.append((job, cursor))
        cursor = cursor + step
    return result
