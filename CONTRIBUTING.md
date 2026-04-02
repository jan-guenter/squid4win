# Contributing to squid4win

Thanks for helping improve squid4win.

This repository is in an architecture transition. Good contributions keep the
current checked-in implementation working while moving the project toward the
accepted target state in ADR `0006`.

## Read first

Before you open a pull request or propose a non-trivial change, read:

- `README.md`
- `AGENTS.md`
- `.github\README.md`
- `.agents\design\0005-quality-and-distribution-automation.md`
- `.agents\design\0006-target-state-architecture-reset.md`

Those files are the source of truth for contributor guidance, workflow intent,
and the distinction between validated behavior and planned target-state work.

## Project direction

Keep your change aligned with these current project rules:

- the repo root `conanfile.py` is the single primary Conan recipe for the
  native Squid build only; Python 3.14 + `uv` owns stage assembly, runtime DLL
  adjacency, notice harvesting, smoke testing, bundle packaging, and
  service-runner validation orchestration
- repo-level automation is moving to Python 3.14 + `uv`
- the tray app is moving toward a direct `.NET 10` build from
  `src\tray\Squid4Win.Tray`
- PowerShell is a narrow Windows exception for MSI custom actions,
  installer-time helpers, and short-term compatibility shims that cannot yet be
  retired
- the repository's own code and docs are GPL-2.0-or-later

## Current implementation versus target state

The checked-in core build, staging, validation, and packaging workflows now use
Python 3.14 + `uv` and the direct `.NET 10` tray build path. The major
repo-level PowerShell orchestration scripts have been removed; the remaining
`scripts\*.ps1` files are narrow exceptions: the installed-payload service
helper, optional Authenticode signing, the version-update fallback, and small
utilities.

When you add new contributor or CI automation:

- prefer the Python automation package and `uv` entry points over adding new
  repo-level PowerShell orchestration
- do not reintroduce tray-through-Conan packaging as the target model
- keep documentation explicit about whether a statement describes today's
  implementation, a validated historical path, or the intended target state

## Ways to contribute

### Report a bug

Use the bug issue template for reproducible problems in source, build,
installer, release, or workflow behavior.

### Propose a feature or change

Use the feature request template for features, workflow reshaping,
architecture ideas, or release-process improvements.

### Send a pull request

Pull requests are welcome for code, docs, automation, packaging, and quality
improvements when they stay within the current repository contracts.

## Ground rules

- Keep `CONAN_HOME` repo-local at `.\.conan2`.
- Do not split the native Windows build back into multiple primary Conan
  recipes.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conandata.yml` aligned when the Squid pin changes. Prefer
  `uv run squid4win-automation upstream-version --execute` for that update flow;
  keep `.\scripts\Update-SquidVersion.ps1` only as a transitional fallback when
  the Python automation environment is unavailable.
- Preserve artifact names `squid4win.msi` and `squid4win-portable.zip` unless
  you also update the downstream package metadata flow in the same change.
- Keep live package-feed publication credential-gated.
- Do not hand-edit externally synced content under `.agents\skills\`.
  Keep repo-owned skills under `skills\` and expose them in
  `.agents\skills\` through mirror directories backed by symlinked files.
- Do not copy source code from `diladele/squid-windows`.
- Never commit secrets, certificates, tokens, or machine-specific paths.
- Do not claim clean-host installer proof, installed-service plus tray
  lifecycle proof, or full target-state validation unless you actually ran and
  captured that validation.

## Preparing a change

Try to keep each pull request focused on one concern.

If your change affects contributor-facing behavior, update the matching docs in
the same pull request. Typical pairings are:

- workflow changes with `.github\README.md`
- contributor-process changes with `CONTRIBUTING.md`, `SUPPORT.md`, or
  `.github\SECURITY.md`
- architecture changes with the relevant ADR under `.agents\design\`
- release or package-manager changes with the related scripts, workflows, and
  docs together

## Validation

Run the existing validation that matches your change.

The main repository lint job now runs MegaLinter plus `ty`.

If Docker is available locally, the closest match to CI is:

```powershell
npx --yes mega-linter-runner --release v9.4.0
uv sync --locked
uv run ty check src
```

For Markdown-only or community-file changes, the lightweight repo-local spot
check is still:

```powershell
npx --yes markdownlint-cli2 --no-globs CONTRIBUTING.md CODE_OF_CONDUCT.md SUPPORT.md .github\README.md .github\SECURITY.md .github\PULL_REQUEST_TEMPLATE.md
```

If you change workflows, scripts, or product code, use the existing repository
validation paths instead of inventing new ones. Keep your pull request clear
about which commands ran and which target-state claims are still pending.

## Pull request expectations

A good pull request for this repository:

- explains whether it targets the current checked-in implementation, the
  accepted target-state migration, or both
- lists the validation you ran
- keeps docs truthful about current versus planned behavior
- updates related automation, packaging, and documentation together when a
  contract changes

## Licensing

By contributing to squid4win, you agree that your contribution is provided under
the repository's GPL-2.0-or-later licensing terms. Keep existing third-party
notices intact when a change touches bundled or vendored content.
