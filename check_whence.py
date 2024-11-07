#!/usr/bin/env python3

import os, re, stat, sys
from io import open


def list_whence(whence_file):
    with open(whence_file, encoding="utf-8") as whence:
        for line in whence:
            match = re.match(r'(?:RawFile|File|Source):\s*"(.*)"', line)
            if match:
                yield match.group(1)
                continue
            match = re.match(r"(?:RawFile|File|Source):\s*(\S*)", line)
            if match:
                yield match.group(1)
                continue
            match = re.match(
                r"Licen[cs]e: (?:.*\bSee (.*) for details\.?|(\S*))\n", line
            )
            if match:
                if match.group(1):
                    for name in re.split(r", | and ", match.group(1)):
                        yield name
                    continue
                if match.group(2):
                    # Just one word - may or may not be a filename
                    if not re.search(
                        r"unknown|distributable", match.group(2), re.IGNORECASE
                    ):
                        yield match.group(2)
                        continue


def list_whence_files(whence_file):
    with open(whence_file, encoding="utf-8") as whence:
        for line in whence:
            match = re.match(r"(?:RawFile|File):\s*(.*)", line)
            if match:
                yield match.group(1).replace(r"\ ", " ").replace('"', "")
                continue


def list_links_list(whence_file):
    with open(whence_file, encoding="utf-8") as whence:
        for line in whence:
            match = re.match(r"Link:\s*(.*)", line)
            if match:
                linkname, target = match.group(1).split("->")

                linkname = linkname.strip().replace(r"\ ", " ").replace('"', "")
                target = target.strip().replace(r"\ ", " ").replace('"', "")

                # Link target is relative to the link
                target = os.path.join(os.path.dirname(linkname), target)
                target = os.path.normpath(target)

                yield (linkname, target)
                continue


def list_git():
    git_files = os.popen("git ls-files")
    for line in git_files:
        yield line.rstrip("\n")

    if git_files.close():
        sys.stderr.write("W: git file listing failed, skipping some validation\n")


def main():
    ret = 0
    whence_list = list(list_whence("WHENCE")) + list(list_whence("WHENCE.ubuntu"))
    whence_files = list(list_whence_files("WHENCE")) + list(
        list_whence_files("WHENCE.ubuntu")
    )
    links_list = list(list_links_list("WHENCE")) + list(
        list_links_list("WHENCE.ubuntu")
    )
    whence_links = list(zip(*links_list))[0]
    known_files = set(name for name in whence_list if not name.endswith("/")) | set(
        [
            ".codespell.cfg",
            ".editorconfig",
            ".gitea/workflows/pr_check.yaml",
            ".gitignore",
            ".gitlab-ci.yml",
            ".pre-commit-config.yaml",
            "Dockerfile",
            "Makefile",
            "LICENSE",
            "README.md",
            "WHENCE",
            "WHENCE.ubuntu",
            "build_packages.py",
            "check_whence.py",
            "contrib/process_linux_firmware.py",
            "contrib/templates/debian.changelog",
            "contrib/templates/debian.control",
            "contrib/templates/debian.copyright",
            "contrib/templates/rpm.spec",
            "copy-firmware.sh",
            "dedup-firmware.sh",
        ]
    )
    known_prefixes = set(name for name in whence_list if name.endswith("/"))
    git_files = set(list_git())
    executable_files = set(
        [
            "build_packages.py",
            "carl9170fw/genapi.sh",
            "carl9170fw/autogen.sh",
            "check_whence.py",
            "contrib/process_linux_firmware.py",
            "copy-firmware.sh",
            "dedup-firmware.sh",
        ]
    )

    for name in set(name for name in whence_files if name.endswith("/")):
        sys.stderr.write("E: %s listed in WHENCE as File, but is directory\n" % name)
        ret = 1

    for name in set(name for name in whence_files if whence_files.count(name) > 1):
        sys.stderr.write("E: %s listed in WHENCE twice\n" % name)
        ret = 1

    for name in set(link for link in whence_links if whence_links.count(link) > 1):
        sys.stderr.write("E: %s listed in WHENCE twice\n" % name)
        ret = 1

    for name in set(file for file in whence_files if os.path.islink(file)):
        sys.stderr.write("E: %s listed in WHENCE as File, but is a symlink\n" % name)
        ret = 1

    for name in set(link[0] for link in links_list if os.path.islink(link[0])):
        sys.stderr.write("E: %s listed in WHENCE as Link, is in tree\n" % name)
        ret = 1

    invalid_targets = set(link[0] for link in links_list)
    for link, target in sorted(links_list):
        if target in invalid_targets:
            sys.stderr.write(
                "E: target %s of link %s is also a link\n" % (target, link)
            )
            ret = 1

    for name in sorted(list(known_files - git_files) if len(git_files) else list()):
        sys.stderr.write("E: %s listed in WHENCE does not exist\n" % name)
        ret = 1

    # A link can point to a file...
    valid_targets = set(git_files)

    # ... or to a directory
    for target in set(valid_targets):
        dirname = target
        while True:
            dirname = os.path.dirname(dirname)
            if dirname == "":
                break
            valid_targets.add(dirname)

    for link, target in sorted(links_list if len(git_files) else list()):
        if target not in valid_targets:
            sys.stderr.write(
                "E: target %s of link %s in WHENCE does not exist\n" % (target, link)
            )
            ret = 1

    for name in sorted(list(git_files - known_files)):
        # Ignore subdirectory changelogs and GPG detached signatures
        if name.endswith("/ChangeLog") or (
            name.endswith(".asc") and name[:-4] in known_files
        ):
            continue

        # Ignore unknown files in known directories
        for prefix in known_prefixes:
            if name.startswith(prefix):
                break
        else:
            sys.stderr.write("E: %s not listed in WHENCE\n" % name)
            ret = 1

    for name in sorted(list(executable_files)):
        mode = os.stat(name).st_mode
        if not (mode & stat.S_IXUSR and mode & stat.S_IXGRP and mode & stat.S_IXOTH):
            sys.stderr.write("E: %s is missing execute bit\n" % name)
            ret = 1

    for name in sorted(list(git_files - executable_files)):
        if name.startswith("debian/"):
            continue
        mode = os.stat(name).st_mode
        if stat.S_ISDIR(mode):
            if not (
                mode & stat.S_IXUSR and mode & stat.S_IXGRP and mode & stat.S_IXOTH
            ):
                sys.stderr.write("E: %s is missing execute bit\n" % name)
                ret = 1
        elif stat.S_ISREG(mode):
            if mode & stat.S_IXUSR or mode & stat.S_IXGRP or mode & stat.S_IXOTH:
                sys.stderr.write("E: %s incorrectly has execute bit\n" % name)
                ret = 1
        else:
            sys.stderr.write("E: %s is neither a directory nor regular file\n" % name)
            ret = 1

    return ret


if __name__ == "__main__":
    sys.exit(main())
