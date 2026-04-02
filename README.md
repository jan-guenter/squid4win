# squid4win

Windows-first build and packaging repository for upstream Squid on native
Windows.

## Architecture direction

The repository is being reset toward the target state defined in ADR `0006`:

- one self-contained native Squid Conan recipe at the repo root owns Squid
  source retrieval, patch application, native MSYS2 + MinGW-w64 build, staged
  bundle assembly, and native notice/runtime harvesting for shipped Squid
  artifacts
- repo-level contributor and CI automation moves to Python 3.14 + `uv` instead
  of additional PowerShell orchestration
- the tray app builds directly with `.NET 10` from `src\tray\Squid4Win.Tray`
  and is no longer a Conan-packaged dependency target
- PowerShell remains a narrow Windows exception for MSI custom actions and other
  install-time helper logic that truly has to run inside the installer path
- markdown authoring and review should follow the repo-owned GFM guidance at
  `skills\gfm\SKILL.md` plus markdown audit automation; keep
  markdownlint clean and avoid inventing parallel markdown policy
- the repository's own code and docs are GPL-2.0-or-later

## Current validation status

### Legacy validated path (pre-ADR 0006)

The most recent cited validation comes from the pre-reset implementation:

- local native Squid build on Windows
- local install tree creation
- staged bundle assembly
- portable zip creation
- MSI build from that staged payload

That legacy validation is useful project memory, but it does not prove the
target-state Python 3.14 + `uv` orchestration, the direct `.NET 10` tray build
path, or the narrowed installer-time PowerShell boundary. Keep docs explicit
about that distinction.

### Target-state validation still pending

The repository should not yet claim:

- clean-host installer validation for the in-progress architecture reset
- end-to-end installed-service plus tray lifecycle proof on a clean host
- cited successful end-to-end validation of the Python 3.14 + `uv` automation
  path
- cited successful end-to-end validation of the direct `.NET 10` tray build
  integration into released artifacts

## Contributor guardrails

- Treat ADR `0006` as the current target-state source of truth and ADR `0005`
  as the current quality/distribution companion. ADRs `0001` through `0004`
  remain historical context after the architecture reset.
- Keep `CONAN_HOME` repo-local at `.\.conan2`.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conandata.yml` aligned when the Squid pin changes. Prefer
  `uv run squid4win-automation upstream-version --execute`; keep
  `.\scripts\Update-SquidVersion.ps1` only as a transitional fallback when the
  Python automation environment is unavailable.
- Preserve artifact names `squid4win.msi` and `squid4win-portable.zip` unless
  the downstream packaging metadata changes with them.
- Keep live feed publication credential-gated.
- Do not copy GPL code from `diladele/squid-windows`; architectural inspiration
  is acceptable, source reuse is not.
- Treat `skills\` as the canonical home for repo-owned skills.
- Treat `.agents\skills\` as externally synced skills plus symlinks that expose
  repo-owned skills from `skills\`; `skills\gfm\SKILL.md` is repo-owned
  guidance, not vendored implementation.
- Never imply more validation than has actually been cited.

## Transitional implementation note

The supported repo-level entry points for Squid builds, tray builds, bundle
packaging, and Conan lockfile refresh now live under
`uv run squid4win-automation ...`.

Some checked-in `scripts\*.ps1` files still remain for installer-time behavior,
signing, smoke tests, dedicated installed-service validation, and historical
fallbacks. Keep them narrow and do not extend them as the long-term
orchestration model.

CI linting is now centered on MegaLinter via `.mega-linter.yml` and
`.github\linters\`, with `ty` kept as a companion Python type-check step
because MegaLinter does not currently expose a `ty` descriptor.

The installed service helper validates generated configs with
`squid.exe -k parse`, initializes the cache hierarchy with `squid.exe -z`, and
then registers the named Windows service with `squid.exe -i`.
`squid.exe -i -f <config>` follows Squid's native Windows service model: the
service keeps Squid-controlled runtime startup parameters, while the selected
config association is persisted separately for the named service.

Likewise, any remaining tray-related Conan packaging or editable flows should
be treated as migration leftovers or compatibility shims, not as the future
architecture.

## Target-state tooling

Plan future contributor and CI work around:

- Windows x64
- Git
- Conan 2 with repo-local `CONAN_HOME`
- Python 3.14
- `uv`
- .NET 10 SDK
- internet access to ConanCenter so the native Squid recipe can restore its
  managed MSYS2 and MinGW toolchain inputs

Current fallback validation may still rely on the older PowerShell helper
scripts for smoke tests and installed-service lifecycle validation, but new
contributor and CI automation should use `pyproject.toml`, `uv.lock`,
Python 3.14, and `uv` as the primary repo-level automation path. The core
automation commands — `squid-build`, `tray-build`, `bundle-package`, and
`conan-lockfile-update` — are now native Python orchestration with no
PowerShell bridge.

## Repository map

- `README.md` - contributor-facing project summary and migration status
- `AGENTS.md` - concise change guidance for human and AI contributors
- `.github\copilot-instructions.md` - repo-specific Copilot guardrails
- `.agents\design\` - ADR-style project memory, with ADR `0006` describing the
  current target state
- `skills\` - repo-owned custom skills and `skills\README.md`
- `.agents\skills\` - externally synced skills plus symlinks that expose
  repo-owned skills to Copilot
- `conanfile.py` and `conan\` - native Squid recipe inputs, patch metadata,
  host profiles, and lockfiles
- `scripts\` - transitional PowerShell automation plus installer-time helper
  scripts
- `src\tray\Squid4Win.Tray\` - direct `.NET 10` tray app source
- `packaging\wix\` - WiX v4 MSI authoring
- `.github\workflows\` - CI and release automation; do not infer the long-term
  architecture from lagging workflow details alone

## License

This repository is licensed under GPL-2.0-or-later. See `LICENSE`. Bundled or
vendored third-party content keeps its own notices and license terms.
