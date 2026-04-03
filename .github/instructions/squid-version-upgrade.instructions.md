---
applyTo: "**"
---

# Squid version upgrade checklist

Use this checklist when a change updates the pinned upstream Squid release or
the automation around that update flow.

- Prefer `uv run squid4win-automation upstream-version --execute` over
  hand-editing version files. Keep `scripts\Update-SquidVersion.ps1` only as a
  transitional fallback when the Python automation environment is unavailable.
- Keep `config\squid-version.json`, `conan\squid-release.json`, and
  `conan\recipes\squid\all\conandata.yml` synchronized.
- Re-check the ordered patch series under
  `conan\recipes\squid\all\patches\*.patch` and the
  matching `conan\recipes\squid\all\conandata.yml` patch entries against the new
  upstream release, and remove or adjust patches only with evidence.
- Re-run the native build path and smoke tests after the version bump.
- Update any release, package-manager, or documentation text that mentions the
  pinned Squid version.
- If the upgrade changes accepted behavior, add or update an ADR under
  `.agents\design\`.
- Keep update PR messaging honest about what was regenerated versus what was
  manually changed.
