"""Tests for lib/whence.py."""

import io
from pathlib import Path

import git
import pytest

from lib.whence import Whence, WhenceError, parse_sections, section_file_licenses

from .conftest import commit_file, commit_files


class TestParseSections:
    """Tests for parse_sections function."""

    def test_empty_input(self) -> None:
        """Empty input returns empty list."""
        result = parse_sections(io.StringIO(""))
        assert result == []

    def test_single_section(self) -> None:
        """Input without separators returns one section."""
        content = "File: foo.bin\nLicense: BSD"
        result = parse_sections(io.StringIO(content))
        assert result == [["File: foo.bin", "License: BSD"]]

    def test_multiple_sections(self) -> None:
        """Separator-delimited input returns multiple sections."""
        content = "Header line\n----------\nFile: a.bin\n----------\nFile: b.bin"
        result = parse_sections(io.StringIO(content))
        assert len(result) == 3
        assert result[0] == ["Header line"]
        assert result[1] == ["File: a.bin"]
        assert result[2] == ["File: b.bin"]

    def test_unescapes_backslash_space(self) -> None:
        """Backslash-space in File/RawFile/Link/Source is unescaped."""
        content = r"File: foo\ bar.bin"
        result = parse_sections(io.StringIO(content))
        assert result[0][0] == "File: foo bar.bin"

    def test_strips_quotes(self) -> None:
        """Single and double quotes are stripped from File/RawFile/Link/Source."""
        content = "File: \"foo.bin\"\nRawFile: 'bar.bin'"
        result = parse_sections(io.StringIO(content))
        assert result[0][0] == "File: foo.bin"
        assert result[0][1] == "RawFile: bar.bin"


