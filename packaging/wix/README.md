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
- the first install materializes `etc\squid.conf` from
  `packaging\defaults\squid.conf.template` if the file is not already present

What is still pending:

- validating the MSI against a fully successful native Squid stage
- expanding runtime license harvesting once the final DLL set is stable
- richer UI and customization options if they are needed later
