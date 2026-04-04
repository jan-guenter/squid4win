# GitHub Copilot instructions for squid4win

Start with `README.md`, `AGENTS.md`, and ADR `0006` under `.agents\design\`.
Those files are the source of truth for repository state, contributor guidance,
and validation status. ADRs `0001` through `0004` are historical context after
the architecture reset.

Repo-specific directives:

- Preserve the target state: one self-contained native Squid Conan recipe under
  `conan\recipes\squid\all\` owns Squid source retrieval, patch application,
  and native MSYS2/MinGW build only.
- Keep Python 3.14 + `uv` responsible for staged bundle assembly, runtime DLL
  adjacency, notice harvesting, smoke testing, bundle packaging, and other
  repo-level orchestration around the pure Conan output.
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
- Keep the installed service helper on the current `squid.exe -k parse`,
  `squid.exe -z`, then `-i`/`-r` flow. `squid.exe -i -f <config>` follows
  Squid's native Windows service model: the service keeps Squid-controlled
  runtime startup parameters, while the selected config association is
  persisted separately for the named service. The helper must explicitly verify
  the registry-backed `ConfigFile` and `CommandLine` values so service startup
  and spawned Squid processes do not fall back to compiled defaults. Because
  upstream service startup splits the stored `CommandLine` on whitespace
  without quote support, the install root used for service registration must
  remain space-free.
- Keep `CONAN_HOME` repo-local at `.\.conan2` and prefer repo-relative paths.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conan\recipes\squid\all\conandata.yml` aligned when the Squid pin changes. Prefer
  `uv run squid4win-automation upstream-version --execute`; keep
  `.\scripts\Update-SquidVersion.ps1` only as a transitional fallback when the
  Python automation environment is unavailable.
- Keep staged native notice harvesting synchronized between the Python
  automation's Python metadata, the Squid recipe options, and any direct tray
  release assets that ship.
- Keep Conan-sourced Windows runtime DLLs staged from the selected Conan
  package bins into `build\install\...` so `bundle-package` mirrors them into
  `artifacts\install-root`, and keep the runtime notice manifest aligned when
  shared Conan dependencies add DLLs.
- Treat `.agents\design\*.md` as project memory. If an accepted design changes,
  update the ADR and preserve alternatives/history sections.
- Treat `skills\` as the canonical home for repo-owned skills.
- Treat `.agents\skills\` as externally synced skill content plus mirror
  directories backed by symlinked files for repo-owned skills under `skills\`;
  `skills\gfm\SKILL.md` is repo-owned
  guidance, not vendored content.
- Keep markdown policy centralized in `skills\gfm\SKILL.md`, markdown audits,
  `.mega-linter.yml`, and markdownlint; do not create competing local markdown
  rules.
- Keep MegaLinter rule files under `.github\linters\` and preserve `ty` as the
  companion Python type-check step until the repo intentionally adopts a
  MegaLinter-native replacement.
- Local target-state validation now includes the Python-owned `squid-build`,
  `smoke-test`, and `bundle-package` path.
- Do not claim clean-host installer behavior or installed-service plus tray
  lifecycle validation after the workflow migration unless that validation is
  explicitly cited.
- Do not copy GPL code from `diladele/squid-windows`. Architectural inspiration
  is acceptable; source reuse is not.
- Preserve current artifact names `squid4win.msi` and
  `squid4win-portable.zip` unless you also update the downstream packaging
  metadata flow.
- Keep live feed publication credential-gated.
- The repository's own code and docs are GPL-2.0-or-later. Do not revert or
  dilute the license migration.
- Never commit secrets or machine-specific paths.
