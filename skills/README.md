# Repo-owned Copilot skills

This directory is the canonical home for squid4win-owned Copilot skills.
`.agents\skills\` contains externally synced skills plus symlinks that expose
these repo-owned skills to Copilot.

## Index

- `conan2-package-creation` - Conan 2 package-authoring guidance for
  recipes, binary compatibility, `test_package`, editables, and safe
  publishing.
- `conan2-usage` - Conan 2 consumer guidance for installs, profiles, CMake
  integration, remotes, and reproducible dependency graphs.
- `gfm` - GitHub Flavored Markdown guidance for squid4win docs, GitHub
  rendering, advanced formatting, and Mermaid diagrams.

## Maintaining this layout

- Externally synced skills: add them with
  `npx skills add -a github-copilot -y <repo> --skill <skill>`. That updates
  `.agents\skills\` and `skills-lock.json`; do not move them into
  `skills\`.
- Repo-owned skills: create them under `skills\<skill-name>\`, create the
  matching `.agents\skills\<skill-name>` symlink that points back to
  `..\..\skills\<skill-name>`, and keep this README in sync.
