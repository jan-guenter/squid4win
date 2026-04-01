---
applyTo: "**"
---

# Repo-owned skill layout

- Treat `skills-lock.json` as the source of truth for externally synced
  skills.
- Add external skills with
  `npx skills add -a github-copilot -y <repo> --skill <skill>` and leave them
  under `.agents\skills\`.
- Add repo-owned skills under `skills\<skill-name>\`.
- Create or update the matching `.agents\skills\<skill-name>` symlink so
  Copilot can discover the repo-owned skill from the standard skill
  location.
- Update `skills\README.md` whenever a repo-owned skill is added, renamed,
  removed, or materially re-described.
- When docs mention a repo-owned skill, prefer the canonical `skills\...`
  path and mention `.agents\skills\...` only when the symlink or
  discovery path matters.
