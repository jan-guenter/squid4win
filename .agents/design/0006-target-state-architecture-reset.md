# ADR 0006: Target-state architecture reset

- Status: Accepted
- Date: 2026-04-01
- Supersedes: ADRs 0001, 0002, 0003, and 0004

## Context

The repository has started a GPL-2.0-or-later license migration while other
implementation streams are also moving the build, tray, and documentation
story. Existing contributor docs still describe repo-level PowerShell
orchestration and tray-through-Conan packaging as the future target, but that
is no longer the intended direction.

The project needs one source of truth that tells contributors what to build
toward without overstating what has already been validated locally or in CI.

## Decision

The target architecture is:

- keep a single self-contained native Squid Conan recipe under
  `conan\recipes\squid\all\`; it owns Squid source retrieval, patch
  application, and native MSYS2 + MinGW-w64 build only
- allow the Squid recipe to source native library inputs such as `openssl`,
  `libxml2`, `pcre2`, and `zlib` either from Conan requirements or from
  MSYS2/system packages via recipe options, while keeping the validated default
  on the MSYS2/system path
- move repo-level automation to Python 3.14 + `uv`; new developer entry points,
  CI helpers, staged bundle assembly, runtime adjacency, notice harvesting,
  validation, packaging, and metadata update flows should land there instead of
  in new repo-level PowerShell wrappers
- build the tray app directly with `.NET 10` from `src\tray\Squid4Win.Tray`; do
  not model it as a Conan package dependency of the root Squid product
- keep PowerShell as a narrow Windows-specific exception for MSI custom actions
  and install-time helper logic that genuinely runs inside the installer or
  installed payload lifecycle
- treat markdown quality as a first-class repo concern; use the repo-owned
  GFM skill at `skills\gfm\SKILL.md`, exposed through `.agents\skills\gfm`,
  plus markdown audits for first-party docs, while leaving externally synced
  skills excluded unless they are intentionally edited
- treat GPL-2.0-or-later as the repository license for first-party code and
  docs, while preserving separate notices and licenses for vendored or bundled
  third-party content
- keep documentation explicit about which claims are legacy validated facts and
  which are target-state migration goals

## Rationale

- One Conan recipe removes split ownership between the native Squid build and a
  separate tray packaging recipe.
- Python 3.14 + `uv` offers a better long-term orchestration layer than growing
  Windows-only PowerShell wrappers.
- Direct `dotnet` tray builds match the managed app's ecosystem and reduce
  cross-tool coupling.
- MSI custom actions remain a legitimate PowerShell exception because Windows
  installer integration is still platform-specific and already
  PowerShell-friendly.
- A repo-owned GFM skill and markdown audits make documentation review more
  deliberate during a fast-moving architecture transition.
- The GPL migration requires consistent first-party license language across docs
  and automation.

## Consequences

- Existing PowerShell build scripts and tray Conan wiring are transitional
  implementation, not the future architecture.
- Contributors should stop adding new top-level automation entry points to
  `scripts\` unless they are installer-time or clearly temporary compatibility
  shims.
- Contributor docs, Copilot guidance, and ADRs must stop describing the tray as
  a Conan-packaged dependency target.
- The single CCI-style Squid recipe under `conan\recipes\squid\all\conanfile.py`
  remains the source of truth for native Squid build inputs, while the Python
  automation package owns stage assembly, packaging, and repo-level validation.
- Runtime DLL harvesting, third-party notices, and Python CLI option handling
  now need to stay aligned with whichever dependency source the Squid recipe
  selects for shipped native libraries.
- Non-default dependency-source selections should default to build-local
  lockfiles so the committed lockfile continues to represent the validated
  MSYS2/system baseline unless a change intentionally refreshes a different
  graph.
- The repo must keep `CONAN_HOME` repo-local at `.\.conan2`.
- Markdown changes should keep markdownlint passing and align with
  `skills\gfm\SKILL.md` plus the repo-owned markdown audit direction.
- Validation language must distinguish the last proven legacy path from the
  in-progress target-state migration.

## Implementation notes

- Update `README.md`, `AGENTS.md`, and `.github\copilot-instructions.md` when
  this target state changes.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conan\recipes\squid\all\conandata.yml` aligned when the Squid pin changes. Prefer
  `uv run squid4win-automation upstream-version --execute`; keep
  `.\scripts\Update-SquidVersion.ps1` only as a transitional fallback when the
  Python automation environment is unavailable.
- Preserve current artifact names `squid4win.msi` and
  `squid4win-portable.zip` unless downstream package metadata changes too.
- Keep live feed publication credential-gated.
- Do not disturb externally synced `.agents\skills\` content when landing
  repo-owned documentation guidance under `skills\`, which may be symlinked
  back into `.agents\skills\` for discovery.
- Current cited local validation now includes the Python-owned `squid-build`,
  `smoke-test`, and `bundle-package` path, including local portable zip and MSI
  generation. Workflow YAMLs have been migrated from PowerShell validator entry
  points to Python CLI commands. Clean-host installer and isolated
  installed-service lifecycle validation on a dedicated Windows runner are still
  pending.
- The installed service helper currently validates generated configs with
  `squid.exe -k parse`, initializes cache directories with `squid.exe -z`, and
  then registers the named Windows service with `squid.exe -i`.
  `squid.exe -i -f <config>` follows Squid's native Windows service model: the
  service keeps Squid-controlled runtime startup parameters, while the selected
  config association is persisted separately for the named service. The helper
  now verifies the registry-backed `ConfigFile` and `CommandLine` entries so
  service startup and spawned Squid processes do not fall back to the compiled
  default config path. Because upstream service startup splits the stored
  `CommandLine` on whitespace without quote support, the install root used for
  service registration must remain space-free.

## Alternatives considered

### Keep the existing PowerShell + tray-Conan direction as the target state

Rejected because it would keep new architecture work pointed at the same split
ownership model that the migration is removing.

### Remove PowerShell entirely, including MSI custom actions

Rejected because installer-time PowerShell remains the simplest Windows-specific
integration point and is intentionally a narrow exception, not the repo-wide
orchestration layer.

### Treat markdown guidance as informal repository culture only

Rejected because the GPL migration and architecture reset need explicit,
reviewable documentation standards rather than scattered conventions.
