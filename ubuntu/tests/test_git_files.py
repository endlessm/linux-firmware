"""Tests for lib/git_files.py."""

from pathlib import Path

import git
import pytest

from lib.git_files import (
    GitFiles,
    GitFilesError,
    PathSpecs,
    _split_pathspecs,
)

from .conftest import commit_binary, commit_file, commit_files, commit_symlink


class TestSplitPathspecs:
    """Tests for _split_pathspecs helper."""

    def test_empty(self) -> None:
        """Empty input returns two empty lists."""
        assert _split_pathspecs([]) == ([], [])

    def test_only_included(self) -> None:
        """Entries without ! prefix are included."""
        assert _split_pathspecs(["foo/*", "bar.bin"]) == (["foo/*", "bar.bin"], [])

    def test_only_excluded(self) -> None:
        """Entries with ! prefix are excluded (prefix stripped)."""
        assert _split_pathspecs(["!foo/skip.bin", "!bar/*"]) == ([], ["foo/skip.bin", "bar/*"])

    def test_mixed(self) -> None:
        """Both included and excluded entries are separated."""
        specs = ["amd/*.bin", "!amd/excluded.bin", "intel/*"]
        included, excluded = _split_pathspecs(specs)
        assert included == ["amd/*.bin", "intel/*"]
        assert excluded == ["amd/excluded.bin"]


class TestPathSpecsMatchFiles:
    """Tests for PathSpecs.match_files method."""

    def test_include_only(self) -> None:
        """Filters to only paths matching include globs."""
        paths = ["a.bin", "b.txt", "c.bin"]
        assert PathSpecs(["*.bin"]).match_files(paths) == ["a.bin", "c.bin"]

    def test_include_and_exclude(self) -> None:
        """Excludes paths matching ! globs from included set."""
        paths = ["amd/a.bin", "amd/b.bin", "amd/skip.bin"]
        specs = ["amd/*.bin", "!amd/skip.bin"]
        assert PathSpecs(specs).match_files(paths) == ["amd/a.bin", "amd/b.bin"]

    def test_no_pathspecs(self) -> None:
        """No pathspecs returns empty (nothing included)."""
        assert PathSpecs([]).match_files(["a.bin", "b.bin"]) == []

    def test_unmatched_include_raises(self) -> None:
        """Include pattern matching nothing raises GitFilesError."""
        with pytest.raises(GitFilesError, match="Invalid include pathspec"):
            PathSpecs(["*.bin"]).match_files(["a.txt"])

    def test_unmatched_exclude_raises(self) -> None:
        """Exclude pattern matching nothing in included set raises GitFilesError."""
        paths = ["a.bin", "b.bin"]
        with pytest.raises(GitFilesError, match="Invalid exclude pathspec"):
            PathSpecs(["*.bin", "!nonexistent.bin"]).match_files(paths)

    def test_directory_pattern_anchored_to_root(self) -> None:
        """Trailing-slash pattern matches only at the root, not nested occurrences."""
        paths = ["foo/a.bin", "bar/foo/b.bin"]
        assert PathSpecs(["foo/"]).match_files(paths) == ["foo/a.bin"]


class TestGitFilesError:
    """Tests for GitFilesError exception."""

    def test_message(self) -> None:
        """str(err) returns the message."""
        err = GitFilesError("git failed")
        assert str(err) == "git failed"


