from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class JobStatus(str, Enum):
    PENDING = "pending"
    PUSHING = "pushing"
    FAILED = "failed"
    DONE = "done"


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


@dataclass
class Settings:
    push_spacing_minutes: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Settings:
        if not data:
            return cls()
        return cls(
            push_spacing_minutes=int(data.get("push_spacing_minutes", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Job:
    path: str
    scheduled_at: datetime
    requested_at: datetime
    id: str = field(default_factory=lambda: str(uuid4()))
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    last_error: str | None = None
    ssh_passphrase: str | None = None
    commit_message: str = ""
    commit_head: str | None = None
    commit_created: bool = False

    @property
    def is_commit(self) -> bool:
        return bool(self.commit_message.strip())

    @property
    def operation_name(self) -> str:
        return "Commit" if self.is_commit else "Push"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        status_raw = data.get("status", JobStatus.PENDING.value)
        try:
            status = JobStatus(status_raw)
        except ValueError:
            status = JobStatus.PENDING
        passphrase = data.get("ssh_passphrase")
        commit_message = data.get("commit_message", "")
        commit_head = data.get("commit_head")
        commit_created = bool(data.get("commit_created", False))
        return cls(
            id=str(data.get("id") or uuid4()),
            path=str(data["path"]),
            scheduled_at=_parse_dt(data["scheduled_at"]),
            requested_at=_parse_dt(data["requested_at"]),
            status=status,
            created_at=_parse_dt(data.get("created_at", datetime.now().astimezone())),
            last_error=data.get("last_error"),
            ssh_passphrase=str(passphrase) if passphrase is not None else None,
            commit_message=str(commit_message) if commit_message is not None else "",
            commit_head=str(commit_head) if commit_head is not None else None,
            commit_created=commit_created,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "scheduled_at": self.scheduled_at.isoformat(),
            "requested_at": self.requested_at.isoformat(),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "last_error": self.last_error,
            "ssh_passphrase": self.ssh_passphrase,
            "commit_message": self.commit_message,
            "commit_head": self.commit_head,
            "commit_created": self.commit_created,
        }
