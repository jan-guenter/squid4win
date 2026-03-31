# ADR 0002: Conan and dependency management

- Status: Accepted
- Date: 2026-03-30

## Context

This project will need repeatable dependency resolution for a Windows-native
Squid build, MSI packaging, and the companion tray application. Some
dependencies are naturally sourced from MSYS2, while others may benefit from
Conan 2 for version pinning or reusable tool requirements.

The repository now includes Conan 2 scaffolding in `conanfile.py`, a committed
MSYS2/MinGW-w64 host profile, repo-local `CONAN_HOME` helpers, generated Squid
release metadata, and a companion workflow for Conan lockfile refresh. At the
same time, the native build path is still intentionally MSYS2 `mingw64` first
on Windows, and the current Conan-owned graph is small.

The project also needs to avoid polluting developer-global Conan state because
shared machine profiles make CI reproduction and troubleshooting harder.

## Decision

Dependency management will use a split model:

- use MSYS2 and `pacman` for the foundational shell, compiler, and MinGW-w64
  environment
- use Conan 2 as a repo-owned supplement for selected versioned build inputs,
  metadata, and tool requirements
- record the current MinGW toolchain and core native dependency references in
  `config\build-profile.json` so the Conan-owned graph remains reviewable even
  while MSYS2 still owns the proven bootstrap path
- isolate `CONAN_HOME` to `<repo>\.conan2` for both local work and CI
- keep committed profile templates, generated metadata, and lockfile locations
  in the repository instead of relying on developer-global profiles or user
  cache conventions
- generate the effective MSYS2/MinGW Conan profile from the resolved MSYS2 root
- treat lockfiles as a repository artifact class with dedicated refresh
  automation, using the same generated profile that the native build uses

Conan is a complement to the Windows-native toolchain plan, not a reason to
hide build behavior in global user state.

## Rationale

- MSYS2 remains the most natural source for the base Unix-like environment and
  MinGW-w64 packages.
- Conan 2 is useful when package pinning, provenance, or reusable dependency
  metadata matter more than ad hoc system packages.
- A repo-local `.conan2` directory improves repeatability and keeps the project
  self-contained.
- Lockfile scaffolding and refresh automation are worth committing early so
  Conan-owned graph changes remain reviewable, even before the full dependency
  picture is stable.

## Consequences

- The project must document which dependencies come from MSYS2 and which come
  from Conan.
- Future scripts must ensure Conan sees the intended compiler, environment, and
  path translations when called from PowerShell or MSYS2.
- Native bootstrap logic must resolve the actual MSYS2 installation root instead
  of assuming every machine uses `C:\msys64`.
- Dependency update automation will be split: supported ecosystems can use
  Dependabot, while Conan references remain custom-updated.
- Contributors must not assume `%USERPROFILE%\.conan2` contains valid project
  state.
- The current committed build flow should be described honestly: MSYS2 owns the
  foundational native toolchain and core package installation, while Conan now
  records `mingw-builds` and the core `openssl`/`pcre2`/`libxml2`/`zlib`
  dependency references as the versioned source of truth the native path is
  converging toward.
- Lockfile automation exists now, but reproducibility claims should stay modest
  until a resolved lockfile is generated and validated as part of the evolving
  native build path.

## Implementation notes

- Set `CONAN_HOME` to a repo-relative `.conan2` path in every documented local
  and CI entry point.
- Keep `conan\profiles\msys2-mingw-x64` as the seed profile shape for the
  native Squid path, then generate the effective profile under
  `.conan2\profiles\` from the detected MSYS2 root.
- Keep `scripts\Resolve-ConanHome.ps1` and GitHub workflow environment settings
  aligned on repo-local Conan state.
- Use `conan\lockfiles\` as the repository location for Conan lockfile outputs,
  refreshed by dedicated automation when the Conan-owned graph changes.
- Keep the versioned Conan refs in `config\build-profile.json` synchronized with
  any workflow or documentation changes that claim a new native dependency
  baseline.

## Alternatives considered

### MSYS2 only

Rejected because some dependencies or tools may need stronger pinning and reuse
than a pure `pacman` approach provides.

### Conan for everything

Rejected because the base MSYS2 shell and MinGW-w64 environment are still the
most natural foundation for the Squid build itself.

### Global user-scoped Conan home

Rejected because it hides state, makes CI reproduction brittle, and increases
the chance of machine-specific failures.
