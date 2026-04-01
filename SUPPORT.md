# Support

Use this guide to choose the right path before opening a new public thread.

## Before you open anything

Read the current project state first:

- `README.md`
- `CONTRIBUTING.md`
- `.github\README.md`
- ADRs `0005` and `0006` under `.agents\design\`

That context matters because the repository is in transition between a last
validated legacy implementation and a new target architecture.

## Where to ask for help

### Reproducible bugs and regressions

Open a bug report and include:

- the branch, tag, or commit you tested
- the workflow, script, or file path involved
- reproduction steps
- relevant logs or error messages

### Features, workflow reshaping, and architecture ideas

Open a feature request issue. Be explicit about whether the request is about:

- the current checked-in implementation
- the target-state migration toward root Conan ownership, Python 3.14 + `uv`,
  and direct `.NET 10` tray builds
- both

### Security concerns

Follow `.github\SECURITY.md`. Do not post unresolved exploit details,
credentials, or signing material in a public issue.

### Documentation or process gaps

Open an issue or pull request that points at the exact file paths that appear to
be out of date.

## Please do not post publicly

- secrets, tokens, private keys, certificates, or machine credentials
- exploit details for unresolved security issues
- personal information that you do not want permanently attached to a public
  thread

## Response expectations

Support is handled on a best-effort basis by the maintainers. Clear
reproduction details and precise file references make it much easier to help.
