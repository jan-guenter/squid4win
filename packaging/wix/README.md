# WiX packaging

## Current committed installer contract

This directory contains the committed WiX v4 installer project for Squid4Win:

- `Squid4Win.Installer.wixproj` harvests the staged install payload
- `Product.wxs` defines the MSI package, shortcuts, and service custom actions

These files document the current committed installer payload contract. They do
not, on their own, prove clean-host or end-to-end target-state validation.

The current installer contract intentionally stays close to Squid's native
Windows layout:

- the payload is staged under `artifacts\install-root`
- the MSI installs to `C:\Squid4Win` by default to avoid path-with-spaces issues
- the MSI invokes Squid's built-in `-i` and `-r` service verbs through the
  installed helper scripts under `installer\`, with `installer\svc.ps1` as the
  entry point
- the staged payload intentionally omits a machine-specific `etc\squid.conf`
  and the first install materializes it from
  `packaging\defaults\squid.conf.template` if the file is not already present
- `uv run squid4win-automation bundle-package --service-name ... --execute`
  is the supported repo-level entry point for building the MSI from the staged
  payload, while
  `uv run squid4win-automation service-runner-validation --execute`
  is the supported isolated Windows-runner path for installing temporary MSI
  instances with unique service names; Squid's upstream `-n` contract requires
  that override to stay alphanumeric and no longer than 32 characters
- the installed service helper validates generated configs with
  `squid.exe -k parse`, initializes cache directories with `squid.exe -z`, and
  then registers the named service
- `squid.exe -i -f <config>` follows Squid's native Windows service model: the
  service keeps Squid-controlled runtime startup parameters, while the selected
  config association is persisted separately for the named service; the helper
  explicitly verifies that registry-backed `ConfigFile` value after
  registration so runtime startup does not fall back to compiled defaults
- the WiX service custom actions pass the install root to `installer\svc.ps1`
  as `"[INSTALLFOLDER]."` rather than raw `"[INSTALLFOLDER]"` so the trailing
  directory separator does not escape the closing quote in the underlying
  `WixQuietExec` command line
- the staged payload already includes the harvested third-party notice bundle
  under `licenses\third-party\` before WiX harvests the file tree

## Validation still pending

- cited successful execution of the dedicated runner lifecycle workflow,
  clean-host confirmation that installer behavior matches it, plus upgrade
  coverage
- end-to-end installed service plus tray-app interaction on a clean host for
  the in-progress target-state architecture
- richer UI and customization options if they are needed later
