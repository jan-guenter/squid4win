---
applyTo: "**"
---

# Pull request review checklist

When reviewing or preparing a change in this repository:

- Verify the change matches the current contracts in `README.md`, `AGENTS.md`,
  and `.agents\design\`.
- Keep `config\squid-version.json` and `conan\squid-release.json` aligned if the
  Squid pin changes.
- If a workflow, script, or installer behavior changed, verify the corresponding
  documentation changed too.
- Preserve the current native Windows build path unless the replacement was
  actually validated.
- Do not introduce machine-specific paths, secrets, or hidden global build
  state.
- Treat `.agents\skills\` as vendored third-party content and avoid incidental
  edits there.
- If artifact names, release URLs, or package metadata changed, update
  `scripts\Export-PackageManagerMetadata.ps1` and related workflow/docs in the
  same change.
- If a change affects an accepted design decision, update the relevant ADR under
  `.agents\design\`.
