#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
#
# Copy firmware files based on WHENCE list
#

verbose=:
# shellcheck disable=SC2209
compress=cat
compext=
destdir=
num_jobs=1

usage() {
    echo "Usage: $0 [-v] [-jN] [--xz|--zstd] <destination directory>"
}

err() {
    printf "ERROR: %s\n" "$*"
    usage
    exit 1
}

warn() {
    printf "WARNING: %s\n" "$*"
}

has_gnu_parallel() {
    if command -v parallel > /dev/null; then
        # The moreutils package comes with a simpler version of "parallel"
        # that does not support the --version or -a options.  Check for
        # that first.  In some distros, installing the "parallel" package
        # will replace the moreutils version with the GNU version.
        if ! parallel --version > /dev/null 2>&1; then
            return 1
        fi
        if parallel --version | grep -Fqi 'gnu parallel'; then
           return 0
        fi
    fi
    return 1
}

while test $# -gt 0; do
    case $1 in
        -v | --verbose)
            # shellcheck disable=SC2209
            verbose=echo
            shift
            ;;

        -j*)
            num_jobs=$(echo "$1" | sed 's/-j//')
            num_jobs=${num_jobs:-1}
            if [ "$num_jobs" -gt 1 ] && ! has_gnu_parallel; then
                    err "the GNU parallel command is required to use -j"
            fi
            parallel_args_file=$(mktemp)
            trap 'rm -f $parallel_args_file' EXIT INT QUIT TERM
            shift
            ;;

        --xz)
            if test "$compext" = ".zst"; then
                err "cannot mix XZ and ZSTD compression"
            fi
            compress="xz --compress --quiet --stdout --check=crc32"
            compext=".xz"
            shift
            ;;

        --zstd)
            if test "$compext" = ".xz"; then
                err "cannot mix XZ and ZSTD compression"
            fi
            # shellcheck disable=SC2209
            compress="zstd --compress --quiet --stdout"
            compext=".zst"
            shift
            ;;

        -h|--help)
            usage
            exit 1
            ;;

        -*)
            # Ignore anything else that begins with - because that confuses
            # the "test" command below
            warn "ignoring option $1"
            shift
            ;;

        *)
            if test -n "$destdir"; then
                err "unknown command-line options: $*"
            fi

            destdir="$1"
            shift
            ;;
    esac
done

if test -z "$destdir"; then
    err "destination directory was not specified"
fi

if test -d "$destdir"; then
    find "$destdir" -type d -empty >/dev/null || warn "destination folder is not empty."
fi

if test -e .git/config; then
    $verbose "Checking that WHENCE file is formatted properly"
    ./check_whence.py || err "check_whence.py has detected errors."
fi

# shellcheck disable=SC2162 # file/folder name can include escaped symbols
grep -h -E '^(RawFile|File):' WHENCE WHENCE.ubuntu | sed -E -e 's/^(RawFile|File): */\1 /;s/"//g' | while read k f; do
    install -d "$destdir/$(dirname "$f")"
    $verbose "copying/compressing file $f$compext"
    if test "$compress" != "cat" && test "$k" = "RawFile"; then
        $verbose "compression will be skipped for file $f"
        if [ "$num_jobs" -gt 1 ]; then
            echo "cat \"$f\" > \"$destdir/$f\"" >> "$parallel_args_file"
        else
            cat "$f" > "$destdir/$f"
        fi
    else
        if [ "$num_jobs" -gt 1 ]; then
            echo "$compress \"$f\" > \"$destdir/$f$compext\"" >> "$parallel_args_file"
        else
            $compress "$f" > "$destdir/$f$compext"
        fi
    fi
done
if [ "$num_jobs" -gt 1 ]; then
    parallel -j"$num_jobs" -a "$parallel_args_file"
    echo > "$parallel_args_file" # prepare for next run
fi

# shellcheck disable=SC2162 # file/folder name can include escaped symbols
grep -h -E '^Link:' WHENCE WHENCE.ubuntu | sed -e 's/^Link: *//g;s/-> //g' | while read l t; do
    directory="$destdir/$(dirname "$l")"
    install -d "$directory"
    target="$(cd "$directory" && realpath -m -s "$t")"
    if test -e "$target"; then
        $verbose "creating link $l -> $t"
        if [ "$num_jobs" -gt 1 ]; then
            echo "ln -s \"$t\" \"$destdir/$l\"" >> "$parallel_args_file"
        else
            ln -s "$t" "$destdir/$l"
        fi
    else
        $verbose "creating link $l$compext -> $t$compext"
        if [ "$num_jobs" -gt 1 ]; then
            echo "ln -s \"$t$compext\" \"$destdir/$l$compext\"" >> "$parallel_args_file"
        else
            ln -s "$t$compext" "$destdir/$l$compext"
        fi
    fi
done
if [ "$num_jobs" -gt 1 ]; then
    parallel -j"$num_jobs" -a "$parallel_args_file"
fi

# Verify no broken symlinks
if test "$(find "$destdir" -xtype l | wc -l)" -ne 0 ; then
    err "Broken symlinks found:\n$(find "$destdir" -xtype l)"
fi

exit 0

# vim: et sw=4 sts=4 ts=4
