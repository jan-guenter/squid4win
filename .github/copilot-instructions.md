# GitHub Copilot instructions for squid4win

Start with `README.md`, `AGENTS.md`, and ADR `0006` under `.agents\design\`.
Those files are the source of truth for repository state, contributor guidance,
and validation status. ADRs `0001` through `0004` are historical context after
the architecture reset.

Repo-specific directives:

- Preserve the target state: one self-contained native Squid Conan recipe at
  the repo root owns Squid source retrieval, patch application, native
  MSYS2/MinGW build, staged bundle assembly, and native notice/runtime
  harvesting for shipped Squid artifacts.
- Move repo-level automation toward Python 3.14 + `uv`. Do not add new
  repository-wide PowerShell orchestration for build, packaging, release, or
  contributor workflows.
- Treat `uv run squid4win-automation ...` as the supported repo-level entry
  surface for Squid builds, tray builds, bundle packaging, and Conan lockfile
  refresh.
- Build the tray app directly with `.NET 10` from `src\tray\Squid4Win.Tray`; do
  not route it back through Conan packaging, lockfiles, or editables.
- Keep PowerShell only where Windows installer integration genuinely requires
  it, such as MSI custom actions or shipped install-time helper scripts.
- Keep `CONAN_HOME` repo-local at `.\.conan2` and prefer repo-relative paths.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conandata.yml` aligned when the Squid pin changes. Prefer
  `uv run squid4win-automation upstream-version --execute`; keep
  `.\scripts\Update-SquidVersion.ps1` only as a transitional fallback when the
  Python automation environment is unavailable.
- Keep staged native notice harvesting synchronized with the root
  `conanfile.py`, `conandata.yml`, and any direct tray release assets that
  ship.
- Treat `.agents\design\*.md` as project memory. If an accepted design changes,
  update the ADR and preserve alternatives/history sections.
- Treat `skills\` as the canonical home for repo-owned skills.
- Treat `.agents\skills\` as externally synced skill content plus symlinks for
  repo-owned skills under `skills\`; `skills\gfm\SKILL.md` is repo-owned
  guidance, not vendored content.
- Keep markdown policy centralized in `skills\gfm\SKILL.md`, markdown audits,
  and markdownlint; do not create competing local markdown rules.
- The last cited end-to-end validation still comes from the legacy PowerShell +
  tray-Conan flow that predated the current Python-owned entry points.
- Treat that legacy validation as historical proof only. Do not claim
  target-state validation for Python 3.14 + `uv` orchestration, direct
  `.NET 10` tray builds, clean-host installer behavior, or installed-service
  plus tray lifecycle behavior unless it is explicitly cited.
- Do not copy GPL code from `diladele/squid-windows`. Architectural inspiration
  is acceptable; source reuse is not.
- Preserve current artifact names `squid4win.msi` and
  `squid4win-portable.zip` unless you also update the downstream packaging
  metadata flow.
- Keep live feed publication credential-gated.
- The repository's own code and docs are GPL-2.0-or-later. Do not revert or
  dilute the license migration.
- Never commit secrets or machine-specific paths.
