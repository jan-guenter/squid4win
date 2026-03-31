# GitHub Copilot instructions for squid4win

Before changing this repository, read `README.md`, `AGENTS.md`, and the ADRs
under `.agents\design\`.

Key repository rules:

- Keep `config\squid-version.json` and `conan\squid-release.json` synchronized.
  Prefer `scripts\Update-SquidVersion.ps1` over editing only one file.
- Do not copy GPL code from `diladele/squid-windows`. Architectural inspiration
  is acceptable; source reuse is not.
- Preserve the currently proven native Windows build path:
  `MSYS2 + MinGW-w64 + PowerShell orchestration + WiX packaging`.
- Keep `CONAN_HOME` repo-local at `.\.conan2` and prefer repo-relative paths.
- Treat `.agents\skills\` as vendored third-party content. Update it
  intentionally with `npx skills add -a github-copilot -y <repo> --skill <skill>`
  instead of hand-editing skill files.
- If you change workflows, build scripts, review guidance, or upgrade guidance,
  update `README.md`, `AGENTS.md`, and any affected files under
  `.github\instructions\` in the same change.
- If you change an accepted architectural decision, update the relevant ADR under
  `.agents\design\`.
- Never commit secrets or copy values from `.env`.

Release and packaging rules:

- Preserve the current artifact names `squid4win.msi` and
  `squid4win-portable.zip` unless you also update the downstream package-manager
  metadata generation flow.
- Keep Sonar exclusions aligned with the repository layout, especially generated
  directories and vendored skills.
- Keep package-manager publication credential-gated. Generating manifests is
  safe; live publication should only run through the documented secret-gated
  workflow path.
- If you change feed metadata generation or publication, keep
  `scripts\Export-PackageManagerMetadata.ps1`, the package-manager publish
  helpers under `scripts\`, `.github\workflows\package-managers.yml`, and
  `.github\workflows\package-manager-publish.yml` synchronized.
