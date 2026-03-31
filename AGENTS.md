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
- Current native source patch hook: `scripts\Apply-SquidSourcePatches.ps1`
  carries the MinGW `crtd_message.h` `ERROR`-macro fix, the
  `src\dns\rfc1035.cc` unused-parameter workaround, the MinGW `pipe()`,
  `kill()`, signal-constant, `syslog()`, and wait-status compatibility shims,
  the `DiskThreads\aiops_win32.cc` allocator and local maperror fixes, the
  RADIUS helper Winsock-link fix, the `src\ip\QosConfig.cc` Winsock
  `setsockopt()` argument-cast workaround, the
  `src\ipc\TypedMsgHdr.cc` first-control-message workaround for MinGW
  `CMSG_FIRSTHDR`, the
  `src\security\cert_generators\file\certificate_db.cc` MinGW lock-path fix,
  the `security_file_certgen` helper-local `fatalf()` fallback and MinGW
  link-library fix, the Win32 globals/OS-enum exposure and `src\ipc_win32.cc`
  Winsock adapter fixes, the MinGW Windows-service guard fixes, the MinGW
  user/group compatibility shims, the `src\cbdata.cc` pointer-width cookie
  fix, the global MinGW `_PATH_DEVNULL` fallback, the generated-`configure`
  strict-error/dependency-tracking workarounds, the `src\fd.cc` WSAMSG-backed
  `recvmsg()`/`sendmsg()` bridge, the `src\main.cc` MinGW-as-Windows startup
  guards, the `src\tools.cc` and `src\comm.cc` Winsock/nonblocking fixes, the
  MinGW-local `WIN32_maperror()`/`dbg_mutex` support in `src\win32.cc`, and the
  `src\DiskIO\AIO` Win32 guard plus pointer-width fixes needed for native link
  and install completion
- `scripts\Invoke-SquidBuild.ps1` now extracts Squid into a build-scoped source
  root and takes an exclusive lock per build profile/configuration so one local
  troubleshooting run cannot silently invalidate another
- `scripts\Invoke-SquidBuild.ps1` now also adds `/usr/bin/core_perl` to the
  MSYS2 `PATH` because Squid still invokes `pod2man` during `make` and
  `make install`
- `scripts\Publish-TrayApp.ps1` and `scripts\Build-Installer.ps1` now route
  `dotnet` output to the host so callers capture only the final return value
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
  current scan plus quality-gate enforcement
- Package-manager metadata generation now lives in
  `scripts\Export-PackageManagerMetadata.ps1` and
  `.github\workflows\package-managers.yml`
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
- Keep `config\squid-version.json` and `conan\squid-release.json` aligned when
  the Squid release pin changes. Prefer `scripts\Update-SquidVersion.ps1`.
- Keep docs truthful about what is scaffolded versus what is production-ready.
- Keep `.github\workflows\` and `scripts\` synchronized with any contributor
  instructions you add.
- Keep `.github\copilot-instructions.md` and `.github\instructions\` synchronized
  with workflow, review, or upgrade-process changes.
- If you change installer behavior, keep `scripts\Stage-ReleasePayload.ps1`,
  `scripts\Build-Installer.ps1`, and `packaging\wix\` synchronized.
- If you change feed metadata generation, keep
  `scripts\Export-PackageManagerMetadata.ps1` and
  `.github\workflows\package-managers.yml` synchronized.
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
- `config\*.json` and `conan\*.json` if version metadata or defaults changed

Future contributors should be able to understand the current truth of the
repository without reconstructing it from commit history.
