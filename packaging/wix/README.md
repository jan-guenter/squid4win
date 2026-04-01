# WiX packaging

This directory now contains the committed WiX v4 installer project for
Squid4Win:

- `Squid4Win.Installer.wixproj` harvests the staged install payload
- `Product.wxs` defines the MSI package, shortcuts, and service custom actions

The current installer contract intentionally stays close to Squid's native
Windows layout:

- the payload is staged under `artifacts\install-root`
- the MSI installs to `C:\Squid4Win` by default to avoid path-with-spaces issues
- the MSI invokes Squid's built-in `-i` and `-r` service verbs through the
  installed helper script `installer\svc.ps1`
- the staged payload intentionally omits a machine-specific `etc\squid.conf`
  and the first install materializes it from
  `packaging\defaults\squid.conf.template` if the file is not already present
- `scripts\Build-Installer.ps1 -ServiceName ...` can override the default
  service name so `.github\workflows\service-runner-validation.yml` can install
  isolated temporary instances on Windows runners; Squid's upstream `-n`
  contract requires that override to stay alphanumeric and no longer than 32
  characters
- the staged payload already includes the harvested third-party notice bundle
  under `licenses\third-party\` before WiX harvests the file tree

What is still pending:

- cited successful execution of the dedicated runner lifecycle workflow,
  clean-host confirmation that installer behavior matches it, plus upgrade
  coverage
- end-to-end installed service plus tray-app interaction on a clean host
- richer UI and customization options if they are needed later
