"""Debian changelog parsing library for ubuntu firmware packages."""

import os
import re
import sys
import textwrap
from pathlib import Path

import git
import requests
from debian.changelog import Changelog, format_date

from .git_files import GitFiles


class ChangelogError(Exception):
    """Raised when a changelog file cannot be read or parsed."""


def _commit_message(commit: git.Commit) -> str:
    """Return the commit message as a string."""
    raw = commit.message
    return raw.decode() if isinstance(raw, bytes) else raw


def _get_bug_title(bug: str) -> str:
    """Fetch bug title from Launchpad API."""
    url = f"https://api.launchpad.net/devel/bugs/{bug}"
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise ChangelogError(f"Failed to fetch bug {bug}: {e}") from e
    return str(r.json()["title"])


def _wrap_titles(titles: list[str], width: int = 96) -> list[str]:
    """Combine titles and wrap to width, preserving LP: # references."""
    escaped = [t.replace("LP: #", "LP###") for t in titles]
    lines = textwrap.wrap("#// ".join(escaped), width)
    return [line.replace("LP###", "LP: #").replace("#//", " //") for line in lines]


class PackageChangelog:
    """Represents a package's Debian changelog file at a given commit or worktree."""

    def __init__(self, path: Path, commit: str | None = None) -> None:
        """Initialize from a changelog file path.

        Raises ChangelogError if the file does not exist at the given commit.
        """
        self.path = path
        self.commit = commit
        self._repo = git.Repo()
        self._changelog: Changelog | None = None

        if not GitFiles(self.commit).exists(str(path)):
            raise ChangelogError(f"No such file: {path} (commit {self.commit})")

    @property
    def Changelog(self) -> Changelog:
        """Lazily parse and return the Debian changelog."""
        if self._changelog is None:
            content = GitFiles(self.commit).read(str(self.path))
            self._changelog = Changelog(content)
        return self._changelog

    def base_commit(self, upstream_version: str) -> str:
        """Return the git commit SHA that introduced the first changelog entry.

        Changelogs are newest-first, so the last matching line is the oldest entry.
        """
        rev = self.commit or "HEAD"

        try:
            output = self._repo.git.blame("-l", rev, "--", str(self.path))
        except git.GitCommandError as e:
            raise ChangelogError(str(e)) from e

        commit: str | None = None
        for line in output.splitlines():
            if "linux-firmware" in line and f" ({upstream_version}" in line:
                # Root commits in blame output are prefixed with ^
                commit = line.split()[0].lstrip("^")

        return commit or rev

    @property
    def release_commit(self) -> str:
        """Return the commit SHA that introduced the current changelog version.

        Raises ChangelogError if:
        - Version in blame doesn't match current changelog version
        - Brand new package with no previous release
        """
        try:
            output = self._repo.git.blame("-l", "-L", "1,1", self.commit or "HEAD", "--", str(self.path))
        except git.GitCommandError as e:
            raise ChangelogError(str(e)) from e

        if not output:
            raise ChangelogError(f"No previous release found for: {self.path}")

        version = str(self.Changelog.version)
        if f" ({version}) " not in output:
            raise ChangelogError(f"Previous release version mismatch (expected {version})")

        return str(output.lstrip("^").split()[0])

    def changes(self, paths: list[str], since: str | None = None) -> list[git.Commit]:
        """Return commits affecting paths since a revision (default: release_commit)."""
        rev_range = f"{since or self.release_commit}..{self.commit or 'HEAD'}"
        try:
            output = self._repo.git.log("--format=%H", rev_range, "--", *paths)
        except git.GitCommandError as e:
            raise ChangelogError(str(e)) from e

        if not output:
            return []

        return [self._repo.commit(sha) for sha in output.splitlines()]

    def _next_version(self, upstream_version: str, sru: bool = False) -> str:
        """Calculate next package version based on current version and upstream."""
        version = str(self.Changelog.version)
        is_meta = "-" not in version

        if version.startswith(upstream_version):
            if is_meta:
                if sru:
                    return f"{version}0.0"
                base = version.rsplit(".", 1)[0]
                upload = version.rsplit(".", 1)[1].removesuffix("ubuntu")
                return f"{base}.{int(upload) + 1}ubuntu"
            else:
                if sru:
                    return f"{version}.0"
                match = re.search(r"(\d+)$", version)
                if not match:
                    raise ChangelogError(f"Cannot parse version number from: {version}")
                upload = match.group(1)
                return f"{version[: -len(upload)]}{int(upload) + 1}"
        else:
            if is_meta:
                return f"{upstream_version}.1ubuntu"
            else:
                return f"{upstream_version}-0ubuntu1"

    @staticmethod
    def format_changes(commits: list[git.Commit]) -> list[str]:
        """Format commits into changelog entry lines."""
        groups: dict[str, list[git.Commit]] = {}
        for commit in commits:
            message = _commit_message(commit)
            lines = message.split("\n")

            if "Ignore: yes" in lines:
                continue

            refs: set[str] = set()
            for line in lines:
                if line.startswith("CVE-"):
                    refs.add(line)
                elif line.startswith("BugLink: "):
                    refs.add(line.split("/")[-1])
            if not refs:
                if lines[0].strip().startswith("UBUNTU:"):
                    refs.add("UBUNTU")
                else:
                    refs.add("UPSTREAM")

            key = " ".join(sorted(refs))
            groups.setdefault(key, []).append(commit)

        result: list[str] = []
        for key, grouped_commits in groups.items():
            titles: list[str] = []
            for ref in key.split():
                if ref == "UBUNTU":
                    title = "Miscellaneous Ubuntu changes"
                elif ref == "UPSTREAM":
                    title = "Miscellaneous upstream changes"
                elif ref.startswith("CVE-"):
                    title = ref
                else:
                    title = f"{_get_bug_title(ref)} (LP: #{ref})"
                titles.append(title)

            wrapped = _wrap_titles(titles)
            result.append(f"  * {wrapped[0]}")
            for line in wrapped[1:]:
                result.append(f"    {line}")

            for commit in grouped_commits:
                subject = _commit_message(commit).split("\n")[0].strip().removeprefix("UBUNTU:").strip()
                result.append(f"    - {subject}")

        return result

    def update(
        self,
        upstream_version: str,
        paths: list[str],
        series: str | None = None,
        sru: bool = False,
        rebuild: bool = False,
    ) -> bool:
        """Update the changelog file with a new entry.

        Returns False if no changes and rebuild=False, True otherwise.
        Raises ChangelogError if no release_commit (initial release).
        """
        if sru:
            changes = ["  * Initial dummy SRU version"]
        else:
            commits = self.changes(paths)
            commits.reverse()
            changes = self.format_changes(commits)
            if not changes:
                if rebuild:
                    changes = ["  * No-change rebuild"]
                else:
                    return False

        series = series or str(self.Changelog.distributions)
        new_version = self._next_version(upstream_version, sru)
        author = os.environ.get("DEBFULLNAME", "")
        email = os.environ.get("DEBEMAIL", "")

        self.Changelog.new_block(
            package=str(self.Changelog.package),
            version=new_version,
            distributions=series,
            urgency=str(self.Changelog.urgency),
            author=f"{author} <{email}>",
            date=format_date(localtime=True),
        )
        self.Changelog.add_change("")
        for change in changes:
            self.Changelog.add_change(change)
        self.Changelog.add_change("")

        # Remove the previous entry if it's a dummy SRU entry
        if str(self.Changelog[1].version).endswith(".0"):
            print("WW: Replace dummy SRU version entry", file=sys.stderr)
            self.Changelog._blocks.pop(1)

        with open(self.path, "w", encoding="utf-8") as f:
            self.Changelog.write_to_open_file(f)

        return True
