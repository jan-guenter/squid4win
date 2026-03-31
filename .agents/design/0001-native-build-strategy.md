# ADR 0001: Native Windows build strategy

- Status: Accepted
- Date: 2026-03-30

## Context

This project needs to produce Windows-native Squid builds that can be packaged
into an MSI and shipped with a C# WPF tray application. The build path must work
both on GitHub-hosted Windows runners and on contributor workstations.

Squid is primarily built with Unix-style tooling, so the project must choose a
Windows-compatible environment that stays close to upstream expectations without
forcing a Linux host into the critical path.

## Decision

The primary build strategy is:

- use a native Windows host
- run the Squid build inside MSYS2
- target the `mingw64` MinGW-w64 environment first
- support x64 first before considering additional architectures
- produce a staged install tree that is later consumed by WiX and the tray app

This project does not treat WSL, Docker, Cygwin, or Linux cross-compilation as
the primary supported path for the first implementation.

## Rationale

- GitHub Actions Windows runners can host both MSYS2 and the Windows-specific
  packaging toolchain needed later for WiX and WPF.
- MSYS2 and MinGW-w64 keep the Squid build closer to upstream autotools and
  package expectations than a pure MSVC port would.
- A native Windows host reduces the hand-off complexity between Squid build
  outputs, MSI packaging, service registration, and tray application delivery.

## Consequences

- Build orchestration must clearly separate PowerShell-side paths from MSYS2
  shell paths.
- CI images must provision both the Unix-like build environment and the native
  Windows packaging tools.
- Some Windows-specific patches or configure options may be needed and must be
  tracked explicitly in repo automation rather than applied ad hoc on one
  machine.
- The first implementation can optimize for one supported target instead of
  spreading effort across x86, x64, and ARM simultaneously.

## Implementation notes

- Future scripts should stage install outputs into a repo-local directory such
  as `build\stage\`.
- The staged install tree is the contract between the Squid build and MSI
  packaging.
- The tray application should consume staged outputs or installed artifacts, not
  compile Squid itself.

## Alternatives considered

### WSL or Linux cross-build as the primary path

Rejected for the first phase because it adds another environment boundary before
Windows packaging and service integration.

### Cygwin as the primary environment

Rejected because MSYS2 and MinGW-w64 align better with the intended native
Windows deliverable and broader package ecosystem.

### Full MSVC port first

Rejected because it would pull the project further away from upstream build
assumptions before a baseline Windows pipeline exists.
