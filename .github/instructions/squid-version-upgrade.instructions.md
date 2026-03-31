---
applyTo: "**"
---

# Squid version upgrade checklist

Use this checklist when a change updates the pinned upstream Squid release or
the automation around that update flow.

- Prefer `scripts\Update-SquidVersion.ps1` over hand-editing version files.
- Keep `config\squid-version.json` and `conan\squid-release.json` synchronized.
- Re-check `scripts\Apply-SquidSourcePatches.ps1` against the new upstream
  release and remove or adjust patches only with evidence.
- Re-run the native build path and smoke tests after the version bump.
- Update any release, package-manager, or documentation text that mentions the
  pinned Squid version.
- If the upgrade changes accepted behavior, add or update an ADR under
  `.agents\design\`.
- Keep update PR messaging honest about what was regenerated versus what was
  manually changed.
