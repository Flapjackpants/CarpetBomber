from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Static,
)
from textual import work

from carpetbomber import daemon, gitops, launchd, store
from carpetbomber.banner import render_title
from carpetbomber.models import Job, JobStatus, Settings
from carpetbomber.scheduler import (
    active_jobs,
    default_schedule_time,
    next_due_job,
    next_free_slot,
    overdue_jobs,
    parse_user_datetime,
    pending_jobs,
    pushing_jobs,
)
from carpetbomber.vim_buffer import VimBuffer


def sync_daemon_with_queue(jobs: list[Job] | None = None) -> None:
    """Start LaunchAgent when pending/pushing jobs exist; stop it when none remain."""
    jobs = jobs if jobs is not None else store.load_queue()
    if active_jobs(jobs):
        launchd.ensure_daemon_running()
    else:
        launchd.stop_daemon()


def format_dt(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def dumps_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


def parse_editor_json(text: str) -> dict[str, Any] | str:
    """Return parsed dict, or an error message string."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON: {exc.msg} (line {exc.lineno})"
    if not isinstance(data, dict):
        return "JSON root must be an object"
    return data


class JsonEditScreen(Screen[None]):
    """Home-like shell hosting a vim-lite JSON buffer."""

    def __init__(self, title: str, initial_text: str) -> None:
        super().__init__()
        self._title = title
        self._initial_text = initial_text

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._title, classes="title")
        with Vertical(id="editor-wrap"):
            yield VimBuffer(self._initial_text, id="editor")
        yield Static("-- NORMAL --", id="mode-bar")
        yield Static("", id="showcmd")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#editor", VimBuffer).focus()

    def _echo_cmd(self, key: str) -> None:
        self.query_one("#showcmd", Static).update(key)

    def on_vim_buffer_mode_changed(self, event: VimBuffer.ModeChanged) -> None:
        self.query_one("#mode-bar", Static).update(event.status)

    def on_vim_buffer_command_submitted(self, event: VimBuffer.CommandSubmitted) -> None:
        cmd = event.command.strip()
        self._echo_cmd(f":{cmd}")
        if cmd == "q":
            self.app.pop_screen()
            return
        if cmd in ("w", "wq"):
            err = self._save()
            if err:
                self.notify(err, severity="error")
                return
            if cmd == "wq":
                self.app.pop_screen()
            return
        self.notify(f"Unknown command: :{cmd}", severity="warning")

    def _save(self) -> str | None:
        text = self.query_one("#editor", VimBuffer).get_text()
        data = parse_editor_json(text)
        if isinstance(data, str):
            return data
        return self.apply(data)

    def apply(self, data: dict[str, Any]) -> str | None:
        """Apply parsed JSON. Return error message or None on success."""
        raise NotImplementedError


def apply_settings(data: dict[str, Any]) -> str | None:
    raw = data.get("push_spacing_minutes", 1)
    try:
        spacing = max(1, int(raw))
    except (TypeError, ValueError):
        return "push_spacing_minutes must be a positive integer"
    store.save_settings(Settings(push_spacing_minutes=spacing))
    return None


def schedule_fields_from_data(data: dict[str, Any]) -> tuple[str, str, str] | str:
    path = data.get("path", "")
    date = data.get("date", "")
    time = data.get("time", "")
    if not isinstance(path, str):
        return "path must be a string"
    if not isinstance(date, str):
        return "date must be a string"
    if not isinstance(time, str):
        return "time must be a string"
    return path.strip(), date.strip(), time.strip()


def read_ssh_passphrase(data: dict[str, Any]) -> tuple[bool, str] | str:
    """
    Parse optional ssh_passphrase from editor JSON.
    Returns (key_present, value) on success, or an error message string.
    """
    if "ssh_passphrase" not in data:
        return False, ""
    raw = data["ssh_passphrase"]
    if raw is None:
        return True, ""
    if not isinstance(raw, str):
        return "ssh_passphrase must be a string"
    return True, raw


def apply_add_job(
    path_raw: str,
    date_raw: str,
    time_raw: str,
    ssh_passphrase: str | None = None,
) -> tuple[Job, datetime] | str:
    """Return (job, requested) on success, or an error message."""
    if not path_raw:
        return "Path is required"

    resolved = gitops.resolve_repo_path(path_raw)
    if resolved is None:
        return "Not a git repository"

    try:
        requested = parse_user_datetime(date_raw, time_raw)
    except (ValueError, IndexError):
        return "Invalid date or time"

    passphrase: str | None = None
    if gitops.requires_ssh_auth(resolved):
        passphrase = ssh_passphrase or None

    settings = store.load_settings()
    new_job_id: str | None = None

    def mutator(jobs: list[Job]) -> list[Job]:
        nonlocal new_job_id
        scheduled = next_free_slot(requested, jobs, settings.push_spacing_minutes)
        job = Job(
            path=str(resolved),
            scheduled_at=scheduled,
            requested_at=requested,
            ssh_passphrase=passphrase,
        )
        new_job_id = job.id
        return list(jobs) + [job]

    new_jobs = store.update_queue(mutator)

    added = next((j for j in new_jobs if j.id == new_job_id), None)
    if added is None:
        return "Failed to queue push"
    return added, requested


def apply_edit_job(
    job_id: str,
    path_raw: str,
    date_raw: str,
    time_raw: str,
    ssh_passphrase: str | None = None,
    passphrase_provided: bool = False,
) -> tuple[Job, datetime] | str:
    """Return (job, requested) on success, or an error message.

    If passphrase_provided and ssh_passphrase is non-empty, update it.
    If passphrase_provided and empty, keep existing.
    If not passphrase_provided, leave passphrase unchanged unless remote is not SSH.
    """
    if not path_raw:
        return "Path is required"

    resolved = gitops.resolve_repo_path(path_raw)
    if resolved is None:
        return "Not a git repository"

    try:
        requested = parse_user_datetime(date_raw, time_raw)
    except (ValueError, IndexError):
        return "Invalid date or time"

    settings = store.load_settings()
    needs_ssh = gitops.requires_ssh_auth(resolved)

    def mutator(jobs: list[Job]) -> list[Job]:
        updated: list[Job] = []
        found = False
        for job in jobs:
            if job.id != job_id:
                updated.append(job)
                continue
            found = True
            scheduled = next_free_slot(
                requested,
                jobs,
                settings.push_spacing_minutes,
                exclude_id=job_id,
            )
            job.path = str(resolved)
            job.requested_at = requested
            job.scheduled_at = scheduled
            if needs_ssh:
                if passphrase_provided and ssh_passphrase:
                    job.ssh_passphrase = ssh_passphrase
                # blank / omitted → keep existing
            else:
                job.ssh_passphrase = None
            updated.append(job)
        if not found:
            return jobs
        return updated

    new_jobs = store.update_queue(mutator)

    edited = next((j for j in new_jobs if j.id == job_id), None)
    if edited is None:
        return "Job not found"
    return edited, requested


class SettingsScreen(JsonEditScreen):
    def __init__(self) -> None:
        settings = store.load_settings()
        super().__init__("Settings", dumps_json(settings.to_dict()))

    def apply(self, data: dict[str, Any]) -> str | None:
        err = apply_settings(data)
        if err:
            return err
        spacing = max(1, int(data.get("push_spacing_minutes", 1)))
        self.notify(f"Saved spacing: {spacing} minute(s)")
        return None


class AddPushScreen(JsonEditScreen):
    def __init__(self, initial_path: str | None = None) -> None:
        default = default_schedule_time()
        path = initial_path or ""
        payload: dict[str, Any] = {
            "path": path,
            "date": default.strftime("%Y-%m-%d"),
            "time": "00:00",
        }
        # Include passphrase field when the path is already an SSH remote
        resolved = gitops.resolve_repo_path(path) if path else None
        if resolved and gitops.requires_ssh_auth(resolved):
            payload["ssh_passphrase"] = ""
        super().__init__("Schedule a push", dumps_json(payload))

    def apply(self, data: dict[str, Any]) -> str | None:
        fields = schedule_fields_from_data(data)
        if isinstance(fields, str):
            return fields
        path_raw, date_raw, time_raw = fields
        pw = read_ssh_passphrase(data)
        if isinstance(pw, str):
            return pw
        _present, passphrase = pw
        result = apply_add_job(
            path_raw,
            date_raw,
            time_raw,
            ssh_passphrase=passphrase or None,
        )
        if isinstance(result, str):
            return result
        added, requested = result
        extra = ""
        req = requested.replace(second=0, microsecond=0)
        got = added.scheduled_at.replace(second=0, microsecond=0)
        if got != req:
            extra = f" (slot adjusted to {format_dt(added.scheduled_at)})"
        self.notify(
            f"Scheduled {Path(added.path).name} for {format_dt(added.scheduled_at)}{extra}"
        )
        return None


class EditPushScreen(JsonEditScreen):
    def __init__(self, job: Job) -> None:
        self.job = job
        local = job.requested_at.astimezone()
        payload: dict[str, Any] = {
            "path": job.path,
            "date": local.strftime("%Y-%m-%d"),
            "time": local.strftime("%H:%M"),
        }
        if gitops.requires_ssh_auth(job.path):
            # Blank = keep stored passphrase (never echo the secret into the buffer)
            payload["ssh_passphrase"] = ""
        super().__init__("Edit scheduled push", dumps_json(payload))

    def apply(self, data: dict[str, Any]) -> str | None:
        fields = schedule_fields_from_data(data)
        if isinstance(fields, str):
            return fields
        path_raw, date_raw, time_raw = fields
        pw = read_ssh_passphrase(data)
        if isinstance(pw, str):
            return pw
        passphrase_provided, passphrase = pw
        result = apply_edit_job(
            self.job.id,
            path_raw,
            date_raw,
            time_raw,
            ssh_passphrase=passphrase or None,
            passphrase_provided=passphrase_provided,
        )
        if isinstance(result, str):
            return result
        edited, requested = result
        extra = ""
        req = requested.replace(second=0, microsecond=0)
        got = edited.scheduled_at.replace(second=0, microsecond=0)
        if got != req:
            extra = f" (slot adjusted to {format_dt(edited.scheduled_at)})"
        self.notify(
            f"Updated {Path(edited.path).name} for {format_dt(edited.scheduled_at)}{extra}"
        )
        return None


class QueueScreen(Screen[None]):
    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("e", "edit_selected", "Edit"),
        Binding("r", "run_selected", "Run"),
        Binding("c", "cancel_selected", "Cancel"),
        Binding("s", "settings", "Settings"),
        Binding("q", "quit", "Quit"),
        Binding("y", "confirm_cancel_yes", "Yes"),
        Binding("n", "confirm_cancel_no", "No"),
    ]

    _NORMAL_ACTIONS = frozenset(
        {"add", "edit_selected", "run_selected", "cancel_selected", "settings", "quit"}
    )
    _CONFIRM_ACTIONS = frozenset({"confirm_cancel_yes", "confirm_cancel_no"})

    CSS = """
    QueueScreen {
        layout: vertical;
    }
    #banner {
        height: auto;
        padding: 0 2;
        background: $boost;
        content-align: center top;
    }
    #table-wrap {
        height: 1fr;
        padding: 0 1;
    }
    DataTable {
        height: 1fr;
    }
    #status-bar {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }
    #showcmd {
        height: 1;
        padding: 0 2;
        content-align: right middle;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._loading_job_id: str | None = None
        self._loading_name: str | None = None
        self._loading_frame = 0
        self._loading_timer = None
        self._schedule_timer = None
        self._spacing_after_push = False
        self._cancel_confirm_id: str | None = None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self._loading_job_id is not None and action in (
            self._NORMAL_ACTIONS | self._CONFIRM_ACTIONS
        ):
            return False
        confirming = self._cancel_confirm_id is not None
        if action in self._CONFIRM_ACTIONS:
            return confirming
        if action in self._NORMAL_ACTIONS:
            return not confirming
        return True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="banner")
        with Vertical(id="table-wrap"):
            yield DataTable(id="queue-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="status-bar")
        yield Static("", id="showcmd")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.add_columns("Path", "Requested", "Scheduled", "Status", "Error")
        # While the TUI is open it owns push execution — pause LaunchAgent to avoid races
        launchd.stop_daemon()
        n = daemon.recover_stale_pushing()
        if n:
            self.notify(f"Recovered {n} interrupted push(es)", severity="warning")
        self._refresh_banner()
        self.refresh_table()
        self._arm_next_push()

    def on_resize(self, event) -> None:
        self._refresh_banner()

    def on_screen_resume(self) -> None:
        self.refresh_table()
        self._arm_next_push()

    def on_unmount(self) -> None:
        self._cancel_schedule_timer()
        self._cancel_loading_timer()

    def _refresh_banner(self) -> None:
        self.query_one("#banner", Static).update(render_title())

    def _cancel_schedule_timer(self) -> None:
        if self._schedule_timer is not None:
            self._schedule_timer.stop()
            self._schedule_timer = None

    def _arm_next_push(self) -> None:
        """Schedule a one-shot timer for the next due push (no polling)."""
        self._cancel_schedule_timer()
        if self._loading_job_id is not None:
            return

        jobs = store.load_queue()
        now = datetime.now().astimezone()
        overdue = overdue_jobs(jobs, now)
        if overdue:
            delay = 0.05
            if self._spacing_after_push:
                spacing = max(1, store.load_settings().push_spacing_minutes)
                delay = float(spacing * 60)
            self._spacing_after_push = False
            self._schedule_timer = self.set_timer(delay, self._on_schedule_fire)
            return

        self._spacing_after_push = False
        nxt = next_due_job(jobs, now)
        if nxt is None:
            return
        delay = max(0.05, (nxt.scheduled_at - now).total_seconds())
        self._schedule_timer = self.set_timer(delay, self._on_schedule_fire)

    def _on_schedule_fire(self) -> None:
        self._schedule_timer = None
        if self._loading_job_id is not None:
            return
        jobs = store.load_queue()
        now = datetime.now().astimezone()
        overdue = overdue_jobs(jobs, now)
        if not overdue:
            # Not due yet (clock / schedule changed) — re-arm for the next slot
            self._arm_next_push()
            return
        job = overdue[0]
        self._begin_push(job.id, job.path)

    def _show_loading(self, job_id: str, path: str) -> None:
        if self._loading_job_id == job_id:
            return
        if self._loading_job_id is not None:
            self._dismiss_loading()
        self._loading_job_id = job_id
        self._loading_name = Path(path).name
        self._loading_frame = 0
        self._update_loading_status()
        self._loading_timer = self.set_interval(0.15, self._advance_loading)

    def _update_loading_status(self) -> None:
        frames = "|/-\\"
        frame = frames[self._loading_frame % len(frames)]
        name = self._loading_name or "push"
        self.query_one("#status-bar", Static).update(f"{frame} Pushing {name}…")

    def _advance_loading(self) -> None:
        if self._loading_job_id is None:
            self._cancel_loading_timer()
            return
        self._loading_frame += 1
        self._update_loading_status()

    def _cancel_loading_timer(self) -> None:
        if self._loading_timer is not None:
            self._loading_timer.stop()
            self._loading_timer = None

    def _dismiss_loading(self) -> None:
        if self._loading_job_id is None:
            return
        self._cancel_loading_timer()
        self._loading_job_id = None
        self._loading_name = None

    def _begin_push(self, job_id: str, path: str) -> None:
        """Show loading and run git push off the UI thread."""
        if self._loading_job_id is not None:
            return
        self._cancel_schedule_timer()
        name = Path(path).name
        self._show_loading(job_id, path)
        self.refresh_table()
        self._run_push_worker(job_id, name)

    def refresh_table(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        # Preserve cursor across rebuilds when possible
        prev_key = None
        if table.row_count > 0:
            try:
                prev_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            except Exception:
                prev_key = None

        table.clear()
        jobs = store.load_queue()
        for job in sorted(jobs, key=lambda j: (j.scheduled_at, j.created_at)):
            err = (job.last_error or "")[:40]
            table.add_row(
                job.path,
                format_dt(job.requested_at),
                format_dt(job.scheduled_at),
                job.status.value,
                err,
                key=job.id,
            )

        if prev_key is not None:
            try:
                table.move_cursor(row=table.get_row_index(prev_key))
            except Exception:
                pass

        if self._cancel_confirm_id is not None:
            if any(j.id == self._cancel_confirm_id for j in jobs):
                self.query_one("#status-bar", Static).update("Confirm?")
            else:
                self._cancel_confirm_id = None
                self._update_status_bar(jobs)
                self.refresh_bindings()
        else:
            self._update_status_bar(jobs)

    def _update_status_bar(self, jobs: list[Job]) -> None:
        if self._loading_job_id is not None:
            self._update_loading_status()
            return
        pending = pending_jobs(jobs)
        pushing = pushing_jobs(jobs)
        failed = [j for j in jobs if j.status == JobStatus.FAILED]
        spacing = store.load_settings().push_spacing_minutes
        parts = [f"{len(pending)} pending"]
        if pushing:
            parts.append(f"{len(pushing)} pushing")
        parts.append(f"{len(failed)} failed")
        parts.append("daemon paused")
        parts.append(f"spacing {spacing}m")
        self.query_one("#status-bar", Static).update(" · ".join(parts))

    def _selected_job_id(self) -> str | None:
        table = self.query_one("#queue-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:
            return None
        if row_key is None:
            return None
        return str(row_key.value)

    def _echo_cmd(self, key: str) -> None:
        self.query_one("#showcmd", Static).update(key)

    def action_add(self) -> None:
        self._echo_cmd("a")
        self.app.push_screen(AddPushScreen())

    def action_edit_selected(self) -> None:
        self._echo_cmd("e")
        job_id = self._selected_job_id()
        if not job_id:
            self.notify("No job selected", severity="warning")
            return
        jobs = store.load_queue()
        job = next((j for j in jobs if j.id == job_id), None)
        if job is None:
            self.notify("Job not found", severity="warning")
            self.refresh_table()
            return
        if job.status != JobStatus.PENDING:
            self.notify("Only pending jobs can be edited", severity="warning")
            return
        self.app.push_screen(EditPushScreen(job))

    def action_run_selected(self) -> None:
        self._echo_cmd("r")
        if self._loading_job_id is not None:
            self.notify("A push is already in progress", severity="warning")
            return
        job_id = self._selected_job_id()
        if not job_id:
            self.notify("No job selected", severity="warning")
            return
        jobs = store.load_queue()
        job = next((j for j in jobs if j.id == job_id), None)
        if job is None:
            self.notify("Job not found", severity="warning")
            self.refresh_table()
            return
        if job.status not in (JobStatus.PENDING, JobStatus.FAILED):
            self.notify("Only pending or failed jobs can be run", severity="warning")
            return

        path = job.path
        now = datetime.now().astimezone()

        def prepare(current: list[Job]) -> list[Job]:
            updated: list[Job] = []
            for j in current:
                if j.id == job_id:
                    j.status = JobStatus.PENDING
                    j.last_error = None
                    j.scheduled_at = now
                    j.requested_at = now
                updated.append(j)
            return updated

        store.update_queue(prepare)
        self._begin_push(job_id, path)

    @work(thread=True, exclusive=True, group="push")
    def _run_push_worker(self, job_id: str, name: str) -> None:
        ok = daemon.execute_push(job_id)
        self.app.call_from_thread(self._finish_push, job_id, name, ok)

    def _finish_push(self, job_id: str, name: str, ok: bool) -> None:
        remaining = store.load_queue()
        if self._loading_job_id == job_id:
            self._dismiss_loading()
        self.refresh_table()
        if ok:
            self.notify(f"Pushed {name}")
        else:
            failed = next((j for j in remaining if j.id == job_id), None)
            err = (failed.last_error if failed else None) or "git push failed"
            self.notify(f"Push failed: {err[:120]}", severity="error")

        # Space catch-up pushes when more overdue work remains
        now = datetime.now().astimezone()
        if overdue_jobs(remaining, now):
            self._spacing_after_push = True
        self._arm_next_push()

    def action_settings(self) -> None:
        self._echo_cmd("s")
        self.app.push_screen(SettingsScreen())

    def action_cancel_selected(self) -> None:
        self._echo_cmd("c")
        job_id = self._selected_job_id()
        if not job_id:
            self.notify("No job selected", severity="warning")
            return
        jobs = store.load_queue()
        job = next((j for j in jobs if j.id == job_id), None)
        if job is None:
            self.notify("Job not found", severity="warning")
            self.refresh_table()
            return

        self._cancel_confirm_id = job_id
        self.query_one("#status-bar", Static).update("Confirm?")
        self.refresh_bindings()

    def action_confirm_cancel_yes(self) -> None:
        self._echo_cmd("y")
        job_id = self._cancel_confirm_id
        if not job_id:
            return

        def mutator(current: list[Job]) -> list[Job]:
            return [j for j in current if j.id != job_id]

        store.update_queue(mutator)
        self._cancel_confirm_id = None
        self.refresh_table()
        self.refresh_bindings()
        self._arm_next_push()
        self.notify("Cancelled")

    def action_confirm_cancel_no(self) -> None:
        self._echo_cmd("n")
        self._cancel_confirm_id = None
        self._update_status_bar(store.load_queue())
        self.refresh_bindings()

    def action_quit(self) -> None:
        self._echo_cmd("q")
        self._cancel_schedule_timer()
        self.app.exit()


class CarpetBomberApp(App[None]):
    TITLE = "CarpetBomber"
    SUB_TITLE = "scheduled git pushes"
    CSS = """
    Screen {
        background: #0f1419;
    }
    SettingsScreen,
    AddPushScreen,
    EditPushScreen {
        layout: vertical;
    }
    .title {
        text-style: bold;
        color: #e8c47c;
        margin-bottom: 1;
        padding: 0 2;
    }
    Header {
        background: #1a2332;
    }
    Footer {
        background: #1a2332;
    }
    DataTable > .datatable--cursor {
        background: #2a4a6a;
    }
    #editor-wrap {
        height: 1fr;
        padding: 0 1;
    }
    #editor-wrap VimBuffer {
        height: 1fr;
    }
    #mode-bar {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }
    #showcmd {
        height: 1;
        padding: 0 2;
        content-align: right middle;
        color: $text-muted;
    }
    """

    def __init__(self, initial_add_path: str | None = None) -> None:
        super().__init__()
        self.initial_add_path = initial_add_path

    def on_mount(self) -> None:
        self.push_screen(QueueScreen())
        if self.initial_add_path is not None:
            self.push_screen(AddPushScreen(initial_path=self.initial_add_path))


def main() -> None:
    initial_add_path: str | None = None
    if len(sys.argv) > 1 and sys.argv[1] == "this":
        initial_add_path = str(Path.cwd())
    try:
        CarpetBomberApp(initial_add_path=initial_add_path).run()
    finally:
        # Hand remaining pending jobs back to the LaunchAgent after the TUI exits
        sync_daemon_with_queue()


if __name__ == "__main__":
    main()
