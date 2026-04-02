# GitHub Actions workflows

This directory contains the repository's CI, release, update, and feed
publication workflows. Repo-level automation inside these workflows should call
`uv run squid4win-automation ...` for build, validation, packaging, and metadata
tasks rather than reviving repo-wide PowerShell orchestration.

## Core validation workflows

- `ci.yml` - runs MegaLinter, `ty`, the Python `tray-build` command (`.NET 10`
  tray app), the Python `squid-build` command (native MSYS2/MinGW bundle), the
  Python `smoke-test` command, and SonarQube analysis.
- `service-runner-validation.yml` - runs on an isolated Windows runner, runs the
  Python `squid-build` command, runs the Python `smoke-test` command, then runs
  the Python `service-runner-validation` command to exercise MSI install/start/
  stop/uninstall behavior.

## Release-building workflows

- `build-release-artifacts.yml` - reusable workflow that runs the Python
  `squid-build` command, validates with the Python `smoke-test` command, runs
  the Python `bundle-package` command to produce `squid4win-portable.zip` and
  `squid4win.msi`, and uploads release artifacts plus integrity sidecars.
- `prerelease.yml` - tag-driven wrapper around
  `build-release-artifacts.yml` for prerelease publication.
- `release.yml` - tag-driven wrapper around
  `build-release-artifacts.yml` for stable release publication after approval.

## Dependency and update workflows

- `update-upstream.yml` - checks upstream Squid releases, updates the pinned
  version metadata through Python automation, and opens a pull request.
- `conan-update.yml` - refreshes the committed Conan lockfile and opens or
  updates a pull request.
- `dependabot-auto-merge.yml` - enables auto-merge for trusted automation pull
  requests that satisfy the repository policy.

## Downstream package-manager workflows

- `package-managers.yml` - downloads published release artifacts and generates
  winget, Chocolatey, and Scoop metadata from the real binaries.
- `package-manager-publish.yml` - manual, credential-gated publication workflow
  that reuses generated metadata and publishes only the selected feeds.
