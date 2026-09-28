from __future__ import annotations

from carpetbomber import app, gitops


def test_apply_add_job_resolves_this_to_current_directory(tmp_path, monkeypatch):
    current_dir = tmp_path / "working"
    repo_root = tmp_path / "repository"
    current_dir.mkdir()
    repo_root.mkdir()
    monkeypatch.chdir(current_dir)
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path / "config"))

    paths: list[str] = []

    def resolve_repo_path(path):
        paths.append(str(path))
        return repo_root

    monkeypatch.setattr(gitops, "resolve_repo_path", resolve_repo_path)
    monkeypatch.setattr(gitops, "requires_ssh_auth", lambda _path: False)

    result = app.apply_add_job(" this ", "2030-01-01", "12:00")

    assert not isinstance(result, str)
    job, _requested = result
    assert paths == [str(current_dir)]
    assert job.path == str(repo_root)


def test_apply_add_job_keeps_regular_path_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("CARPETBOMBER_CONFIG_DIR", str(tmp_path / "config"))
    paths: list[str] = []
    repo_root = tmp_path / "repository"

    def resolve_repo_path(path):
        paths.append(str(path))
        return repo_root

    monkeypatch.setattr(gitops, "resolve_repo_path", resolve_repo_path)
    monkeypatch.setattr(gitops, "requires_ssh_auth", lambda _path: False)

    result = app.apply_add_job(" /some/repo ", "2030-01-01", "12:00")

    assert not isinstance(result, str)
    assert paths == ["/some/repo"]


def test_apply_add_job_this_requires_current_directory_to_be_a_repo(tmp_path, monkeypatch):
    current_dir = tmp_path / "working"
    current_dir.mkdir()
    monkeypatch.chdir(current_dir)
    monkeypatch.setattr(gitops, "resolve_repo_path", lambda _path: None)

    assert app.apply_add_job("this", "2030-01-01", "12:00") == "Not a git repository"