class TestWhenceSections:
    """Tests for Whence.sections property."""

    def test_single_file(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Reads and parses a single WHENCE file."""
        repo, _ = git_repo
        whence_content = "Header\n----------\nFile: foo.bin"
        commit_file(repo, "WHENCE", whence_content)

        whence = Whence(Path("WHENCE"))
        assert len(whence.sections) == 2
        assert whence.sections[0] == ["Header"]
        assert whence.sections[1] == ["File: foo.bin"]

    def test_glob_multiple_files(self, git_repo: tuple[git.Repo, Path]) -> None:
        """WHENCE* glob merges multiple files."""
        repo, _ = git_repo
        commit_files(
            repo,
            {
                "WHENCE": "File: a.bin",
                "WHENCE.ubuntu": "File: b.bin",
            },
        )

        whence = Whence(Path("WHENCE*"))
        paths = [line for section in whence.sections for line in section if line.startswith("File:")]
        assert "File: a.bin" in paths
        assert "File: b.bin" in paths

    def test_missing_file_raises(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Missing file raises WhenceError."""
        repo, _ = git_repo
        commit_file(repo, "dummy", "placeholder")

        whence = Whence(Path("WHENCE"))
        with pytest.raises(WhenceError, match="No WHENCE files found"):
            _ = whence.sections

    def test_sections_cached(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Second access returns cached sections."""
        repo, _ = git_repo
        commit_file(repo, "WHENCE", "File: foo.bin")

        whence = Whence(Path("WHENCE"))
        sections1 = whence.sections
        sections2 = whence.sections
        assert sections1 is sections2


class TestWhenceFiles:
    """Tests for Whence.files property."""

    def test_extracts_file_rawfile_source(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Extracts File:, RawFile:, and Source: paths as pathspecs."""
        repo, _ = git_repo
        content = "File: a.bin\nRawFile: b.bin\nSource: c.tar"
        commit_file(repo, "WHENCE", content)

        whence = Whence(Path("WHENCE"))
        pathspecs = whence.files.pathspecs()
        assert "a.bin" in pathspecs
        assert "b.bin" in pathspecs
        assert "c.tar" in pathspecs

    def test_link_resolution(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Link: target is resolved relative to link directory."""
        repo, _ = git_repo
        content = "Link: dir/link.bin -> ../target.bin"
        commit_file(repo, "WHENCE", content)

        whence = Whence(Path("WHENCE"))
        pathspecs = whence.files.pathspecs()
        assert "target.bin" in pathspecs


class TestSectionFileLicenses:
    """Tests for section_file_licenses function."""

    def test_file_with_licence(self) -> None:
        """File followed by Licence yields (file, license) pair."""
        section = ["File: foo.bin", "Licence: Redistributable. See LICENCE.foo for details."]
        result = list(section_file_licenses(section, {"LICENSES/LICENCE.foo"}))
        assert result == [("foo.bin", "LICENSES/LICENCE.foo")]

    def test_multiple_files_single_licence(self) -> None:
        """Multiple files followed by one Licence yields pairs for all files."""
        section = ["File: a.bin", "File: b.bin", "Licence: See LICENCE.x for details."]
        result = list(section_file_licenses(section, {"LICENSES/LICENCE.x"}))
        assert result == [("a.bin", "LICENSES/LICENCE.x"), ("b.bin", "LICENSES/LICENCE.x")]

    def test_multiple_licences_same_files(self) -> None:
        """Consecutive Licence lines apply to the same accumulated files."""
        section = [
            "File: a.bin",
            "File: b.bin",
            "Licence: See LICENCE.x for details.",
            "Licence: See LICENCE.y for details.",
        ]
        result = list(section_file_licenses(section, {"LICENSES/LICENCE.x", "LICENSES/LICENCE.y"}))
        assert ("a.bin", "LICENSES/LICENCE.x") in result
        assert ("a.bin", "LICENSES/LICENCE.y") in result
        assert ("b.bin", "LICENSES/LICENCE.x") in result
        assert ("b.bin", "LICENSES/LICENCE.y") in result

    def test_interleaved_files_licences(self) -> None:
        """Files after a Licence line start a new group."""
        section = [
            "File: a.bin",
            "Licence: See LICENCE.x for details.",
            "File: b.bin",
            "Licence: See LICENCE.y for details.",
        ]
        result = list(section_file_licenses(section, {"LICENSES/LICENCE.x", "LICENSES/LICENCE.y"}))
        assert result == [("a.bin", "LICENSES/LICENCE.x"), ("b.bin", "LICENSES/LICENCE.y")]

    def test_files_with_no_licence(self) -> None:
        """Files with no Licence line yield (file, None)."""
        section = ["File: foo.bin", "File: bar.bin"]
        result = list(section_file_licenses(section, {"LICENSES/LICENCE.foo"}))
        assert result == [("foo.bin", None), ("bar.bin", None)]

    def test_token_not_in_tree(self) -> None:
        """Licence tokens not in tree_files are excluded."""
        section = ["File: foo.bin", "Licence: See LICENCE.missing for details."]
        result = list(section_file_licenses(section, set()))
        assert result == []

    def test_trailing_punctuation_stripped(self) -> None:
        """Trailing punctuation is stripped before matching."""
        section = ["File: foo.bin", "Licence: See LICENCE.foo."]
        result = list(section_file_licenses(section, {"LICENSES/LICENCE.foo"}))
        assert result == [("foo.bin", "LICENSES/LICENCE.foo")]

    def test_license_spelling(self) -> None:
        """Both Licence and License spellings are recognized."""
        section = ["File: foo.bin", "License: Redistributable. See MIT for details"]
        result = list(section_file_licenses(section, {"LICENSES/MIT"}))
        assert result == [("foo.bin", "LICENSES/MIT")]

    def test_link_lines_ignored(self) -> None:
        """Link lines do not accumulate into the file list."""
        section = [
            "File: a.bin",
            "Link: dir/link.bin -> ../target.bin",
            "Licence: See LICENCE.x for details.",
        ]
        result = list(section_file_licenses(section, {"LICENSES/LICENCE.x"}))
        assert result == [("a.bin", "LICENSES/LICENCE.x")]

    def test_rawfile_and_source(self) -> None:
        """RawFile and Source lines accumulate like File."""
        section = [
            "RawFile: raw.bin",
            "Source: src.tar",
            "Licence: See LICENCE.x for details.",
        ]
        result = list(section_file_licenses(section, {"LICENSES/LICENCE.x"}))
        assert result == [("raw.bin", "LICENSES/LICENCE.x"), ("src.tar", "LICENSES/LICENCE.x")]

    def test_multiple_licence_tokens_one_line(self) -> None:
        """Multiple valid tokens on one Licence line are all yielded."""
        section = ["File: a.bin", "Licence: See LICENCE.a and LICENCE.b for details"]
        tree = {"LICENSES/LICENCE.a", "LICENSES/LICENCE.b"}
        result = list(section_file_licenses(section, tree))
        assert ("a.bin", "LICENSES/LICENCE.a") in result
        assert ("a.bin", "LICENSES/LICENCE.b") in result

    def test_files_after_licence_not_flagged_unlicensed(self) -> None:
        """Files consumed by a licence are not yielded as unlicensed at section end."""
        section = ["File: a.bin", "Licence: See LICENCE.x for details."]
        result = list(section_file_licenses(section, {"LICENSES/LICENCE.x"}))
        assert ("a.bin", None) not in result


class TestWhenceLicenses:
    """Tests for Whence.licenses method."""

    def test_aggregates_across_sections(self, git_repo: tuple[git.Repo, Path]) -> None:
        """License paths are collected across all sections."""
        repo, _ = git_repo
        content = (
            "File: a.bin\nLicence: See LICENCE.a for details\n"
            "----------\n"
            "File: b.bin\nLicence: See LICENCE.b for details\n"
        )
        commit_files(
            repo,
            {
                "WHENCE": content,
                "LICENSES/LICENCE.a": "license a",
                "LICENSES/LICENCE.b": "license b",
                "a.bin": "binary a",
                "b.bin": "binary b",
            },
        )

        whence = Whence(Path("WHENCE"))
        license_pathspecs = whence.licenses().pathspecs()
        assert "LICENSES/LICENCE.a" in license_pathspecs
        assert "LICENSES/LICENCE.b" in license_pathspecs

    def test_filtered_by_files(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Filtered licenses returns only licenses for the given files."""
        repo, _ = git_repo
        content = (
            "File: a.bin\nLicence: See LICENCE.a for details\n"
            "----------\n"
            "File: b.bin\nLicence: See LICENCE.b for details\n"
        )
        commit_files(
            repo,
            {
                "WHENCE": content,
                "LICENSES/LICENCE.a": "license a",
                "LICENSES/LICENCE.b": "license b",
                "a.bin": "binary a",
                "b.bin": "binary b",
            },
        )

        whence = Whence(Path("WHENCE"))
        license_pathspecs = whence.licenses(["a.bin"]).pathspecs()
        assert "LICENSES/LICENCE.a" in license_pathspecs
        assert "LICENSES/LICENCE.b" not in license_pathspecs

    def test_interleaved_section_filtered(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Filtering works correctly with interleaved files/licences in one section."""
        repo, _ = git_repo
        content = (
            "File: a.bin\n"
            "Licence: See LICENCE.x for details\n"
            "File: b.bin\n"
            "Licence: See LICENCE.y for details\n"
        )
        commit_files(
            repo,
            {
                "WHENCE": content,
                "LICENSES/LICENCE.x": "license x",
                "LICENSES/LICENCE.y": "license y",
                "a.bin": "binary a",
                "b.bin": "binary b",
            },
        )

        whence = Whence(Path("WHENCE"))
        # Only b.bin is packaged; should only get LICENCE.y
        license_pathspecs = whence.licenses(["b.bin"]).pathspecs()
        assert "LICENSES/LICENCE.y" in license_pathspecs
        assert "LICENSES/LICENCE.x" not in license_pathspecs
