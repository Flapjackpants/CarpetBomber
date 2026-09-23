from __future__ import annotations

from carpetbomber.app import parse_editor_json, schedule_fields_from_data
from carpetbomber.vim_buffer import EditorMode, VimBufferModel


def test_motion_hjkl_boundaries():
    buf = VimBufferModel("ab\ncd")
    assert (buf.row, buf.col) == (0, 0)

    buf.handle_key("l")
    assert (buf.row, buf.col) == (0, 1)

    buf.handle_key("l")  # stay on last char in normal mode
    assert (buf.row, buf.col) == (0, 1)

    buf.handle_key("j")
    assert (buf.row, buf.col) == (1, 1)

    buf.handle_key("h")
    assert (buf.row, buf.col) == (1, 0)

    buf.handle_key("k")
    assert (buf.row, buf.col) == (0, 0)

    buf.handle_key("h")  # stay at start
    assert (buf.row, buf.col) == (0, 0)


def test_arrow_keys_move():
    buf = VimBufferModel("xy")
    buf.handle_key("right")
    assert buf.col == 1
    buf.handle_key("left")
    assert buf.col == 0


def test_insert_and_escape_to_normal():
    buf = VimBufferModel("hi")
    buf.handle_key("i")
    assert buf.mode == EditorMode.INSERT
    assert buf.status_text() == "-- INSERT --"

    buf.handle_key("x", "x")
    assert buf.get_text() == "xhi"
    assert buf.col == 1

    buf.handle_key("escape")
    assert buf.mode == EditorMode.NORMAL
    assert buf.status_text() == "-- NORMAL --"


def test_insert_newline_and_backspace_join():
    buf = VimBufferModel("ab")
    buf.handle_key("i")
    buf.handle_key("right")
    buf.handle_key("right")
    buf.handle_key("enter")
    assert buf.get_text() == "ab\n"
    assert (buf.row, buf.col) == (1, 0)

    buf.handle_key("backspace")
    assert buf.get_text() == "ab"
    assert (buf.row, buf.col) == (0, 2)


def test_command_wq():
    buf = VimBufferModel("{}")
    buf.handle_key("colon")
    assert buf.mode == EditorMode.COMMAND
    assert buf.status_text() == ":"

    for ch in "wq":
        assert buf.handle_key(ch, ch) is None
    assert buf.cmdline == "wq"

    cmd = buf.handle_key("enter")
    assert cmd == "wq"
    assert buf.mode == EditorMode.NORMAL


def test_command_escape_cancels():
    buf = VimBufferModel("{}")
    buf.handle_key("colon")
    buf.handle_key("q", "q")
    assert buf.handle_key("escape") is None
    assert buf.mode == EditorMode.NORMAL
    assert buf.cmdline == ""


def test_parse_editor_json_ok_and_errors():
    assert parse_editor_json('{"a": 1}') == {"a": 1}
    err = parse_editor_json("{")
    assert isinstance(err, str) and "Invalid JSON" in err
    err = parse_editor_json("[1]")
    assert err == "JSON root must be an object"


def test_schedule_fields_from_data():
    assert schedule_fields_from_data(
        {"path": " /tmp/r ", "date": "2026-01-01", "time": "12:00"}
    ) == ("/tmp/r", "2026-01-01", "12:00")
    assert schedule_fields_from_data({"path": 1}) == "path must be a string"
