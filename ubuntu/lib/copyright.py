"""DEP-5 copyright file parsing for firmware packages."""

from fnmatch import fnmatch
from pathlib import Path

from debian.copyright import Copyright

from .git_files import GitFiles, GitFilesError


class CopyrightError(Exception):
    """Raised when a copyright file cannot be parsed or read."""


class PackageCopyright:
    """Reads and parses a DEP-5 copyright file from a commit or worktree.

    Lazily loads and parses the file on first access, using git-aware reading
    to support both worktree and committed file states.
    """

    def __init__(self, path: Path, commit: str | None = None) -> None:
        """Initialize from a copyright file path.

        Raises CopyrightError if the file does not exist at the given commit.
        """
        self.path = path
        self.commit = commit
        self._copyright: Copyright | None = None

        if not GitFiles(self.commit).exists(str(path)):
            raise CopyrightError(f"No such file: {path} (commit {self.commit})")

    @property
    def copyright(self) -> Copyright:
        """Lazily parse and return the DEP-5 copyright object."""
        if self._copyright is None:
            try:
                content = GitFiles(self.commit).read(str(self.path))
            except GitFilesError as e:
                raise CopyrightError(str(e)) from e
            self._copyright = Copyright(content.splitlines(True))
        return self._copyright

    def file_licenses(self, files: list[str]) -> list[tuple[str, str]]:
        """Return (file, license_synopsis) for each file matching a Files: stanza.

        Uses DEP-5 last-match-wins semantics via find_files_paragraph().
        Files not matching any stanza are silently omitted from the result.
        """
        result = []
        for f in files:
            para = self.copyright.find_files_paragraph(f)
            if para is not None:
                result.append((f, para.license.synopsis))  # type: ignore[attr-defined]
        return result

    def has_debian_stanza(self) -> bool:
        """Return True if a Files: debian/* stanza is present."""
        for para in self.copyright.all_files_paragraphs():
            if "debian/*" in para.files:
                return True
        return False

    def unmatched_patterns(self, files: list[str]) -> list[str]:
        """Return Files: glob patterns that don't match any of the given files.

        Ignores patterns starting with debian/ (the debian/* stanza is expected
        to never match firmware paths and is validated separately).
        """
        unmatched = []
        for para in self.copyright.all_files_paragraphs():
            for pattern in para.files:
                if pattern.startswith("debian/"):
                    continue
                if not any(fnmatch(f, pattern) for f in files):
                    unmatched.append(pattern)
        return unmatched

    def unresolved_licenses(self) -> list[str]:
        """Return license synopses referenced in Files: stanzas but not defined.

        A license is unresolved if a Files: paragraph references it (with no
        inline text) and no standalone License: paragraph provides the text.
        """
        standalone = {
            para.license.synopsis  # type: ignore[attr-defined]
            for para in self.copyright.all_license_paragraphs()
        }
        unresolved = []
        for para in self.copyright.all_files_paragraphs():
            synopsis = para.license.synopsis  # type: ignore[attr-defined]
            if not para.license.text and synopsis not in standalone:  # type: ignore[attr-defined]
                if synopsis not in unresolved:
                    unresolved.append(synopsis)
        return unresolved

    def orphaned_licenses(self) -> list[str]:
        """Return standalone License: paragraphs not referenced by any Files: stanza."""
        referenced = {
            para.license.synopsis  # type: ignore[attr-defined]
            for para in self.copyright.all_files_paragraphs()
        }
        orphaned = []
        for para in self.copyright.all_license_paragraphs():
            if para.license.synopsis not in referenced:  # type: ignore[attr-defined]
                orphaned.append(para.license.synopsis)  # type: ignore[attr-defined]
        return orphaned
