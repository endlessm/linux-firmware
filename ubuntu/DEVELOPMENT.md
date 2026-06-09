# Development Guide

## Overview

### Directory Structure

```
ubuntu/
  bin/                     CLI scripts (entry points)
  lib/                     Shared library
    git_files.py             GitFiles base class (pathspec resolution via git)
    whence.py                WHENCE parsing + license extraction
    package.py               PackageFiles, Package, PackageWhence
    changelog.py             Debian changelog handling
  debian/                    Shared Debian packaging files (rules, postinst, etc.)
  templates/                 Templates for generating package files
  package/<pkg>/
    files                    Included/excluded pathspecs
    WHENCE                   Package-specific WHENCE (generated)
    changelog                Debian changelog
    control                  Debian control file
    copyright                Debian copyright file
    patches/                 Single-patch quilt series
    source/                  include-binaries list
  tests/                     pytest test suite
  unpackaged                 Files deliberately not in any package
  upstream                   COMMIT= and VERSION= of upstream base
```

### Data Flow

```
                            WHENCE* (upstream)
                                 |
                                 | parse_sections()
                                 v
                        +------------------+
                        |     Sections     |
                        +------------------+
                         /                \
        section_paths() /                  \ section_file_licenses(section, tree_files)
                       v                    v
                Firmware Paths         (file, license) pairs
                       |                    |
                       v                    v
            PackageWhence.update()     Whence.licenses(files) -> GitFiles
            (filter by package files)       |
                       |                    |
                       v                    |
       ubuntu/package/<pkg>/WHENCE          |
                 |                          |
                 | Whence.files.paths()     |
                 v                          v
          Package.check()         Package.orig.paths()
          (verify all packaged    (files + licenses + WHENCE)
           files are in WHENCE)            |
                                           v
                                  create-orig-tarball
                                  (git archive at upstream_commit)
                                           |
                                           v
                                      orig tarball
```

## Architecture

The packaging toolset consists of a Python library (`lib/`) and CLI scripts (`bin/`).

### Library Modules

- **lib/git_files.py** — `GitFiles` class for resolving file pathspecs against
  `git ls-tree` (committed state) or `git ls-files` (worktree). Provides
  `paths()`, `exists()`, `read()`, `tree()`, and `entries()` methods. `PathSpecs`
  provides pure include/exclude pattern matching.

- **lib/whence.py** — Parses WHENCE files into sections, extracts firmware file
  paths (`section_paths`) and file-to-license mappings (`section_file_licenses`)
  from each section. The `Whence` class provides lazy loading from git at a given
  commit, with glob support for matching multiple WHENCE files.

- **lib/package.py** — Package management: file list expansion via git pathspecs
  (`PackageFiles`, subclass of `GitFiles`), package-specific WHENCE generation
  (`PackageWhence`), delta/patch computation (`Package.update_delta`), and
  validation checks (`Package.check` with sub-checks: `check_excluded_subset`,
  `check_packaged_files`, `check_whence_coverage`, `check_copyright_coverage`,
  `check_orig_tarball`).

- **lib/copyright.py** — DEP-5 copyright file parsing (`PackageCopyright`).
  Lazily loads from git at a given commit, wrapping `python-debian`'s
  `Copyright` class. Provides `file_licenses()` (file-to-license mapping),
  `has_debian_stanza()`, and `unmatched_patterns()` (dead pattern detection).

- **lib/changelog.py** — Debian changelog parsing, version bumping, release
  formatting, and commit message generation.

### Key Design Decisions

- All file operations go through git. When `commit` is set, uses `ls-tree` and
  `show`; when `commit=None`, uses `ls-files` and reads the working tree
  directly. Scripts that need committed state (e.g., `update-package`,
  `list-package-files`) pass `"HEAD"` explicitly.

- Each `Package`, `PackageFiles`, `GitFiles`, `Whence`, etc. instance takes an
  optional `commit` parameter (default: `None`, meaning worktree).

## WHENCE Parsing

The upstream `WHENCE` file documents firmware origin and licensing. It is divided
into sections separated by lines of dashes (`----------`).

Each section typically contains:
- `Driver:` — the kernel driver
- `File:`, `RawFile:`, `Source:` — firmware file paths
- `Link:` — symlinks (`link -> target`, resolved relative to link directory)
- `Licence:` or `License:` — licensing information

