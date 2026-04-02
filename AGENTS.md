# Agent guidance for squid4win

Before changing this repository, verify the current state from the files that
actually drive it. Do not rely on stale templates or earlier assumptions.

## Read first

1. `README.md`
2. every ADR under `.agents\design\`, with ADR `0006` as the target-state
   source of truth and ADRs `0001` through `0004` as historical context
3. `config\squid-version.json`, `conan\squid-release.json`, and `conandata.yml`
   if you touch the Squid pin or native build metadata
4. `conanfile.py`, the Python automation package files, `scripts\`,
   `packaging\wix\`, and `.github\workflows\` if you touch automation,
   packaging, or release behavior
5. `.github\copilot-instructions.md` and `.github\instructions\` if you touch
   contributor or Copilot guidance

## Current state summary

- Upstream pin: Squid `7.5` (`SQUID_7_5`)
- The target architecture is one self-contained native Squid Conan recipe plus a
  direct `.NET 10` tray build outside Conan.
- Repo-level automation is moving to Python 3.14 + `uv`.
- Repository linting is centered on `.mega-linter.yml` plus
  `.github\linters\`; `ty` remains a companion Python type-check step outside
  MegaLinter.
- PowerShell remains allowed for MSI custom actions and install-time helper
  logic, not as the long-term repo orchestration layer.
- The installed service helper now runs `squid.exe -k parse`, `squid.exe -z`,
  and then `squid.exe -i` for first-install cache initialization and service
  registration.
- `squid.exe -i -f <config>` follows Squid's native Windows service model: the
  service keeps Squid-controlled runtime startup parameters, while the selected
  config association is persisted separately for the named service.
- WiX v4 MSI authoring and payload staging are already committed.
- The repository's own code and docs are GPL-2.0-or-later.
- The last cited validation still comes from the legacy PowerShell +
  tray-Conan implementation: native build, native install tree creation, staged
  bundle assembly, portable zip creation, and MSI build.
- Treat that legacy validation as historical proof only. It does not validate
  the Python 3.14 + `uv` automation path, the direct `.NET 10` tray build
  integration, or clean-host installer and installed-service plus tray lifecycle
  behavior.

For detailed architecture, quality, and distribution rationale, use
`README.md` plus ADRs `0005` and `0006` instead of duplicating those details
here.

## Project memory rule

- Treat `.agents\design\*.md` as required project memory.
- ADR `0006` is the accepted target-state architecture decision.
- ADR `0005` remains the current quality and distribution automation companion.
- ADRs `0001` through `0004` are preserved for historical rationale after the
  reset. Preserve their alternatives and any history notes if you touch them.
- If the target architecture changes again, add or update an ADR instead of
  relying on commit history.
- If one ADR replaces another, mark the old ADR as superseded and point to the
  replacement.

## Change hygiene

- Keep `README.md`, `AGENTS.md`, and `.github\copilot-instructions.md` aligned
  when contributor guidance changes.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conandata.yml` aligned when the Squid pin changes. Prefer
  `uv run squid4win-automation upstream-version --execute`; keep
  `.\scripts\Update-SquidVersion.ps1` only as a transitional fallback when the
  Python automation environment is unavailable.
- Keep `CONAN_HOME` repo-local at `.\.conan2`.
- Keep the native Squid build owned by the root `conanfile.py`; do not split it
  back into multiple primary Conan recipes.
- Do not add new repo-level PowerShell orchestration. Put new contributor and
  CI automation in the Python 3.14 + `uv` package and entry points.
- Treat `uv run squid4win-automation ...` as the supported repo-level surface
  for Squid builds, tray builds, bundle packaging, and Conan lockfile refresh.
- Do not reintroduce tray-app Conan packaging or editable flows as the target
  model; the tray builds directly with `dotnet` from
  `src\tray\Squid4Win.Tray`.
- Keep PowerShell limited to installer-time MSI custom actions or shipped
  Windows helper scripts that genuinely need it.
- Keep docs truthful about committed implementation, cited validation, and
  migration plans.
- Keep markdown guidance centralized. Use markdownlint,
  `skills\gfm\SKILL.md`, `.mega-linter.yml`, and the repo-owned markdown audit
  direction instead of scattered local rules.
- Keep MegaLinter rule files under `.github\linters\` when new first-party lint
  configuration is required.
- Treat `skills\` as the canonical home for repo-owned custom skills.
- Treat `.agents\skills\` as externally synced skills plus symlinks back to
  `skills\`. Do not disturb unrelated skill-vendoring changes.
- Preserve current artifact names `squid4win.msi` and
  `squid4win-portable.zip` unless downstream packaging metadata changes too.
- Keep live feed publication credential-gated.
- The repository's own code and docs are GPL-2.0-or-later; do not revert or
  dilute the license migration.
- Do not copy GPL code from `diladele/squid-windows`; architectural inspiration
  is acceptable, source reuse is not.
- Never commit secrets or machine-specific paths.

## When current state changes

At minimum, update:

- `README.md` for contributor-facing state and migration status
- `AGENTS.md` for future contributor guidance
- the affected ADR under `.agents\design\`
- `.github\copilot-instructions.md` or `.github\instructions\` when Copilot
  guidance changes
- `skills\README.md` when repo-owned skill inventory or descriptions change
- the relevant Python automation docs or package metadata when contributor entry
  points change
- `config\*.json`, `conan\*.json`, and `conandata.yml` when version metadata or
  native build defaults change

If markdown audit policy changes, update `skills\gfm\SKILL.md`,
`skills\README.md`, markdown lint expectations, and top-level contributor docs
together.

Future contributors should be able to understand the current truth of the
repository without reconstructing it from commit history.
