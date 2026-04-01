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
- Release automation now separates prerelease and stable GitHub release paths,
  but both build from the root Conan recipe before payload staging and MSI
  assembly.
- The staged release bundle now carries harvested third-party notices for Squid,
  the bundled native runtime DLL set, and the tray app's shipped NuGet package
  dependency set.
- The current repo state has been locally validated through native build,
  native install tree creation, portable zip creation, and MSI build.
- The repository now includes committed GitHub Actions automation for a
  runner-safe installed-service lifecycle path on isolated Windows runners with
  unique temporary service names and isolated cleanup.
- `main` is protected by required checks for `Lint automation`, `Build tray
  app`, `Build MSYS2/MinGW-w64`, and `SonarCloud Code Analysis`.
- Tag-triggered GitHub release publication now pauses on the
  `release-approval` environment after artifact build/upload and before the
  GitHub release is published, and it refuses to publish unsigned artifacts
  when signing credentials are not configured.
- Tag-triggered release/prerelease publication now consumes the committed
  `conan\lockfiles\` state without refreshing it during the publish run and only
  allows tags that point to commits already reachable from `main`.
- Cited successful execution of that workflow, clean-host installer upgrade
  validation, and end-to-end installed-service plus tray-app lifecycle
  validation are still pending.

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
- Do not claim successful runner-safe, clean-host, or tray-app lifecycle proof
  beyond the committed automation and any explicitly cited successful
  validation.
- If installer behavior changes, keep `conanfile.py`,
  `scripts\Stage-ReleasePayload.ps1`, `scripts\Build-Installer.ps1`, and
  `packaging\wix\` synchronized.
- If release workflow behavior changes, keep
  `.github\workflows\build-release-artifacts.yml`,
  `.github\workflows\prerelease.yml`, `.github\workflows\release.yml`, and
  `.github\workflows\package-managers.yml` synchronized.
- Keep tag-triggered GitHub release publication gated by the `release-approval`
  environment after artifacts are built and before the GitHub release is
  published, and keep signed-artifact checks in place so release/prerelease tag
  runs fail instead of publishing unsigned assets.
- Keep tag-triggered release/prerelease publication tied to the committed Conan
  lockfile and to commits already reachable from `main`; do not re-resolve the
  reviewed lockfile graph during the publish run.
- If native runtime DLL harvesting or MinGW-linked imports change, keep
  `conandata.yml`, `conanfile.py`, and the staged notice bundle synchronized.
- Keep the committed `conan\lockfiles\` flow cache-backed; use
  `-UseTrayEditable` only for local root+tray iteration so editable lockfiles
  stay under `build\conan\`.
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
