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

- keep a single self-contained native Squid Conan recipe at the repo root; it
  owns Squid source retrieval, patch application, native MSYS2 + MinGW-w64
  build, staged bundle assembly, native runtime adjacency, and shipped native
  notice harvesting
- move repo-level automation to Python 3.14 + `uv`; new developer entry points,
  CI helpers, and metadata update flows should land there instead of in new
  repo-level PowerShell wrappers
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
- The root `conanfile.py` remains the single source of truth for native Squid
  build inputs and bundle assembly.
- The repo must keep `CONAN_HOME` repo-local at `.\.conan2`.
- Markdown changes should keep markdownlint passing and align with
  `skills\gfm\SKILL.md` plus the repo-owned markdown audit direction.
- Validation language must distinguish the last proven legacy path from the
  in-progress target-state migration.

## Implementation notes

- Update `README.md`, `AGENTS.md`, and `.github\copilot-instructions.md` when
  this target state changes.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conandata.yml` aligned when the Squid pin changes. Until the Python
  replacement lands, existing update scripts may remain temporary fallbacks.
- Preserve current artifact names `squid4win.msi` and
  `squid4win-portable.zip` unless downstream package metadata changes too.
- Keep live feed publication credential-gated.
- Do not disturb externally synced `.agents\skills\` content when landing
  repo-owned documentation guidance under `skills\`, which may be symlinked
  back into `.agents\skills\` for discovery.
- The last cited local validation still comes from the legacy PowerShell +
  tray-Conan implementation: native build, install tree creation, staged bundle
  assembly, portable zip creation, and MSI build. Clean-host and end-to-end
  target-state validation are still pending.
- The installed service helper currently validates generated configs with
  `squid.exe -k parse`, initializes cache directories with `squid.exe -z`, and
  then registers the named Windows service with `squid.exe -i`.
  `squid.exe -i -f <config>` follows Squid's native Windows service model: the
  service keeps Squid-controlled runtime startup parameters, while the selected
  config association is persisted separately for the named service.

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
