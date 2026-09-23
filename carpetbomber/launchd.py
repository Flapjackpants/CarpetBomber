from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.carpetbomber.daemon"

# launchctl can stall; never block process exit on it
_LAUNCHCTL_TIMEOUT = 0.5


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_dir() -> Path:
    from carpetbomber.store import ensure_config_dir

    return ensure_config_dir()


def find_daemon_executable() -> str:
    """Resolve carpetbomber-daemon on PATH or next to the current interpreter."""
    found = shutil.which("carpetbomber-daemon")
    if found:
        return found
    candidate = Path(sys.executable).resolve().parent / "carpetbomber-daemon"
    if candidate.exists():
        return str(candidate)
    # Fallback: run module via same Python
    return sys.executable


def daemon_program_args() -> list[str]:
    exe = find_daemon_executable()
    # When only the interpreter is available, invoke the daemon entrypoint via -c
    if Path(exe).name.startswith("python") or exe == sys.executable:
        return [exe, "-c", "from carpetbomber.daemon import main; main()"]
    return [exe]


def build_plist() -> dict:
    stdout = str(log_dir() / "launchd.stdout.log")
    stderr = str(log_dir() / "launchd.stderr.log")
    program_args = daemon_program_args()
    return {
        "Label": LABEL,
        "ProgramArguments": program_args,
        "RunAtLoad": True,
        "KeepAlive": {
            "SuccessfulExit": False,
        },
        "StandardOutPath": stdout,
        "StandardErrorPath": stderr,
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
            "HOME": str(Path.home()),
        },
    }


def write_plist() -> Path:
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        plistlib.dump(build_plist(), fh)
    return path


def _uid() -> str:
    return str(os.getuid())


def _run_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run launchctl with a hard timeout so a stall cannot hang the process."""
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=_LAUNCHCTL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, returncode=-1, stdout="", stderr="timeout")


def is_loaded() -> bool:
    if sys.platform != "darwin":
        return False
    result = _run_launchctl(["launchctl", "print", f"gui/{_uid()}/{LABEL}"])
    return result.returncode == 0


def bootstrap() -> None:
    """Install/update LaunchAgent and start the daemon (macOS)."""
    if sys.platform != "darwin":
        return
    path = write_plist()
    domain = f"gui/{_uid()}"
    # bootout first if already loaded so ProgramArguments updates take effect
    if is_loaded():
        _run_launchctl(["launchctl", "bootout", f"{domain}/{LABEL}"])
    result = _run_launchctl(["launchctl", "bootstrap", domain, str(path)])
    if result.returncode != 0:
        # Older macOS fallback
        _run_launchctl(["launchctl", "load", "-w", str(path)])
    _run_launchctl(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"])


def bootout() -> None:
    """Unload LaunchAgent so nothing stays resident."""
    if sys.platform != "darwin":
        return
    domain = f"gui/{_uid()}"
    _run_launchctl(["launchctl", "bootout", f"{domain}/{LABEL}"])
    path = plist_path()
    _run_launchctl(["launchctl", "unload", "-w", str(path)])


def ensure_daemon_running() -> None:
    """Start the LaunchAgent if it is not already loaded.

    Avoid bootout/restart when already running — that kills the daemon mid-sleep
    and can leave scheduled pushes stranded until the next TUI session.
    """
    if sys.platform != "darwin":
        return
    write_plist()
    if is_loaded():
        return
    bootstrap()


def stop_daemon() -> None:
    bootout()
