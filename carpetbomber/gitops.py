from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int


def _run(args: list[str], cwd: str | Path | None = None, timeout: float = 120) -> GitResult:
    try:
        proc = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return GitResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            returncode=proc.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        return GitResult(
            ok=False,
            stdout=(exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            stderr="git command timed out",
            returncode=-1,
        )
    except OSError as exc:
        return GitResult(ok=False, stdout="", stderr=str(exc), returncode=-1)


def is_git_repo(path: str | Path) -> bool:
    p = Path(path).expanduser()
    if not p.exists() or not p.is_dir():
        return False
    result = _run(["git", "-C", str(p.resolve()), "rev-parse", "--is-inside-work-tree"])
    return result.ok and result.stdout.strip() == "true"


def resolve_repo_path(path: str | Path) -> Path | None:
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        return None
    if not is_git_repo(p):
        return None
    result = _run(["git", "-C", str(p), "rev-parse", "--show-toplevel"])
    if not result.ok:
        return p
    top = result.stdout.strip()
    return Path(top) if top else p


def has_upstream(path: str | Path) -> bool:
    p = Path(path)
    result = _run(["git", "-C", str(p), "rev-parse", "--abbrev-ref", "@{u}"])
    return result.ok


def unpushed_count(path: str | Path) -> int | None:
    """Return number of unpushed commits, or None if upstream/repo unavailable."""
    p = Path(path)
    if not is_git_repo(p):
        return None
    if not has_upstream(p):
        return None
    result = _run(["git", "-C", str(p), "rev-list", "--count", "@{u}..HEAD"])
    if not result.ok:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def has_something_to_push(path: str | Path) -> bool:
    count = unpushed_count(path)
    return count is not None and count > 0


def git_push(path: str | Path, timeout: float = 300) -> GitResult:
    p = Path(path)
    return _run(["git", "-C", str(p), "push"], timeout=timeout)