class TestGitFilesPathspecs:
    """Tests for GitFiles.pathspecs method."""

    def test_all(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns all pathspecs when opt is None."""
        repo, _ = git_repo
        commit_file(repo, "dummy", "placeholder")

        gf = GitFiles(None, ["foo/*.bin", "!foo/skip.bin", "bar.txt"])
        assert gf.pathspecs() == ["foo/*.bin", "!foo/skip.bin", "bar.txt"]

    def test_included(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns only non-excluded pathspecs."""
        repo, _ = git_repo
        commit_file(repo, "dummy", "placeholder")

        gf = GitFiles(None, ["foo/*.bin", "!foo/skip.bin", "bar.txt"])
        assert gf.pathspecs("included") == ["foo/*.bin", "bar.txt"]

    def test_excluded(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns only excluded pathspecs with prefix stripped."""
        repo, _ = git_repo
        commit_file(repo, "dummy", "placeholder")

        gf = GitFiles(None, ["foo/*.bin", "!foo/skip.bin", "!baz/*"])
        assert gf.pathspecs("excluded") == ["foo/skip.bin", "baz/*"]


class TestGitFilesPaths:
    """Tests for GitFiles.paths method."""

    def test_expands_globs(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Pathspecs expand to matching files in the git tree."""
        repo, _ = git_repo
        commit_files(
            repo,
            {
                "amd/a.bin": "binary a",
                "amd/b.bin": "binary b",
                "amd/skip.bin": "excluded",
                "intel/c.bin": "other",
            },
        )

        gf = GitFiles(None, ["amd/*.bin", "!amd/skip.bin"])
        paths = gf.paths()
        assert "amd/a.bin" in paths
        assert "amd/b.bin" in paths
        assert "amd/skip.bin" not in paths
        assert "intel/c.bin" not in paths

    def test_unmatched_raises(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Pathspecs not matching any files raise GitFilesError."""
        repo, _ = git_repo
        commit_file(repo, "unrelated.txt", "text")

        gf = GitFiles(None, ["nonexistent/*.bin"])
        with pytest.raises(GitFilesError, match="Invalid include pathspec"):
            gf.paths()

    def test_exact_path(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Exact file path works as a pathspec."""
        repo, _ = git_repo
        commit_file(repo, "firmware/iwlwifi.ucode", "fw data")

        gf = GitFiles(None, ["firmware/iwlwifi.ucode"])
        assert gf.paths() == ["firmware/iwlwifi.ucode"]

    def test_included_opt(self, git_repo: tuple[git.Repo, Path]) -> None:
        """opt='included' ignores exclusions."""
        repo, _ = git_repo
        commit_files(
            repo,
            {
                "amd/a.bin": "a",
                "amd/skip.bin": "skip",
            },
        )

        gf = GitFiles(None, ["amd/*.bin", "!amd/skip.bin"])
        paths = gf.paths("included")
        assert "amd/a.bin" in paths
        assert "amd/skip.bin" in paths

    def test_excluded_opt(self, git_repo: tuple[git.Repo, Path]) -> None:
        """opt='excluded' returns only files matching exclusion patterns."""
        repo, _ = git_repo
        commit_files(
            repo,
            {
                "amd/a.bin": "a",
                "amd/skip.bin": "skip",
            },
        )

        gf = GitFiles(None, ["amd/*.bin", "!amd/skip.bin"])
        paths = gf.paths("excluded")
        assert paths == ["amd/skip.bin"]


class TestGitFilesTree:
    """Tests for GitFiles.tree method."""

    def test_returns_tuples(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns (mode, sha1, path) tuples."""
        repo, _ = git_repo
        commit_file(repo, "foo.txt", "content")

        gf = GitFiles("HEAD", ["foo.txt"])
        tree = gf.tree()
        assert len(tree) == 1
        mode, sha1, path = tree[0]
        assert mode == "100644"
        assert len(sha1) == 40
        assert path == "foo.txt"

    def test_multiple_files(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns entries for all matched files."""
        repo, _ = git_repo
        commit_files(
            repo,
            {
                "a.bin": "aaa",
                "b.bin": "bbb",
            },
        )

        gf = GitFiles("HEAD", ["*.bin"])
        tree = gf.tree()
        paths = [p for _, _, p in tree]
        assert "a.bin" in paths
        assert "b.bin" in paths


class TestGitFilesEntries:
    """Tests for GitFiles.entries method."""

    def test_detects_text(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Text file is detected as type='text'."""
        repo, _ = git_repo
        commit_file(repo, "readme.txt", "hello world")

        gf = GitFiles("HEAD", ["readme.txt"])
        entries = gf.entries()
        assert len(entries) == 1
        _, file_type, _, path = entries[0]
        assert file_type == "text"
        assert path == "readme.txt"

    def test_detects_binary(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Binary file is detected as type='binary'."""
        repo, _ = git_repo
        commit_binary(repo, "firmware.bin", b"\x00\x01\x02\xff")

        gf = GitFiles("HEAD", ["firmware.bin"])
        entries = gf.entries()
        assert len(entries) == 1
        _, file_type, _, path = entries[0]
        assert file_type == "binary"
        assert path == "firmware.bin"

    def test_detects_link(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Symlink is detected as type='link'."""
        repo, _ = git_repo
        commit_file(repo, "target.txt", "target content")
        commit_symlink(repo, "link.txt", "target.txt")

        gf = GitFiles("HEAD", ["link.txt", "target.txt"])
        entries = gf.entries()
        types = {path: ftype for _, ftype, _, path in entries}
        assert types["link.txt"] == "link"
        assert types["target.txt"] == "text"

    def test_mixed_types(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Multiple file types are correctly classified."""
        repo, _ = git_repo
        commit_file(repo, "doc.txt", "documentation")
        commit_binary(repo, "fw.bin", b"\x00\x01\x02\x03")
        commit_symlink(repo, "fw_link.bin", "fw.bin")

        gf = GitFiles("HEAD", ["doc.txt", "fw.bin", "fw_link.bin"])
        entries = gf.entries()
        types = {path: ftype for _, ftype, _, path in entries}
        assert types["doc.txt"] == "text"
        assert types["fw.bin"] == "binary"
        assert types["fw_link.bin"] == "link"
