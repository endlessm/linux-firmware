# Ubuntu Firmware Packaging Tools

Tools for splitting linux-firmware into Ubuntu Debian packages.

> Note: This code was developed with AI assistance (Claude).

## Development Workflow

### Rebase to newer upstream

```sh
$ ubuntu/bin/rebase-upstream [REV]
```

### Update package files following the rebase

```sh
$ ubuntu/bin/update-packages
$ ubuntu/bin/commit-packages

# Run checks, which should fail if firmware files were added or deleted by the rebase
# Update the package files (ubuntu/package/*/files) accordingly
$ ubuntu/bin/check-packages
```

### Create package releases

```sh
# Update and commit the changelogs of all packages
$ ubuntu/bin/update-changelogs
$ ubuntu/bin/commit-releases
```

### Build new orig tarballs and source packages

```sh
$ ubuntu/bin/create-orig-tarballs
$ ubuntu/bin/build-packages -- -S -sa
```

## SRU Workflow

### Create initial dummy SRU releases

```sh
$ ubuntu/bin/update-changelogs --sru
$ ubuntu/bin/commit-releases
```

### Create package release

```sh
# Update and commit the package files
$ ubuntu/bin/update-package <package>
$ ubuntu/bin/commit-package <package>

# Run checks
$ ubuntu/bin/check-packages

# Update the changelog and commit the release
$ ubuntu/bin/update-changelog <package>
$ ubuntu/bin/commit-release <package>

# Build the source package
$ ubuntu/bin/build-package <package> -- -S
```

## Miscellaneous Steps

### Review source package

```sh
$ ubuntu/bin/create-debdiff <package>
$ ubuntu/bin/review-debdiff <package>
```

### Upload source package

```sh
# To a PPA
$ ubuntu/bin/dput-package <package> ppa:foo/bar

# To the archive (simulated)
$ ubuntu/bin/dput-package <package> -s ubuntu

# To the archive (for real)
$ ubuntu/bin/dput-package <package> ubuntu
```

### No-change rebuild

```sh
$ ubuntu/bin/update-changelog <package> --rebuild
$ ubuntu/bin/commit-release <package>
```

## Development

Dependencies:

- gitpython
- python-debian
- requests

Run tests:

```sh
$ pytest ubuntu
```

Run linter, formatter and type checker:

```sh
$ ubuntu/bin/lint
```
