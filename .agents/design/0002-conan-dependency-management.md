# ADR 0002: Conan and dependency management

- Status: Accepted
- Date: 2026-03-30

## Context

This project will need repeatable dependency resolution for a Windows-native
Squid build, MSI packaging, and the companion tray application. Some
dependencies are naturally sourced from MSYS2 packages, while the project also
needs Conan 2 to own the shell/compiler bootstrap, versioned source metadata,
lockfiles, and release packaging graph.

The repository now includes a Conan-owned root product recipe, a committed
MSYS2/MinGW-w64 host profile, repo-local `CONAN_HOME` helpers, generated Squid
release metadata, and a companion workflow for Conan lockfile refresh. The
native build path is still intentionally MSYS2 `mingw64` first on Windows, but
the actual shell/compiler/tool bootstrap now comes from Conan tool requirements
instead of probing local machine install roots.

The project also needs to avoid polluting developer-global Conan state because
shared machine profiles make CI reproduction and troubleshooting harder.

## Decision

Dependency management will use a split model:

- use Conan 2 tool requirements for the foundational shell, compiler, and
  MinGW-w64 runtime environment via `msys2/cci.latest` and `mingw-builds/15.1.0`
- use `conandata.yml` as the repo-owned source of truth for build metadata such
  as tool requirements, MSYS2 package composition, runtime DLL harvesting, and
  `configure` defaults
- isolate `CONAN_HOME` to `<repo>\.conan2` for both local work and CI
- keep the committed host profile, generated metadata, and lockfile locations in
  the repository instead of relying on developer-global profiles or user cache
  conventions
- use the committed `conan\profiles\msys2-mingw-x64` host profile together with
  a detected default build profile instead of generating machine-specific
  effective profiles
- expose release-only bundle features through recipe options so default builds
  stay focused on Squid itself and its required toolchain/runtime dependencies
- treat lockfiles as a repository artifact class with dedicated refresh
  automation, using the same Conan-owned profiles and recipe options that the
  native build uses
- allow the tray app recipe to switch between a cache-backed export for
  committed lockfile refreshes and a local editable mode for root+tray
  co-development

Conan now owns the Windows-native toolchain bootstrap, but it still does so in a
way that preserves the proven MSYS2/MinGW build path instead of replacing it
with a different platform stack.

## Rationale

- MSYS2 remains the most natural source for the base Unix-like environment and
  MinGW-w64 packages, and the ConanCenter `msys2/cci.latest` package exposes
  that environment in a repo-owned form.
- Conan 2 is useful for package pinning, provenance, reusable tool requirements,
  and a single reviewable place to model Windows packaging options.
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
- Native bootstrap logic must restore the Conan-managed MSYS2 and MinGW tool
  requirements instead of assuming every machine already has `C:\msys64`.
- Dependency update automation will be split: supported ecosystems can use
  Dependabot, while Conan references remain custom-updated.
- Contributors must not assume `%USERPROFILE%\.conan2` contains valid project
  state.
- The current committed build flow should be described honestly: MSYS2 still
  provides the shell-facing package ecosystem, while Conan now owns the
  top-level product recipe, versioned source metadata in `conandata.yml`, the
  Windows compatibility patch set under `conan\patches\`, the Conan-managed tool
  bootstrap, and the separate tray-app package consumed by the final bundle.
- The committed repository lockfile remains cache-backed; local editable tray
  work should use a build-local lockfile instead of rewriting
  `conan\lockfiles\`.
- Lockfile automation exists now, but reproducibility claims should stay modest
  until a resolved lockfile is generated and validated as part of the evolving
  native build path.

## Implementation notes

- Set `CONAN_HOME` to a repo-relative `.conan2` path in every documented local
  and CI entry point.
- Keep `conan\profiles\msys2-mingw-x64` as the committed host profile for the
  native Squid path and let `conan profile detect --force` maintain the default
  build profile in the repo-local Conan home.
- Keep `scripts\Resolve-ConanHome.ps1` and GitHub workflow environment settings
  aligned on repo-local Conan state.
- Export the repo-local `python_requires` helper before all local product builds
  and lockfile refreshes.
- Export the tray recipe before committed lockfile refreshes and cache-backed
  product builds; use the tray recipe as a Conan editable for local root+tray
  iteration.
- Use `conan\lockfiles\` as the repository location for Conan lockfile outputs,
  refreshed by dedicated automation when the Conan-owned graph changes, and keep
  editable-only lockfiles under `build\conan\`.
- Keep `conandata.yml` build metadata, wrapper option switches, and workflow
  defaults synchronized when the native dependency or packaging baseline
  changes.

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
