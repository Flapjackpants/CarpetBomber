# CarpetBomber

Schedule `git push` jobs for later. The interactive TUI manages the queue; a macOS LaunchAgent daemon runs pushes in the background after you quit the terminal — including catch-up after sleep or reboot.

## Install

Install from GitHub without cloning (requires `sudo`, `curl`, and Python 3.11+):

```bash
curl -fsSL https://raw.githubusercontent.com/Flapjackpants/CarpetBomber/main/download.sh | bash
```

This creates a venv in `/Applications/CarpetBomber`, `pip install`s the package from GitHub’s source archive, and links:

- `CarpetBomber` — Textual TUI
- `carpetbomber-daemon` — background worker (normally started via LaunchAgent)

into `/usr/local/bin` so you can run them from anywhere.

### Development install

```bash
git clone https://github.com/Flapjackpants/CarpetBomber.git
cd CarpetBomber
python3 -m venv .venv
source .venv/bin/activate
pip install -i https://pypi.org/simple -e ".[dev]"
```

Or from a local checkout, run `./download.sh` to install the same system layout as the curl one-liner.

## Usage

```bash
CarpetBomber
CarpetBomber this   # open Add with the current directory as path
```

From the queue screen:

| Action | Key |
|--------|-----|
| Add push | `a` |
| Edit selected | `e` |
| Run selected now | `r` |
| Cancel selected | `c` (then `y`/`n`) |
| Settings | `s` |
| Quit | `q` |

**Cancel:** with a job selected, `c` replaces the status line with `Confirm?`; `y` removes it, `n` aborts.

**Settings / Add / Edit** open a JSON buffer with the same shell layout as the queue (header, editor, status, footer). Controls are vim-lite:

| Mode | Keys |
|------|------|
| NORMAL | `h`/`j`/`k`/`l` or arrows move; `i` insert; `:` command |
| INSERT | type to edit; arrows move; `Esc` back to NORMAL |
| COMMAND | `:w` save, `:wq` save and quit, `:q` quit without saving; `Esc` cancels |

**Add a push:** edit JSON fields `path`, `date` (`YYYY-MM-DD`), and `time` (`HH:MM`). Defaults to **00:00 tomorrow**. CarpetBomber runs `git push` only (no commit). If the repo’s upstream is SSH (`git@…` / `ssh://…`), an `ssh_passphrase` field is included — fill it when the key is passphrase-protected (stored on the job in `queue.json`).

**Edit a push:** with a pending job selected, `e` opens the same JSON pre-filled so you can change path and/or schedule time. When SSH applies, `ssh_passphrase` is shown blank; leave it blank to keep a previously stored value.

**Run now:** with a pending or failed job selected, `r` runs `git push` immediately (failed jobs are re-queued first). An ASCII spinner appears in the status bar while the push runs. Success removes the job; failure keeps it as failed with the error.

**While the TUI is open**, CarpetBomber runs due pushes itself (no background polling). When a scheduled time arrives, the status bar shows an ASCII spinner while the job runs; the job is removed on success or marked failed. The LaunchAgent daemon is paused while the TUI is open and restarted on quit if pending jobs remain.

**Settings:** edit `push_spacing_minutes` in the JSON buffer, then `:wq`.

**Same-time collisions:** if that minute is taken, the job is placed on the next free slot stepped by **push spacing** (default 1 minute), configurable in Settings.

**Quit:** leaves the daemon running if pending jobs remain.

## How background pushes work

Config lives in `~/.config/carpetbomber/`:

- `settings.json` — `push_spacing_minutes`
- `queue.json` — scheduled jobs (including optional `ssh_passphrase`)
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
