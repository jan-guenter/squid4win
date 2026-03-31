# squid4win

Windows-first bootstrap for building upstream Squid on native Windows, staging
the result, and shipping a companion WPF tray app.

The repository is past the "blank scaffold" stage. It already contains ADR-style
project memory under `.agents\design\`, repo-committed skills under
`.agents\skills\`, version metadata, Conan scaffolding, PowerShell automation,
GitHub workflow scaffolding, GitHub Copilot instructions, and a buildable
.NET 8 tray application with live Windows service status and control wiring. It
now also contains committed WiX-based MSI authoring and release-payload
staging, and the current repo state has now been validated locally through a
native MSYS2/MinGW `make`, `make install`, real payload staging, portable zip
creation, and MSI build against a completed native Squid stage. It still does
not have a validated end-to-end installer and service run on a clean Windows
host.

## Current pinned upstream release

- Repository: `squid-cache/squid`
- Track: `stable`
- Version: `7.5`
- Tag: `SQUID_7_5`
- Canonical metadata files:
  - `config\squid-version.json`
  - `conan\squid-release.json`

When the upstream pin changes, keep both metadata files aligned. Prefer
`scripts\Update-SquidVersion.ps1` over hand-editing one file and forgetting the
other.

## Current project direction

- Native Windows builds use MSYS2 and MinGW-w64 first.
- Conan 2 is used where it helps, with `CONAN_HOME` isolated to `.\.conan2`.
- The tray app is a separate .NET 8 WPF deliverable under `src\tray\`.
- WiX v4 is the committed MSI toolchain, and the first installer contract
  defaults to `C:\Squid4Win` to avoid known Windows path-with-spaces problems in
  Squid.

## What is already implemented

- ADR-style design records under `.agents\design\`
- repo-committed skills under `.agents\skills\`
- repo-level config under `config\`
- generated upstream release metadata under `conan\squid-release.json`
- Conan entry point plus profile and lockfile scaffolding under `conan\` and
  `conanfile.py`
- PowerShell automation for:
  - repo-local Conan home resolution
  - native environment bootstrap and MSYS2 detection
  - generated Conan MSYS2 profile creation
  - upstream release metadata refresh
  - native Squid build orchestration
  - Squid smoke tests
  - Conan lockfile refresh
- GitHub workflow scaffolding for:
  - CI linting and Windows native build execution
  - SonarQube scan and quality-gate enforcement on CI builds
  - release artifact staging
  - package-manager metadata generation for winget, Chocolatey, and Scoop
  - upstream Squid version refresh PRs
  - Conan lockfile refresh PRs
  - Dependabot auto-merge enablement
- GitHub Copilot instructions under `.github\copilot-instructions.md` and
  `.github\instructions\`
- Dependabot configuration for GitHub Actions and pip
- a buildable `.NET 8` WPF tray application with real Windows service control in
  `src\tray\Squid4Win.Tray`
- tray publishing, payload staging, and installer build scripts under `scripts\`
- committed WiX v4 source under `packaging\wix\`
- installer support assets under `packaging\defaults\`

## What is still missing

- end-to-end validation that the MSI installs, initializes, and removes the
  Squid service correctly against a completed native payload
- final release-signing flow
- runtime license harvesting for every shipped DLL in the final bundle
- broader installer UX such as configurable install locations or startup policy
- live package publication to winget, Chocolatey, and Scoop once the required
  accounts and credentials are available
- interactive SonarQube issue triage from the MCP server while the current TLS
  handshake problem remains unresolved

The tray project already contains service-controller code and UI scaffolding,
but that should not be described as completed installer or shipped service
integration.

## Native bootstrap

Run native bootstrap validation before the first local build, after moving
MSYS2, or when diagnosing toolchain issues:

```powershell
.\scripts\Initialize-NativeToolchain.ps1 -Configuration Release
```

For a non-failing diagnostic run on a machine that might be missing pieces:

```powershell
.\scripts\Invoke-SquidBuild.ps1 -BootstrapOnly -AllowMissingPrerequisites
```

The bootstrap validation:

- enforces repo-local `CONAN_HOME`
- checks that `config\squid-version.json` and `conan\squid-release.json` stay aligned
- resolves MSYS2 from `-Msys2Root`, `MSYS2_ROOT`, `MSYS2_LOCATION`, or common
  Windows and GitHub Actions install roots
- validates the required MSYS2 packages from `config\build-profile.json`
- generates the effective Conan profile under `.conan2\profiles\`

## Repository layout

- `README.md` - contributor overview and current-state summary
- `AGENTS.md` - instructions for future human and AI contributors
- `.agents\design\` - ADR-style design memory
- `.agents\skills\` - repo-committed skill catalog
- `config\` - small machine-readable defaults
- `conan\` - Squid release metadata, profiles, and lockfile outputs
- `conanfile.py` - Conan 2 entry point for native Windows builds
- `scripts\` - PowerShell automation for local and CI tasks
- `.github\workflows\` - CI, release, and update workflow scaffolding
- `.github\copilot-instructions.md` - repo-wide GitHub Copilot guidance
- `.github\instructions\` - task-specific Copilot instruction files
- `.github\dependabot.yml` - Dependabot configuration
- `sonar-project.properties` - SonarQube scan scope and exclusions
- `src\tray\Squid4Win.Tray\` - buildable WPF tray app with live service control wiring
- `packaging\defaults\` - installer-time config templates
- `packaging\wix\` - WiX v4 installer project and authoring

## Current prerequisites

For contributor workflows that touch the current bootstrap, plan around:

- Windows x64
- Git
- PowerShell 7 recommended for local script execution
- Python 3.12 and `pip install -r .\requirements-automation.txt`
- .NET 8 SDK for the tray project
- Conan 2 via `requirements-automation.txt`
- MSYS2 with the `mingw64` toolchain if you want to run the native Squid build
  locally

If MSYS2 is not installed in one of the common detected roots, pass the real
`msys64` location explicitly:

```powershell
.\scripts\Initialize-NativeToolchain.ps1 -Msys2Root 'D:\custom\msys64'
.\scripts\Invoke-SquidBuild.ps1 -Configuration Release -Msys2Root 'D:\custom\msys64'
```

The CI workflows currently provision these MSYS2 packages for the native build:

- `autoconf`
- `automake`
- `libtool`
- `make`
- `mingw-w64-x86_64-pkgconf`
- `mingw-w64-x86_64-binutils`
- `mingw-w64-x86_64-gcc`
- `mingw-w64-x86_64-libgnurx`
- `mingw-w64-x86_64-libxml2`
- `mingw-w64-x86_64-openssl`
- `mingw-w64-x86_64-pcre2`
- `mingw-w64-x86_64-zlib`

The Conan entry point now also records the current versioned toolchain and core
library intent used by the native build:

- tool requirement: `mingw-builds/15.1.0`
- dependency references:
  - `openssl/3.6.1`
  - `pcre2/10.44`
  - `libxml2/2.15.2`
  - `zlib/1.3.1`

MSYS2 remains the currently proven bootstrap and install mechanism. The Conan
graph is the reviewable source of truth for versioned toolchain intent while the
repo continues validating deeper Conan ownership of the native path. The default
`conanDependencyMode` is currently `metadata-only`, so the native MSYS2 build
records the core library refs without asking the main CI path to compile those
third-party packages yet.

Local build and lockfile flow:

1. `.\scripts\Initialize-NativeToolchain.ps1 -Configuration Release`
2. `.\scripts\Update-ConanLockfile.ps1 -Configuration Release`
3. `.\scripts\Invoke-SquidBuild.ps1 -Configuration Release`
4. `.\scripts\Publish-TrayApp.ps1 -Configuration Release`
5. `.\scripts\Stage-ReleasePayload.ps1 -Configuration Release -CreatePortableZip`
6. `.\scripts\Build-Installer.ps1 -Configuration Release`

`Invoke-SquidBuild.ps1` now consumes the generated lockfile when present and will
generate a build-scoped lockfile automatically if a committed one is not
available yet. The native MSYS2 path also forces the MinGW-host `pkg-config`
binary and pre-seeds the known x86_64-w64-mingw32 autoconf cache values that
Squid currently mis-detects under this toolchain. It also reapplies the current
MinGW-specific upstream source patches during extraction in a build-scoped
source tree so clean rebuilds do not regress on the Windows `ERROR` macro
collision in `crtd_message.h`, the `rfc1035.cc` unused-parameter warnings, the
MinGW `pipe()`, `kill()`, signal-constant, `syslog()`, and wait-status
compatibility shims plus the `aiops_win32.cc` fixes in `DiskThreads`, the MinGW
RADIUS Winsock-link workaround, the `QosConfig.cc` Winsock `setsockopt()`
argument-cast workaround, the `ipc\TypedMsgHdr.cc` first-control-message
workaround for MinGW `CMSG_FIRSTHDR`, the
`security\cert_generators\file\certificate_db.cc` MinGW lock-path fix, the
`security_file_certgen` helper-local `fatalf()` fallback and MinGW link-library
fix, the Win32 globals/OS-enum exposure and `ipc_win32.cc` Winsock adapter
fixes, the MinGW Windows-service guard fixes, the MinGW user/group
compatibility shims, the `cbdata.cc` pointer-width cookie fix, the global MinGW
`_PATH_DEVNULL` fallback, or the generated-`configure`
strict-error/dependency-tracking workarounds, the `src\fd.cc` WSAMSG-backed
`recvmsg()`/`sendmsg()` bridge, the `src\main.cc` MinGW-as-Windows guard and
`chroot_dir` handling, the `src\tools.cc` and `src\comm.cc` Winsock/nonblocking
fixes, the MinGW-local `WIN32_maperror()`/`dbg_mutex` support in `src\win32.cc`,
and the `src\DiskIO\AIO` Win32 guard plus pointer-width fixes needed to link and
install a native Squid `7.5` build.
`Invoke-SquidBuild.ps1` also now
takes an exclusive build lock for the selected profile/configuration so
concurrent local runs fail fast instead of silently mutating the same work and
source roots, and it stops immediately when `make` fails instead of falling
through to `make install`. For native MSYS2 reliability it now defaults to a
serial `make -j1`; pass `-MakeJobs` to opt in to a higher parallelism level
after local validation. The current Windows profile also restricts Negotiate
auth on native MinGW to `SSPI` because the upstream `wrapper` helper relies on
`fork()`, and it omits the current LDAP/AD-dependent helper family because
Squid's helper probes and Windows-specific AD helper sources are not yet
consistently MinGW-clean in this environment.
The Windows build profile also disables Automake dependency tracking because the
generated `am--depfiles` bootstrap currently fails under this MinGW setup, and
it disables Squid strict error checking so MinGW warning noise does not halt
native release builds with upstream `-Werror` defaults. It also disables
Linux-only `netfilter-conntrack` probing to keep the MinGW configure path out of
an irrelevant feature branch. The build orchestration now also adds
`/usr/bin/core_perl` to the MSYS2 `PATH` so Squid's `pod2man`-generated helper
documentation does not fail during `make` or `make install`.

Keep Conan state repo-local:

```powershell
python -m pip install -r .\requirements-automation.txt
$env:CONAN_HOME = "$PWD\.conan2"
```

The committed MSI authoring uses the .NET-based WiX SDK project under
`packaging\wix\`. Contributors only need WiX packages restored when they are
actually building the installer.

## Current automation summary

- `ci.yml` lints Markdown, workflows, PowerShell, and C#, then runs the native
  Windows build and smoke-test path on GitHub-hosted runners, followed by a
  SonarQube scan and quality-gate check when the Sonar secrets and variables are
  configured
- `release.yml` publishes the tray app, stages a combined install payload,
  creates the portable zip, and builds the MSI through the WiX SDK project
- `package-managers.yml` downloads release assets and generates winget,
  Chocolatey, and Scoop metadata from the released MSI and portable zip
- `update-upstream.yml` refreshes pinned Squid release metadata
- `conan-update.yml` refreshes Conan lockfiles because Dependabot does not manage
  Conan 2 package graphs directly
- Latest local validation on this repo state completed a native MSYS2/MinGW
  `make`, `make install`, `Stage-ReleasePayload.ps1 -CreatePortableZip`, and
  `Build-Installer.ps1`, producing `artifacts\squid4win.msi` from a real native
  Squid install tree

These workflows exist in the repository now, but the presence of a workflow file
should not be described as proof that the full native build and installed
service path have already been proven end to end. Direct runtime and
service-lifecycle smoke tests still need a clean, isolated Windows host because
this shared environment did not permit safe termination and revalidation of a
running `squid.exe` process.

## Feed publication prerequisites

Future live publication to downstream package feeds will need:

- winget:
  - a GitHub identity that can open PRs against `microsoft/winget-pkgs`
  - a GitHub token with permission to fork, push, and open pull requests
- Chocolatey:
  - a Chocolatey account
  - a Chocolatey API key stored as a GitHub Actions secret
- Scoop:
  - a GitHub identity that can push to the target Scoop bucket repository
  - a token with contents-write permission to that bucket

Until those credentials exist, the repository generates feed manifests and keeps
the publish path credential-gated instead of attempting a blind live push.

## Contributor conventions

- Treat `.agents\design\*.md` as project memory.
- Treat `.agents\skills\` as vendored third-party content unless you are
  intentionally updating a skill.
- Keep `config\squid-version.json` and `conan\squid-release.json` synchronized.
- Keep docs truthful about the difference between committed scaffolding and a
  finished Windows installer product.
- Prefer repo-relative configuration and repo-local build state.
- Keep upstream Squid changes minimal and explicit.
- Use ASCII in docs and config unless a file already requires something else.

## License

This repository is MIT-licensed. See `LICENSE`.
