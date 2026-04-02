# ADR 0005: Quality scanning and downstream package automation

- Status: Accepted
- Date: 2026-03-31
- Updated: 2026-04-01

## Context

The repository now has a proven native Windows build and packaging path, but it
also needs a repeatable quality gate and a durable hand-off into downstream
distribution channels. The user has already provisioned SonarQube project
credentials for GitHub Actions and wants the repository to prepare future
publication to winget, Chocolatey, and Scoop.

At the same time, the repository now keeps externally synced skills under
`.agents\skills\` while storing repo-owned skills canonically under
`skills\` and exposing them back through `.agents\skills\` symlinks.
Externally synced skill files should not be scanned or reviewed as first-party
project code by default, except for repo-owned guidance such as
`skills\gfm\SKILL.md`.

Repository guidance now includes the repo-owned GFM skill at
`skills\gfm\SKILL.md` plus a markdown audit path, so documentation quality
needs to be part of the first-party quality story instead of an implicit side
concern.

## Decision

The automation baseline is:

- run SonarQube analysis from CI after the native Windows build and smoke tests
- enforce the Sonar quality gate on pull requests and mainline builds
- keep the Sonar host configurable, with a default compatible with SonarCloud
- add installed-service lifecycle validation automation in a dedicated Windows
  workflow that builds an MSI with a unique temporary service name, installs it
  under an isolated root, starts and stops the service, and uninstalls it with
  cleanup
- exclude generated outputs, local caches, and externally synced
  `.agents\skills\` content from scan scope
- keep markdownlint, `skills\gfm\SKILL.md`, and repo-owned markdown audits
  as the first-party documentation quality path, while continuing to exclude
  externally synced `.agents\skills\` content unless a change intentionally
  updates it
- keep prerelease artifact publication separate from stable release publication,
  and do not auto-generate downstream package-manager metadata from prerelease
  GitHub releases
- gate tag-triggered GitHub release publication with the `release-approval`
  environment after artifact build/upload completes and before the GitHub
  release itself is published
- add release-integrity scaffolding that emits a SHA256 manifest for the MSI and
  portable zip, attempts GitHub artifact attestations when the platform supports
  them, and uploads the attestation bundle alongside the built artifacts
- keep Windows Authenticode signing hooks for staged payload executables,
  packaged helper scripts, and the MSI available for non-publishing/manual
  builds until signing material is explicitly provisioned
- fail tag-triggered GitHub release publication when signing material is absent
  or when the portable zip payload or MSI would be published unsigned
- require tag-triggered GitHub release/prerelease publication to point to a
  commit already reachable from `main`
- generate winget, Chocolatey, and Scoop metadata from released artifacts in a
  dedicated workflow
- keep live publication in a separate manual workflow that reuses that
  metadata-generation path and only runs the explicitly selected feed jobs
- require the expected feed accounts, tokens, and repository variables before
  any live publication job runs

## Rationale

- The native Windows build is the highest-value validation path, so quality
  analysis should attach to that pipeline instead of a disconnected static-only
  job.
- Installed-service lifecycle validation needs service control and MSI cleanup,
  so it should stay in a dedicated workflow instead of being bolted onto the
  shared CI job that other changes may edit concurrently.
- Unique temporary service names keep runner validation isolated from any other
  service registration on the same machine.
- Quality gates help keep automated version bumps and dependency updates from
  silently degrading maintainability.
- Documentation quality is part of the repository's architecture control
  surface, especially while contributor guidance is resetting around the GPL
  migration and the automation split.
- Package-manager metadata should be generated from the real release artifacts so
  URLs and checksums stay aligned with the published MSI and portable zip.
- Release consumers need an integrity signal before final code-signing
  credentials exist, so checksums and attestations should be available without
  changing the artifact names or forcing a new credential dependency.
- Unsigned artifact builds are still useful for local validation and non-
  publishing workflow runs, but tag-triggered GitHub releases should never
  publish an unsigned MSI or portable zip.
- Tag-triggered publication should inherit the repository's protected-main
  quality posture instead of trusting maintainers to tag an arbitrary SHA.
- Vendored skills should not generate noise in Sonar or review flows unless a
  change intentionally updates those skills.

## Consequences

- CI now owns both native build health and the Sonar quality signal.
- Quality automation now also owns a dedicated Windows runner automation path
  for MSI install/register/start/stop/uninstall exercises with explicit
  cleanup.
- Release automation must preserve stable artifact names because downstream
  package metadata generation depends on them.
- Preview releases stop at GitHub prerelease assets; downstream package-manager
  metadata remains a stable-release concern.
- `README.md`, `AGENTS.md`, `.github\copilot-instructions.md`, and
  `skills\gfm\SKILL.md` now need to stay synchronized with the markdown
  audit expectations.
- Release assets may now include checksum and attestation sidecars in addition
  to the MSI and portable zip, while tag-triggered GitHub release publication
  now remains blocked until real Authenticode signing credentials are available.
- Release/prerelease tag publication now also rejects tags that do not point to
  commits already reachable from `main`.
- Feed publication now stays tied to the generated metadata, but it runs only
  from the dedicated manual publication workflow instead of the metadata
  workflow itself.
- Any change to artifact names, release URLs, or scan exclusions must update the
  workflows, docs, and Copilot instructions together.

## Implementation notes

- Keep the Sonar scope in `sonar-project.properties`.
 - Keep
   `uv run squid4win-automation service-runner-validation --execute`
   responsible for generating a unique temporary service name, staging an
   isolated validation root, invoking the MSI, and cleaning up leftover runner
   state.
- Keep `.github\workflows\service-runner-validation.yml` responsible for the
  isolated Windows runner lifecycle validation path.
- Keep `.markdownlint-cli2.jsonc` as the baseline markdown lint
  configuration, and align `skills\gfm\SKILL.md` plus any repo-owned
  markdown audit helper with it.
- Keep feed metadata generation in
  `uv run squid4win-automation package-manager-export --execute`, backed by the
  Python automation package.
- Keep `scripts\Invoke-AuthenticodeSigning.ps1` responsible for optional
  Authenticode signing when a certificate path or base64-encoded PFX secret is
  provided.
- Keep the credential-gated winget, Chocolatey, and Scoop hand-off steps in the
  Python automation package, with workflows passing secrets and target
  repositories through environment variables instead of repo-local PowerShell
  wrappers.
- Keep `.github\workflows\package-managers.yml` scoped to stable published
  releases; prerelease workflows should stop after GitHub prerelease asset
  publication.
- Keep `.github\workflows\build-release-artifacts.yml` responsible for
  generating the release checksum manifest and best-effort GitHub artifact
  attestations for the MSI and portable zip.
- Keep `.github\workflows\package-managers.yml` responsible for downloading
  release assets and generating feed metadata from those real binaries.
- Keep `.github\workflows\package-manager-publish.yml` responsible for the
  manual credential-gated publication path.
- Keep credentials out of the repository and document required secret names in
  the contributor docs instead.

## Alternatives considered

### Run Sonar only on a lightweight lint job

Rejected because the most important risk in this repository is the native
Windows build and packaging path, not only repo text files.

### Publish directly to package feeds from the first workflow revision

Rejected because feed automation without the required accounts, tokens, and
publisher policy would create a brittle blind push path.
