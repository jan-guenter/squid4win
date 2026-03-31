# Agent guidance for squid4win

Before changing this repository, verify the current bootstrap from the files
that actually drive it. Do not rely on stale assumptions or generic project
templates.

## Required reading order

1. `README.md`
2. every Markdown file under `.agents\design\`
3. `config\squid-version.json`
4. `conan\squid-release.json`
5. if touching automation: `.github\workflows\` and `scripts\`
6. if touching review or upgrade guidance: `.github\copilot-instructions.md` and
   `.github\instructions\`
7. if touching the tray app: `src\tray\Squid4Win.Tray\`

## Current working baseline

- Pinned upstream release: Squid `7.5` with tag `SQUID_7_5`
- Native build direction: MSYS2 + MinGW-w64 on Windows
- Conan rule: keep `CONAN_HOME` repo-local at `.\.conan2`
- Current native source patch set lives in `conandata.yml` plus the ordered
  patch series under `conan\patches\squid\0001-mingw-compat-core-shims.patch`
  through `0007-mingw-main-and-service-integration.patch`. Keep that series
  logically grouped by concern (core shims, build/link flags, disk I/O,
  socket/IPC wrappers, Win32 runtime helpers, certificate tooling, and
  runtime/service integration) instead of collapsing it back into one monolith.
- `scripts\Invoke-SquidBuild.ps1` is now a Conan-first wrapper: it exports the
  repo-local recipes, refreshes or consumes the lockfile, takes an exclusive
  build lock per profile/configuration, and hands off source/build work to the
  root `conanfile.py`
- `scripts\Publish-TrayApp.ps1` is now a Conan-backed convenience wrapper for
  `conan\recipes\tray-app`; do not reintroduce direct `dotnet publish` as the
  authoritative tray packaging path
- The root `conanfile.py` now owns Squid source retrieval, `conandata.yml`
  patch application, the native MSYS2 build, autoconf header repair, and final
  bundle assembly
- The tray app now has a dedicated Conan application recipe under
  `conan\recipes\tray-app`, and the root product recipe consumes it when
  assembling the staged bundle
- The build recipe still adds `/usr/bin/core_perl` to the MSYS2 `PATH` because
  Squid still invokes `pod2man` during `make` and `make install`
- `scripts\Build-Installer.ps1` routes `dotnet` output to the host so callers
  capture only the final return value
- The current MinGW Windows profile explicitly restricts Negotiate auth to
  `SSPI` because the upstream `wrapper` helper uses `fork()`, and it omits the
  current LDAP-dependent helper family because Squid's native LDAP probes still
  miss the `winldap.h` path and leave those helpers without the required
  `HAVE_LDAP*` macros
- Current native configure profile also disables Automake dependency tracking on
  MinGW because `config.status` depfile bootstrap is currently unstable there
- Current native configure profile also disables Squid strict error checking on
  MinGW because upstream warning-as-error defaults currently block native builds
- Current native configure profile also disables Linux-only
  `netfilter-conntrack` probing on MinGW
- Current repo contents: docs, ADRs, config, Conan scaffolding, PowerShell
  scripts, GitHub workflows, and a buildable .NET 8 WPF tray app with live
  Windows service control wiring
- Repo-committed skills now live under `.agents\skills\`; treat them as vendored
  third-party content and update them deliberately through `npx skills add -a github-copilot`
- SonarQube scan scope is defined in `sonar-project.properties`, and CI owns the
  scanner plus quality-gate path only when `SONAR_CI_SCAN_ENABLED=true`; keep
  that variable off until SonarCloud Automatic Analysis is disabled for the
  project
- Package-manager metadata generation now lives in
  `scripts\Export-PackageManagerMetadata.ps1` and
  `.github\workflows\package-managers.yml`, while credential-gated publication
  lives in the package-manager publish helpers under `scripts\` and
  `.github\workflows\package-manager-publish.yml`
- Current installer state: committed WiX v4 project plus payload-staging scripts
  exist, and the current repo state has now completed a local native `make`,
  `make install`, real payload staging, portable zip creation, and MSI build;
  end-to-end installer service validation still needs a clean isolated host

Do not claim any of the following unless you have added and validated them:

- a finished MSI release path
- end-to-end installed Squid service plus tray app integration
- local native-build validation on a machine that does not actually have MSYS2

The native build scripts probe common roots such as `C:\msys64` and
`C:\tools\msys64`. If neither is present on the current machine, say so plainly
instead of implying the native build was already proven locally.

## Project memory rule

- Files under `.agents\design\` are ADR-style records and act as project memory.
- If a change affects an accepted design decision, update the relevant
  `.agents\design\*.md` file in the same change.
- If a new major decision is introduced, add a new numbered ADR.
- If one ADR replaces another, mark the old ADR as superseded and point to the
  replacement.

## Change hygiene

- Keep `README.md`, `AGENTS.md`, and the relevant `.agents\design\*.md` files aligned.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conandata.yml` aligned when the Squid release pin changes. Prefer
  `scripts\Update-SquidVersion.ps1`.
- Keep docs truthful about what is scaffolded versus what is production-ready.
- Keep `.github\workflows\` and `scripts\` synchronized with any contributor
  instructions you add.
- Keep `.github\copilot-instructions.md` and `.github\instructions\` synchronized
  with workflow, review, or upgrade-process changes.
- If you change installer behavior, keep `conanfile.py`,
  `scripts\Stage-ReleasePayload.ps1`, `scripts\Build-Installer.ps1`, and
  `packaging\wix\` synchronized.
- If you change native MinGW-linked imports or bundled MSYS2 package
  composition, keep `config\build-profile.json` `runtimeDlls`, the staged-bundle
  harvesting in `conanfile.py`, and runtime launch validation synchronized.
- If you change feed metadata generation or publication, keep
  `scripts\Export-PackageManagerMetadata.ps1`, the package-manager publish
  helpers under `scripts\`, `.github\workflows\package-managers.yml`, and
  `.github\workflows\package-manager-publish.yml` synchronized.
- Prefer repo-relative paths and repo-local state.
- Do not introduce secrets, signing material, or machine-specific paths beyond
  documented tool defaults such as `C:\msys64`.
- Use ASCII in docs and config unless an existing file requires something else.

## When current state changes

At minimum, update:

- `README.md` for contributor-facing state, prerequisites, or workflow changes
- `AGENTS.md` for future agent guidance
- the affected ADR under `.agents\design\` if an accepted design changed
- `.github\copilot-instructions.md` or `.github\instructions\` when review or
  upgrade guidance changes
- `config\*.json`, `conan\*.json`, and `conandata.yml` if version metadata or
  defaults changed

Future contributors should be able to understand the current truth of the
repository without reconstructing it from commit history.
