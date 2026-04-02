# ADR 0004: Installer payload contract

- Status: Superseded by ADR 0006
- Date: 2026-03-30
- Superseded on: 2026-04-01

## Superseded note

ADR `0006` replaces this ADR as the target-state architecture direction. This
ADR is preserved as historical rationale for the first committed MSI payload
contract and its broader PowerShell helper model.

## Context

The repository now has enough build and tray-app scaffolding to commit a first
real MSI authoring pass. At the same time, the native Squid build is still being
proven, and Squid on Windows is known to be sensitive to install paths that
contain spaces. The installer therefore needs a conservative first contract that
matches the current native stage layout instead of inventing a second packaging
model too early.

## Decision

The first committed installer contract is:

- stage a combined release payload under `artifacts\install-root`
- build that payload from the Conan-owned native Squid bundle, with the tray app
  consumed as a package dependency of the root product recipe
- default the MSI install root to `C:\Squid4Win`
- keep Squid config and runtime directories under the install root for now
- stage `squid.conf.template` plus the upstream reference configs, but omit a
  machine-specific `etc\squid.conf` and materialize that file during install if
  it is missing
- register and remove the Windows service using Squid's built-in `-i` and `-r`
  verbs through an installed PowerShell helper
- keep the service name overridable so runner automation can validate isolated
  temporary service instances without colliding with a shared registration
- keep the tray app tolerant of both `ProgramData` locations and install-root
  `etc`/`var\logs` fallbacks
- bundle the required MSYS2 runtime DLL set beside each staged native
  executable directory so `sbin\squid.exe` and the `libexec\*.exe` helpers can
  launch from the installed payload without an external PATH dependency

## Rationale

- A default root like `C:\Squid4Win` avoids spaces without requiring a custom UI
  flow on day one.
- Reusing Squid's own service support avoids shipping a second service wrapper
  and stays aligned with upstream behavior.
- Parameterizing the service name lets automation exercise the real installer
  path without reusing runner-global service state.
- Generating `squid.conf` from a template at install time lets the config use the
  actual resolved install root without hard-coding one machine path into the
  staged payload.
- Tray fallback logic keeps the tray useful before a future `ProgramData`
  migration is fully designed and tested.

## Consequences

- The first MSI is intentionally conservative: it prioritizes a stable payload
  contract over advanced installer UX.
- Future work can still move runtime state into `ProgramData`, but that change
  must update the tray path model, payload staging, and installer helper
  together.
- The release payload now has an explicit shape that workflows and docs must keep
  synchronized: Conan-built staged bundle, runtime DLL adjacency for native
  executables, config template, installer helper, and notices bundle.
- The notices bundle is part of the payload contract, not a post-processing
  afterthought: the staged payload must carry the third-party notice files for
  Squid, the bundled native runtime DLLs, and any shipped tray-app package
  dependencies before WiX harvests the payload.

## Implementation notes

- The root `conanfile.py` is the source of truth for assembling the staged
  bundle that later becomes `artifacts\install-root`.
- `conandata.yml` declares the `build.runtime_dlls` list that the root recipe
  harvests from the Conan-managed MSYS2 and MinGW dependency graph into each
  staged native executable directory.
- `conandata.yml` also declares the runtime notice artifacts that the root
  recipe copies into `licenses\third-party\windows-runtime\` for the staged
  bundle.
- `uv run squid4win-automation bundle-package --execute` is the supported
  repo-level entry point that mirrors the Conan-built staged bundle into
  `artifacts\install-root`, optionally creates the portable zip, and can build
  the MSI from that staged payload.
- The staged bundle should carry the installer helper entry point plus any
  helper scripts it imports under `installer\`.
- That staged bundle should carry `squid.conf.template`,
  `squid.conf.default`, and `squid.conf.documented`, but not a generated
  `etc\squid.conf`.
- `scripts\Build-Installer.ps1` remains available as an internal validation
  helper, but it is no longer the preferred contributor-facing entry point.
- `packaging\wix\Squid4Win.Installer.wixproj` harvests the staged payload instead
  of hand-maintaining every Squid file in WiX XML.
- `uv run squid4win-automation tray-build --execute` now publishes the tray app
  and harvests license and notice files for shipped NuGet package dependencies
  so the root recipe can merge them into the staged bundle before MSI
  harvesting.
- `scripts\installer\Manage-SquidService.ps1` runs inside the installed payload
  and performs config materialization, `squid.exe -k parse`, then service
  registration or removal. It intentionally skips `squid.exe -z` because the
  current native Windows build crashes during cache initialization on Windows
  runners. `squid.exe -i -f <config>` follows Squid's native Windows service
  model: the service keeps Squid-controlled runtime startup parameters, while
  the selected config association is persisted separately for the named
  service.
- `scripts\installer\Manage-SquidService.ps1` stops a running named service
  before removing it so reinstall and runner cleanup stay reliable.
- `packaging\wix\Product.wxs` must pass the install root to
  `installer\svc.ps1` as `"[INSTALLFOLDER]."` rather than raw
  `"[INSTALLFOLDER]"`, because MSI directory properties include a trailing
  backslash and that suffix would otherwise escape the closing quote in the raw
  `WixQuietExec` command line.

## Alternatives considered

### Install to Program Files by default

Rejected for the first contract because Squid historically has trouble with
paths that contain spaces.

### Move config and logs to ProgramData immediately

Deferred because it would require more path rewriting, migration logic, and
validation than the current native build proof has yet earned.

### Hand-author every installed file in WiX

Rejected because Squid's staged file set will change with the native build and
is better harvested from the staged payload.
