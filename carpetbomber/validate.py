from __future__ import annotations

from carpetbomber.gitops import has_something_to_push
from carpetbomber.models import Job, JobStatus


def jobs_still_valid(jobs: list[Job]) -> tuple[list[Job], list[Job]]:
    """Split into (kept, cancelled) based on whether each pending job still has something to push."""
    kept: list[Job] = []
    cancelled: list[Job] = []
    for job in jobs:
        if job.status != JobStatus.PENDING:
            # Drop completed; keep failed visible until user clears? Plan says cancel nothing-to-push.
            # Failed jobs stay so the user can see them in the UI.
            if job.status == JobStatus.FAILED:
                kept.append(job)
            continue
        if has_something_to_push(job.path):
            kept.append(job)
        else:
            cancelled.append(job)
    return kept, cancelled


def revalidate_queue(jobs: list[Job]) -> tuple[list[Job], list[Job]]:
    """Return (new_queue, cancelled_jobs)."""
    return jobs_still_valid(jobs)
