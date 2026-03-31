# ADR 0004: Installer payload contract

- Status: Accepted
- Date: 2026-03-30

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
- materialize `etc\squid.conf` from `packaging\defaults\squid.conf.template`
  during install if the file is missing
- register and remove the Windows service using Squid's built-in `-i` and `-r`
  verbs through an installed PowerShell helper
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
- Generating `squid.conf` from a template at install time lets the config use the
  actual resolved install root without hard-coding one machine path in the repo.
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

## Implementation notes

- The root `conanfile.py` is the source of truth for assembling the staged
  bundle that later becomes `artifacts\install-root`.
- `config\build-profile.json` declares the `runtimeDlls` list that the root
  recipe harvests from the resolved MSYS2 environment into each staged native
  executable directory.
- `scripts\Stage-ReleasePayload.ps1` is now a thin wrapper that mirrors the
  Conan-built staged bundle into `artifacts\install-root` and optionally creates
  the portable zip.
- `scripts\Build-Installer.ps1` is the preferred entry point for building the
  MSI from the staged payload.
- `packaging\wix\Squid4Win.Installer.wixproj` harvests the staged payload instead
  of hand-maintaining every Squid file in WiX XML.
- `scripts\installer\Manage-SquidService.ps1` runs inside the installed payload
  and performs config materialization, `squid.exe -k parse`, `squid.exe -z`, and
  service registration or removal.

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
