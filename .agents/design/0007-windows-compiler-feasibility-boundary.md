# ADR 0007: Windows compiler feasibility boundary

- Status: Accepted
- Date: 2026-04-04
- Relates to: ADR 0006

## Context

The repository's accepted target state already centers on one standalone Squid
Conan recipe and a validated MSYS2 + MinGW-w64 Windows build path. A follow-up
request asked the project to explore whether the same Squid recipe should also
support direct Microsoft `cl.exe` and `clang-cl` builds, potentially with
user-supplied bash implementations such as WSL, MSYS2, or Git Bash plus
automatic Visual Studio discovery through `vswhere` and `VsDevCmd.bat`.

That investigation matters because the enabling plumbing is partially real:

- Microsoft documents `vswhere`, `VsDevCmd.bat`, and Developer PowerShell as the
  supported Visual Studio activation surfaces
- Conan 2 already supports `tools.microsoft.bash:path`,
  `tools.microsoft.bash:subsystem`, and `VCVars`
- `clang-cl` can participate in MSVC-style Windows builds when the underlying
  source tree and build system support it

However, Squid's upstream Windows build and Autotools model still assume a
GCC/MinGW-style environment with the MinGW runtime and POSIX compatibility
layer. The blockers therefore sit above toolchain discovery.

## Decision

The current feasibility boundary is:

- keep direct Microsoft `cl.exe` support out of the repository's current target
  state
- keep direct `clang-cl` support out of the repository's current target state
- keep MSYS2 + MinGW-w64 as the validated and accepted Windows compiler model
- if the project wants a Clang-based Windows follow-up, prefer **MSYS2-Clang**
  first because it preserves the MinGW runtime and POSIX compatibility layer
- only revisit direct `cl.exe` or `clang-cl` if a future ADR explicitly accepts
  an upstream-divergent Squid patch strategy and new validation evidence

## Rationale

- Squid's upstream `configure.ac` and Windows guidance remain GCC/MinGW-oriented
  rather than MSVC-oriented.
- The core blocker is not Visual Studio discovery; it is Squid's dependence on
  MinGW/POSIX semantics that the MSVC runtime does not provide.
- `clang-cl` inherits the same build-system and portability blockers even though
  the Visual Studio and LLVM plumbing is technically available.
- WSL does not solve the direct MSVC-family problem because it cannot natively
  execute Win32 toolchain binaries inside the Linux kernel environment.
- MSYS2-Clang offers the practical LLVM path because it keeps the runtime model
  Squid already expects while still enabling Clang-based diagnostics and tool
  experimentation.

## Consequences

- Contributor docs and Copilot guidance must not imply that direct `cl.exe` or
  `clang-cl` support is accepted or validated today.
- The repository should not expand Windows profiles, lockfiles, or workflow
  matrices around direct MSVC-family compilers in the current phase.
- Future LLVM-on-Windows work should start with MSYS2-Clang rather than with a
  Visual-Studio-runtime path.
- Any future direct `cl.exe` or `clang-cl` spike must stay explicitly
  experimental until a later ADR and full validation say otherwise.

## Implementation notes

- Keep `conan\profiles\msys2-mingw-x64` as the baseline Windows profile.
- If a Clang-based follow-up is implemented, add it as a local-proof-first path
  that preserves the MinGW runtime model.
- Keep `README.md`, `AGENTS.md`, and `.github\copilot-instructions.md` aligned
  with this boundary.
- If a later implementation revisits direct `cl.exe` or `clang-cl`, document the
  required Squid patch maintenance strategy in a new ADR instead of hiding it in
  recipe code.

## Alternatives considered

### Pursue direct `cl.exe` support now

Rejected because the upstream Squid build system and Windows portability layer
remain GCC/MinGW-oriented, so the problem is larger than Visual Studio
discovery or shell activation.

### Pursue direct `clang-cl` support now

Rejected because it inherits the same Autotools flag-model and POSIX-runtime
blockers even though Conan and Visual Studio can supply the required toolchain
plumbing.

### Leave the feasibility result undocumented

Rejected because future contributors would otherwise repeat the same
investigation and risk overclaiming support that the repository does not
actually have.