### Path Extraction

`section_paths(section)` yields resolved file paths from `File:`, `RawFile:`,
`Source:`, and `Link:` lines.

### License File Extraction

`section_file_licenses(section, tree_files)` yields `(file_path, license_path)`
pairs from a section by:

1. Accumulating file paths from `File:`/`RawFile:`/`Source:` lines
2. When a `Licence:`/`License:` line is encountered, extracting license file
   paths by tokenizing the line value, stripping trailing punctuation (`. , ; )`),
   and intersecting with `tree_files`
3. Yielding `(file, license)` for each accumulated file x each license path
4. Resetting the file accumulator when a new `File:`/`RawFile:`/`Source:` line
   appears after a licence line (Link lines are ignored)
5. Yielding `(file, None)` for files with no associated licence line

This handles sections with multiple interleaved file/licence groups, as well as
consecutive licence lines that apply to the same set of files.

`Whence.licenses(files=None)` aggregates license paths across all sections. When
`files` is provided, returns only licenses that apply to those specific files.
`Package.licenses` uses this to return only the license files needed for the
packaged firmware files.

## Package Files

Each package's file list lives in `ubuntu/package/<pkg>/files`. The format:

```text
# List of files and directories to be included in the package

amdgpu/
radeon/

# List of files and directories to be excluded from the package

!amdgpu/obsolete.bin
```

Lines are git pathspecs. Directories (trailing `/`) match all contents.
Exclusions are prefixed with `!`. `PackageFiles` resolves these against
`git ls-tree` at a given commit to produce the concrete file list.

## License Files

License files are **not** listed in package file lists. They are computed on
the fly from WHENCE `Licence:`/`License:` lines. This is used in:

- **create-orig-tarball** — license files are included in the tarball alongside
  firmware files
- **check-packages** — license files are accounted for in the "all files
  packaged or excluded" cross-package check
- **list-package-files --licenses** — lists per-package license files

## Package Delta (Patches)

`Package.update_delta()` computes the difference between a package's files at
the current commit vs. the orig tarball (upstream base). It generates:

- `debian/patches/ubuntu.patch` — unified diff for new/changed text files
- `debian/source/include-binaries` — list of new/changed binary files

## Changelogs

`PackageChangelog` wraps `python-debian` changelog parsing. It supports:

- Reading the current version and base commit
- Bumping versions (upstream or revision)
- Formatting commit summaries into changelog entries
- Writing updated changelog files

## Package Build Process

Building a source package involves two steps:

### 1. Create the orig tarball (`create-orig-tarball`)

Uses `git archive` at the **upstream commit** to produce
`linux-firmware-<pkg>_<version>.orig.tar.xz` containing:

- Firmware files (from `package/<pkg>/files`, intersected with the upstream tree)
- License files (computed from WHENCE `Licence:`/`License:` lines)
- The `WHENCE` file

### 2. Build the source package (`build-package`)

Assembles a build tree under `ubuntu/build/<source-name>/`:

1. Extracts firmware files from git at the release commit (first changelog
   entry's commit)
2. Copies shared Debian packaging from `ubuntu/debian/` (rules, postinst, tests,
   etc.)
3. Overlays per-package files from `ubuntu/package/<pkg>/` (changelog, control,
   copyright, patches, source)
4. Generates `debian/control` by combining `ubuntu/templates/control.source.in`
   with the per-package control stanza, substituting `@package@` placeholders
5. Links the orig tarball into the build directory
6. Runs `dpkg-buildpackage` with any extra arguments (e.g., `-S` for
   source-only)

The meta package (`meta`) skips the firmware extraction and only copies its own
packaging files.

## Package Validation

`Package.check()` runs per-package checks:

1. Excluded files are a subset of included files
2. Packaged files == included - excluded
3. All packaged files are referenced in WHENCE

`check-packages` runs cross-package checks:

1. No file appears in multiple packages
2. Excluded files are not in `ubuntu/unpackaged`
3. All git-tracked files are either packaged, excluded, unpackaged, or license
   files

## Running Checks

```sh
# Run tests
pytest ubuntu

# Run linter, formatter, and type checker
ubuntu/bin/lint
```
