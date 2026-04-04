# Pull request

## Summary

- Describe the change.

## Related issues

- Link issues or write `None`.

## Repository state targeted by this change

- [ ] Current checked-in implementation
- [ ] Target-state migration work
- [ ] Both

## Validation

- [ ] Not run (explain why)
- [ ] Ran the following commands:
  - ``

## Notes for reviewers

- Add anything reviewers should pay extra attention to.

## Checklist

- [ ] I kept documentation truthful about validated behavior versus target-state goals.
- [ ] I did not add new repo-level PowerShell orchestration unless this change is installer-time logic or a short-term compatibility shim.
- [ ] If I changed the Squid pin, I updated `config\squid-version.json`, `conan\squid-release.json`, and `conan\recipes\squid\all\conandata.yml` together.
- [ ] If I changed workflows, release assets, or package-manager behavior, I updated the related docs and automation together.
- [ ] I preserved `squid4win.msi` and `squid4win-portable.zip`, or I updated the downstream metadata flow in the same change.
- [ ] I did not commit secrets, certificates, tokens, or machine-specific paths.
- [ ] I did not edit vendored `.agents\skills\` content unintentionally.
