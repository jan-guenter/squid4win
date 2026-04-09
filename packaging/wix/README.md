# WiX packaging

## Current committed installer contract

This directory contains the committed WiX v4 installer project for Squid4Win:

- `Squid4Win.Installer.wixproj` harvests separate staged payload roots for the
  core install and the optional tray feature
- `Product.wxs` defines the MSI package, feature tree, installer UI, shortcuts,
  and service custom actions

These files document the current committed installer payload contract. They do
not, on their own, prove clean-host or end-to-end target-state validation.

The current installer contract intentionally stays close to Squid's native
Windows layout:

- the payload is staged under `artifacts\install-root`
- the WiX project harvests repo-shaped installer roots under
  `artifacts\install-root-core` and `artifacts\install-root-tray` so the tray
  binaries can stay optional in MSI feature selection while the portable bundle
  continues to use the full staged payload
- the MSI installs to `C:\Squid4Win` by default to avoid path-with-spaces issues
- the installer uses a built-in WiX UI with install-directory and feature
  selection support, including optional tray installation and optional
  tray-at-logon registration
- the MSI invokes Squid's built-in `-i` and `-r` service verbs through the
  installed helper scripts under `installer\`, with `installer\svc.ps1` as the
  entry point
- the staged payload intentionally omits a machine-specific `etc\squid.conf`
  and the first install materializes it from
  `packaging\defaults\squid.conf.template` if the file is not already present
- the staged payload converts the upstream Squid man-page sources into
  `docs\html\` with `docs\html\index.html` as the Windows-friendly entry point,
  and prunes the raw `share\man` tree from the installed root
- the installer payload omits non-runtime extras such as tray `.pdb` files and
  stock Squid sample/default config variants that are not needed in the
  installed root
- `uv run squid4win-automation bundle-package --service-name ...`
  is the supported repo-level entry point for building the MSI from the staged
  payload, while
  `uv run squid4win-automation service-runner-validation`
  is the supported isolated Windows-runner path for installing temporary MSI
  instances with unique service names; Squid's upstream `-n` contract requires
  that override to stay alphanumeric and no longer than 32 characters
- the installed service helper validates generated configs with
  `squid.exe -k parse`, initializes cache directories with `squid.exe -z`, and
  then registers the named service
- `squid.exe -i -f <config>` follows Squid's native Windows service model: the
  service keeps Squid-controlled runtime startup parameters, while the selected
  config association is persisted separately for the named service; the helper
  explicitly verifies the registry-backed `ConfigFile` and `CommandLine` values
  after registration so runtime startup and spawned Squid processes do not fall
  back to compiled defaults. Because upstream service startup splits the stored
  `CommandLine` on whitespace without quote support, the install root used for
  service registration must remain space-free
- the WiX service custom actions pass the install root to `installer\svc.ps1`
  as `"[INSTALLFOLDER]."` rather than raw `"[INSTALLFOLDER]"` so the trailing
  directory separator does not escape the closing quote in the underlying
  `WixQuietExec` command line
- the repository root `NuGet.config` clears inherited user-level sources so WiX
  package restore resolves from the committed `nuget.org` source set rather
  than machine-global feed state
- the WiX harvest step suppresses expected Heat warning `HEAT5151` for native
  `.exe` and `.dll` files that are not managed assemblies
- the staged payload already includes the harvested third-party notice bundle
  under `licenses\third-party\` before WiX harvests the file tree

These Python entry points execute by default. Use `--dry-run` when you need to
preview the staging or validation plan without invoking WiX or installer
lifecycle actions.

## Validation still pending

- cited successful execution of the dedicated runner lifecycle workflow,
  clean-host confirmation that installer behavior matches it, plus upgrade
  coverage
- end-to-end installed service plus tray-app interaction on a clean host for
  the in-progress target-state architecture
- cited local proof that the current feature-tree UI, install-directory
  selection, tray feature toggles, and unattended feature properties behave as
  authored
