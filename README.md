# squid4win

Windows-first build and packaging repository for upstream Squid on native
Windows.

## Architecture direction

The repository is being reset toward the target state defined in ADR `0006`:

- one self-contained native Squid Conan recipe under
  `conan\recipes\squid\all\` owns Squid source retrieval, patch application,
  and native MSYS2 + MinGW-w64 build
- Python 3.14 + `uv` owns repo-level stage assembly, runtime DLL adjacency,
  notice harvesting, smoke testing, MSI/portable packaging, and release-helper
  orchestration
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

### Cited local target-state validation

The current cited local validation for the reset architecture is:

- local `uv run squid4win-automation squid-build --execute --with-tray --with-runtime-dlls --with-packaging-support`
- local `uv run squid4win-automation smoke-test --execute --configuration Release --require-notices`
- local `uv run squid4win-automation bundle-package --execute --configuration Release --create-portable-zip`
- generated local artifacts at `artifacts\squid4win-portable.zip` and
  `artifacts\squid4win.msi`

That validates the Python-owned build, staging, direct `.NET 10` tray
integration, smoke-test, and packaging path on a development machine. It does
not yet prove clean-host installer behavior or installed-service lifecycle
validation on an isolated runner.

### Target-state validation still pending

The repository should not yet claim:

- clean-host installer validation for the in-progress architecture reset
- end-to-end installed-service plus tray lifecycle proof on a clean host
- cited successful execution of the Python `service-runner-validation` command
  on a dedicated isolated Windows runner

## Contributor guardrails

- Treat ADR `0006` as the current target-state source of truth and ADR `0005`
  as the current quality/distribution companion. ADRs `0001` through `0004`
  remain historical context after the architecture reset.
- Keep `CONAN_HOME` repo-local at `.\.conan2`.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conan\recipes\squid\all\conandata.yml` aligned when the Squid pin changes. Prefer
  `uv run squid4win-automation upstream-version --execute`; keep
  `.\scripts\Update-SquidVersion.ps1` only as a transitional fallback when the
  Python automation environment is unavailable.
- Preserve artifact names `squid4win.msi` and `squid4win-portable.zip` unless
  the downstream packaging metadata changes with them.
- Keep live feed publication credential-gated.
- Do not copy GPL code from `diladele/squid-windows`; architectural inspiration
  is acceptable, source reuse is not.
- Treat `skills\` as the canonical home for repo-owned skills.
- Treat `.agents\skills\` as externally synced skills plus mirror directories
  backed by symlinked files that expose repo-owned skills from `skills\`;
  `skills\gfm\SKILL.md` is repo-owned
  guidance, not vendored implementation.
- Never imply more validation than has actually been cited.

## Transitional implementation note

The supported repo-level entry points for Squid builds, tray builds, bundle
packaging, validation, metadata updates, and Conan lockfile refresh now live under
`uv run squid4win-automation ...`.

The CCI-style Squid recipe at `conan\recipes\squid\all\conanfile.py` can now
source `openssl`, `libxml2`, `pcre2`, and `zlib` either from Conan requirements
or from the MSYS2/system package set. The supported Python entry points expose
the matching `--openssl-source`, `--libxml2-source`, `--pcre2-source`, and
`--zlib-source` switches, while the default remains `system` to preserve the
current MSYS2-first validated path.
CI recipe validation now exercises three dependency profiles on both Linux and
Windows runners:

- `system-libraries`
- `conan-mixed` (Conan dependencies with shared OpenSSL and static `libxml2`,
  `pcre2`, and `zlib`)
- `conan-static` (Conan dependencies with static linkage for the same library set)

On Windows, the Conan-managed `libxml2` path currently forces `libxml2`'s
optional `iconv` feature off because the current Conan Center `libiconv/1.17`
recipe does not build reliably under MinGW/UCRT.

When any of those switches select `conan` and no explicit `--lockfile-path` is
provided, the Python automation uses a build-local lockfile under `build\`
instead of rewriting the committed default lockfile.

Some checked-in `scripts\*.ps1` files still remain for installer-time behavior,
optional signing, and historical update fallbacks. Keep them narrow and do not
extend them as the long-term orchestration model.

CI linting is now centered on MegaLinter via `.mega-linter.yml` and
`.github\linters\`, with `ty` kept as a companion Python type-check step
because MegaLinter does not currently expose a `ty` descriptor.

The installed service helper validates generated configs with
`squid.exe -k parse`, initializes the cache hierarchy with `squid.exe -z`, and
then registers the named Windows service with `squid.exe -i`.
`squid.exe -i -f <config>` follows Squid's native Windows service model: the
service keeps Squid-controlled runtime startup parameters, while the selected
config association is persisted separately for the named service. The helper
now verifies the registry-backed `ConfigFile` and `CommandLine` values
explicitly so service startup and spawned Squid processes do not fall back to
Squid's compiled default config path. Because upstream service startup splits
the stored `CommandLine` on whitespace without quote support, the install root
used for service registration must remain space-free.

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

Contributor and CI automation should use `pyproject.toml`, `uv.lock`, Python
3.14, and `uv` as the primary repo-level automation path. The core automation
commands — `squid-build`, `tray-build`, `bundle-package`, `smoke-test`,
`service-runner-validation`, and `conan-lockfile-update` — are now native
Python orchestration. `service-runner-validation` is intended for isolated
admin-capable Windows runners rather than shared development machines.

## Repository map

- `README.md` - contributor-facing project summary and migration status
- `AGENTS.md` - concise change guidance for human and AI contributors
- `.github\copilot-instructions.md` - repo-specific Copilot guardrails
- `.agents\design\` - ADR-style project memory, with ADR `0006` describing the
  current target state
- `skills\` - repo-owned custom skills and `skills\README.md`
- `.agents\skills\` - externally synced skills plus mirror directories backed
  by symlinked files that expose repo-owned skills to Copilot
- `conan\recipes\squid\all\` and `conan\` - the CCI-style native Squid recipe,
  patch metadata, host profiles, and lockfiles
- `scripts\` - installer-time helper scripts plus remaining narrow PowerShell
  exceptions such as optional signing and version-update fallback
- `src\tray\Squid4Win.Tray\` - direct `.NET 10` tray app source
- `packaging\wix\` - WiX v4 MSI authoring
- `.github\workflows\` - CI and release automation; do not infer the long-term
  architecture from lagging workflow details alone

## License

This repository is licensed under GPL-2.0-or-later. See `LICENSE`. Bundled or
vendored third-party content keeps its own notices and license terms.
