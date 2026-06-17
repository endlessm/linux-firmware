"""Package management for ubuntu firmware packages."""

import os
import sys
import tarfile
from functools import cached_property
from pathlib import Path

import git

from .changelog import PackageChangelog
from .copyright import PackageCopyright
from .git_files import EMPTY_TREE, GitFiles
from .whence import Whence, section_paths


class PackageError(Exception):
    """Raised when a package operation fails."""

    def __init__(self, message: str, files: list[str] | None = None) -> None:
        super().__init__(message)
        self.files: list[str] = files or []


def read_upstream(commit: str | None = None) -> tuple[str, str]:
    """Read ubuntu/upstream and return (upstream_commit, version).

    Raises PackageError if the file is missing or malformed.
    """
    content = GitFiles(commit).read("ubuntu/upstream")

    upstream_commit: str | None = None
    upstream_version: str | None = None
    for line in content.splitlines():
        if line.startswith("COMMIT="):
            upstream_commit = line.split("=", 1)[1]
        elif line.startswith("VERSION="):
            upstream_version = line.split("=", 1)[1]

    if upstream_commit is None:
        raise PackageError(f"COMMIT not found in ubuntu/upstream (commit {commit})")
    if upstream_version is None:
        raise PackageError(f"VERSION not found in ubuntu/upstream (commit {commit})")

    return (upstream_commit, upstream_version)


class PackageFiles(GitFiles):
    """GitFiles subclass that reads pathspecs from a git-tracked file list."""

    def __init__(self, path: Path, commit: str | None = None) -> None:
        """Load pathspecs from a file at the given commit."""
        content = GitFiles(commit).read(str(path))
        parsed_specs = [line for line in content.splitlines() if line and not line.startswith("#")]
        super().__init__(commit, parsed_specs)


def _section_matches(section: list[str], package_files: set[str]) -> bool:
    """Return True if any file/link in section is in package_files."""
    return any(p in package_files for p in section_paths(section))


class PackageWhence(Whence):
    """A package-specific WHENCE file with update capability."""

    def update(self, files: PackageFiles, whence: Whence) -> None:
        """Regenerate this WHENCE from global Whence, filtered to package files.

        Writes directly to self.path on disk.
        """
        sections = whence.sections
        if not sections:
            return

        package_files = set(files.paths())
        separator = "-" * 78
        matching = [s for s in sections[1:] if _section_matches(s, package_files)]
        content = "\n".join(sections[0]) + "\n"
        for section in matching:
            content += separator + "\n" + "\n".join(section) + "\n"
        content += separator + "\n"

        self.path.write_text(content, encoding="utf-8")


class PackageOrig:
    """Represents an Ubuntu firmware orig tarball and its file operations."""

    def __init__(self, name: str, commit: str | None = None) -> None:
        """Initialize orig tarball view from file lists at commit, resolved at upstream.

        Reads the file list and WHENCE at the given commit to determine what goes
        into the tarball, then resolves actual content at the upstream commit
        (from ubuntu/upstream).
        """
        self.name = name
        self.commit = commit
        self.source_name = f"linux-firmware-{self.name}"
        self.upstream_commit, self.upstream_version = read_upstream(self.commit)

        self.path = Path("ubuntu") / "package" / name
        self.files = PackageFiles(self.path / "files", self.commit)
        self.whence = PackageWhence(self.path / "WHENCE", self.commit)

        # Licenses extracted from WHENCE
        self.licenses = self.whence.licenses(self.files.paths())

        files = set(self.files.paths())
        licenses = set(self.licenses.paths())

        # FIXUP: The real orig tarballs were built using the old toolset and
        # are missing some license files. Sigh.
        if self.upstream_version == "20260319.git217ca6e4":
            if self.name == "qualcomm-misc":
                licenses.discard("LICENSE.qcom")

        # Old file lists included firmware, licenses and WHENCE but we only want
        # firmwares, so subtract the others.
        # Note: Use strict=False because paths at commit might not exist at upstream_commit
        self.firmwares = GitFiles(self.upstream_commit, sorted(files - licenses - {"WHENCE"}), strict=False)

        # Tarball content
        # Note: Use strict=False because paths at commit might not exist at upstream_commit
        self.content = GitFiles(self.upstream_commit, sorted(files | licenses | {"WHENCE"}), strict=False)


