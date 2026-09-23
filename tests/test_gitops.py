from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from carpetbomber import gitops
from carpetbomber.gitops import GitResult
from carpetbomber.models import Job, JobStatus

TZ = timezone(timedelta(hours=-4))


def test_is_ssh_url_detection():
    assert gitops._is_ssh_url("git@github.com:user/repo.git")
    assert gitops._is_ssh_url("ssh://git@example.com/repo.git")
    assert gitops._is_ssh_url("ssh:host/path")
    assert not gitops._is_ssh_url("https://github.com/user/repo.git")
    assert not gitops._is_ssh_url("http://example.com/repo.git")


def test_requires_ssh_auth_uses_upstream_url():
    with patch.object(gitops, "upstream_push_url", return_value="git@github.com:a/b.git"):
        assert gitops.requires_ssh_auth("/repo") is True
    with patch.object(gitops, "upstream_push_url", return_value="https://github.com/a/b.git"):
        assert gitops.requires_ssh_auth("/repo") is False
    with patch.object(gitops, "upstream_push_url", return_value=None):
        assert gitops.requires_ssh_auth("/repo") is False


def test_upstream_push_url_from_upstream_ref():
    def fake_run(args, **kwargs):
        cmd = " ".join(args)
        if "rev-parse" in cmd and "@{u}" in cmd:
            return GitResult(ok=True, stdout="origin/main\n", stderr="", returncode=0)
        if "remote get-url --push origin" in cmd or (
            args[-2:] == ["--push", "origin"]
        ):
            return GitResult(
                ok=True,
                stdout="git@github.com:user/repo.git\n",
                stderr="",
                returncode=0,
            )
        return GitResult(ok=False, stdout="", stderr="no", returncode=1)

    with patch.object(gitops, "_run", side_effect=fake_run):
        assert gitops.upstream_push_url("/repo") == "git@github.com:user/repo.git"


def test_git_push_without_passphrase_uses_batch_mode():
    captured: dict = {}

    def fake_run(args, cwd=None, timeout=120, env=None, start_new_session=False):
        captured["env"] = env
        captured["args"] = args
        captured["start_new_session"] = start_new_session
        return GitResult(ok=True, stdout="", stderr="", returncode=0)

    with patch.object(gitops, "_run", side_effect=fake_run):
        result = gitops.git_push("/repo")
    assert result.ok
    assert captured["env"] is not None
    assert "BatchMode=yes" in captured["env"]["GIT_SSH_COMMAND"]
    assert "SSH_ASKPASS" not in captured["env"]
    assert captured["start_new_session"] is True
    assert captured["args"] == ["git", "-C", "/repo", "push"]


def test_git_push_with_passphrase_sets_askpass(tmp_path: Path):
    captured: dict = {}

    def fake_run(args, cwd=None, timeout=120, env=None, start_new_session=False):
        captured["env"] = env
        captured["start_new_session"] = start_new_session
        # Read secret via askpass script while files still exist
        askpass = Path(env["SSH_ASKPASS"])
        assert askpass.exists()
        secret_line = askpass.read_text(encoding="utf-8").strip().splitlines()[-1]
        # cat 'path'
        secret_path = Path(secret_line.split("'", 2)[1])
        captured["secret"] = secret_path.read_text(encoding="utf-8")
        return GitResult(ok=True, stdout="", stderr="", returncode=0)

    with patch.object(gitops, "_run", side_effect=fake_run):
        result = gitops.git_push("/repo", ssh_passphrase="s3cret!")
    assert result.ok
    env = captured["env"]
    assert env is not None
    assert env["SSH_ASKPASS_REQUIRE"] == "force"
    assert env.get("DISPLAY")  # setdefault ":0" when unset; keep existing otherwise
    assert "SSH_ASKPASS" in env
    assert "BatchMode" not in env["GIT_SSH_COMMAND"]
    assert captured["secret"].rstrip("\n") == "s3cret!"
    assert captured["start_new_session"] is True
    # Temp files cleaned up
    assert not Path(env["SSH_ASKPASS"]).exists()


def test_job_passphrase_roundtrip():
    job = Job(
        path="/repo",
        scheduled_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        requested_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        ssh_passphrase="hunter2",
    )
    restored = Job.from_dict(job.to_dict())
    assert restored.ssh_passphrase == "hunter2"


def test_execute_push_passes_passphrase(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path))
    from carpetbomber import daemon, store

    job = Job(
        path="/repo",
        scheduled_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        requested_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        ssh_passphrase="pw",
    )
    store.save_queue([job])
    mock_push = MagicMock(return_value=GitResult(ok=True, stdout="", stderr="", returncode=0))

    with patch.object(daemon, "_log"), patch.object(gitops, "git_push", mock_push):
        assert daemon.execute_push(job.id) is True

    mock_push.assert_called_once_with("/repo", ssh_passphrase="pw")
    assert store.load_queue() == []


def test_execute_push_failed_then_rerun(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path))
    from carpetbomber import daemon, store

    job = Job(
        path="/repo",
        scheduled_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        requested_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        status=JobStatus.FAILED,
        last_error="previous",
    )
    store.save_queue([job])

    # Mimic QueueScreen prepare step
    def prepare(current):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=TZ)
        for j in current:
            if j.id == job.id:
                j.status = JobStatus.PENDING
                j.last_error = None
                j.scheduled_at = now
                j.requested_at = now
        return current

    store.update_queue(prepare)

    with (
        patch.object(daemon, "_log"),
        patch.object(
            gitops,
            "git_push",
            return_value=GitResult(ok=True, stdout="", stderr="", returncode=0),
        ),
    ):
        assert daemon.execute_push(job.id) is True

    assert store.load_queue() == []


def test_execute_push_records_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path))
    from carpetbomber import daemon, store

    job = Job(
        path="/repo",
        scheduled_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
        requested_at=datetime(2026, 9, 24, 0, 0, tzinfo=TZ),
    )
    store.save_queue([job])

    with (
        patch.object(daemon, "_log"),
        patch.object(
            gitops,
            "git_push",
            return_value=GitResult(ok=False, stdout="", stderr="permission denied", returncode=1),
        ),
    ):
        assert daemon.execute_push(job.id) is False

    remaining = store.load_queue()
    assert len(remaining) == 1
    assert remaining[0].status == JobStatus.FAILED
    assert remaining[0].last_error == "permission denied"
