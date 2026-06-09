"""WHENCE file parsing and resolution for firmware packages."""

import io
import os
from collections.abc import Iterator
from pathlib import Path
from typing import IO

from .git_files import GitFiles


class WhenceError(Exception):
    """Raised when a WHENCE file cannot be parsed or read."""


def parse_sections(fh: IO[str]) -> list[list[str]]:
    """Parse a WHENCE file handle into a list of sections.

    Each section is a list of stripped lines. Sections are delimited by lines
    starting with '--------'. File, RawFile, Source, and Link values have backslash-space
    unescaped and quotes stripped, matching generate-whence behaviour.
    """
    sections: list[list[str]] = []
    section: list[str] = []
    for line in fh:
        if line.startswith("--------"):
            if section:
                sections.append(section)
                section = []
        else:
            if line.split(":")[0] in ("File", "RawFile", "Link", "Source"):
                line = line.replace(r"\ ", " ").replace("'", "").replace('"', "")
            section.append(line.rstrip())
    if section:
        sections.append(section)
    return sections


def section_paths(section: list[str]) -> Iterator[str]:
    """Yield resolved file paths from a WHENCE section."""
    for line in section:
        if line.startswith(("File:", "RawFile:", "Source:")):
            yield line.split(":", 1)[1].strip()
        elif line.startswith("Link:"):
            link, _, target = line.split(":", 1)[1].partition(" -> ")
            yield os.path.normpath(os.path.join(os.path.dirname(link.strip()), target.strip()))


def section_file_licenses(section: list[str], tree_files: set[str]) -> Iterator[tuple[str, str | None]]:
    """Yield (file_path, license_path|None) pairs from a WHENCE section.

    Iterates lines accumulating File/RawFile/Source paths. When a Licence/License
    line is encountered, associates accumulated files with extracted license paths.
    Resets the accumulator when a new File/RawFile/Source line appears after a
    licence line. Link lines are ignored. Files with no licence yield (path, None).
    """
    accumulator: list[str] = []
    licence_seen = False

    for line in section:
        if line.startswith(("File:", "RawFile:", "Source:")):
            if licence_seen:
                accumulator = []
                licence_seen = False
            accumulator.append(line.split(":", 1)[1].strip())
        elif line.startswith(("Licence:", "License:")):
            tokens = set(token.rstrip(".,;)") for token in line.split(":", 1)[1].split())
            license_paths = sorted(tokens & tree_files)
            for f in accumulator:
                for lic in license_paths:
                    yield (f, lic)
            licence_seen = True

    if not licence_seen:
        for f in accumulator:
            yield (f, None)


class Whence:
    """Reads and parses WHENCE file(s) matching a path pattern from a commit or worktree."""

    def __init__(self, path: Path | str, commit: str | None = None) -> None:
        self.path = Path(path) if isinstance(path, str) else path
        self.commit = commit
        self._sections: list[list[str]] | None = None

    @property
    def sections(self) -> list[list[str]]:
        """Lazily parse WHENCE file(s) matching self.path.

        Raises WhenceError if no files match or reading fails.
        """
        if self._sections is None:
            whence_paths = GitFiles(self.commit, [str(self.path)], strict=False).paths()
            if not whence_paths:
                raise WhenceError(f"No WHENCE files found matching: {self.path}")

            all_sections: list[list[str]] = []
            for whence_path in whence_paths:
                content = GitFiles(self.commit).read(whence_path)
                all_sections.extend(parse_sections(io.StringIO(content)))

            self._sections = all_sections
        return self._sections

    @property
    def files(self) -> GitFiles:
        """Return a GitFiles with pathspecs extracted from File/RawFile/Source/Link lines."""
        whence_paths = [p for section in self.sections for p in section_paths(section)]
        return GitFiles(self.commit, whence_paths)

    def licenses(self, files: list[str] | set[str] | None = None) -> GitFiles:
        """Return a GitFiles with license file paths referenced in Licence:/License: lines.

        If files is provided, returns only licenses that apply to those files.
        If files is None, returns all licenses referenced in WHENCE.
        """
        tree_files = set(GitFiles(self.commit).paths())
        file_set = set(files) if files is not None else None
        result: set[str] = set()
        for section in self.sections:
            for file_path, lic in section_file_licenses(section, tree_files):
                if lic is not None:
                    if file_set is None or file_path in file_set:
                        result.add(lic)

        # Remove common licenses, we don't want them in the packages
        result = result - set(["Apache-2", "GPL-2", "GPL-3"])

        return GitFiles(self.commit, sorted(result))
