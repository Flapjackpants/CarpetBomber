from __future__ import annotations

import signal
import sys
import time
from datetime import datetime

from carpetbomber import gitops, launchd, store
from carpetbomber.models import Job, JobStatus
from carpetbomber.scheduler import active_jobs, next_due_job, overdue_jobs, pending_jobs


_STOP = False


def _handle_signal(signum, frame) -> None:  # noqa: ARG001
    global _STOP
    _STOP = True


def _log(msg: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    store.append_log(f"[{stamp}] {msg}")


def _claim_push(job_id: str) -> Job | None:
    """Mark a pending job as pushing. Returns the claimed job, or None if not claimable."""
    claimed: dict[str, Job | None] = {"job": None}

    def mutator(jobs: list[Job]) -> list[Job]:
        updated: list[Job] = []
        for j in jobs:
            if j.id == job_id and j.status == JobStatus.PENDING:
                j.status = JobStatus.PUSHING
                j.last_error = None
                claimed["job"] = j
            updated.append(j)
        return updated

    store.update_queue(mutator)
    return claimed["job"]


def recover_stale_pushing() -> int:
    """Reset leftover PUSHING jobs to PENDING (e.g. after a crash). Returns count reset."""
    reset = {"n": 0}

    def mutator(jobs: list[Job]) -> list[Job]:
        updated: list[Job] = []
        for j in jobs:
            if j.status == JobStatus.PUSHING:
                j.status = JobStatus.PENDING
                reset["n"] += 1
            updated.append(j)
        return updated

    store.update_queue(mutator)
    return reset["n"]


def _finalize_push(job_id: str, *, ok: bool, error: str | None) -> bool:
    """
    Apply push outcome for a job still in PUSHING.
    Success removes the job; failure sets FAILED + last_error.
    Returns True if the job was successfully removed.
    """
    removed = {"ok": False}

    def mutator(jobs: list[Job]) -> list[Job]:
        target = next((j for j in jobs if j.id == job_id), None)
        if target is None or target.status != JobStatus.PUSHING:
            return jobs
        if ok:
            removed["ok"] = True
            return [j for j in jobs if j.id != job_id]
        updated: list[Job] = []
        for j in jobs:
            if j.id == job_id:
                j.status = JobStatus.FAILED
                j.last_error = (error or "git push failed")[:500]
            updated.append(j)
        return updated

    store.update_queue(mutator)
    return removed["ok"]


def remove_stale_commit_jobs(path: str, current_head: str | None = None) -> bool:
    """Remove pending commit jobs for a repo whose recorded HEAD has advanced."""
    if current_head is None:
        current_head = gitops.repo_head(path)
    if current_head is None:
        return False

    removed = {"any": False}

    def mutator(jobs: list[Job]) -> list[Job]:
        kept: list[Job] = []
        for job in jobs:
            if (
                job.path == path
                and job.is_commit
                and job.status == JobStatus.PENDING
                and job.commit_head is not None
                and job.commit_head != current_head
            ):
                removed["any"] = True
                continue
            kept.append(job)
        return kept

    store.update_queue(mutator)
    if removed["any"]:
        _log(f"cancelled scheduled commit(s) for {path}: repository HEAD advanced")
    return removed["any"]


def execute_push(job_id: str) -> bool:
    """
    Run git push for a pending job.
    Returns True on success (job removed), False on failure or if job was not pending.
    """
    queued = next((j for j in store.load_queue() if j.id == job_id), None)
    if queued is None or queued.status != JobStatus.PENDING:
        return False

    before_head = gitops.repo_head(queued.path) if queued.is_commit else None
    if queued.is_commit and not queued.commit_created and queued.commit_head and before_head:
        if before_head != queued.commit_head:
            remove_stale_commit_jobs(queued.path, before_head)
            return False

    claimed = _claim_push(job_id)
    if claimed is None:
        return False

    action = claimed.operation_name.lower()
    verb = "committing and pushing" if claimed.is_commit else "pushing"
    _log(f"{verb} {claimed.path}")
    if claimed.is_commit:
        if not claimed.commit_created:
            result = gitops.git_commit(claimed.path, claimed.commit_message.strip())
            if result.ok:
                after_commit_head = gitops.repo_head(claimed.path)

                def mark_commit_created(jobs: list[Job]) -> list[Job]:
                    for job in jobs:
                        if job.id == job_id and job.status == JobStatus.PUSHING:
                            job.commit_created = True
                            if after_commit_head:
                                job.commit_head = after_commit_head
                    return jobs

                store.update_queue(mark_commit_created)
                if after_commit_head and after_commit_head != before_head:
                    remove_stale_commit_jobs(claimed.path, after_commit_head)
                claimed.commit_created = True
        else:
            result = gitops.GitResult(ok=True, stdout="", stderr="", returncode=0)

        if result.ok:
            result = gitops.git_push(claimed.path, ssh_passphrase=claimed.ssh_passphrase)
    else:
        result = gitops.git_push(claimed.path, ssh_passphrase=claimed.ssh_passphrase)

    if result.ok:
        _log(f"ok {action} {claimed.path}")
        return _finalize_push(job_id, ok=True, error=None)

    err = (result.stderr or result.stdout or f"git {action} failed").strip()
    _log(f"fail {action} {claimed.path}: {err}")
    _finalize_push(job_id, ok=False, error=err)
    return False


# Backwards-compatible alias used by tests / internal callers
_execute_push = execute_push


def run_once_cycle() -> bool:
    """
    Process overdue jobs (spaced), then return whether any pending remain.
    Returns False when the daemon should exit.
    """
    settings = store.load_settings()
    spacing = max(1, settings.push_spacing_minutes)

    jobs = store.load_queue()
    if not active_jobs(jobs):
        # Keep failed jobs visible in TUI but daemon should not stay alive for them alone
        # unless there are pending/pushing. Failed-only → exit.
        _log("queue empty of pending jobs; exiting")
        return False

    # A push already in flight (e.g. TUI run-now) — wait rather than exit or double-claim
    if not pending_jobs(jobs):
        time.sleep(1.0)
        return True

    now = datetime.now().astimezone()
    overdue = overdue_jobs(jobs, now)
    if overdue:
        for index, job in enumerate(overdue):
            if _STOP:
                break
            if index > 0:
                # Space catch-up pushes
                time.sleep(spacing * 60)
                if _STOP:
                    break
            # Re-check still pending
            current = store.load_queue()
            live = next((j for j in current if j.id == job.id and j.status == JobStatus.PENDING), None)
            if live is None:
                continue
            _execute_push(job.id)

        jobs = store.load_queue()
        if not active_jobs(jobs):
            _log("queue empty of pending jobs; exiting")
            return False
        return True

    nxt = next_due_job(jobs, now)
    if nxt is None:
        # Only pushing jobs left (or race); stay alive until they clear
        return bool(active_jobs(jobs))

    wait_seconds = (nxt.scheduled_at - now).total_seconds()
    # Cap sleep so we periodically notice TUI changes
    sleep_for = min(max(wait_seconds, 0), 60)
    _log(f"sleeping {sleep_for:.0f}s until next check (due {nxt.scheduled_at.isoformat()})")
    end = time.time() + sleep_for
    while time.time() < end and not _STOP:
        time.sleep(min(1.0, end - time.time()))
    return True


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    _log("daemon starting")
    n = recover_stale_pushing()
    if n:
        _log(f"recovered {n} stale pushing job(s)")
    try:
        while not _STOP:
            keep_going = run_once_cycle()
            if not keep_going:
                break
    finally:
        _log("daemon stopped")
        # When queue is empty, unload launch agent so KeepAlive doesn't restart us
        jobs = store.load_queue()
        if not active_jobs(jobs):
            try:
                launchd.bootout()
            except Exception:  # pragma: no cover
                pass
    sys.exit(0)


if __name__ == "__main__":
    main()
