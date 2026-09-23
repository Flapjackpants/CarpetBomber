from __future__ import annotations

import signal
import sys
import time
from datetime import datetime

from carpetbomber import gitops, launchd, store
from carpetbomber.models import JobStatus
from carpetbomber.scheduler import next_due_job, overdue_jobs, pending_jobs


_STOP = False


def _handle_signal(signum, frame) -> None:  # noqa: ARG001
    global _STOP
    _STOP = True


def _log(msg: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    store.append_log(f"[{stamp}] {msg}")


def execute_push(job_id: str) -> bool:
    """
    Run git push for a pending job.
    Returns True on success (job removed), False on failure or if job was not pending.
    """
    outcome = {"ok": False}

    def mutator(jobs):
        target = next((j for j in jobs if j.id == job_id), None)
        if target is None or target.status != JobStatus.PENDING:
            return jobs

        _log(f"pushing {target.path}")
        result = gitops.git_push(target.path, ssh_passphrase=target.ssh_passphrase)
        if result.ok:
            _log(f"ok {target.path}")
            outcome["ok"] = True
            return [j for j in jobs if j.id != job_id]

        err = (result.stderr or result.stdout or "git push failed").strip()
        _log(f"fail {target.path}: {err}")
        updated = []
        for j in jobs:
            if j.id == job_id:
                j.status = JobStatus.FAILED
                j.last_error = err[:500]
            updated.append(j)
        return updated

    store.update_queue(mutator)
    return outcome["ok"]


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
    pending = pending_jobs(jobs)
    if not pending:
        # Keep failed jobs visible in TUI but daemon should not stay alive for them alone
        # unless there are pending. Failed-only → exit.
        _log("queue empty of pending jobs; exiting")
        return False

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
        if not pending_jobs(jobs):
            _log("queue empty of pending jobs; exiting")
            return False
        return True

    nxt = next_due_job(jobs, now)
    if nxt is None:
        return False

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
    try:
        while not _STOP:
            keep_going = run_once_cycle()
            if not keep_going:
                break
    finally:
        _log("daemon stopped")
        # When queue is empty, unload launch agent so KeepAlive doesn't restart us
        jobs = store.load_queue()
        if not pending_jobs(jobs):
            try:
                launchd.bootout()
            except Exception:  # pragma: no cover
                pass
    sys.exit(0)


if __name__ == "__main__":
    main()
