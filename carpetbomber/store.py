from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from carpetbomber.models import Job, Settings

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix
    fcntl = None  # type: ignore[assignment]


def config_dir() -> Path:
    override = os.environ.get("CARPETBOMBER_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".config" / "carpetbomber"


def ensure_config_dir() -> Path:
    path = config_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return ensure_config_dir() / "settings.json"


def queue_path() -> Path:
    return ensure_config_dir() / "queue.json"


def daemon_log_path() -> Path:
    return ensure_config_dir() / "daemon.log"


def lock_path() -> Path:
    return ensure_config_dir() / ".lock"


@contextmanager
def file_lock() -> Iterator[None]:
    ensure_config_dir()
    lock_file = lock_path().open("a+")
    try:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def _atomic_write(path: Path, data: object) -> None:
    ensure_config_dir()
    text = json.dumps(data, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_settings() -> Settings:
    path = settings_path()
    if not path.exists():
        return Settings()
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return Settings.from_dict(data)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return Settings()


def save_settings(settings: Settings) -> None:
    with file_lock():
        _atomic_write(settings_path(), settings.to_dict())


def load_queue() -> list[Job]:
    path = queue_path()
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            return []
        return [Job.from_dict(item) for item in data]
    except (json.JSONDecodeError, OSError, TypeError, KeyError, ValueError):
        return []


def save_queue(jobs: list[Job]) -> None:
    with file_lock():
        _atomic_write(queue_path(), [job.to_dict() for job in jobs])


def update_queue(mutator) -> list[Job]:
    """Load queue under lock, apply mutator(jobs) -> jobs, save, return new list."""
    with file_lock():
        path = queue_path()
        jobs: list[Job] = []
        if path.exists():
            try:
                with path.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    jobs = [Job.from_dict(item) for item in data]
            except (json.JSONDecodeError, OSError, TypeError, KeyError, ValueError):
                jobs = []
        jobs = mutator(jobs)
        _atomic_write(path, [job.to_dict() for job in jobs])
        return jobs


def append_log(message: str) -> None:
    ensure_config_dir()
    with daemon_log_path().open("a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")
