"""Tests for lib/package.py."""

from pathlib import Path

import git
import pytest

from lib.package import (
    Package,
    PackageError,
    PackageFiles,
    PackageWhence,
    _section_matches,
)
from lib.whence import Whence

from .conftest import commit_file, commit_files


class TestPackageError:
    """Tests for PackageError exception."""

    def test_message(self) -> None:
        """str(err) returns the message."""
        err = PackageError("something failed")
        assert str(err) == "something failed"

    def test_files_attribute(self) -> None:
        """err.files returns the file list."""
        err = PackageError("missing files", files=["a.bin", "b.bin"])
        assert err.files == ["a.bin", "b.bin"]

    def test_files_default_empty(self) -> None:
        """err.files defaults to empty list."""
        err = PackageError("no files")
        assert err.files == []


class TestPackageFilesPathspecs:
    """Tests for PackageFiles.pathspecs method."""

    def test_all(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns all non-comment lines."""
        repo, _ = git_repo
        content = "# comment\nfoo/*.bin\n!foo/excluded.bin"
        commit_file(repo, "files", content)

        pf = PackageFiles(Path("files"))
        assert pf.pathspecs() == ["foo/*.bin", "!foo/excluded.bin"]


class TestPackageFilesPaths:
    """Tests for PackageFiles.paths method."""

    def test_empty_pathspecs(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Empty pathspecs returns empty list."""
        repo, _ = git_repo
        commit_file(repo, "files", "# only comments")

        pf = PackageFiles(Path("files"))
        assert pf.paths() == []


class TestPackageWhenceSectionMatches:
    """Tests for _section_matches function."""

    def test_file_match(self) -> None:
        """File: matches package_files."""
        section = ["File: foo.bin", "License: BSD"]
        assert _section_matches(section, {"foo.bin"}) is True

    def test_rawfile_match(self) -> None:
        """RawFile: matches package_files."""
        section = ["RawFile: bar.bin"]
        assert _section_matches(section, {"bar.bin"}) is True

    def test_link_resolution(self) -> None:
        """Link: target is resolved and matched."""
        section = ["Link: dir/link.bin -> ../target.bin"]
        assert _section_matches(section, {"target.bin"}) is True

    def test_no_match(self) -> None:
        """Returns False when no file matches."""
        section = ["File: other.bin"]
        assert _section_matches(section, {"foo.bin"}) is False


class TestPackageWhenceUpdate:
    """Tests for PackageWhence.update method."""

    def test_filters_sections(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Only matching sections are written."""
        repo, _ = git_repo
        global_whence = "Header\n----------\nFile: a.bin\n----------\nFile: b.bin"
        commit_files(
            repo,
            {
                "WHENCE": global_whence,
                "pkg/files": "a.bin",
                "a.bin": "binary a",
            },
        )

        whence = Whence(Path("WHENCE"))
        files = PackageFiles(Path("pkg/files"))
        pkg_whence_path = Path("pkg/WHENCE")
        pkg_whence_path.parent.mkdir(parents=True, exist_ok=True)
        pkg_whence = PackageWhence(pkg_whence_path)

        pkg_whence.update(files, whence)

        content = pkg_whence_path.read_text()
        assert "File: a.bin" in content
        assert "File: b.bin" not in content

    def test_writes_correct_format(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Header + separator + sections + trailing separator."""
        repo, _ = git_repo
        global_whence = "Header line\n----------\nFile: foo.bin"
        commit_files(
            repo,
            {
                "WHENCE": global_whence,
                "pkg/files": "foo.bin",
                "foo.bin": "binary foo",
            },
        )

        whence = Whence(Path("WHENCE"))
        files = PackageFiles(Path("pkg/files"))
        pkg_whence_path = Path("pkg/WHENCE")
        pkg_whence_path.parent.mkdir(parents=True, exist_ok=True)
        pkg_whence = PackageWhence(pkg_whence_path)

        pkg_whence.update(files, whence)

        content = pkg_whence_path.read_text()
        lines = content.split("\n")
        assert lines[0] == "Header line"
        assert lines[1].startswith("---")
        assert "File: foo.bin" in content
        assert content.rstrip().endswith("-" * 78)

    def test_empty_sections_noop(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Empty global sections does nothing."""
        repo, _ = git_repo
        commit_files(
            repo,
            {
                "dummy": "placeholder",
                "pkg/files": "foo.bin",
                "foo.bin": "binary foo",
            },
        )

        whence = Whence.__new__(Whence)
        whence._sections = []

        files = PackageFiles(Path("pkg/files"))
        pkg_whence_path = Path("pkg/WHENCE")
        pkg_whence_path.parent.mkdir(parents=True, exist_ok=True)
        pkg_whence = PackageWhence(pkg_whence_path)

        pkg_whence.update(files, whence)

        assert not pkg_whence_path.exists()


class TestPackage:
    """Tests for Package class."""

    def test_regular_package(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Regular package sets up paths and components."""
        repo, _ = git_repo

        commit_files(
            repo,
            {
                "ubuntu/package/test-pkg/files": "foo.bin",
                "ubuntu/package/test-pkg/WHENCE": "File: foo.bin\nLicence: See LICENCE.test for details",
                "ubuntu/package/test-pkg/changelog": (
                    "linux-firmware (1.0) noble; urgency=medium\n\n"
                    "  * Test\n\n"
                    " -- Test <t@t.com>  Mon, 01 Jan 2024 00:00:00 +0000\n"
                ),
                "ubuntu/package/test-pkg/copyright": (
                    "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
                    "Upstream-Name: linux-firmware\n\n"
                    "Files: debian/*\n"
                    "Copyright: 2026 Canonical Ltd.\n"
                    "License: GPL-2+\n\n"
                    "Files: *\n"
                    "Copyright: 2024, Test\n"
                    "License: Redistributable\n"
                ),
                "foo.bin": "binary",
                "LICENCE.test": "license text",
            },
        )

        pkg = Package("test-pkg")
        assert pkg.name == "test-pkg"
        assert pkg.is_meta is False
        assert pkg.path == Path("ubuntu/package/test-pkg")
        assert isinstance(pkg.files, PackageFiles)
        assert isinstance(pkg.whence, PackageWhence)

    def test_meta_package(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Meta package has is_meta=True and no file components."""
        repo, _ = git_repo

        commit_files(
            repo,
            {
                "ubuntu/package/meta/changelog": (
                    "linux-firmware (1.0) noble; urgency=medium\n\n"
                    "  * Test\n\n"
                    " -- Test <t@t.com>  Mon, 01 Jan 2024 00:00:00 +0000\n"
                ),
            },
        )

        pkg = Package("meta")
        assert pkg.name == "meta"
        assert pkg.is_meta is True
        assert not hasattr(pkg, "files")
        assert not hasattr(pkg, "whence")


class TestPackageTrackedPaths:
    """Tests for Package.tracked_paths property."""

    def test_meta_package(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Meta package returns only its directory."""
        repo, _ = git_repo

        commit_files(
            repo,
            {
                "ubuntu/package/meta/changelog": (
                    "linux-firmware (1.0) noble; urgency=medium\n\n"
                    "  * Test\n\n"
                    " -- Test <t@t.com>  Mon, 01 Jan 2024 00:00:00 +0000\n"
                ),
            },
        )

        pkg = Package("meta")
        assert pkg.tracked_paths == ["ubuntu/package/meta/"]

    def test_regular_package(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Regular package returns pathspecs + common dirs."""
        repo, _ = git_repo

        commit_files(
            repo,
            {
                "ubuntu/package/test-pkg/files": "amd/*.bin\nintel/*.bin\n!amd/excluded.bin",
                "ubuntu/package/test-pkg/WHENCE": "File: foo.bin",
                "ubuntu/package/test-pkg/changelog": (
                    "linux-firmware (1.0) noble; urgency=medium\n\n"
                    "  * Test\n\n"
                    " -- Test <t@t.com>  Mon, 01 Jan 2024 00:00:00 +0000\n"
                ),
                "ubuntu/package/test-pkg/copyright": (
                    "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
                    "Upstream-Name: linux-firmware\n\n"
                    "Files: debian/*\n"
                    "Copyright: 2026 Canonical Ltd.\n"
                    "License: GPL-2+\n\n"
                    "Files: *\n"
                    "Copyright: 2024, Test\n"
                    "License: Redistributable\n"
                ),
                "amd/test.bin": "binary",
                "amd/excluded.bin": "binary",
                "intel/test.bin": "binary",
            },
        )

        pkg = Package("test-pkg")
        paths = pkg.tracked_paths

        # Should include all pathspecs from files (including exclusions)
        assert "amd/*.bin" in paths
        assert "intel/*.bin" in paths
        assert "!amd/excluded.bin" in paths

        # Should include common dirs
        assert "ubuntu/debian/" in paths
        assert "ubuntu/package/test-pkg/" in paths
        assert "ubuntu/templates/" in paths
        assert "ubuntu/upstream" in paths


# --- Constants for TestPackageDeltaUpdate ---

_PKG = "ubuntu/package/test-pkg"

_CHANGELOG_V1 = (
    "linux-firmware-test-pkg (1.0-0ubuntu1) noble; urgency=medium\n\n"
    "  * Initial release\n\n"
    " -- Test <test@test.com>  Mon, 01 Jan 2024 00:00:00 +0000\n"
)


def _make_copyright(patterns: list[str], license_name: str = "Redistributable") -> str:
    """Generate a minimal DEP-5 copyright file covering the given glob patterns."""
    lines = [
        "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/",
        "Upstream-Name: linux-firmware",
        "Upstream-Contact: linux-firmware@kernel.org",
        "Source: https://git.kernel.org/pub/scm/linux/firmware/linux-firmware.git",
        "",
        "Files: debian/*",
        "Copyright: 2026 Canonical Ltd.",
        "License: GPL-2+",
        "",
    ]
    for pattern in patterns:
        lines.extend([
            f"Files: {pattern}",
            "Copyright: 2024, Test Corporation",
            f"License: {license_name}",
            "",
        ])
    # Add standalone License paragraphs to resolve references
    lines.extend([
        f"License: {license_name}",
        " Redistribution permitted.",
        "",
        "License: GPL-2+",
        " See /usr/share/common-licenses/GPL-2.",
        "",
    ])
    return "\n".join(lines)

_WHENCE_TEMPLATE = (
    "Header\n"
    "------------------------------------------------------------------------------\n"
    "{entries}\n"
    "------------------------------------------------------------------------------\n"
)


def _commit_mixed(
    repo: git.Repo,
    text: dict[str, str] | None = None,
    binary: dict[str, bytes] | None = None,
    symlinks: dict[str, str] | None = None,
    message: str = "commit",
) -> str:
    """Commit text, binary, and symlink files in a single commit. Returns SHA."""
    root = Path(repo.working_dir)
    all_paths: list[str] = []

    for path, content in (text or {}).items():
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        all_paths.append(path)

    for path, data in (binary or {}).items():
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        all_paths.append(path)

    for path, target in (symlinks or {}).items():
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        if full.exists() or full.is_symlink():
            full.unlink()
        full.symlink_to(target)
        all_paths.append(path)

    if all_paths:
        repo.index.add(all_paths)
    return repo.index.commit(message).hexsha


def _make_changelog_v2(v1_content: str) -> str:
    """Create a v2 changelog by prepending a new entry to v1."""
    v2_entry = (
        "linux-firmware-test-pkg (1.0-0ubuntu2) noble; urgency=medium\n\n"
        "  * Second release\n\n"
        " -- Test <test@test.com>  Tue, 02 Jan 2024 00:00:00 +0000\n\n"
    )
    return v2_entry + v1_content


def _make_whence(firmware_files: list[str], license_files: list[str]) -> str:
    """Generate a WHENCE file referencing firmware and license files."""
    lines = [f"File: {f}" for f in firmware_files]
    lines.extend(f"Licence: {f}" for f in license_files)
    return _WHENCE_TEMPLATE.format(entries="\n".join(lines))


class TestPackageDeltaUpdate:
    """Tests for Package.update_delta().

    update_delta() compares file entries between the orig tarball (at the
    upstream commit, using pathspecs from base_commit) and the current package
    (at self.commit). It produces:
      - patches/ubuntu.patch: unified diff for changed text and link files
      - source/include-binaries: list of changed binary and link files

    Test setup uses 3 commits:
      C0 (upstream): The upstream firmware state. Contains firmware files and
          WHENCE but no ubuntu/ packaging. This is what ends up in the orig
          tarball. Referenced by ubuntu/upstream COMMIT=<sha>.
      C1 (1st release): Adds ubuntu/ packaging on top of C0: files list,
          changelog (v1.0-0ubuntu1), package WHENCE, and ubuntu/upstream.
          May also modify firmware files. This commit becomes base_commit
          (via git blame on the changelog), so its files list determines
          which pathspecs are used for the orig tarball.
      C2 (2nd release): Further firmware changes plus a changelog bump to
          v1.0-0ubuntu2. This is the commit where update_delta() is called.
          The delta is always C0 vs C2 (not C1 vs C2).

    Truth table (C0, C1, C2):
      P = present in package (listed in files, exists in git)
      M = present in package, content modified from previous state
      A = absent from package (not in files list)

      C0=P (file exists at upstream):
        Row  1: P-P-P  no delta        test_no_delta_and_cleanup
        Row  2: P-P-M  patch/binary    test_modification_from_upstream
        Row  3: P-P-A  no delta        test_no_delta_and_cleanup
        Row  4: P-M-P  binary only     test_modification_from_upstream
        Row  5: P-M-M  patch/binary    test_modification_from_upstream
        Row  6: P-M-A  no delta        test_no_delta_and_cleanup
        Row  7: P-A-P  patch/binary    test_removed_then_readded
        Row  8: P-A-M  patch/binary    test_removed_then_readded
        Row  9: P-A-A  no delta        test_no_delta_and_cleanup

      C0=A (file absent from upstream):
        Row 10/13: A-{P,M}-P  patch/binary  test_addition_to_package
        Row 11/14: A-{P,M}-M  patch/binary  test_addition_to_package
        Row 12/15: A-{P,M}-A  no delta      test_no_delta_and_cleanup
        Row 16/17: A-A-{P,M}  patch/binary  test_addition_to_package
        Row 18:    A-A-A       invalid -- file never exists anywhere

      Rows 7-8 and 10-17: file is not in orig (C1's pathspecs exclude it),
      so the diff is generated against EMPTY_TREE regardless of whether the
      file happens to exist at C0.

      Pairs 10=13, 11=14, 12=15, 16=17 collapse because when C0=A there is
      no prior content to distinguish "unchanged" from "modified" at C1.

      All 13 valid rows are covered across the 4 test methods.
    """

    def test_modification_from_upstream(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Files present in orig with modified content at C2 appear in delta.

        Truth table rows exercised:
          fw/text.txt  — row 2:  P-P-M (modified only at C2)
          fw/data.bin  — row 4:  P-M-P (modified at C1, unchanged at C2)
          fw/link      — row 5:  P-M-M (modified at C1, modified again at C2)
          LICENSE.test — row 2:  P-P-M (license file modified at C2)

        Expected:
          ubuntu.patch: diffs for fw/link, fw/text.txt, LICENSE.test
          include-binaries: fw/data.bin, fw/link
        """
        repo, root = git_repo

        # --- C0 (upstream): all files present with original content ---
        c0 = _commit_mixed(
            repo,
            text={
                "fw/text.txt": "original text\n",
                "LICENSE.test": "Original license\n",
                "WHENCE": _make_whence(["fw/text.txt", "fw/data.bin", "fw/link"], ["LICENSE.test"]),
            },
            binary={"fw/data.bin": b"\x00\x01\x02\x03"},
            symlinks={"fw/link": "text.txt"},
            message="upstream",
        )

        # --- C1 (1st release): modify binary + link, add packaging ---
        _commit_mixed(
            repo,
            text={
                "ubuntu/upstream": f"COMMIT={c0}\nVERSION=1.0",
                f"{_PKG}/files": "fw/text.txt\nfw/data.bin\nfw/link",
                f"{_PKG}/changelog": _CHANGELOG_V1,
                f"{_PKG}/WHENCE": _make_whence(["fw/text.txt", "fw/data.bin", "fw/link"], ["LICENSE.test"]),
                f"{_PKG}/copyright": _make_copyright(["fw/*", "LICENSE.test"]),
            },
            binary={"fw/data.bin": b"\x10\x00\x12\x13"},  # row 4: modified at C1
            symlinks={"fw/link": "data.bin"},  # row 5: modified at C1
            message="first release",
        )

        # --- C2 (2nd release): modify text + link + license, bump changelog ---
        _commit_mixed(
            repo,
            text={
                "fw/text.txt": "modified text\n",  # row 2: modified at C2
                "LICENSE.test": "Modified license\n",  # row 2: license modified at C2
                f"{_PKG}/changelog": _make_changelog_v2(_CHANGELOG_V1),
                f"{_PKG}/WHENCE": _make_whence(["fw/text.txt", "fw/data.bin", "fw/link"], ["LICENSE.test"]),
            },
            symlinks={"fw/link": "LICENSE.test"},  # row 5: modified again at C2
            message="second release",
        )

        # --- Act ---
        pkg = Package("test-pkg", "HEAD")
        pkg.update_delta()

        # --- Assert: include-binaries ---
        include_binaries = (root / _PKG / "source" / "include-binaries").read_text()
        assert include_binaries == "fw/data.bin\nfw/link\n"

        # --- Assert: ubuntu.patch ---
        patch = (root / _PKG / "patches" / "ubuntu.patch").read_text()
        assert "diff --git a/LICENSE.test b/LICENSE.test" in patch
        assert "diff --git a/fw/link b/fw/link" in patch
        assert "diff --git a/fw/text.txt b/fw/text.txt" in patch
        # Binary file should NOT be in the patch
        assert "fw/data.bin" not in patch

        # --- Assert: series file ---
        series = (root / _PKG / "patches" / "series").read_text()
        assert series == "ubuntu.patch\n"

    def test_addition_to_package(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Files not present in orig but added to package appear in delta.

        Truth table rows exercised:
          fw/text.txt  — row 10/13: A-M-P (added at C1, unchanged at C2)
          fw/data.bin  — row 16/17: A-A-M (added at C2, not in C1)
          fw/link      — row 11/14: A-M-M (added at C1, modified at C2)
          LICENSE.new  — row 10/13: A-M-P (license added at C1, unchanged at C2)

        Expected:
          ubuntu.patch: diffs for fw/link, fw/text.txt, LICENSE.new
          include-binaries: fw/data.bin, fw/link
        """
        repo, root = git_repo

        # --- C0 (upstream): only WHENCE, no firmware files ---
        # The firmware files do not exist at the upstream commit (C0=A for all).
        c0 = _commit_mixed(
            repo,
            text={"WHENCE": "Header\n"},
            message="upstream",
        )

        # --- C1 (1st release): add text + link + license, but NOT binary ---
        _commit_mixed(
            repo,
            text={
                "fw/text.txt": "added text\n",  # row 10/13: added at C1
                "LICENSE.new": "New license\n",  # row 10/13: license added at C1
                "ubuntu/upstream": f"COMMIT={c0}\nVERSION=1.0",
                f"{_PKG}/files": "fw/text.txt\nfw/link",
                f"{_PKG}/changelog": _CHANGELOG_V1,
                f"{_PKG}/WHENCE": _make_whence(["fw/text.txt", "fw/link"], ["LICENSE.new"]),
                f"{_PKG}/copyright": _make_copyright(["fw/*", "LICENSE.new"]),
            },
            symlinks={"fw/link": "text.txt"},  # row 11/14: added at C1
            message="first release",
        )

        # --- C2 (2nd release): add binary, modify link, update files list ---
        _commit_mixed(
            repo,
            text={
                # Expand the files list to include the new binary
                f"{_PKG}/files": "fw/text.txt\nfw/data.bin\nfw/link",
                f"{_PKG}/changelog": _make_changelog_v2(_CHANGELOG_V1),
                f"{_PKG}/WHENCE": _make_whence(["fw/text.txt", "fw/data.bin", "fw/link"], ["LICENSE.new"]),
            },
            binary={"fw/data.bin": b"\x20\x00\x22\x23"},  # row 16/17: added at C2
            symlinks={"fw/link": "data.bin"},  # row 11/14: modified at C2
            message="second release",
        )

        # --- Act ---
        pkg = Package("test-pkg", "HEAD")
        pkg.update_delta()

        # --- Assert: include-binaries ---
        include_binaries = (root / _PKG / "source" / "include-binaries").read_text()
        assert include_binaries == "fw/data.bin\nfw/link\n"

        # --- Assert: ubuntu.patch ---
        patch = (root / _PKG / "patches" / "ubuntu.patch").read_text()
        assert "diff --git a/fw/text.txt b/fw/text.txt" in patch
        assert "diff --git a/fw/link b/fw/link" in patch
        assert "diff --git a/LICENSE.new b/LICENSE.new" in patch
        # Binary should NOT be in patch
        assert "fw/data.bin" not in patch

        # --- Assert: series file ---
        series = (root / _PKG / "patches" / "series").read_text()
        assert series == "ubuntu.patch\n"

    def test_removed_then_readded(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Files removed from C1's files list then re-added at C2 appear in delta.

        This tests the critical interaction between base_commit pathspecs and
        orig tarball contents. The orig tarball uses C1's files list to determine
        which paths to include. If a file is not in C1's files list, it won't
        be in orig — even if the file exists at C0 with identical content.

        Truth table rows exercised:
          fw/text.txt  — row 7: P-A-P (re-added with SAME content as C0)
          fw/data.bin  — row 8: P-A-M (re-added with different content)
          fw/link      — row 8: P-A-M (re-added with different target)
          LICENSE.test — row 7: P-A-P (license re-added, same content as C0)

        Expected:
          include-binaries: fw/data.bin, fw/link
          ubuntu.patch: diffs for fw/text.txt, LICENSE.test, fw/link
              (all are new relative to orig, which uses C1's pathspecs)

        Key insight: Row 7 files are not in orig (C1's pathspecs exclude them),
        so they appear as full additions in the delta. The diff is generated
        against EMPTY_TREE, not against C0 — even though the content at C2
        happens to match C0.
        """
        repo, root = git_repo

        # --- C0 (upstream): all files present ---
        c0 = _commit_mixed(
            repo,
            text={
                "fw/text.txt": "original text\n",
                "LICENSE.test": "Original license\n",
                "WHENCE": _make_whence(["fw/text.txt", "fw/data.bin", "fw/link"], ["LICENSE.test"]),
            },
            binary={"fw/data.bin": b"\x00\x01\x02\x03"},
            symlinks={"fw/link": "text.txt"},
            message="upstream",
        )

        # --- C1 (1st release): files list does NOT include the test files ---
        # The files still exist in git, but are not listed in the package's
        # files list. This means orig (which uses C1's pathspecs) won't
        # include them.
        _commit_mixed(
            repo,
            text={
                "ubuntu/upstream": f"COMMIT={c0}\nVERSION=1.0",
                # Empty files list (or listing other files); the key point is
                # these 4 files are NOT listed
                f"{_PKG}/files": "WHENCE",
                f"{_PKG}/changelog": _CHANGELOG_V1,
                # WHENCE at C1 doesn't reference our test files (they're not packaged)
                f"{_PKG}/WHENCE": _make_whence([], []),
                f"{_PKG}/copyright": _make_copyright(["fw/*", "LICENSE.test"]),
            },
            message="first release",
        )

        # --- C2 (2nd release): re-add files to the package ---
        _commit_mixed(
            repo,
            text={
                # Row 7: re-add text with SAME content as C0 (no write needed,
                # it's still in git from C0). Just update the files list.
                f"{_PKG}/files": "fw/text.txt\nfw/data.bin\nfw/link",
                f"{_PKG}/changelog": _make_changelog_v2(_CHANGELOG_V1),
                f"{_PKG}/WHENCE": _make_whence(["fw/text.txt", "fw/data.bin", "fw/link"], ["LICENSE.test"]),
            },
            # Row 8: re-add binary with DIFFERENT content
            binary={"fw/data.bin": b"\x50\x00\x52\x53"},
            # Row 8: re-add link with DIFFERENT target
            symlinks={"fw/link": "LICENSE.test"},
            message="second release",
        )

        # --- Act ---
        pkg = Package("test-pkg", "HEAD")
        pkg.update_delta()

        # --- Assert: include-binaries ---
        # Both binary and link appear (row 7 binary + row 8 link)
        include_binaries = (root / _PKG / "source" / "include-binaries").read_text()
        assert include_binaries == "fw/data.bin\nfw/link\n"

        # --- Assert: ubuntu.patch ---
        patch = (root / _PKG / "patches" / "ubuntu.patch").read_text()
        # Row 7 text: not in orig, so full diff against EMPTY_TREE as addition
        assert "diff --git a/fw/text.txt b/fw/text.txt" in patch
        # Row 7 license: not in orig, full diff as addition
        assert "diff --git a/LICENSE.test b/LICENSE.test" in patch
        # Row 8 link: target changed from C0, diff shows the change
        assert "diff --git a/fw/link b/fw/link" in patch
        # Row 8 binary: never in patch (binary type)
        assert "diff --git a/fw/data.bin b/fw/data.bin" not in patch

    def test_no_delta_and_cleanup(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Unchanged and removed files produce no delta; existing output is cleaned up.

        Truth table rows exercised:
          fw/text.txt     — row 1:     P-P-P (unchanged throughout)
          fw/data.bin     — row 1:     P-P-P (unchanged binary)
          fw/link         — row 1:     P-P-P (unchanged link)
          LICENSE.test    — row 1:     P-P-P (unchanged license)
          fw/removed.txt  — row 3:     P-P-A (present, then removed at C2)
          fw/gone.bin     — row 6:     P-M-A (modified at C1, removed at C2)
          fw/dropped.txt  — row 9:     P-A-A (removed from files at C1, still absent)
          fw/transient.txt— row 12/15: A-M-A (added at C1, removed at C2)

        Expected:
          No patches/ directory (or removed if pre-existing)
          No source/ directory (or removed if pre-existing)

        Also verifies that pre-existing output files are cleaned up when
        update_delta() finds no changes.
        """
        repo, root = git_repo

        # --- C0 (upstream): files for rows 1, 3, 6, 9 ---
        c0 = _commit_mixed(
            repo,
            text={
                "fw/text.txt": "unchanged text\n",  # row 1
                "fw/removed.txt": "will be removed\n",  # row 3
                "fw/gone.bin": "placeholder\n",  # row 6 (will become binary at C1)
                "fw/dropped.txt": "will be dropped\n",  # row 9
                "LICENSE.test": "Unchanged license\n",  # row 1
                "WHENCE": _make_whence(
                    ["fw/text.txt", "fw/removed.txt", "fw/gone.bin", "fw/dropped.txt", "fw/link"],
                    ["LICENSE.test"],
                ),
            },
            binary={"fw/data.bin": b"\x00\x01\x02\x03"},  # row 1
            symlinks={"fw/link": "text.txt"},  # row 1
            message="upstream",
        )

        # --- C1 (1st release) ---
        # - rows 1,3: unchanged files stay in files list
        # - row 6: fw/gone.bin modified
        # - row 9: fw/dropped.txt NOT in files list
        # - row 12/15: fw/transient.txt added
        _commit_mixed(
            repo,
            text={
                "fw/transient.txt": "temporary\n",  # row 12/15: added at C1
                "ubuntu/upstream": f"COMMIT={c0}\nVERSION=1.0",
                # files list: includes rows 1,3,6 and row 12/15; excludes row 9
                f"{_PKG}/files": ("fw/text.txt\nfw/data.bin\nfw/link\nfw/removed.txt\nfw/gone.bin\nfw/transient.txt"),
                f"{_PKG}/changelog": _CHANGELOG_V1,
                f"{_PKG}/WHENCE": _make_whence(
                    ["fw/text.txt", "fw/data.bin", "fw/link", "fw/removed.txt", "fw/gone.bin", "fw/transient.txt"],
                    ["LICENSE.test"],
                ),
                f"{_PKG}/copyright": _make_copyright(["fw/*", "LICENSE.test"]),
            },
            binary={"fw/gone.bin": b"\xaa\x00\xcc\xdd"},  # row 6: modified at C1
            message="first release",
        )

        # --- C2 (2nd release) ---
        # - row 1: unchanged (P-P-P)
        # - row 3: fw/removed.txt dropped from files list (P-P-A)
        # - row 6: fw/gone.bin dropped from files list (P-M-A)
        # - row 12/15: fw/transient.txt dropped from files list (A-M-A)
        # Only row 1 files remain in the package, all unchanged from C0
        _commit_mixed(
            repo,
            text={
                # Reduced files list: only unchanged files
                f"{_PKG}/files": "fw/text.txt\nfw/data.bin\nfw/link",
                f"{_PKG}/changelog": _make_changelog_v2(_CHANGELOG_V1),
                f"{_PKG}/WHENCE": _make_whence(["fw/text.txt", "fw/data.bin", "fw/link"], ["LICENSE.test"]),
            },
            message="second release",
        )

        # --- Pre-create output files to verify cleanup ---
        patches_dir = root / _PKG / "patches"
        source_dir = root / _PKG / "source"
        patches_dir.mkdir(parents=True)
        (patches_dir / "ubuntu.patch").write_text("stale patch\n")
        (patches_dir / "series").write_text("ubuntu.patch\n")
        source_dir.mkdir(parents=True)
        (source_dir / "include-binaries").write_text("stale/binary.bin\n")

        # --- Act ---
        pkg = Package("test-pkg", "HEAD")
        pkg.update_delta()

        # --- Assert: output directories removed ---
        assert not patches_dir.exists(), "patches/ dir should be removed when no text changes"
        assert not source_dir.exists(), "source/ dir should be removed when no binary changes"


# --- Tests for Package.check_*() methods ---


def _make_check_package(
    repo: git.Repo,
    files: str,
    whence: str,
    copyright: str,
    firmware: dict[str, str] | None = None,
) -> str:
    """Create a minimal package with given files/WHENCE/copyright and commit.

    Creates two commits:
      C0 (upstream): firmware files + WHENCE (the pristine upstream tree)
      C1 (release):  packaging + firmware (references C0 as upstream commit)

    Returns the release commit SHA.
    """
    # C0: upstream commit with firmware and WHENCE
    upstream_files: dict[str, str] = {"WHENCE": whence}
    if firmware:
        upstream_files.update(firmware)
    c0 = commit_files(repo, upstream_files, message="upstream")

    # C1: release commit with packaging referencing C0
    all_files: dict[str, str] = {
        f"{_PKG}/files": files,
        f"{_PKG}/WHENCE": whence,
        f"{_PKG}/copyright": copyright,
        f"{_PKG}/changelog": _CHANGELOG_V1,
        "ubuntu/upstream": f"COMMIT={c0}\nVERSION=1.0",
    }
    if firmware:
        all_files.update(firmware)
    return commit_files(repo, all_files, message="release")


class TestCheckExcludedSubset:
    """Tests for Package.check_excluded_subset().

    Note: The failure case (excluded not subset of included) cannot occur with
    the current Package.__init__ because strict pathspec validation in
    PackageFiles catches invalid exclusions first (as GitFilesError). The check
    method exists as a public API for independent use.
    """

    def test_passes_when_excluded_is_subset(self, git_repo: tuple[git.Repo, Path]) -> None:
        """No error when excluded files are a subset of included."""
        repo, _ = git_repo
        _make_check_package(
            repo,
            files="fw/*.bin\n!fw/skip.bin",
            whence=_make_whence(["fw/a.bin"], []),
            copyright=_make_copyright(["fw/*"]),
            firmware={"fw/a.bin": "data", "fw/skip.bin": "data"},
        )
        pkg = Package("test-pkg")
        pkg.check_excluded_subset()  # Should not raise


class TestCheckPackagedFiles:
    """Tests for Package.check_packaged_files()."""

    def test_passes_when_correct(self, git_repo: tuple[git.Repo, Path]) -> None:
        """No error when packaged == included - excluded."""
        repo, _ = git_repo
        _make_check_package(
            repo,
            files="fw/*.bin\n!fw/skip.bin",
            whence=_make_whence(["fw/a.bin"], []),
            copyright=_make_copyright(["fw/*"]),
            firmware={"fw/a.bin": "data", "fw/skip.bin": "data"},
        )
        pkg = Package("test-pkg")
        pkg.check_packaged_files()  # Should not raise


class TestCheckWhenceCoverage:
    """Tests for Package.check_whence_coverage()."""

    def test_passes_all_referenced(self, git_repo: tuple[git.Repo, Path]) -> None:
        """No error when all packaged files are in WHENCE."""
        repo, _ = git_repo
        _make_check_package(
            repo,
            files="fw/a.bin",
            whence=_make_whence(["fw/a.bin"], []),
            copyright=_make_copyright(["fw/*"]),
            firmware={"fw/a.bin": "data"},
        )
        pkg = Package("test-pkg")
        pkg.check_whence_coverage()  # Should not raise

    def test_fails_unreferenced_file(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Raises PackageError when a packaged file is not in WHENCE."""
        repo, _ = git_repo
        _make_check_package(
            repo,
            files="fw/a.bin\nfw/b.bin",
            whence=_make_whence(["fw/a.bin"], []),  # missing fw/b.bin
            copyright=_make_copyright(["fw/*"]),
            firmware={"fw/a.bin": "data", "fw/b.bin": "data"},
        )
        pkg = Package("test-pkg")
        with pytest.raises(PackageError, match="Packaged files not referenced in WHENCE"):
            pkg.check_whence_coverage()

    def test_directory_prefix_covers_file(self, git_repo: tuple[git.Repo, Path]) -> None:
        """A WHENCE directory entry covers files under it."""
        repo, _ = git_repo
        # WHENCE has "Source: fw/" which generates "fw/" as a directory path
        whence_content = (
            "Header\n"
            "------------------------------------------------------------------------------\n"
            "Source: fw/\n"
            "------------------------------------------------------------------------------\n"
        )
        _make_check_package(
            repo,
            files="fw/a.bin",
            whence=whence_content,
            copyright=_make_copyright(["fw/*"]),
            firmware={"fw/a.bin": "data"},
        )
        pkg = Package("test-pkg")
        pkg.check_whence_coverage()  # Should not raise


class TestCheckCopyrightCoverage:
    """Tests for Package.check_copyright_coverage()."""

    def test_passes_all_covered(self, git_repo: tuple[git.Repo, Path]) -> None:
        """No error when all packaged files are covered and no dead patterns."""
        repo, _ = git_repo
        _make_check_package(
            repo,
            files="fw/a.bin\nfw/b.bin",
            whence=_make_whence(["fw/a.bin", "fw/b.bin"], []),
            copyright=_make_copyright(["fw/*"]),
            firmware={"fw/a.bin": "data", "fw/b.bin": "data"},
        )
        pkg = Package("test-pkg")
        pkg.check_copyright_coverage()  # Should not raise

    def test_fails_missing_debian_stanza(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Raises PackageError when debian/* stanza is missing."""
        repo, _ = git_repo
        # Copyright without debian/* stanza
        copyright_content = (
            "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
            "Upstream-Name: linux-firmware\n\n"
            "Files: fw/*\n"
            "Copyright: 2024, Test\n"
            "License: Redistributable\n"
        )
        _make_check_package(
            repo,
            files="fw/a.bin",
            whence=_make_whence(["fw/a.bin"], []),
            copyright=copyright_content,
            firmware={"fw/a.bin": "data"},
        )
        pkg = Package("test-pkg")
        with pytest.raises(PackageError, match="Missing Files: debian/\\* stanza"):
            pkg.check_copyright_coverage()

    def test_fails_uncovered_file(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Raises PackageError when a packaged file is not covered."""
        repo, _ = git_repo
        # Copyright only covers intel/*, but we package fw/*
        _make_check_package(
            repo,
            files="fw/a.bin",
            whence=_make_whence(["fw/a.bin"], []),
            copyright=_make_copyright(["intel/*"]),
            firmware={"fw/a.bin": "data"},
        )
        pkg = Package("test-pkg")
        with pytest.raises(PackageError, match="Firmware files not covered in copyright"):
            pkg.check_copyright_coverage()

    def test_fails_dead_pattern(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Raises PackageError when a copyright pattern matches nothing."""
        repo, _ = git_repo
        # Copyright has both fw/* (matches) and intel/* (dead)
        _make_check_package(
            repo,
            files="fw/a.bin",
            whence=_make_whence(["fw/a.bin"], []),
            copyright=_make_copyright(["fw/*", "intel/*"]),
            firmware={"fw/a.bin": "data"},
        )
        pkg = Package("test-pkg")
        with pytest.raises(PackageError, match="Copyright patterns match no firmware files"):
            pkg.check_copyright_coverage()

    def test_debian_stanza_not_flagged_as_dead(self, git_repo: tuple[git.Repo, Path]) -> None:
        """The debian/* pattern is never flagged as a dead pattern."""
        repo, _ = git_repo
        _make_check_package(
            repo,
            files="fw/a.bin",
            whence=_make_whence(["fw/a.bin"], []),
            copyright=_make_copyright(["fw/*"]),
            firmware={"fw/a.bin": "data"},
        )
        pkg = Package("test-pkg")
        # Should pass — debian/* doesn't match any firmware path but is exempted
        pkg.check_copyright_coverage()

    def test_fails_unresolved_license(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Raises PackageError when a license reference has no definition."""
        repo, _ = git_repo
        # Copyright references "Redistributable" but has no standalone paragraph for it
        copyright_content = (
            "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
            "Upstream-Name: linux-firmware\n\n"
            "Files: debian/*\n"
            "Copyright: 2026 Canonical Ltd.\n"
            "License: GPL-2+\n\n"
            "Files: fw/*\n"
            "Copyright: 2024, Test\n"
            "License: Redistributable\n\n"
            "License: GPL-2+\n"
            " See /usr/share/common-licenses/GPL-2.\n"
        )
        _make_check_package(
            repo,
            files="fw/a.bin",
            whence=_make_whence(["fw/a.bin"], []),
            copyright=copyright_content,
            firmware={"fw/a.bin": "data"},
        )
        pkg = Package("test-pkg")
        with pytest.raises(PackageError, match="Unresolved license references"):
            pkg.check_copyright_coverage()

    def test_fails_orphaned_license(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Raises PackageError when a standalone license paragraph is unused."""
        repo, _ = git_repo
        # Copyright has an extra standalone "Unused" paragraph
        copyright_content = (
            "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
            "Upstream-Name: linux-firmware\n\n"
            "Files: debian/*\n"
            "Copyright: 2026 Canonical Ltd.\n"
            "License: GPL-2+\n\n"
            "Files: fw/*\n"
            "Copyright: 2024, Test\n"
            "License: Redistributable\n\n"
            "License: GPL-2+\n"
            " See /usr/share/common-licenses/GPL-2.\n\n"
            "License: Redistributable\n"
            " Redistribution permitted.\n\n"
            "License: Unused\n"
            " This is not referenced.\n"
        )
        _make_check_package(
            repo,
            files="fw/a.bin",
            whence=_make_whence(["fw/a.bin"], []),
            copyright=copyright_content,
            firmware={"fw/a.bin": "data"},
        )
        pkg = Package("test-pkg")
        with pytest.raises(PackageError, match="Orphaned license paragraphs"):
            pkg.check_copyright_coverage()


class TestCheckMeta:
    """Tests for Package.check() on meta package."""

    def test_meta_skips_all_checks(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Meta package check() returns without error."""
        repo, _ = git_repo
        commit_files(
            repo,
            {
                "ubuntu/package/meta/changelog": (
                    "linux-firmware (1.0) noble; urgency=medium\n\n"
                    "  * Test\n\n"
                    " -- Test <t@t.com>  Mon, 01 Jan 2024 00:00:00 +0000\n"
                ),
            },
        )
        pkg = Package("meta")
        pkg.check()  # Should not raise
