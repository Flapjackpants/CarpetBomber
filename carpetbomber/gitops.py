from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int


def _run(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: float = 120,
    env: dict[str, str] | None = None,
    *,
    start_new_session: bool = False,
) -> GitResult:
    try:
        proc = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
            stdin=subprocess.DEVNULL,
            start_new_session=start_new_session,
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


def _is_ssh_url(url: str) -> bool:
    u = url.strip()
    return u.startswith("git@") or u.startswith("ssh://") or u.startswith("ssh:")


def upstream_push_url(path: str | Path) -> str | None:
    """Return the push URL for the repo's upstream remote, or origin as fallback."""
    p = Path(path)
    remote_name: str | None = None

    upstream = _run(["git", "-C", str(p), "rev-parse", "--abbrev-ref", "@{u}"])
    if upstream.ok and upstream.stdout.strip():
        # e.g. origin/main
        remote_name = upstream.stdout.strip().split("/", 1)[0]

    if not remote_name:
        remotes = _run(["git", "-C", str(p), "remote"])
        names = [line.strip() for line in remotes.stdout.splitlines() if line.strip()]
        if "origin" in names:
            remote_name = "origin"
        elif names:
            remote_name = names[0]
        else:
            return None

    url_result = _run(["git", "-C", str(p), "remote", "get-url", "--push", remote_name])
    if not url_result.ok or not url_result.stdout.strip():
        url_result = _run(["git", "-C", str(p), "remote", "get-url", remote_name])
    url = url_result.stdout.strip()
    return url or None


def requires_ssh_auth(path: str | Path) -> bool:
    url = upstream_push_url(path)
    if not url:
        return False
    return _is_ssh_url(url)


def _make_askpass_files(passphrase: str) -> tuple[Path, Path]:
    """Write a short-lived askpass script + secret file; returns (script, secret)."""
    secret_fd, secret_name = tempfile.mkstemp(prefix="carpetbomber-askpass-secret-")
    secret = Path(secret_name)
    script_fd, script_name = tempfile.mkstemp(prefix="carpetbomber-askpass-", suffix=".sh")
    script = Path(script_name)
    try:
        with os.fdopen(secret_fd, "w", encoding="utf-8") as fh:
            # OpenSSH reads askpass stdout as a line; include trailing newline.
            fh.write(passphrase)
            if not passphrase.endswith("\n"):
                fh.write("\n")
        os.chmod(secret, 0o600)
        with os.fdopen(script_fd, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n")
            fh.write(f"cat '{secret}'\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    except Exception:
        for p in (script, secret):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return script, secret


def git_push(
    path: str | Path,
    timeout: float = 300,
    ssh_passphrase: str | None = None,
) -> GitResult:
    """
    Run `git push`.

    When a passphrase is provided, feed it via SSH_ASKPASS and detach from the
    controlling TTY so OpenSSH cannot hang on a hidden /dev/tty prompt (common
    inside the Textual TUI). Without a passphrase, enable BatchMode so a locked
    key fails fast instead of timing out.
    """
    p = Path(path)
    env = os.environ.copy()
    askpass: Path | None = None
    secret: Path | None = None

    try:
        if ssh_passphrase:
            askpass, secret = _make_askpass_files(ssh_passphrase)
            env["SSH_ASKPASS"] = str(askpass)
            env["SSH_ASKPASS_REQUIRE"] = "force"
            # OpenSSH still wants DISPLAY set to consider askpass in some builds
            env.setdefault("DISPLAY", ":0")
            env["GIT_SSH_COMMAND"] = (
                "ssh -o StrictHostKeyChecking=accept-new -o NumberOfPasswordPrompts=1"
            )
        else:
            # Never block on an interactive passphrase/host prompt.
            env["GIT_SSH_COMMAND"] = (
                "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
            )

        return _run(
            ["git", "-C", str(p), "push"],
            timeout=timeout,
            env=env,
            # New session → no controlling terminal → ssh won't open /dev/tty
            start_new_session=True,
        )
    finally:
        for pth in (askpass, secret):
            if pth is not None:
                try:
                    pth.unlink(missing_ok=True)
                except OSError:
                    pass
