# GitHub automation and community files

This directory contains GitHub-facing automation, policy, and contributor
metadata for squid4win.

The repository is in transition. ADR `0006` defines the target state:

- one self-contained native Squid Conan recipe under `conan\recipes\squid\all\`
- Python 3.14 + `uv` for repo-level automation
- a direct `.NET 10` tray build from `src\tray\Squid4Win.Tray`
- PowerShell kept narrow to installer-time Windows needs

Some workflows still exercise the last cited PowerShell-based implementation and
older tool versions. Keep that distinction explicit when you edit or document
workflow behavior.

## Directory map

| Path | Purpose |
| --- | --- |
| `.github\README.md` | This reference for GitHub-facing files and workflows. |
| `.github\SECURITY.md` | Security reporting policy. |
| `.github\PULL_REQUEST_TEMPLATE.md` | Pull request checklist for repo contracts and validation notes. |
| `.github\ISSUE_TEMPLATE\` | GitHub issue forms for bugs and feature requests. |
| `.github\copilot-instructions.md` | Repo-specific Copilot guidance. |
| `.github\dependabot.yml` | Dependabot rules for GitHub Actions and the pinned Conan CLI dependency. |
| `.github\instructions\` | Additional contributor and review instruction files. |
| `.github\workflows\` | CI, release, maintenance, and publication workflows. |

## Workflow reference

| Workflow | Triggers | Purpose | Current notes |
| --- | --- | --- | --- |
| `ci.yml` | Pull requests, pushes to `main`, manual dispatch | Lints Markdown, workflows, PowerShell, Python, and C#; builds the tray package path; builds the native Squid path; validates the Linux Squid recipe matrix; smoke-tests the staged result; optionally runs SonarQube scanning. | Active. Python automation now runs through `uv` on Python 3.14, the tray build uses the direct `.NET 10` path, and the native build runs through the Python CLI around the CCI-style Squid recipe under `conan\recipes\squid\all\`. |
| `conan-validate-recipe.yml` | Reusable `workflow_call` | Validates the Linux Squid recipe with `conan create` for a caller-supplied host profile. | Active reusable validation path for Linux GCC and Clang scenarios driven from `ci.yml`. |
| `build-release-artifacts.yml` | Reusable `workflow_call` | Builds release artifacts, stages the payload, creates the portable zip, builds the MSI, generates checksums, and attempts signing and GitHub artifact attestations. | Active reusable workflow for `release.yml` and `prerelease.yml`. The workflow now sets up Python 3.14 + `uv`, uses the Python CLI for build and bundle orchestration, and still depends on Windows-specific signing and installer helper paths where required. |
| `release.yml` | `v*` tag pushes and manual dispatch | Verifies that a stable tag points to a commit reachable from `main`, then calls the reusable release builder for stable assets and GitHub release publication. | Active stable-release path. The workflow does not make clean-host or end-to-end installed-service claims by itself. |
| `prerelease.yml` | `v*-*` tag pushes and manual dispatch | Verifies that a prerelease tag points to a commit reachable from `main`, then calls the reusable release builder with prerelease publication enabled. | Active prerelease path. Downstream package-manager publication remains stable-release only. |
| `service-runner-validation.yml` | Manual dispatch, selected pull-request paths, selected pushes to `main` | Builds the current installer path and validates install, service lifecycle, and uninstall behavior on a GitHub-hosted Windows runner. | Active runner validation. It now uses Python 3.14 + `uv` for the native build path and the Python `service-runner-validation` entry point for install/service assertions. |
| `update-upstream.yml` | Weekly schedule and manual dispatch | Updates Squid version metadata and opens a pull request when the pinned upstream release changes. | Active. The workflow now runs the Python 3.14 + `uv` upstream-version helper instead of the previous direct PowerShell version-update script. |
| `conan-update.yml` | Weekly schedule and manual dispatch | Refreshes the committed Conan lockfile and opens an automation pull request. | Active maintenance workflow. Python automation setup now uses `uv` on Python 3.14, and the lockfile refresh runs through the Python CLI. |
| `package-managers.yml` | Published releases, manual dispatch, reusable `workflow_call` | Downloads the released MSI and portable zip, then generates winget, Chocolatey, and Scoop metadata from those real binaries. | Active metadata-generation path. Python 3.14 + `uv` now owns metadata export through the Python CLI, prereleases are intentionally excluded, and the workflow does not publish feeds by itself. |
| `package-manager-publish.yml` | Manual dispatch | Validates requested targets, reuses generated package-manager metadata, and performs credential-gated publication to the selected feeds. | Active manual publication path. Python 3.14 + `uv` now owns the publication wrappers too, while feed publication stays gated by environment approval, secrets, and explicit per-feed inputs. |
| `dependabot-auto-merge.yml` | `pull_request_target` events | Enables auto-merge for trusted Dependabot or repository automation pull requests that touch only allowlisted files. | Active safeguard workflow. It intentionally stays narrow. |

## Supporting configuration

- `dependabot.yml` manages GitHub Actions plus the Python automation dependency
  graph in `pyproject.toml` and `uv.lock`.
- `copilot-instructions.md` mirrors the current repository contracts for AI
  contributors and should stay aligned with `README.md`, `AGENTS.md`,
  `CONTRIBUTING.md`, and the accepted ADRs.

## Workflow editing guardrails

When you update anything under `.github\workflows\`:

- keep documentation truthful about validated behavior versus target-state goals
- do not add new repo-level PowerShell orchestration when the change should land
  in Python 3.14 + `uv` automation instead
- do not reintroduce tray-through-Conan packaging as the intended end state
- preserve credential-gated publication flows
- preserve artifact names `squid4win.msi` and `squid4win-portable.zip` unless
  downstream metadata and docs change with them
