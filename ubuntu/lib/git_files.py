"""Git-tracked file list resolution for firmware packages."""

import git
from pathspec import GitIgnoreSpec

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class GitFilesError(Exception):
    """Raised when a git file operation fails."""


def _split_pathspecs(pathspecs: list[str]) -> tuple[list[str], list[str]]:
    """Separate pathspecs into (included, excluded) lists, stripping the ! prefix."""
    included = [entry for entry in pathspecs if not entry.startswith("!")]
    excluded = [entry[1:] for entry in pathspecs if entry.startswith("!")]
    return included, excluded


def _normalize_pathspecs(pathspecs: list[str]) -> list[str]:
    """Normalize git pathspecs: strip ':(glob)' prefix and replace ':^' with '!'."""
    result = []
    for p in pathspecs:
        p = p.removeprefix(":(glob)")
        if p.startswith(":^"):
            p = "!" + p[2:]
        result.append(p)
    return result


class PathSpecs:
    """Resolves include/exclude pathspecs against a set of file paths."""

    def __init__(self, pathspecs: list[str] | None = None) -> None:
        self._pathspecs = _normalize_pathspecs(pathspecs or [])

    def pathspecs(self, opt: str | None = None) -> list[str]:
        """Return raw pathspecs, optionally filtered by 'included' or 'excluded'."""
        if opt == "included":
            return _split_pathspecs(self._pathspecs)[0]
        if opt == "excluded":
            return _split_pathspecs(self._pathspecs)[1]
        return self._pathspecs

    def match_files(self, paths: list[str], opt: str | None = None, strict: bool = True) -> list[str]:
        """Return paths matching include specs minus those matching exclude specs.

        Raises GitFilesError if strict=True and any pattern matches nothing.
        """
        ps_included, ps_excluded = _split_pathspecs(self.pathspecs(opt))
        included = ["/" + p for p in ps_included]
        excluded = ["/" + p for p in ps_excluded]

        included_paths = set(GitIgnoreSpec.from_lines(included).match_files(paths))
        excluded_paths = set(GitIgnoreSpec.from_lines(excluded).match_files(included_paths))

        if strict:
            unmatched = [p for p in included if not any(GitIgnoreSpec.from_lines([p]).match_files(paths))]
            if unmatched:
                raise GitFilesError(f"Invalid include pathspec: {unmatched}")

            unmatched = [p for p in excluded if not any(GitIgnoreSpec.from_lines([p]).match_files(included_paths))]
            if unmatched:
                raise GitFilesError(f"Invalid exclude pathspec: {unmatched}")

        return sorted([str(p) for p in (included_paths - excluded_paths)])


class GitFiles:
    """A set of git-tracked files, optionally filtered by pathspecs, at a commit or worktree."""

    def __init__(self, commit: str | None = None, pathspecs: list[str] | None = None, strict: bool = True) -> None:
        self.commit = commit
        self._pathspecs = PathSpecs(pathspecs) if pathspecs is not None else None
        self._strict = strict
        self._repo = git.Repo()

    def pathspecs(self, opt: str | None = None) -> list[str]:
        """Return raw pathspecs, optionally filtered by 'included' or 'excluded'."""
        if self._pathspecs:
            return self._pathspecs.pathspecs(opt)
        return []

    def paths(self, opt: str | None = None) -> list[str]:
        """Return file paths matching pathspecs at the given commit or worktree.

        When commit is set, uses git ls-tree. Otherwise uses git ls-files (index).
        Returns all tracked paths if pathspecs were not provided (None).
        Returns empty list if pathspecs were provided but empty.
        """
        if opt and not self._pathspecs:
            raise GitFilesError(f"GitFiles().paths(opt={opt}) requires pathspecs")

        try:
            if self.commit:
                output = self._repo.git.ls_tree("-r", "--name-only", self.commit)
            else:
                output = self._repo.git.ls_files()
        except git.GitCommandError as e:
            raise GitFilesError(str(e)) from e

        all_paths = sorted(output.splitlines())

        if self._pathspecs:
            return self._pathspecs.match_files(all_paths, opt=opt, strict=self._strict)
        return all_paths

    def tree(self, opt: str | None = None) -> list[tuple[str, str, str]]:
        """Return (mode, sha1, path) tuples for matched files. Requires a commit."""
        if not self.commit:
            raise GitFilesError("GitFiles.tree() requires a commit")

        paths = self.paths(opt)
        try:
            output = self._repo.git.ls_tree("-r", self.commit, "--", *paths)
        except git.GitCommandError as e:
            raise GitFilesError(str(e)) from e

        ls_tree: dict[str, tuple[str, str]] = {}
        for line in output.splitlines():
            meta, _, path = line.partition("\t")
            mode, _, sha1 = meta.split()
            ls_tree[path] = (mode, sha1)

        return [(mode, sha1, path) for path, (mode, sha1) in ls_tree.items()]

    def entries(self, opt: str | None = None) -> list[tuple[str, str, str, str]]:
        """Return (mode, type, sha1, path) tuples. Type is 'text', 'binary', or 'link'.

        Requires a commit.
        """
        if not self.commit:
            raise GitFilesError("GitFiles.entries() requires a commit")

        tree = self.tree(opt)
        file_types: dict[str, str] = {}
        non_links = []
        for mode, _, path in tree:
            if mode == "120000":
                file_types[path] = "link"
            else:
                non_links.append(path)

        if non_links:
            try:
                output = self._repo.git.diff_tree("--numstat", EMPTY_TREE, self.commit, "--", *non_links)
            except git.GitCommandError as e:
                raise GitFilesError(str(e)) from e
            for line in output.splitlines():
                added, _, path = line.split("\t")
                file_types[path] = "binary" if added == "-" else "text"

        return [(mode, file_types[path], sha1, path) for mode, sha1, path in tree]

    def exists(self, path: str) -> bool:
        """Check if a file exists in this tree."""
        return path in self.paths()

    def read(self, path: str) -> str:
        """Read file contents from the commit or worktree.

        Raises GitFilesError if the file cannot be read.
        """
        try:
            if self.commit:
                return str(self._repo.git.show(f"{self.commit}:{path}"))
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except (git.GitCommandError, OSError) as e:
            raise GitFilesError(str(e)) from e
