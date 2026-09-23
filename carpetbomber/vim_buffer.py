"""Vim-lite text buffer for JSON editing in the TUI."""

from __future__ import annotations

from enum import Enum
from rich.text import Text
from textual import events
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget


class EditorMode(str, Enum):
    NORMAL = "normal"
    INSERT = "insert"
    COMMAND = "command"


class VimBufferModel:
    """Pure buffer logic (testable without Textual)."""

    def __init__(self, text: str = "") -> None:
        lines = text.split("\n") if text else [""]
        self.lines: list[str] = lines if lines else [""]
        self.row = 0
        self.col = 0
        self.mode = EditorMode.NORMAL
        self.cmdline = ""
        self._clamp_cursor()

    def get_text(self) -> str:
        return "\n".join(self.lines)

    def status_text(self) -> str:
        if self.mode == EditorMode.COMMAND:
            return f":{self.cmdline}"
        if self.mode == EditorMode.INSERT:
            return "-- INSERT --"
        return "-- NORMAL --"

    def _clamp_cursor(self) -> None:
        if not self.lines:
            self.lines = [""]
        self.row = max(0, min(self.row, len(self.lines) - 1))
        line_len = len(self.lines[self.row])
        # In normal mode cursor may sit on last char; allow past end in insert.
        if self.mode == EditorMode.INSERT:
            self.col = max(0, min(self.col, line_len))
        else:
            self.col = max(0, min(self.col, max(0, line_len - 1) if line_len else 0))

    def move_left(self) -> None:
        if self.col > 0:
            self.col -= 1

    def move_right(self) -> None:
        line = self.lines[self.row]
        limit = len(line) if self.mode == EditorMode.INSERT else max(0, len(line) - 1)
        if self.col < limit:
            self.col += 1

    def move_up(self) -> None:
        if self.row > 0:
            self.row -= 1
            self._clamp_cursor()

    def move_down(self) -> None:
        if self.row < len(self.lines) - 1:
            self.row += 1
            self._clamp_cursor()

    def enter_insert(self) -> None:
        self.mode = EditorMode.INSERT
        self._clamp_cursor()

    def enter_normal(self) -> None:
        self.mode = EditorMode.NORMAL
        self.cmdline = ""
        self._clamp_cursor()

    def enter_command(self) -> None:
        self.mode = EditorMode.COMMAND
        self.cmdline = ""

    def insert_char(self, char: str) -> None:
        if self.mode != EditorMode.INSERT or len(char) != 1:
            return
        line = self.lines[self.row]
        self.lines[self.row] = line[: self.col] + char + line[self.col :]
        self.col += 1

    def backspace(self) -> None:
        if self.mode == EditorMode.COMMAND:
            self.cmdline = self.cmdline[:-1]
            return
        if self.mode != EditorMode.INSERT:
            return
        if self.col > 0:
            line = self.lines[self.row]
            self.lines[self.row] = line[: self.col - 1] + line[self.col :]
            self.col -= 1
        elif self.row > 0:
            prev = self.lines[self.row - 1]
            cur = self.lines[self.row]
            self.col = len(prev)
            self.lines[self.row - 1] = prev + cur
            del self.lines[self.row]
            self.row -= 1

    def insert_newline(self) -> None:
        if self.mode != EditorMode.INSERT:
            return
        line = self.lines[self.row]
        left, right = line[: self.col], line[self.col :]
        self.lines[self.row] = left
        self.lines.insert(self.row + 1, right)
        self.row += 1
        self.col = 0

    def handle_key(self, key: str, character: str | None = None) -> str | None:
        """Handle a key. Returns a completed ex-command (without leading ':') or None."""
        if self.mode == EditorMode.COMMAND:
            return self._handle_command_key(key, character)

        if key == "escape":
            self.enter_normal()
            return None

        if self.mode == EditorMode.NORMAL:
            return self._handle_normal_key(key)

        return self._handle_insert_key(key, character)

    def _handle_normal_key(self, key: str) -> str | None:
        if key in ("i",):
            self.enter_insert()
        elif key in ("colon", ":"):
            self.enter_command()
        elif key in ("h", "left"):
            self.move_left()
        elif key in ("l", "right"):
            self.move_right()
        elif key in ("k", "up"):
            self.move_up()
        elif key in ("j", "down"):
            self.move_down()
        return None

    def _handle_insert_key(self, key: str, character: str | None) -> str | None:
        if key in ("left",):
            self.move_left()
        elif key in ("right",):
            self.move_right()
        elif key in ("up",):
            self.move_up()
        elif key in ("down",):
            self.move_down()
        elif key == "enter":
            self.insert_newline()
        elif key == "backspace":
            self.backspace()
        elif character and character.isprintable() and key not in ("enter", "tab"):
            self.insert_char(character)
        return None

    def _handle_command_key(self, key: str, character: str | None) -> str | None:
        if key == "escape":
            self.enter_normal()
            return None
        if key == "enter":
            cmd = self.cmdline.strip()
            self.enter_normal()
            return cmd
        if key == "backspace":
            self.backspace()
            return None
        if character and character.isprintable():
            self.cmdline += character
        return None


class VimBuffer(Widget):
    """Focusable Textual widget wrapping VimBufferModel."""

    can_focus = True
    mode_label: reactive[str] = reactive("-- NORMAL --")

    class CommandSubmitted(Message):
        """Posted when the user finishes an ex-command with Enter."""

        def __init__(self, command: str) -> None:
            self.command = command
            super().__init__()

    class ModeChanged(Message):
        def __init__(self, status: str) -> None:
            self.status = status
            super().__init__()

    DEFAULT_CSS = """
    VimBuffer {
        height: 1fr;
        padding: 0 1;
        background: $surface;
        border: solid $accent;
    }
    VimBuffer:focus {
        border: solid $secondary;
    }
    """

    def __init__(self, text: str = "", *, name: str | None = None, id: str | None = None) -> None:
        super().__init__(name=name, id=id)
        self.model = VimBufferModel(text)

    def get_text(self) -> str:
        return self.model.get_text()

    def status_text(self) -> str:
        return self.model.status_text()

    def _sync_status(self) -> None:
        status = self.model.status_text()
        self.mode_label = status
        self.post_message(self.ModeChanged(status))

    def render(self) -> Text:
        out = Text()
        for i, line in enumerate(self.model.lines):
            if i != self.model.row:
                out.append(line or " ")
                out.append("\n")
                continue
            col = self.model.col
            # Ensure we have a place to draw the cursor on empty/end
            display = line
            if col >= len(display):
                display = display + " "
                col = len(display) - 1
            before = display[:col]
            cursor_ch = display[col]
            after = display[col + 1 :]
            out.append(before)
            out.append(cursor_ch, style="reverse bold")
            out.append(after)
            out.append("\n")
        # Drop trailing newline visual blank if last line rendered with \n
        return out

    def on_mount(self) -> None:
        self._sync_status()

    def on_key(self, event: events.Key) -> None:
        event.stop()
        event.prevent_default()
        character = event.character if event.is_printable else None
        # Textual uses "colon" for ':'
        key = event.key
        if character == ":" and self.model.mode == EditorMode.NORMAL:
            key = "colon"
        cmd = self.model.handle_key(key, character)
        self._sync_status()
        self.refresh()
        if cmd is not None:
            self.post_message(self.CommandSubmitted(cmd))

    def watch_mode_label(self, value: str) -> None:
        # reactive hook keeps Textual happy; status is pushed via ModeChanged
        _ = value
