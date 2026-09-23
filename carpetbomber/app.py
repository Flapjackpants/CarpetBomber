from __future__ import annotations

from datetime import datetime
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
)

from carpetbomber import gitops, launchd, store, validate
from carpetbomber.banner import render_title
from carpetbomber.models import Job, JobStatus, Settings
from carpetbomber.scheduler import default_schedule_time, next_free_slot, parse_user_datetime, pending_jobs


def sync_daemon_with_queue(jobs: list[Job] | None = None) -> None:
    """Start LaunchAgent when pending jobs exist; stop it when none remain."""
    jobs = jobs if jobs is not None else store.load_queue()
    if pending_jobs(jobs):
        launchd.ensure_daemon_running()
    else:
        launchd.stop_daemon()


def format_dt(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


class ConfirmCancelScreen(ModalScreen[bool]):
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
    #confirm-buttons {
        height: auto;
        align: center middle;
    }
    """

    def __init__(self, job: Job) -> None:
        super().__init__()
        self.job = job

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(f"Cancel push for\n{self.job.path}?")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel push", variant="error", id="yes")
                yield Button("Keep", variant="primary", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class SettingsScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    CSS = """
    SettingsScreen {
        padding: 1 2;
    }
    #settings-form {
        width: 70;
        max-width: 100%;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    #settings-form Input {
        margin-bottom: 1;
    }
    #settings-path {
        color: $text-muted;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        settings = store.load_settings()
        yield Header()
        with VerticalScroll():
            yield Static("Settings", classes="title")
            with Vertical(id="settings-form"):
                yield Label("Minutes between pushes (same-time slots & catch-up)")
                yield Input(
                    value=str(settings.push_spacing_minutes),
                    placeholder="1",
                    id="spacing",
                    type="integer",
                )
                yield Label(f"Config directory: {store.config_dir()}", id="settings-path")
                with Horizontal():
                    yield Button("Save", variant="primary", id="save")
                    yield Button("Back", id="back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
            return
        if event.button.id == "save":
            raw = self.query_one("#spacing", Input).value.strip() or "1"
            try:
                spacing = max(1, int(raw))
            except ValueError:
                self.notify("Spacing must be a positive integer", severity="error")
                return
            store.save_settings(Settings(push_spacing_minutes=spacing))
            self.notify(f"Saved spacing: {spacing} minute(s)")
            self.app.pop_screen()


class AddPushScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    CSS = """
    AddPushScreen {
        padding: 1 2;
    }
    #add-form {
        width: 80;
        max-width: 100%;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    #add-form Input {
        margin-bottom: 1;
    }
    #hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        default = default_schedule_time()
        yield Header()
        with VerticalScroll():
            yield Static("Schedule a push", classes="title")
            yield Label(
                f"Default: {format_dt(default)} (tomorrow 00:00). "
                "Leave date/time blank to use default.",
                id="hint",
            )
            with Vertical(id="add-form"):
                yield Label("Repository path")
                yield Input(placeholder="/path/to/repo", id="path")
                yield Label("Date (YYYY-MM-DD)")
                yield Input(placeholder=default.strftime("%Y-%m-%d"), id="date")
                yield Label("Time (HH:MM)")
                yield Input(placeholder="00:00", id="time")
                with Horizontal():
                    yield Button("Add", variant="primary", id="add")
                    yield Button("Back", id="back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
            return
        if event.button.id == "add":
            self._submit()

    def _submit(self) -> None:
        path_raw = self.query_one("#path", Input).value.strip()
        date_raw = self.query_one("#date", Input).value.strip()
        time_raw = self.query_one("#time", Input).value.strip()

        if not path_raw:
            self.notify("Path is required", severity="error")
            return

        resolved = gitops.resolve_repo_path(path_raw)
        if resolved is None:
            self.notify("Not a git repository", severity="error")
            return

        if not gitops.has_something_to_push(resolved):
            self.notify(
                "Nothing to push (no unpushed commits / no upstream)",
                severity="error",
            )
            return

        try:
            requested = parse_user_datetime(date_raw, time_raw)
        except (ValueError, IndexError):
            self.notify("Invalid date or time", severity="error")
            return

        settings = store.load_settings()
        cancelled_paths: list[str] = []
        new_job_id: str | None = None

        def mutator(jobs: list[Job]) -> list[Job]:
            nonlocal new_job_id, cancelled_paths
            scheduled = next_free_slot(requested, jobs, settings.push_spacing_minutes)
            job = Job(
                path=str(resolved),
                scheduled_at=scheduled,
                requested_at=requested,
            )
            new_job_id = job.id
            combined = list(jobs) + [job]
            kept, cancelled = validate.revalidate_queue(combined)
            cancelled_paths = [c.path for c in cancelled]
            return kept

        new_jobs = store.update_queue(mutator)
        sync_daemon_with_queue(new_jobs)

        if cancelled_paths:
            names = ", ".join(Path(p).name for p in cancelled_paths[:3])
            more = f" (+{len(cancelled_paths) - 3})" if len(cancelled_paths) > 3 else ""
            self.notify(
                f"Cancelled {len(cancelled_paths)} with nothing to push: {names}{more}",
                severity="warning",
            )

        added = next((j for j in new_jobs if j.id == new_job_id), None)
        if added is None:
            self.notify(
                "Push not queued — nothing left to push after validation",
                severity="warning",
            )
        else:
            extra = ""
            req = requested.replace(second=0, microsecond=0)
            got = added.scheduled_at.replace(second=0, microsecond=0)
            if got != req:
                extra = f" (slot adjusted to {format_dt(added.scheduled_at)})"
            self.notify(f"Scheduled {Path(added.path).name} for {format_dt(added.scheduled_at)}{extra}")

        self.app.pop_screen()


class QueueScreen(Screen[None]):
    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("c", "cancel_selected", "Cancel"),
        Binding("s", "settings", "Settings"),
        Binding("r", "refresh", "Refresh"),
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
    #actions {
        height: auto;
        padding: 1 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="banner")
        with Vertical(id="table-wrap"):
            yield DataTable(id="queue-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="status-bar")
        with Horizontal(id="actions"):
            yield Button("Add push", variant="primary", id="btn-add")
            yield Button("Cancel selected", id="btn-cancel")
            yield Button("Settings", id="btn-settings")
            yield Button("Refresh", id="btn-refresh")
            yield Button("Quit", id="btn-quit")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.add_columns("Path", "Requested", "Scheduled", "Status", "Error")
        self._refresh_banner()
        self.refresh_table()

    def on_resize(self, event: events.Resize) -> None:
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "btn-add":
                self.action_add()
            case "btn-cancel":
                self.action_cancel_selected()
            case "btn-settings":
                self.action_settings()
            case "btn-refresh":
                self.action_refresh()
            case "btn-quit":
                self.action_quit()

    def action_add(self) -> None:
        self.app.push_screen(AddPushScreen())

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_refresh(self) -> None:
        def mutator(jobs: list[Job]) -> list[Job]:
            kept, _cancelled = validate.revalidate_queue(jobs)
            return kept

        jobs = store.update_queue(mutator)
        sync_daemon_with_queue(jobs)
        self.refresh_table()
        self.notify("Queue refreshed")

    def action_cancel_selected(self) -> None:
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
        self.app.exit()


class CarpetBomberApp(App[None]):
    TITLE = "CarpetBomber"
    SUB_TITLE = "scheduled git pushes"
    CSS = """
    Screen {
        background: #0f1419;
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
    Button {
        margin-right: 1;
        margin-left: 1;
    }
    DataTable > .datatable--cursor {
        background: #2a4a6a;
    }
    """

    def on_mount(self) -> None:
        self.push_screen(QueueScreen())


def main() -> None:
    CarpetBomberApp().run()


if __name__ == "__main__":
    main()
