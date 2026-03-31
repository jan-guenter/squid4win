# squid4win

Windows-first automation for building upstream Squid on native Windows, staging
the result, and shipping a companion WPF tray app.

## Current state

- Upstream pin: Squid `7.5` (`SQUID_7_5`)
- Canonical version metadata:
  - `config\squid-version.json`
  - `conan\squid-release.json`
  - `conandata.yml`
- The project is Conan-first on Windows. The root `conanfile.py` fetches Squid
  from `conandata.yml`, applies the reviewable patch set under
  `conan\patches\`, builds under Conan-managed MSYS2 + MinGW-w64, and assembles
  the staged Windows bundle.
- The tray app is a separate `.NET 8` WPF deliverable under
  `src\tray\Squid4Win.Tray`, packaged through `conan\recipes\tray-app` and
  consumed by the root product recipe.
- WiX v4 MSI authoring and release-payload staging are committed.

## What is validated today

- local native `make`
- local `make install`
- Conan-owned bundle assembly
- portable zip creation
- MSI build from a real native Squid stage

## Known limitations and next milestones

- clean-host MSI install, upgrade, and uninstall lifecycle validation
- end-to-end installed Squid service plus tray-app interaction on a clean host
- final release-signing flow
- complete runtime license harvesting for every shipped DLL
- first end-to-end downstream publication to winget, Chocolatey, and Scoop

The tray app already contains real Windows service status and control wiring,
but that should not be described as a fully validated installed-service
experience.

## Prerequisites

For native build work, plan around:

- Windows x64
- Git
- PowerShell 7 recommended
- Python 3.12 and `python -m pip install -r .\requirements-automation.txt`
- .NET 8 SDK
- internet access to ConanCenter so Conan can restore the managed MSYS2 and
  MinGW toolchain packages

Current Conan-managed native tool requirements include:

- `msys2/cci.latest`
- `mingw-builds/15.1.0`

Keep Conan state repo-local:

```powershell
python -m pip install -r .\requirements-automation.txt
$env:CONAN_HOME = "$PWD\.conan2"
```

## Common flows

### Bootstrap / environment check

```powershell
.\scripts\Setup-Environment.ps1 -Configuration Release
```

For a non-building diagnostic run:

```powershell
.\scripts\Invoke-SquidBuild.ps1 -Configuration Release -BootstrapOnly
```

### Native build

```powershell
.\scripts\Invoke-SquidBuild.ps1 -Configuration Release
```

By default, this builds Squid and the Conan-managed toolchain/runtime inputs
needed for the native build. Tray packaging, runtime DLL harvesting, and
installer-support files are opt-in:

```powershell
.\scripts\Invoke-SquidBuild.ps1 -Configuration Release -WithTray -WithRuntimeDlls -WithPackagingSupport
```

### Release-style packaging

```powershell
.\scripts\Update-ConanLockfile.ps1 -Configuration Release -WithTray -WithRuntimeDlls -WithPackagingSupport
.\scripts\Invoke-SquidBuild.ps1 -Configuration Release -WithTray -WithRuntimeDlls -WithPackagingSupport
.\scripts\Stage-ReleasePayload.ps1 -Configuration Release -RequireTray -RequireNotices -CreatePortableZip
.\scripts\Build-Installer.ps1 -Configuration Release
```

`Update-ConanLockfile.ps1` refreshes the committed lockfile, and
`Invoke-SquidBuild.ps1` consumes it when present.

## Repository map

- `README.md` - contributor overview and current-state summary
- `AGENTS.md` - concise guidance for human and AI contributors
- `.github\copilot-instructions.md` - repo-specific Copilot rules
- `.agents\design\` - ADR-style project memory
- `.agents\skills\` - vendored skills
- `conanfile.py` and `conan\` - root recipe, patch metadata, host profiles, and
  lockfiles
- `scripts\` - PowerShell automation for bootstrap, build, packaging, and
  release support
- `src\tray\Squid4Win.Tray\` - WPF tray app
- `packaging\defaults\` - installer defaults and templates
- `packaging\wix\` - WiX v4 installer authoring
- `.github\workflows\` - CI, release, and update workflows

## Contributor conventions

- Treat `.agents\design\*.md` as project memory. If an accepted design changes,
  update the relevant ADR rather than relying on commit history.
- Keep ADR alternatives sections intact when updating ADRs.
- Treat `.agents\skills\` as vendored third-party content unless you are
  intentionally updating a skill.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conandata.yml` aligned when the Squid pin changes. Prefer
  `.\scripts\Update-SquidVersion.ps1`.
- Keep docs explicit about the difference between committed automation, locally
  validated steps, and not-yet-validated runtime behavior.
- Prefer repo-relative configuration and repo-local build state, including
  `CONAN_HOME=.\.conan2`.

## License

This repository is MIT-licensed. See `LICENSE`.
