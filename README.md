# CarpetBomber

Schedule `git push` jobs for later. The interactive TUI manages the queue; a macOS LaunchAgent daemon runs pushes in the background after you quit the terminal — including catch-up after sleep or reboot.

## Install

```bash
cd CarpetBomber
python3 -m venv .venv
source .venv/bin/activate
pip install -i https://pypi.org/simple -e ".[dev]"
```

This installs two commands:

- `CarpetBomber` — Textual TUI
- `carpetbomber-daemon` — background worker (normally started via LaunchAgent)

## Usage

```bash
CarpetBomber
```

From the queue screen:

| Action | Key |
|--------|-----|
| Add push | `a` |
| Edit selected | `e` |
| Cancel selected | `c` |
| Settings | `s` |
| Quit | `q` |

**Settings / Add / Edit** open a JSON buffer with the same shell layout as the queue (header, editor, status, footer). Controls are vim-lite:

| Mode | Keys |
|------|------|
| NORMAL | `h`/`j`/`k`/`l` or arrows move; `i` insert; `:` command |
| INSERT | type to edit; arrows move; `Esc` back to NORMAL |
| COMMAND | `:w` save, `:wq` save and quit, `:q` quit without saving; `Esc` cancels |

**Add a push:** edit JSON fields `path`, `date` (`YYYY-MM-DD`), and `time` (`HH:MM`). Defaults to **00:00 tomorrow**. CarpetBomber runs `git push` only (no commit).

**Edit a push:** with a pending job selected, `e` opens the same JSON pre-filled so you can change path and/or schedule time.

**Settings:** edit `push_spacing_minutes` in the JSON buffer, then `:wq`.

**Same-time collisions:** if that minute is taken, the job is placed on the next free slot stepped by **push spacing** (default 1 minute), configurable in Settings.

**Quit:** leaves the daemon running if pending jobs remain.

## How background pushes work

Config lives in `~/.config/carpetbomber/`:

- `settings.json` — `push_spacing_minutes`
- `queue.json` — scheduled jobs
- `daemon.log` — push outcomes

On macOS, when the queue is non-empty, CarpetBomber installs a LaunchAgent at:

`~/Library/LaunchAgents/com.carpetbomber.daemon.plist`

The agent starts `carpetbomber-daemon` at login (`RunAtLoad`) and restarts it after a crash. When the queue is empty, the daemon exits and the agent is unloaded.

After sleep or reboot, overdue jobs run in original schedule order, spaced by `push_spacing_minutes`.

Override the config directory (useful for tests):

```bash
export CARPETBOMBER_CONFIG_DIR=/tmp/carpetbomber-test
```

## Requirements

- Python 3.11+
- macOS for LaunchAgent background persistence (daemon can still be run manually elsewhere)
- Git repos with a configured upstream (`@{u}`)

## Tests

```bash
pytest
```
