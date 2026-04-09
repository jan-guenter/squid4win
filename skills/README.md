# Repo-owned Copilot skills

This directory is the canonical home for repository-owned Copilot skills.
`.agents\skills\` contains externally synced skills plus mirror directories with
symlinked files that expose these repo-owned skills to Copilot.

## Index

- `click` - Click guidance for Python CLI commands, groups, parameters, shell
  completion, testing, and packaging-aware entry points.
- `conan2-package-creation` - Conan 2 package-authoring guidance for recipe
  structure, binary compatibility, `test_package`, editables, publication,
  and review criteria.
- `conan2-usage` - Conan 2 consumer guidance for installs, profiles,
  generators, remotes, lockfiles, and reproducible dependency graphs.
- `gfm` - GitHub Flavored Markdown guidance for repository files, GitHub
  rendering, practical patterns, Mermaid diagrams, and review criteria.
- `megalinter` - MegaLinter usage, configuration, local runner, CI
  integration, and review guidance for multi-language repositories.
- `proxy-runtime-validation` - Managed/live Squid runtime validation guidance
  for the Python proxy harness, local protocol matrix, artifact inspection, and
  MinGW DNS/socket regression triage.
- `rich` - Rich guidance for terminal formatting, shared `Console` usage,
  tables, status output, debugging aids, and readable styling.
- `shellingham` - Shellingham guidance for detecting the surrounding shell
  safely, handling `ShellDetectionFailure`, and providing sensible
  fallbacks.
- `skill-authoring` - Skill-authoring guidance for lean instructions,
  realistic evals, with/without-skill baselines, grading, human review, and
  repo-safe layout practices.
- `typer` - Typer guidance for type-hinted Python CLIs, subcommands,
  prompts, testing, completion, and packaging-aware UX.
- `wix-msi-installer` - WiX v4 MSI installer authoring for Windows desktop
  applications: built-in UI sets, feature selection, Squid service registration
  via native verbs, per-machine tray autostart, `WixQuietExec` custom actions,
  and the no-spaces install-root constraint.

## Maintaining this layout

- Externally synced skills: add them with
  `npx skills add -a github-copilot -y <repo> --skill <skill>`. That updates
  `.agents\skills\` and `skills-lock.json`; do not move them into `skills\`.
- Repo-owned skill frontmatter is validated by
  `uv run squid4win-automation skill-frontmatter-lint`.
- Repo-owned skills: create them under `skills\<skill-name>\`, create the
  matching `.agents\skills\<skill-name>\` mirror directory, and symlink the
  files inside it back to the canonical files under `skills\`.
- Keep `.agents\skills\<skill-name>\` as a real directory. Do not replace the
  skill directory itself with a symlink; that path-type change breaks
  Copilot PR review automation.
- Prefer repo-relative symlink targets so the mirrors stay valid on Linux and
  Windows checkouts.
- The common mirror target for a repo-owned skill file is
  `../../../skills/<skill-name>/<file-name>`.
- For this repository, keep repo-owned `SKILL.md` frontmatter on the current
  Copilot-compatible contract: required keys are `name`, `description`, and
  `skill_api_version: 1`. Optional keys should stay within the current
  supported set: `license`, `compatibility`, `metadata`, `allowed-tools`,
  `argument-hint`, `disable-model-invocation`, `user-invocable`, `model`,
  `effort`, `context`, `agent`, `hooks`, `paths`, and `shell`.
- Update this README whenever a repo-owned skill is added, removed, renamed,
  or materially re-described.
