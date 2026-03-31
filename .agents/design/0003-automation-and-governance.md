# ADR 0003: Automation and governance

- Status: Accepted
- Date: 2026-03-30

## Context

This repository is intended to automate native Windows builds, MSI packaging,
and release handling for upstream Squid. Even before implementation lands, the
project needs clear governance for dependency updates, pull request review, and
the relationship between documentation and automation.

## Decision

The project will use GitHub as the automation control plane with these baseline
rules:

- use Dependabot for supported ecosystems
- use a companion workflow for Conan lockfile refresh because official
  Dependabot updates do not support Conan 2 directly
- use Copilot review on pull requests
- keep GitHub Copilot custom instructions in the repository and review them like
  workflow code
- allow auto-merge only after required checks and review policy succeed
- keep release publishing behind explicit approval until signing and packaging
  are proven stable
- keep prerelease artifact publication distinct from stable release publication
  so preview builds do not silently trigger stable downstream distribution work
- treat `.agents\design\*.md` files as required project memory for humans and
  agents
- prefer multiple focused workflows over one monolithic pipeline

Expected workflow separation:

- pull request validation
- native Squid build
- installer packaging
- prerelease publication
- stable release or publish

## Rationale

- Small, focused workflows are easier to reason about, rerun, and secure.
- Dependabot plus Copilot review reduces maintenance drag for supported
  dependency sources without removing human oversight.
- Auto-merge is useful for low-risk updates, but only when protected by status
  checks and repository policy.
- ADR-style design memory keeps future automation aligned with the original
  rationale instead of relying on tribal knowledge.

## Consequences

- Repository settings and branch protection will need to match the documented
  governance model once workflow files exist.
- Some update paths, especially Conan references and MSYS2 package drift, will
  still need manual review or custom automation.
- Contributors must update design docs when changes affect governance, workflow
  boundaries, or accepted architecture.

## Implementation notes

- Plan for Windows-based CI runners as the default execution environment.
- Keep `.github\workflows\update-upstream.yml` and
  `.github\workflows\conan-update.yml` separate so upstream Squid bumps and
  Conan dependency refreshes remain independently diagnosable.
- Keep `.github\workflows\prerelease.yml` separate from
  `.github\workflows\release.yml`, even if they share a reusable artifact-build
  workflow, so preview tags and stable tags remain independently diagnosable.
- Keep auto-merge scoped to changes that have low operational risk and complete
  validation coverage.
- Record workflow intent in documentation before YAML is added, then keep the
  docs synchronized with the implementation.

## Alternatives considered

### Manual builds and manual releases only

Rejected because the main purpose of this repository is automation and
repeatability.

### One large workflow for everything

Rejected because it would make debugging, permissions, and artifact promotion
harder to reason about.

### No persistent design memory

Rejected because build and release automation decisions are easy to lose when a
repository starts from infrastructure scaffolding.
