---
name: megalinter
description: Configure and automate MegaLinter with explicit lint coverage, practical rule files, local runner guidance, and CI artifact handling.
skill_api_version: 1
---

# MegaLinter

Use this skill when you need to add, tune, review, or document MegaLinter
in a repository.

## Use this skill for

- designing or refactoring `.mega-linter.yml`
- choosing and scoping MegaLinter descriptors
- creating or organizing root-level linter config files that the underlying
  tools discover by default
- integrating MegaLinter into GitHub Actions or another CI system
- documenting local `mega-linter-runner` usage
- deciding when to keep a companion linter outside MegaLinter

## Do not use this skill for

- unrelated workflow refactors when the linting surface itself is not in
  scope
- enabling a large set of high-noise linters without a plan for rollout
  and ownership

## Guardrails

- Keep MegaLinter configuration in the repository root at
  `.mega-linter.yml` unless the host tooling requires an explicit
  alternate path.
- Prefer root-level linter config files when the underlying tool supports
  default discovery there.
- Prefer an explicit `ENABLE_LINTERS` list when stability matters so the
  lint surface does not change just because a new file type appears.
- Adopt additional linters in low-noise, reviewable increments.
- Keep separate companion checks when MegaLinter does not provide an
  acceptable equivalent for an existing required tool.
- Upload `megalinter-reports` and `mega-linter.log` as CI artifacts on
  success and failure.
- When MegaLinter is part of PR validation, make GitHub PR decoration explicit
  and pair it with a workflow-native markdown summary or report job so the
  overall lint surface stays readable even when companion checks remain outside
  MegaLinter.
- If the repository pins GitHub Actions by commit SHA, pin MegaLinter the
  same way.
- Remember that local `mega-linter-runner` usage can inherit the current
  shell environment into `docker run`; use a clean shell or scrub
  sensitive variables if that matters.

## Working method

1. Audit the current lint surface before changing it.
   - Identify the linters the repository already relies on.
   - Separate syntax checks, style checks, schema validation, type
     checking, and security scanning.
   - Note any existing rule files, ignore files, or CI-specific
     exceptions.
2. Map current tools to MegaLinter descriptors deliberately.
   - Keep exact-tool parity where practical.
   - If MegaLinter's available tool is stricter or meaningfully
     different, treat that as a policy change rather than a transparent
     migration.
   - Keep non-MegaLinter companion steps only when they remain necessary.
3. Scope the file set before enabling more checks.
   - Exclude generated, vendored, cache, and build directories up front.
   - Use linter-specific include or exclude filters when a descriptor
     should only target part of the tree.
   - Prefer filtering in MegaLinter itself rather than relying on every
     individual linter to rediscover the same scope.
4. Keep rule files close to the lint surface.
   - Reuse existing first-party configs when that avoids drift.
   - If MegaLinter uses a different config format than the repository's
     current standalone tool, document the translation and keep it
     reviewable.
5. Validate the migration with the real runner.
   - Run local `mega-linter-runner` when Docker is available.
   - Check the actual MegaLinter output rather than assuming the YAML is
     correct.
   - If a descriptor fails, determine whether the problem is
     configuration, scope, tooling differences, or genuine repo findings
     before changing code.

## Good defaults

- Use `ENABLE_LINTERS` instead of broad descriptor groups when
  reproducibility is more important than auto-discovery.
- Add `EXCLUDED_DIRECTORIES` early for caches, generated sources, build
  output, and dependency directories.
- Keep formatter-like descriptors blocking only when that matches the
  repository's current contract.
- Prefer low-noise additions such as JSON/YAML syntax or schema
  validation before introducing heavyweight security or policy linters.
- Treat security-oriented repository descriptors as an explicit rollout,
  not as a casual default.

## Minimal configuration pattern

```yaml
ENABLE_LINTERS:
  - MARKDOWN_MARKDOWNLINT
  - YAML_YAMLLINT

EXCLUDED_DIRECTORIES:
  - .agents/skills
  - artifacts
  - build
```

## Generic GitHub Actions recipe

```yaml
- name: MegaLinter
  id: megalinter
  continue-on-error: true
  uses: oxsecurity/megalinter@v9
  env:
    ENABLE_GITHUB_COMMENT: true
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    VALIDATE_ALL_CODEBASE: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}

- name: Upload MegaLinter reports
  if: ${{ always() }}
  uses: actions/upload-artifact@v4
  with:
    name: megalinter-reports
    include-hidden-files: true
    path: |
      megalinter-reports
      mega-linter.log
```

If a repository keeps a companion check outside MegaLinter, run it after
the MegaLinter step with `continue-on-error: true`, then add a final
explicit failure gate so one job can report the full lint surface.

## Local usage

```powershell
npx --yes mega-linter-runner
```

To test a specific release locally:

```powershell
npx --yes mega-linter-runner --release v9.4.0
```

## Evaluation guidance

Before finishing a MegaLinter change, check:

- Are the enabled descriptors exactly the ones the repository intends to
  run?
- Are generated, vendored, or cache directories excluded where
  necessary?
- Do rule files and ignore files match the repository's intended policy?
- Are report artifacts preserved in CI?
- If a companion step remains outside MegaLinter, is that exception still
  justified and documented?
- Have you validated the configuration with the actual runner rather than
  only by reading YAML?
- When iterating on the skill itself, compare at least one configuration
  design prompt and one CI-integration prompt.

## Sources

- MegaLinter docs:
  - [Home](https://megalinter.io/latest/)
  - [Configuration](https://megalinter.io/latest/configuration/)
  - [GitHub Action](https://megalinter.io/latest/install-github/)
  - [MegaLinter Runner](https://megalinter.io/latest/mega-linter-runner/)
  - [Reporters](https://megalinter.io/latest/reporters/)
