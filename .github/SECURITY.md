# Security policy

Security reports are welcome for squid4win.

This repository is in an architecture transition, so please keep reports clear
about whether the issue affects the current checked-in implementation, the
accepted target-state direction, or both.

## What to report

Report vulnerabilities or security-relevant mistakes in:

- source code and default configuration
- the native build, packaging, and installer paths
- GitHub Actions workflows and release automation
- package-manager metadata generation or publication helpers
- shipped artifacts or bundled first-party scripts

## How to report

1. Use GitHub private vulnerability reporting for this repository when that
   option is available.
2. If private reporting is not available, open a minimal public issue that asks
   maintainers for a private handoff. Do not include exploit details,
   credentials, private keys, certificates, or full proof-of-concept payloads
   in that issue.
3. Include the affected branch, tag, or commit, the relevant file paths or
   workflow names, the impact, and the shortest reliable reproduction you have.

## Supported lines

- `main` is the primary supported development line.
- Stable release tags built from `main` are the intended release baseline.
- Prerelease tags are for early validation and may change without downstream
  package-manager publication.
- Older branches or historical tags may not receive backports.

## Response expectations

Reports are handled on a best-effort basis. The maintainers do not currently
publish a guaranteed response or remediation SLA.

## Disclosure guidance

Please keep a report private until maintainers confirm that a fix, mitigation,
or explicit risk acceptance path is ready.
