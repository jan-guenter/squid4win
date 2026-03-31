# GitHub Copilot instructions for squid4win

Start with `README.md`, `AGENTS.md`, and the ADRs under `.agents\design\`.
Those files are the source of truth for repository state, contributor guidance,
and validation status. Do not duplicate their general rules here.

Repo-specific directives:

- Preserve the Conan-first Windows path: the root `conanfile.py` owns Squid
  source retrieval, patch application, native MSYS2/MinGW build, and staged
  bundle assembly.
- Keep the tray app as a separate Conan-packaged `.NET 8` WPF deliverable; do
  not reintroduce an ad hoc primary packaging path.
- Keep `CONAN_HOME` repo-local at `.\.conan2` and prefer repo-relative paths.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conandata.yml` aligned when the Squid pin changes. Prefer
  `.\scripts\Update-SquidVersion.ps1`.
- Treat `.agents\design\*.md` as project memory. If an accepted design changes,
  update the ADR and preserve its alternatives/history sections.
- Treat `.agents\skills\` as vendored third-party content and update it
  deliberately.
- Do not copy GPL code from `diladele/squid-windows`. Architectural inspiration
  is acceptable; source reuse is not.
- Do not imply clean-host installer validation or end-to-end installed-service
  proof unless that validation actually happened.
- Preserve current artifact names `squid4win.msi` and
  `squid4win-portable.zip` unless you also update the downstream packaging
  metadata flow.
- Keep live feed publication credential-gated.
- Never commit secrets or machine-specific paths.
