# GitHub Copilot instructions for squid4win

Start with `README.md`, `AGENTS.md`, and the ADRs under `.agents\design\`.
Those files are the source of truth for repository state, contributor guidance,
and validation status. Do not duplicate their general rules here.

Repo-specific directives:

- Preserve the Conan-first Windows path: the root `conanfile.py` owns Squid
  source retrieval, patch application, native MSYS2/MinGW build, and staged
  bundle assembly.
- Keep the tray app as a separate Conan-packaged `.NET 8` WPF deliverable; do
  not reintroduce an ad hoc primary packaging path.
- Keep `CONAN_HOME` repo-local at `.\.conan2` and prefer repo-relative paths.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conandata.yml` aligned when the Squid pin changes. Prefer
  `.\scripts\Update-SquidVersion.ps1`.
- Keep staged third-party notice harvesting under `licenses\third-party\`
  synchronized between `conandata.yml`, the root `conanfile.py`, and
  `conan\recipes\tray-app\conanfile.py` when shipped runtime DLLs or tray-app
  package dependencies change.
- Keep the committed `conan\lockfiles\` flow cache-backed; use
  `-UseTrayEditable` only for local root+tray iteration so editable lockfiles
  stay under `build\conan\`.
- Treat `.agents\design\*.md` as project memory. If an accepted design changes,
  update the ADR and preserve its alternatives/history sections.
- Treat `.agents\skills\` as vendored third-party content and update it
  deliberately.
- Do not copy GPL code from `diladele/squid-windows`. Architectural inspiration
  is acceptable; source reuse is not.
- Do not imply successful runner-safe installer validation, clean-host
  installer validation, or more installed-service proof than the committed
  automation and any explicitly cited successful runs.
- Keep the staged payload free of a machine-specific `etc\squid.conf`; ship
  `squid.conf.template` plus the upstream reference configs and let install
  materialize the machine-local config.
- Preserve current artifact names `squid4win.msi` and
  `squid4win-portable.zip` unless you also update the downstream packaging
  metadata flow.
- Keep prerelease and stable GitHub release workflows distinct; prereleases
  stop at GitHub prerelease assets, while stable published releases drive
  downstream package-manager metadata.
- Keep tag-triggered GitHub release publication gated by the `release-approval`
  environment after artifact build completion and before the GitHub release is
  published, and do not relax the signed-artifact checks that block unsigned
  tag-triggered release publication.
- Keep tag-triggered release/prerelease publication tied to the committed Conan
  lockfile and to tags that point to commits already reachable from `main`.
- Keep live feed publication credential-gated.
- Never commit secrets or machine-specific paths.
