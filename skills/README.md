# Repo-owned Copilot skills

This directory is the canonical home for repository-owned Copilot skills.
`.agents\skills\` contains externally synced skills plus mirror directories with
symlinked files that expose these repo-owned skills to Copilot.

## Index

- `conan2-package-creation` - Conan 2 package-authoring guidance for recipe
  structure, binary compatibility, `test_package`, editables, and publication.
- `conan2-usage` - Conan 2 consumer guidance for installs, profiles,
  generators, remotes, and reproducible dependency graphs.
- `gfm` - GitHub Flavored Markdown guidance for repository files, GitHub
  rendering, advanced formatting, and Mermaid diagrams.
- `megalinter` - MegaLinter usage, configuration, local runner, and CI guidance
  for multi-language repositories.

## Maintaining this layout

- Externally synced skills: add them with
  `npx skills add -a github-copilot -y <repo> --skill <skill>`. That updates
  `.agents\skills\` and `skills-lock.json`; do not move them into `skills\`.
- Repo-owned skills: create them under `skills\<skill-name>\`, create the
  matching `.agents\skills\<skill-name>\` mirror directory, and symlink the
  files inside it back to the canonical files under `skills\`.
- Keep `.agents\skills\<skill-name>\` as a real directory. Do not replace the
  skill directory itself with a symlink; that path-type change breaks Copilot
  PR review automation.
- Prefer repo-relative symlink targets so the mirrors stay valid on Linux and
  Windows checkouts.
