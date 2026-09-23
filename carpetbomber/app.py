from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    Static,
)

from carpetbomber import gitops, launchd, store
from carpetbomber.banner import render_title
from carpetbomber.models import Job, JobStatus, Settings
from carpetbomber.scheduler import default_schedule_time, next_free_slot, parse_user_datetime, pending_jobs
from carpetbomber.vim_buffer import VimBuffer


def sync_daemon_with_queue(jobs: list[Job] | None = None) -> None:
    """Start LaunchAgent when pending jobs exist; stop it when none remain."""
    jobs = jobs if jobs is not None else store.load_queue()
    if pending_jobs(jobs):
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


class ConfirmCancelScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "confirm", "Cancel push"),
        Binding("n", "keep", "Keep"),
        Binding("escape", "back", "Keep"),
    ]

    CSS = """
    ConfirmCancelScreen {
        align: center middle;
    }
    #confirm-box {
        width: 60;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    #confirm-box Label {
        margin-bottom: 1;
    }
    #showcmd {
        height: 1;
        content-align: right middle;
        color: $text-muted;
    }
    """

    def __init__(self, job: Job) -> None:
        super().__init__()
        self.job = job

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(f"Cancel push for\n{self.job.path}?")
            yield Static("", id="showcmd")
        yield Footer()

    def _echo_cmd(self, key: str) -> None:
        self.query_one("#showcmd", Static).update(key)

    def action_confirm(self) -> None:
        self._echo_cmd("y")
        self.dismiss(True)

    def action_keep(self) -> None:
        self._echo_cmd("n")
        self.dismiss(False)

    def action_back(self) -> None:
        self._echo_cmd("esc")
        self.dismiss(False)


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


def apply_add_job(
    path_raw: str, date_raw: str, time_raw: str
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

    settings = store.load_settings()
    new_job_id: str | None = None

    def mutator(jobs: list[Job]) -> list[Job]:
        nonlocal new_job_id
        scheduled = next_free_slot(requested, jobs, settings.push_spacing_minutes)
        job = Job(
            path=str(resolved),
            scheduled_at=scheduled,
            requested_at=requested,
        )
        new_job_id = job.id
        return list(jobs) + [job]

    new_jobs = store.update_queue(mutator)
    sync_daemon_with_queue(new_jobs)

    added = next((j for j in new_jobs if j.id == new_job_id), None)
    if added is None:
        return "Failed to queue push"
    return added, requested


def apply_edit_job(
    job_id: str, path_raw: str, date_raw: str, time_raw: str
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

    settings = store.load_settings()

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
            updated.append(job)
        if not found:
            return jobs
        return updated

    new_jobs = store.update_queue(mutator)
    sync_daemon_with_queue(new_jobs)

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
        payload = {
            "path": initial_path or "",
            "date": default.strftime("%Y-%m-%d"),
            "time": "00:00",
        }
        super().__init__("Schedule a push", dumps_json(payload))

    def apply(self, data: dict[str, Any]) -> str | None:
        fields = schedule_fields_from_data(data)
        if isinstance(fields, str):
            return fields
        path_raw, date_raw, time_raw = fields
        result = apply_add_job(path_raw, date_raw, time_raw)
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
        payload = {
            "path": job.path,
            "date": local.strftime("%Y-%m-%d"),
            "time": local.strftime("%H:%M"),
        }
        super().__init__("Edit scheduled push", dumps_json(payload))

    def apply(self, data: dict[str, Any]) -> str | None:
        fields = schedule_fields_from_data(data)
        if isinstance(fields, str):
            return fields
        path_raw, date_raw, time_raw = fields
        result = apply_edit_job(self.job.id, path_raw, date_raw, time_raw)
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
        Binding("c", "cancel_selected", "Cancel"),
        Binding("s", "settings", "Settings"),
        Binding("q", "quit", "Quit"),
    ]

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
        self._refresh_banner()
        self.refresh_table()

    def on_resize(self, event) -> None:
        self._refresh_banner()

    def on_screen_resume(self) -> None:
        self.refresh_table()

    def _refresh_banner(self) -> None:
        self.query_one("#banner", Static).update(render_title())

    def refresh_table(self) -> None:
        table = self.query_one("#queue-table", DataTable)
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

        pending = pending_jobs(jobs)
        failed = [j for j in jobs if j.status == JobStatus.FAILED]
        daemon = "running" if launchd.is_loaded() else "stopped"
        spacing = store.load_settings().push_spacing_minutes
        self.query_one("#status-bar", Static).update(
            f"{len(pending)} pending · {len(failed)} failed · daemon {daemon} · spacing {spacing}m"
        )

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

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return

            def mutator(current: list[Job]) -> list[Job]:
                return [j for j in current if j.id != job_id]

            new_jobs = store.update_queue(mutator)
            sync_daemon_with_queue(new_jobs)
            self.refresh_table()
            self.notify("Cancelled")

        self.app.push_screen(ConfirmCancelScreen(job), on_confirm)

    def action_quit(self) -> None:
        self._echo_cmd("q")
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
    CarpetBomberApp(initial_add_path=initial_add_path).run()


if __name__ == "__main__":
    main()