def _write_include_binaries(pkg_path: Path, binaries: list[str]) -> None:
    """Write source/include-binaries, or remove if empty."""
    source_dir = pkg_path / "source"
    include_binaries_path = source_dir / "include-binaries"

    if not binaries:
        if include_binaries_path.exists():
            include_binaries_path.unlink()
        if source_dir.exists() and not any(source_dir.iterdir()):
            source_dir.rmdir()
        return

    source_dir.mkdir(exist_ok=True)
    include_binaries_path.write_text("\n".join(binaries) + "\n", encoding="utf-8")


def _write_ubuntu_patch(pkg_path: Path, patch: str) -> None:
    """Write patches/ubuntu.patch and series, or remove if empty."""
    patches_dir = pkg_path / "patches"
    patch_path = patches_dir / "ubuntu.patch"
    series_path = patches_dir / "series"

    if not patch:
        for p in (patch_path, series_path):
            if p.exists():
                p.unlink()
        if patches_dir.exists() and not any(patches_dir.iterdir()):
            patches_dir.rmdir()
        return

    patches_dir.mkdir(exist_ok=True)
    patch_path.write_text(patch + "\n", encoding="utf-8", errors="surrogateescape")
    series_path.write_text("ubuntu.patch\n", encoding="utf-8")


class Package:
    """Represents an Ubuntu firmware package and its file operations."""

    def __init__(self, name: str, commit: str | None = None) -> None:
        """Initialize package by name, loading its components at the given commit."""
        self.name = name
        self.commit = commit
        self.source_name = f"linux-firmware-{self.name}"
        self.upstream_commit, self.upstream_version = read_upstream(self.commit)
        self._repo = git.Repo()
        self.is_native = name == "meta"

        if self.is_native:
            self.path = Path("ubuntu") / "package" / "meta"
            self.changelog = PackageChangelog(self.path / "changelog", self.commit)
        else:
            self.path = Path("ubuntu") / "package" / name
            self.files = PackageFiles(self.path / "files", self.commit)
            self.changelog = PackageChangelog(self.path / "changelog", self.commit)
            self.whence = PackageWhence(self.path / "WHENCE", self.commit)

            # Licenses extracted from WHENCE
            self.licenses = self.whence.licenses(self.files.paths())

            files = set(self.files.paths())
            licenses = set(self.licenses.paths())

            # Firmware files only. Old file lists also include licenses and WHENCE;
            # Subtract them.
            self.firmwares = GitFiles(self.commit, sorted(files - licenses - {"WHENCE"}))

            # Package content. WHENCE is deliberately excluded since its changes are
            # across all packages and would produce a noisy ubuntu.patch that adds
            # no real benefit.
            self.content = GitFiles(self.commit, sorted((files | licenses) - {"WHENCE"}))

            copyright_path = self.path / "copyright"
            if GitFiles(self.commit).exists(str(copyright_path)):
                self.copyright: PackageCopyright | None = PackageCopyright(copyright_path, self.commit)
            else:
                self.copyright = None

    @property
    def tracked_paths(self) -> list[str]:
        """Pathspecs tracked for changelog purposes (file globs + common dirs)."""
        if self.is_native:
            return [str(self.path) + "/"]
        return self.files.pathspecs() + [
            "ubuntu/debian/",
            str(self.path) + "/",
            "ubuntu/templates/",
            "ubuntu/upstream",
        ]

    @cached_property
    def orig(self) -> PackageOrig:
        """Return PackageOrig using the file list from the base commit."""
        return PackageOrig(self.name, self.changelog.base_commit(self.upstream_version))

    def update_delta(self) -> None:
        """Update patches/ubuntu.patch and source/include-binaries.

        Compares file entries between upstream and the current commit for the
        current file set (firmware + licenses). Generates patches for changed
        text files and updates the binary inclusion list.
        """
        orig_entries = self.orig.content.entries()
        orig_paths = self.orig.content.paths()

        current_entries = self.content.entries()
        changed_entries = set(current_entries) - set(orig_entries)

        binary_files: list[str] = []
        text_files: list[tuple[str, str]] = []

        for _, file_type, _, file_path in changed_entries:
            if file_type in ("binary", "link"):
                binary_files.append(file_path)
            if file_type in ("text", "link"):
                if file_path in orig_paths:
                    text_files.append((self.upstream_commit, file_path))
                else:
                    text_files.append((EMPTY_TREE, file_path))

        patch = ""
        if text_files:
            text_files = sorted(text_files, key=lambda x: x[1])
            patches = [self._repo.git.diff(c, self.commit, "--", p) for c, p in text_files]
            patch = "\n".join(patches)

        _write_include_binaries(self.path, sorted(binary_files))
        _write_ubuntu_patch(self.path, patch)

    def check_excluded_subset(self) -> None:
        """Check that excluded files are a subset of included files.

        Raises PackageError with a list of offending files on failure.
        """
        included = set(self.files.paths("included"))
        excluded = set(self.files.paths("excluded"))

        print("II: Check that excluded files are a subset of included files")
        not_in_included = sorted(excluded - included)
        if not_in_included:
            raise PackageError(
                "Excluded files are not a subset of included files",
                files=not_in_included,
            )

    def check_packaged_files(self) -> None:
        """Check that packaged files == included files - excluded files.

        Raises PackageError with a list of offending files on failure.
        """
        included = set(self.files.paths("included"))
        excluded = set(self.files.paths("excluded"))
        packaged = set(self.files.paths())

        print("II: Check that packaged files == included files - excluded files")
        expected = set(included - excluded)
        if packaged != expected:
            offending = sorted(packaged ^ expected)
            raise PackageError(
                "Packaged files do not equal included minus excluded files",
                files=offending,
            )

    def check_whence_coverage(self) -> None:
        """Check that all packaged files are referenced in WHENCE.

        Raises PackageError with a list of unreferenced files on failure.
        """
        packaged = set(self.files.paths())

        print("II: Check WHENCE coverage")
        whence_files = set(self.whence.files.paths())
        unreferenced = list(packaged - whence_files)
        if unreferenced:
            whence_dirs = [p for p in whence_files if p.endswith("/")]
            unreferenced = [f for f in unreferenced if not any(f.startswith(d) for d in whence_dirs)]
            if unreferenced:
                raise PackageError(
                    "Packaged files not referenced in WHENCE",
                    files=unreferenced,
                )

    def check_copyright_coverage(self) -> None:
        """Check that all firmware files are covered in the copyright file.

        Verifies:
        1. A Files: debian/* stanza is present.
        2. All firmware files (current + orig) are matched by a Files: stanza.
        3. No Files: patterns (other than debian/*) are dead (match nothing).
        4. All license references are resolved (have text defined).
        5. No orphaned standalone License: paragraphs exist.

        Raises PackageError on failure.
        """
        if self.copyright is None:
            raise PackageError("Missing copyright file")

        # All firmware files needing copyright coverage
        firmwares = sorted(set(self.firmwares.paths()) | set(self.orig.firmwares.paths()))

        print("II: Check copyright coverage")
        if not self.copyright.has_debian_stanza():
            raise PackageError("Missing Files: debian/* stanza in copyright")

        covered = {f for f, _ in self.copyright.file_licenses(firmwares)}
        uncovered = sorted(set(firmwares) - covered)
        if uncovered:
            raise PackageError(
                "Firmware files not covered in copyright",
                files=uncovered,
            )

        unmatched = self.copyright.unmatched_patterns(firmwares)
        if unmatched:
            raise PackageError(
                "Copyright patterns match no firmware files",
                files=unmatched,
            )

        unresolved = self.copyright.unresolved_licenses()
        if unresolved:
            raise PackageError(
                "Unresolved license references in copyright",
                files=unresolved,
            )

        orphaned = self.copyright.orphaned_licenses()
        if orphaned:
            raise PackageError(
                "Orphaned license paragraphs in copyright",
                files=orphaned,
            )

    def check_orig_tarball(self) -> None:
        """Check that the orig tarball content matches expectations.

        Raises PackageError if the tarball exists but its content doesn't
        match the expected orig files.  Prints a warning if the tarball
        is not found.
        """
        print("II: Check orig tarball content")
        orig_tarball = f"../{self.source_name}_{self.upstream_version}.orig.tar.xz"
        if os.path.exists(orig_tarball):
            with tarfile.open(orig_tarball, "r:xz") as tar:
                orig_tarball_files = [m.name for m in tar.getmembers() if m.isfile() and "/" in m.name]
            real_orig = set()
            for f in orig_tarball_files:
                real_orig.add(f.split("/", 1)[1])
            orig = set(self.orig.content.paths())
            if orig != real_orig:
                offending = sorted(orig ^ real_orig)
                raise PackageError(
                    "Orig tarball content error",
                    files=offending,
                )
        else:
            print(f"WW: Orig tarball not found: {orig_tarball}", file=sys.stderr)

    def check(self) -> None:
        """Run all sanity checks on the package.

        Raises PackageError with a message and list of offending files on failure.
        Does nothing for the meta package.
        """
        if self.is_native:
            return

        self.check_excluded_subset()
        self.check_packaged_files()
        self.check_whence_coverage()
        self.check_copyright_coverage()
        self.check_orig_tarball()
