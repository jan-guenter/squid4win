---
name: proxy-runtime-validation
description: Validate Squid4Win proxy runtime behavior with a managed Squid process, local origin servers, burst traffic, and advisory external DNS/TLS sanity checks.
skill_api_version: 1
---

# Proxy runtime validation

Use this skill when validating or debugging the real Squid4Win proxy runtime on
Windows, especially after native Squid recipe patches or when investigating
intermittent proxy failures that do not show up in packaging-only checks.

## Use this skill for

- running `uv run squid4win-automation proxy-runtime-validation ...`
- choosing between a managed Squid probe (`--binary-path` + `--install-root`)
  and an existing live proxy (`--proxy-url`)
- exercising the local HTTP/HTTPS/HTTP2/compression/redirect/stream/burst matrix
- reading `summary.md`, `summary.json`, and managed `cache.log` / `access.log`
  artifacts under `artifacts\proxy-runtime\`
- investigating MinGW socket, DNS, TLS tunnel, or descriptor regressions

## Do not use this skill for

- MSI install/uninstall lifecycle validation; use
  `uv run squid4win-automation service-runner-validation`
- browser-driven UI testing; this harness validates the forward proxy itself
- high-volume internet load testing against public services

## Recommended repo flow

1. Rebuild the staged binary:

   `uv run squid4win-automation squid-build --with-runtime-dlls --with-packaging-support`

2. Run the deterministic local matrix against the rebuilt stage:

   `uv run squid4win-automation proxy-runtime-validation --binary-path build\install\release\sbin\squid.exe --install-root build\install\release --skip-external`

3. Add advisory external sanity traffic only when needed for DNS/TLS triage:

   `uv run squid4win-automation proxy-runtime-validation --binary-path build\install\release\sbin\squid.exe --install-root build\install\release`

4. For a live installed proxy already listening, target it directly:

   `uv run squid4win-automation proxy-runtime-validation --proxy-url http://127.0.0.1:3128 --skip-external`

## Reading results

- `summary.md` is the operator-friendly overview.
- `summary.json` is the machine-readable record for follow-up tooling.
- `managed-proxy\var\logs\cache.log` is the first place to look for Squid-side
  runtime failures during managed runs.

## Repo-specific guidance

- The local matrix is the clean cited validation path because it is
  deterministic and self-hosted.
- External scenarios are advisory sanity checks. Upstream endpoint behavior can
  fail independently of Squid; inspect the managed Squid logs before treating an
  external-only failure as a proxy regression.
- If `cache.log` shows `idnsRead ... Bad file descriptor` or
  `fd.cc:169: "fd < Squid_MaxFD"`, suspect a MinGW socket-wrapper regression in
  the Squid recipe patch series.
