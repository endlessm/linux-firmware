"""Shared pytest fixtures for ubuntu/lib tests."""

import os
from collections.abc import Generator
from pathlib import Path

import git
import pytest


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[git.Repo, Path]]:
    """Create a temporary git repo and chdir into it."""
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test")
        cw.set_value("user", "email", "test@test.com")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    yield repo, tmp_path

    os.chdir(old_cwd)


def commit_file(repo: git.Repo, rel_path: str, content: str, message: str = "commit") -> str:
    """Write a file, stage it, and commit. Returns the commit SHA.

    rel_path should be relative to the repo root.
    """
    path = Path(repo.working_dir) / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    repo.index.add([rel_path])
    commit = repo.index.commit(message)
    return commit.hexsha


def commit_files(repo: git.Repo, files: dict[str, str], message: str = "commit") -> str:
    """Write multiple files, stage them, and commit. Returns the commit SHA.

    Keys should be paths relative to the repo root.
    """
    for rel_path, content in files.items():
        path = Path(repo.working_dir) / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        repo.index.add([rel_path])
    commit = repo.index.commit(message)
    return commit.hexsha


def commit_binary(repo: git.Repo, rel_path: str, content: bytes, message: str = "commit") -> str:
    """Write a binary file, stage it, and commit. Returns the commit SHA.

    rel_path should be relative to the repo root.
    """
    path = Path(repo.working_dir) / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    repo.index.add([rel_path])
    commit = repo.index.commit(message)
    return commit.hexsha


def commit_symlink(repo: git.Repo, rel_path: str, target: str, message: str = "commit") -> str:
    """Create a symlink, stage it, and commit. Returns the commit SHA.

    rel_path should be relative to the repo root.
    """
    path = Path(repo.working_dir) / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
    repo.index.add([rel_path])
    commit = repo.index.commit(message)
    return commit.hexsha
