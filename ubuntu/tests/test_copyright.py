"""Tests for ubuntu.lib.copyright module."""

from pathlib import Path

import git
import pytest

from lib.copyright import CopyrightError, PackageCopyright

from .conftest import commit_file

# -- Minimal DEP-5 copyright content for testing --

MINIMAL_COPYRIGHT = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: linux-firmware
Upstream-Contact: linux-firmware@kernel.org
Source: https://git.kernel.org/pub/scm/linux/firmware/linux-firmware.git

Files: debian/*
Copyright: 2026 Canonical Ltd.
License: GPL-2+

Files: intel/*
Copyright: 2014, Intel Corporation.
License: Redistributable-ibt_firmware

Files: realtek/*
Copyright: 2024, Realtek Semiconductor Corporation
License: Redistributable-realtek
"""

MULTI_STANZA_COPYRIGHT = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: linux-firmware
Upstream-Contact: linux-firmware@kernel.org
Source: https://git.kernel.org/pub/scm/linux/firmware/linux-firmware.git

Files: debian/*
Copyright: 2026 Canonical Ltd.
License: GPL-2+

Files: intel/*
Copyright: 2014, Intel Corporation.
License: Redistributable-ibt_firmware

Files: rtl_nic/*
Copyright: 2011-2013, Realtek Semiconductor Corporation
License: Redistributable-r8169

Files: rtl_bt/*
 rtl_nic/rtl8153a-2.fw
 rtl_nic/rtl8153a-3.fw
 rtlwifi/*
Copyright: 2010, Realtek Semiconductor Corporation
License: Redistributable-rtlwifi_firmware
"""

NO_DEBIAN_STANZA_COPYRIGHT = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: linux-firmware
Upstream-Contact: linux-firmware@kernel.org
Source: https://git.kernel.org/pub/scm/linux/firmware/linux-firmware.git

Files: intel/*
Copyright: 2014, Intel Corporation.
License: Redistributable-ibt_firmware
"""


class TestPackageCopyrightInit:
    """Tests for PackageCopyright initialization."""

    def test_init_worktree(self, git_repo: tuple[git.Repo, Path]) -> None:
        """PackageCopyright initializes from a worktree file."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        assert pc.path == Path("ubuntu/package/test/copyright")
        assert pc.commit is None

    def test_init_at_commit(self, git_repo: tuple[git.Repo, Path]) -> None:
        """PackageCopyright initializes from a specific commit."""
        repo, tmp_path = git_repo
        sha = commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"), commit=sha)
        assert pc.commit == sha

    def test_init_missing_file(self, git_repo: tuple[git.Repo, Path]) -> None:
        """PackageCopyright raises CopyrightError if file does not exist."""
        repo, tmp_path = git_repo
        # Commit something so the repo has a tree
        commit_file(repo, "dummy", "x")

        with pytest.raises(CopyrightError, match="No such file"):
            PackageCopyright(Path("ubuntu/package/test/copyright"))


class TestPackageCopyrightLazy:
    """Tests for lazy parsing behavior."""

    def test_copyright_property_parses_on_access(self, git_repo: tuple[git.Repo, Path]) -> None:
        """The copyright property lazily parses the DEP-5 file."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        assert pc._copyright is None
        _ = pc.copyright
        assert pc._copyright is not None

    def test_copyright_property_cached(self, git_repo: tuple[git.Repo, Path]) -> None:
        """The copyright property returns the same object on repeated access."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        first = pc.copyright
        second = pc.copyright
        assert first is second


class TestFileLicenses:
    """Tests for PackageCopyright.file_licenses()."""

    def test_simple_glob_match(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Files matching a glob pattern return the correct license."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        result = pc.file_licenses(["intel/ibt-hw-37.fw", "intel/ibt-20.fw"])
        assert result == [
            ("intel/ibt-hw-37.fw", "Redistributable-ibt_firmware"),
            ("intel/ibt-20.fw", "Redistributable-ibt_firmware"),
        ]

    def test_unmatched_files_omitted(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Files not matching any stanza are silently omitted."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        result = pc.file_licenses(["intel/ibt.fw", "unknown/file.bin"])
        assert result == [("intel/ibt.fw", "Redistributable-ibt_firmware")]

    def test_all_unmatched(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns empty list if no files match."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        result = pc.file_licenses(["unknown/file.bin", "other/thing.fw"])
        assert result == []

    def test_last_match_wins(self, git_repo: tuple[git.Repo, Path]) -> None:
        """DEP-5 last-match-wins: later stanza overrides earlier one."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MULTI_STANZA_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        # rtl_nic/rtl8153a-2.fw matches both rtl_nic/* and the last stanza
        result = pc.file_licenses(["rtl_nic/rtl8153a-2.fw"])
        assert result == [("rtl_nic/rtl8153a-2.fw", "Redistributable-rtlwifi_firmware")]

    def test_multiple_stanzas(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Files from different stanzas get their respective licenses."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MULTI_STANZA_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        result = pc.file_licenses([
            "intel/ibt.fw",
            "rtl_nic/rtl8168g-2.fw",
            "rtl_bt/rtl8761b_fw.bin",
        ])
        assert result == [
            ("intel/ibt.fw", "Redistributable-ibt_firmware"),
            ("rtl_nic/rtl8168g-2.fw", "Redistributable-r8169"),
            ("rtl_bt/rtl8761b_fw.bin", "Redistributable-rtlwifi_firmware"),
        ]

    def test_nested_path_matches_glob(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Nested paths match dir/* patterns (fnmatch * crosses /)."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        result = pc.file_licenses(["intel/sub/deep/file.fw"])
        assert result == [("intel/sub/deep/file.fw", "Redistributable-ibt_firmware")]


class TestHasDebianStanza:
    """Tests for PackageCopyright.has_debian_stanza()."""

    def test_present(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns True when a Files: debian/* stanza exists."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        assert pc.has_debian_stanza() is True

    def test_absent(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns False when no Files: debian/* stanza exists."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", NO_DEBIAN_STANZA_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        assert pc.has_debian_stanza() is False


class TestUnmatchedPatterns:
    """Tests for PackageCopyright.unmatched_patterns()."""

    def test_all_patterns_match(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns empty list when all non-debian patterns match at least one file."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        result = pc.unmatched_patterns(["intel/ibt.fw", "realtek/rt1320.fw"])
        assert result == []

    def test_dead_pattern_detected(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns patterns that match nothing in the file list."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        # Only provide intel files — realtek/* is dead
        result = pc.unmatched_patterns(["intel/ibt.fw"])
        assert result == ["realtek/*"]

    def test_debian_stanza_ignored(self, git_repo: tuple[git.Repo, Path]) -> None:
        """The debian/* pattern is always excluded from results."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        # No files match anything — but debian/* should not appear
        result = pc.unmatched_patterns([])
        assert "debian/*" not in result
        assert "intel/*" in result
        assert "realtek/*" in result

    def test_exact_pattern_dead(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Exact file patterns that don't match are reported."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MULTI_STANZA_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        # Provide files that match intel/* and rtl_bt/* but not the exact rtl_nic patterns
        result = pc.unmatched_patterns([
            "intel/ibt.fw",
            "rtl_bt/rtl8761b_fw.bin",
            "rtl_nic/rtl8168g-2.fw",
            "rtlwifi/rtl8192.fw",
        ])
        # rtl_nic/rtl8153a-2.fw and rtl_nic/rtl8153a-3.fw are dead exact patterns
        assert "rtl_nic/rtl8153a-2.fw" in result
        assert "rtl_nic/rtl8153a-3.fw" in result
        # rtl_nic/* matches rtl_nic/rtl8168g-2.fw so it's not dead
        assert "rtl_nic/*" not in result

    def test_empty_file_list(self, git_repo: tuple[git.Repo, Path]) -> None:
        """All non-debian patterns are dead when file list is empty."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", MINIMAL_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        result = pc.unmatched_patterns([])
        assert sorted(result) == ["intel/*", "realtek/*"]


# -- Copyright content with resolved licenses (standalone paragraphs) --

RESOLVED_COPYRIGHT = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: linux-firmware
Upstream-Contact: linux-firmware@kernel.org
Source: https://git.kernel.org/pub/scm/linux/firmware/linux-firmware.git

Files: debian/*
Copyright: 2026 Canonical Ltd.
License: GPL-2+

Files: intel/*
Copyright: 2014, Intel Corporation.
License: Redistributable-ibt

License: Redistributable-ibt
 Copyright 2014, Intel Corporation.
 Redistribution permitted.

License: GPL-2+
 See /usr/share/common-licenses/GPL-2.
"""

INLINE_LICENSE_COPYRIGHT = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: linux-firmware
Upstream-Contact: linux-firmware@kernel.org
Source: https://git.kernel.org/pub/scm/linux/firmware/linux-firmware.git

Files: debian/*
Copyright: 2026 Canonical Ltd.
License: GPL-2+
 See /usr/share/common-licenses/GPL-2.

Files: intel/*
Copyright: 2014, Intel Corporation.
License: Redistributable-ibt
 Copyright 2014, Intel Corporation.
 Redistribution permitted.
"""

UNRESOLVED_COPYRIGHT = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: linux-firmware
Upstream-Contact: linux-firmware@kernel.org
Source: https://git.kernel.org/pub/scm/linux/firmware/linux-firmware.git

Files: debian/*
Copyright: 2026 Canonical Ltd.
License: GPL-2+

Files: intel/*
Copyright: 2014, Intel Corporation.
License: Redistributable-ibt

License: GPL-2+
 See /usr/share/common-licenses/GPL-2.
"""

ORPHANED_COPYRIGHT = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: linux-firmware
Upstream-Contact: linux-firmware@kernel.org
Source: https://git.kernel.org/pub/scm/linux/firmware/linux-firmware.git

Files: debian/*
Copyright: 2026 Canonical Ltd.
License: GPL-2+

Files: intel/*
Copyright: 2014, Intel Corporation.
License: Redistributable-ibt

License: Redistributable-ibt
 Copyright 2014, Intel Corporation.
 Redistribution permitted.

License: GPL-2+
 See /usr/share/common-licenses/GPL-2.

License: Unused-license
 This license is not referenced by any Files stanza.
"""


class TestUnresolvedLicenses:
    """Tests for PackageCopyright.unresolved_licenses()."""

    def test_all_resolved(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns empty list when all license references are resolved."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", RESOLVED_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        assert pc.unresolved_licenses() == []

    def test_inline_text_not_flagged(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Licenses with inline text don't need a standalone paragraph."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", INLINE_LICENSE_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        assert pc.unresolved_licenses() == []

    def test_unresolved_detected(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns synopses that have no standalone License: paragraph."""
        repo, tmp_path = git_repo
        # Redistributable-ibt is referenced but has no standalone paragraph
        commit_file(repo, "ubuntu/package/test/copyright", UNRESOLVED_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        assert pc.unresolved_licenses() == ["Redistributable-ibt"]

    def test_no_duplicates(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Same unresolved license referenced by multiple stanzas is listed once."""
        repo, tmp_path = git_repo
        # Two stanzas reference the same unresolved license
        content = (
            "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
            "Upstream-Name: linux-firmware\n\n"
            "Files: debian/*\n"
            "Copyright: 2026 Canonical Ltd.\n"
            "License: GPL-2+\n\n"
            "Files: intel/*\n"
            "Copyright: 2014, Intel Corporation.\n"
            "License: Missing-License\n\n"
            "Files: realtek/*\n"
            "Copyright: 2024, Realtek.\n"
            "License: Missing-License\n\n"
            "License: GPL-2+\n"
            " See /usr/share/common-licenses/GPL-2.\n"
        )
        commit_file(repo, "ubuntu/package/test/copyright", content)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        assert pc.unresolved_licenses() == ["Missing-License"]


class TestOrphanedLicenses:
    """Tests for PackageCopyright.orphaned_licenses()."""

    def test_no_orphans(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns empty list when all standalone paragraphs are referenced."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", RESOLVED_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        assert pc.orphaned_licenses() == []

    def test_orphan_detected(self, git_repo: tuple[git.Repo, Path]) -> None:
        """Returns synopses of standalone paragraphs not referenced by any Files: stanza."""
        repo, tmp_path = git_repo
        commit_file(repo, "ubuntu/package/test/copyright", ORPHANED_COPYRIGHT)

        pc = PackageCopyright(Path("ubuntu/package/test/copyright"))
        assert pc.orphaned_licenses() == ["Unused-license"]
