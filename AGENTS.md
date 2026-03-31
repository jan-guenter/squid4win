# Agent guidance for squid4win

Before changing this repository, verify the current state from the files that
actually drive it. Do not rely on stale templates or earlier assumptions.

## Read first

1. `README.md`
2. every ADR under `.agents\design\`
3. `config\squid-version.json`, `conan\squid-release.json`, and `conandata.yml`
   if you touch the Squid pin or native build metadata
4. `scripts\`, `conanfile.py`, `packaging\wix\`, and `.github\workflows\` if you
   touch automation, packaging, or release behavior
5. `.github\copilot-instructions.md` and `.github\instructions\` if you touch
   contributor or Copilot guidance

## Current state summary

- Upstream pin: Squid `7.5` (`SQUID_7_5`)
- Native Windows builds remain Conan-first with Conan-managed MSYS2 + MinGW-w64.
- The root `conanfile.py` owns Squid source retrieval, patch application,
  native build, and bundle assembly.
- The tray app is a separate `.NET 8` WPF deliverable packaged through
  `conan\recipes\tray-app`.
- WiX v4 MSI authoring and payload staging are committed.
- The current repo state has been locally validated through native build,
  native install tree creation, portable zip creation, and MSI build.
- Clean-host installer and installed-service lifecycle validation are still
  pending.

For detailed Conan toolchain, installer, and automation rationale, use
`README.md` plus ADRs `0001` through `0005` instead of duplicating those
details here.

## Project memory rule

- Treat `.agents\design\*.md` as required project memory.
- If an accepted design changes, update the relevant ADR in the same change.
- Preserve ADR alternatives and history sections when updating an ADR.
- If a new major decision is introduced, add a new numbered ADR.
- If one ADR replaces another, mark the old ADR as superseded and point to the
  replacement.

## Change hygiene

- Keep `README.md`, `AGENTS.md`, and `.github\copilot-instructions.md` aligned
  when contributor guidance changes.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conandata.yml` aligned when the Squid pin changes. Prefer
  `.\scripts\Update-SquidVersion.ps1`.
- Keep docs truthful about what is committed, what has only been locally
  validated, and what is still unproven on a clean host.
- Do not claim a finished MSI or installed-service lifecycle path unless you
  actually validated it.
- If installer behavior changes, keep `conanfile.py`,
  `scripts\Stage-ReleasePayload.ps1`, `scripts\Build-Installer.ps1`, and
  `packaging\wix\` synchronized.
- If native runtime DLL harvesting or MinGW-linked imports change, keep
  `conandata.yml` and `conanfile.py` synchronized.
- Treat `.agents\skills\` as vendored third-party content and update it
  deliberately.
- Prefer repo-relative paths and repo-local state; do not introduce
  machine-specific tool paths or secrets.

## When current state changes

At minimum, update:

- `README.md` for contributor-facing state and common flows
- `AGENTS.md` for future contributor guidance
- the affected ADR under `.agents\design\`
- `.github\copilot-instructions.md` or `.github\instructions\` when Copilot
  guidance changes
- `config\*.json`, `conan\*.json`, and `conandata.yml` when version metadata or
  build defaults change

Future contributors should be able to understand the current truth of the
repository without reconstructing it from commit history.
