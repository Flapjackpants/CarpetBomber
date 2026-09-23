from __future__ import annotations

import re

from rich.text import Text

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

TITLE_ART = """\
\x1b[0;97m   \x1b[0;36m▄\x1b[0;97m  \x1b[0;36m▄\x1b[0;37m   \x1b[0;97m     \x1b[0;36m▄\x1b[0;37m   \x1b[0;97m     \x1b[0;36m▄\x1b[0;37m   \x1b[0;97m     \x1b[0;36m▄\x1b[0;37m   \x1b[0;97m     \x1b[0;36m▄\x1b[0;37m   \x1b[0;97m   \x1b[0;36m▄\x1b[0;97m    \x1b[0;36m▄\x1b[0;37m       \x1b[0;97m     \x1b[0;36m▄\x1b[0;37m    \x1b[0;97m   \x1b[0;36m▄\x1b[0;97m   \x1b[0;36m▄\x1b[0;37m   \x1b[0;97m \x1b[0;36m▄\x1b[0;97m \x1b[0;36m▄▄▄\x1b[0;97m \x1b[0;36m▄▄▄\x1b[0;37m   \x1b[0;97m     \x1b[0;36m▄\x1b[0;37m    \x1b[0;97m     \x1b[0;36m▄\x1b[0;37m   \x1b[0;97m     \x1b[0;36m▄\x1b[0;37m   \x1b[0m
\x1b[0;97m \x1b[0;36m▄██▀▐██▄\x1b[0;37m \x1b[0;97m \x1b[0;36m▄█\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m \x1b[0;97m \x1b[0;96m▄\x1b[0;36m█\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m \x1b[0;97m \x1b[0;96m▄\x1b[0;36m█\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m \x1b[0;97m \x1b[0;96m▄\x1b[0;36m█\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m \x1b[0;97m \x1b[0;36m▄██▀\x1b[0;96m▄\x1b[0;36m█▀██▄\x1b[0;37m     \x1b[0;97m \x1b[0;36m▄█\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m  \x1b[0;97m \x1b[0;96m▄\x1b[0;36m██▀\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m \x1b[0;36m▀██▄▀██▄▀██▄\x1b[0;37m \x1b[0;97m \x1b[0;36m▄█\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m  \x1b[0;97m \x1b[0;96m▄\x1b[0;36m█\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m \x1b[0;97m \x1b[0;96m▄\x1b[0;36m█\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m \x1b[0m
\x1b[0;36m▐\x1b[0;96;46m▓\x1b[0;36m█▌\x1b[0;97m  \x1b[0;36m▀█\x1b[0;90;46m░\x1b[0;36m▌\x1b[0;97m \x1b[0;96;46m▓\x1b[0;36m█▌▄▐█\x1b[0;90;46m░\x1b[0;36m▌\x1b[0;97m \x1b[0;96;46m▓\x1b[0;36m█▌\x1b[0;97m  \x1b[0;36m██▌\x1b[0;97m \x1b[0;96;46m▓\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m▄██▌\x1b[0;97m \x1b[0;96;46m▓\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m▄▀█▀▐██\x1b[0;97m  \x1b[0;96;46m▓\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m██▌\x1b[0;37m    \x1b[0;97m \x1b[0;96;46m▓\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m▄██▌\x1b[0;37m \x1b[0;36m▐\x1b[0;96;46m▓\x1b[0;36m█▌\x1b[0;97m   \x1b[0;36m▐█\x1b[0;90;46m░\x1b[0;36m▌\x1b[0;97m \x1b[0;36m▐█\x1b[0;90;46m░\x1b[0;36m▌▐█\x1b[0;90;46m░\x1b[0;36m▌▐█\x1b[0;90;46m░\x1b[0;36m▌\x1b[0;97m \x1b[0;96;46m▓\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m▄██▌\x1b[0;37m \x1b[0;97m \x1b[0;96;46m▓\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m▄▀█▀\x1b[0;97m \x1b[0;96;46m▓\x1b[0;36m█▌\x1b[0;97m  \x1b[0;36m██▌\x1b[0m
\x1b[0;36m█\x1b[0;96;46m▒\x1b[0;36m█\x1b[0;37m       \x1b[0;97m \x1b[0;96;46m▒\x1b[0;36m█▌▀\x1b[0;97m \x1b[0;36m█\x1b[0;90;46m▒\x1b[0;36m█\x1b[0;97m \x1b[0;96;46m▒\x1b[0;36m█\x1b[0;97m \x1b[0;36m▀█▄▀\x1b[0;37m \x1b[0;97m \x1b[0;96;46m▒\x1b[0;36m█▌▀███\x1b[0;37m \x1b[0;97m \x1b[0;96;46m▒\x1b[0;36m█▌▀██▄\x1b[0;37m \x1b[0;97m \x1b[0;36m▀\x1b[0;97m   \x1b[0;96;46m▒\x1b[0;36m█▌\x1b[0;97m  \x1b[0;36m▀\x1b[0;37m     \x1b[0;97m \x1b[0;96;46m▒\x1b[0;36m█▌▀██▀▄\x1b[0;37m \x1b[0;36m█\x1b[0;96;46m▒\x1b[0;36m█ \x1b[0;97m    \x1b[0;36m█\x1b[0;90;46m▒\x1b[0;36m█\x1b[0;97m  \x1b[0;36m█\x1b[0;90;46m▒\x1b[0;36m█\x1b[0;97m \x1b[0;36m█\x1b[0;90;46m▒\x1b[0;36m█\x1b[0;97m \x1b[0;36m█\x1b[0;90;46m▒\x1b[0;36m█\x1b[0;97m \x1b[0;96;46m▒\x1b[0;36m█▌▀██▀▄\x1b[0;37m \x1b[0;97m \x1b[0;96;46m▒\x1b[0;36m█▌▀██▄\x1b[0;37m \x1b[0;97m \x1b[0;96;46m▒\x1b[0;36m█\x1b[0;97m \x1b[0;36m▀█▄▀\x1b[0;37m \x1b[0m
\x1b[0;36m▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;97m  \x1b[0;36m▄█\x1b[0;90;46m▓\x1b[0;36m▌▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m▐█\x1b[0;90;46m▓\x1b[0;36m▌▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m▄█\x1b[0;90;46m▓\x1b[0;37m \x1b[0;36m▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m ▀\x1b[0;37m  \x1b[0;36m▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m▄▀\x1b[0;37m  \x1b[0;97m    \x1b[0;36m▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;37m        \x1b[0;36m▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m ▄█\x1b[0;90;46m█\x1b[0;36m▌▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;97m   \x1b[0;36m▐█\x1b[0;90;46m▓\x1b[0;36m▌\x1b[0;97m \x1b[0;36m▐█\x1b[0;90;46m▓\x1b[0;36m▌▐█\x1b[0;90;46m▓\x1b[0;36m▌▐█\x1b[0;90;46m▓\x1b[0;36m▌▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m ▄█\x1b[0;90;46m█\x1b[0;36m▌▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m▄▀\x1b[0;37m  \x1b[0;36m▐\x1b[0;96;46m░\x1b[0;36m█▌\x1b[0;97m \x1b[0;36m▄█\x1b[0;90;46m▓\x1b[0;37m \x1b[0m
\x1b[0;97m \x1b[0;36m▀██▄▐██▀\x1b[0;37m \x1b[0;97m \x1b[0;36m▀█▀\x1b[0;97m \x1b[0;36m▄██\x1b[0;90m▀\x1b[0;37m \x1b[0;36m▀█▀\x1b[0;97m \x1b[0;36m▐██\x1b[0;90m▀\x1b[0;37m \x1b[0;36m▀█▀\x1b[0;37m      \x1b[0;36m▀█▀\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m \x1b[0;97m    \x1b[0;36m▀█▀\x1b[0;37m         \x1b[0;36m▀█▀▄████\x1b[0;90m▀\x1b[0;37m \x1b[0;97m \x1b[0;36m▀██▄\x1b[0;97m \x1b[0;36m▄██\x1b[0;90m▀\x1b[0;37m \x1b[0;36m▄██\x1b[0;90m▀\x1b[0;36m▄██\x1b[0;90m▀\x1b[0;36m▄██\x1b[0;90m▀\x1b[0;37m \x1b[0;36m▀█▀▄████\x1b[0;90m▀\x1b[0;37m \x1b[0;36m▀█▀\x1b[0;97m \x1b[0;36m▀██▄\x1b[0;37m \x1b[0;36m▀█▀\x1b[0;97m \x1b[0;36m▐██\x1b[0;90m▀\x1b[0;37m \x1b[0m
\x1b[0;97m   \x1b[0;36m▀\x1b[0;97m  \x1b[0;36m▀\x1b[0;37m   \x1b[0;97m     \x1b[0;36m▀\x1b[0;37m   \x1b[0;97m    \x1b[0;36m▀\x1b[0;37m             \x1b[0;97m     \x1b[0;36m ▀\x1b[0;37m                  \x1b[0;97m     \x1b[0;36m▀▀\x1b[0;37m   \x1b[0;97m   \x1b[0;36m▀\x1b[0;97m   \x1b[0;36m▀\x1b[0;37m   \x1b[0;97m \x1b[0;36m▀\x1b[0;97m   \x1b[0;36m▀\x1b[0;97m   \x1b[0;36m▀\x1b[0;37m   \x1b[0;97m     \x1b[0;36m▀▀\x1b[0;37m   \x1b[0;97m     \x1b[0;36m ▀\x1b[0;37m  \x1b[0;97m    \x1b[0;36m▀\x1b[0;37m    \x1b[0m"""

_ART_LINES = TITLE_ART.splitlines()
ART_WIDTH = max(len(_ANSI_RE.sub("", line)) for line in _ART_LINES)
ART_HEIGHT = len(_ART_LINES)

_COMPACT = Text.from_markup("[bold]CarpetBomber[/bold]  —  scheduled git pushes")


def render_title(width: int) -> Text:
    """Return full ANSI art (centered) when width allows, else a compact title."""
    if width < ART_WIDTH:
        return _COMPACT.copy()

    pad = max(0, (width - ART_WIDTH) // 2)
    if pad == 0:
        return Text.from_ansi(TITLE_ART)

    left = " " * pad
    centered = "\n".join(f"{left}{line}" for line in _ART_LINES)
    return Text.from_ansi(centered)
