# ADR 0005: Quality scanning and downstream package metadata

- Status: Accepted
- Date: 2026-03-31

## Context

The repository now has a proven native Windows build and packaging path, but it
also needs a repeatable quality gate and a durable hand-off into downstream
distribution channels. The user has already provisioned SonarQube project
credentials for GitHub Actions and wants the repository to prepare future
publication to winget, Chocolatey, and Scoop.

At the same time, the repository now vendors third-party skills under
`.agents\skills\`, which should not be scanned or reviewed as first-party
project code by default.

## Decision

The automation baseline is:

- run SonarQube analysis from CI after the native Windows build and smoke tests
- enforce the Sonar quality gate on pull requests and mainline builds
- keep the Sonar host configurable, with a default compatible with SonarCloud
- exclude generated outputs, local caches, and vendored `.agents\skills\`
  content from scan scope
- generate winget, Chocolatey, and Scoop metadata from released artifacts in a
  dedicated workflow
- keep live publication to package feeds credential-gated until the required
  feed accounts and tokens are available

## Rationale

- The native Windows build is the highest-value validation path, so quality
  analysis should attach to that pipeline instead of a disconnected static-only
  job.
- Quality gates help keep automated version bumps and dependency updates from
  silently degrading maintainability.
- Package-manager metadata should be generated from the real release artifacts so
  URLs and checksums stay aligned with the published MSI and portable zip.
- Vendored skills should not generate noise in Sonar or review flows unless a
  change intentionally updates those skills.

## Consequences

- CI now owns both native build health and the Sonar quality signal.
- Release automation must preserve stable artifact names because downstream
  package metadata generation depends on them.
- Feed publication remains partially scaffolded until credentials are supplied,
  but the repository can already produce the metadata required for later pushes.
- Any change to artifact names, release URLs, or scan exclusions must update the
  workflows, docs, and Copilot instructions together.

## Implementation notes

- Keep the Sonar scope in `sonar-project.properties`.
- Keep feed metadata generation in `scripts\Export-PackageManagerMetadata.ps1`.
- Keep `.github\workflows\package-managers.yml` responsible for downloading
  release assets and generating feed metadata from those real binaries.
- Keep credentials out of the repository and document required secret names in
  the contributor docs instead.

## Alternatives considered

### Run Sonar only on a lightweight lint job

Rejected because the most important risk in this repository is the native
Windows build and packaging path, not only repo text files.

### Publish directly to package feeds from the first workflow revision

Rejected because feed automation without the required accounts, tokens, and
publisher policy would create a brittle blind push path.
