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
- Treat `.agents\skills\` as externally synced skill content plus repo-owned
  mirror directories backed by symlinked files into `skills\`; make repo-owned
  skill edits in `skills\...` and avoid incidental edits under
  `.agents\skills\`.
- If artifact names, release URLs, or package metadata/publication behavior
  changed, update `src\squid4win\package_managers.py`,
  `.github\workflows\package-managers.yml`,
  `.github\workflows\package-manager-publish.yml`, and the related docs in the
  same change.
- If a change affects an accepted design decision, update the relevant ADR under
  `.agents\design\`.
