---
name: wix-msi-installer
description: Author WiX v4 MSI installers for Windows desktop applications with service registration, tray autostart, UI set selection, and PowerShell custom actions.
skill_api_version: 1
---

# WiX v4 MSI installer authoring

Use this skill when writing, reviewing, or extending the WiX v4 MSI installer
for Squid4Win or any similar Windows application that ships a native service
alongside a tray-app and requires careful install-root and registry hygiene.

## Use this skill for

- selecting and wiring up a built-in WiX UI set (`WixUI_Advanced`,
  `WixUI_Mondo`, `WixUI_FeatureTree`, `WixUI_InstallDir`)
- authoring MSI features and driving selective installs with `ADDLOCAL`
- registering a Windows service through the application's own service verbs
  rather than a generic WiX `ServiceInstall` element
- adding a per-machine tray-app autostart `Run` registry value
- writing `WixQuietExec` custom actions backed by `SetProperty` + `CustomAction`
  pairs
- debugging the trailing-backslash quoting hazard in MSI directory properties
- keeping the install root space-free for Squid's service registration

## Do not use this skill for

- WiX v3 (this skill targets WiX v4 / WixToolset.Sdk 4.x)
- MSI authoring that routes Squid service lifecycle back through Conan packaging
- installer work that is better handled by the Python automation entry points
  (`uv run squid4win-automation bundle-package`, `service-runner-validation`)
- shipping a second service wrapper instead of using Squid's built-in verbs

## WiX v4 project skeleton

```xml
<Project Sdk="WixToolset.Sdk/4.0.5">
  <PropertyGroup>
    <OutputType>Package</OutputType>
    <InstallerPlatform>x64</InstallerPlatform>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="WixToolset.UI.wixext" Version="4.0.5" />
    <PackageReference Include="WixToolset.Util.wixext" Version="4.0.5" />
  </ItemGroup>
</Project>
```

## Built-in UI sets

| UI set | When to use |
|---|---|
| `WixUI_InstallDir` | Single install directory, no feature tree. Simplest. |
| `WixUI_FeatureTree` | Expose an optional-feature checkbox tree. |
| `WixUI_Mondo` | Full wizard: license, features, directory, ready. |
| `WixUI_Advanced` | Typical or custom install path with feature choice. |

Wire in a UI set with one element; point `WIXUI_INSTALLDIR` at your directory
property:

```xml
<UIRef Id="WixUI_InstallDir" />
<Property Id="WIXUI_INSTALLDIR" Value="INSTALLFOLDER" />
```

A license RTF is required when using any `WixUI_*` that shows the license page.
Suppress it with:

```xml
<WixVariable Id="WixUILicenseRtf" Value="path\to\license.rtf" />
```

## Feature selection and ADDLOCAL

Declare features as `<Feature>` elements. Nested features inherit the parent
level unless `Level` is overridden. MSI installs only features whose level is
at or below the `INSTALLLEVEL` property (default 1).

```xml
<Feature Id="MainFeature" Title="Core components" Level="1">
  <ComponentGroupRef Id="CorePayload" />
  <Feature Id="OptionalDocs" Title="Documentation" Level="2">
    <ComponentGroupRef Id="DocsPayload" />
  </Feature>
</Feature>
```

Command-line selective install:

```
msiexec /i product.msi ADDLOCAL=MainFeature
msiexec /i product.msi ADDLOCAL=MainFeature,OptionalDocs
```

`ADDLOCAL=ALL` installs every feature regardless of level. Omitting
`ADDLOCAL` respects the `Level` values in the authored XML.

## Squid service registration

Squid ships its own Windows service support. Use its native verbs instead of
the WiX `ServiceInstall` element.

### Service verb sequence on install

```
squid.exe -k parse -f <config>       # validate config; fail fast before touching the registry
squid.exe -z       -f <config>       # initialize cache directories
squid.exe -i -n <name> -f <config>   # register the Windows service
```

`-i -f <config>` follows Squid's native service model: the runtime `ConfigFile`
and `CommandLine` registry values are persisted by the install helper under
`HKLM\SOFTWARE\squid-cache.org\Squid Web Proxy\<name>`. Verify both values
after registration — Squid does not always remove them on `-r`, so a stale
entry can silently override the new registration.

### Removing the service

```
squid.exe -r -n <name>   # remove the service registration
```

Stop the service before calling `-r` so the SCM releases the binary handle.
Remove the `HKLM\SOFTWARE\squid-cache.org\Squid Web Proxy\<name>` registry
subtree explicitly after `-r` because Squid leaves it behind.

### No-spaces install root

Squid's upstream service startup splits the stored `CommandLine` registry value
on whitespace **without quote support**. A config path containing a space will
be silently truncated, causing Squid to fall back to its compiled default.

- Default the install directory to a space-free root such as `C:\Squid4Win`.
- Validate the resolved config path for whitespace before calling `-i`.
- If the path contains whitespace, abort with a clear error rather than
  registering a broken service.

## Tray autostart via per-machine Run key

MSI installs as a per-machine package (`Scope="perMachine"`). The per-machine
autostart registry hive is `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`.

```xml
<Component Id="TrayAutostart" Guid="*">
  <RegistryValue Root="HKLM"
                 Key="SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
                 Name="Squid4Win"
                 Type="string"
                 Value="[INSTALLFOLDER]Squid4Win.Tray.exe"
                 KeyPath="yes" />
</Component>
```

> **Note:** Per-user autostart lives under `HKCU\...\Run`. Because this MSI
> installs per-machine, use `HKLM` so the tray starts for all users on the
> machine. Do not use `HKCU` with a per-machine package — the component will
> be keyed against whichever user ran the installer.

## WixQuietExec custom action pattern

Use `WixQuietExec` to run a command without spawning a visible window. Every
`WixQuietExec` custom action requires a matching `SetProperty` action to build
the command string, and both must reference the same `Id`.

```xml
<!-- 1. Build the command string -->
<SetProperty Id="InstallSquidService"
             Sequence="execute"
             After="CostFinalize"
             Value="&quot;[System64Folder]WindowsPowerShell\v1.0\powershell.exe&quot; -NoProfile -NonInteractive -ExecutionPolicy Bypass -File &quot;[INSTALLFOLDER]installer\svc.ps1&quot; Install &quot;[INSTALLFOLDER].&quot; &quot;[ServiceName]&quot;"
             Condition="NOT Installed" />

<!-- 2. Execute it -->
<CustomAction Id="InstallSquidService"
              Execute="deferred"
              Impersonate="no"
              Return="check"
              DllEntry="WixQuietExec"
              BinaryRef="Wix4UtilCA_$(sys.BUILDARCHSHORT)" />

<!-- 3. Schedule it -->
<InstallExecuteSequence>
  <Custom Action="InstallSquidService"
          After="InstallFiles"
          Condition="NOT Installed" />
</InstallExecuteSequence>
```

### Trailing-backslash quoting hazard

MSI directory properties (`[INSTALLFOLDER]`, `[System64Folder]`, …) always
include a trailing backslash. When the property appears as the last element
inside a double-quoted command-line argument, that trailing backslash escapes
the closing quote:

```
"C:\Squid4Win\"  →  C:\Squid4Win"   ← broken, quote is consumed
```

**Fix:** append `.` to the directory property so the trailing backslash
becomes a path separator before a literal dot:

```xml
Value="... &quot;[INSTALLFOLDER].&quot; ..."
```

The PowerShell helper then normalizes the path with
`[System.IO.Path]::GetFullPath($path).TrimEnd('\')` to strip the dot.

## PowerShell helper scope

Keep PowerShell only for work that Squid's native service verbs do not cover:

- materializing `squid.conf` from a template (`__SQUID4WIN_INSTALL_ROOT__`
  substitution) when `etc\squid.conf` is absent on first install
- validating that the registry-backed `ConfigFile` and `CommandLine` values
  match the registered config path after `squid.exe -i`
- stopping a running service before removal or reinstall
- cleaning up the `HKLM\SOFTWARE\squid-cache.org\…\<name>` registry subtree
  after `squid.exe -r`

Do not use PowerShell for Squid service registration itself — let
`squid.exe -i / -r` own that lifecycle. Do not introduce new repo-level
PowerShell orchestration; put new contributor automation in the Python 3.14
`uv` package instead.

## Review checklist

Before merging a WiX installer change, confirm:

- Install root defaults to a space-free path; whitespace validation exists in
  the service helper before calling `squid.exe -i`.
- `SetProperty` and `CustomAction` share the same `Id`; both exist.
- Directory properties inside quoted arguments use the `[DIR].` trailing-dot
  pattern to avoid the backslash-quote escape.
- The install sequence is: `-k parse` → `-z` → `-i`; the uninstall sequence
  stops the service, calls `-r`, then removes the registry subtree.
- Registry `ConfigFile` and `CommandLine` values are verified after registration
  and cleaned up after removal.
- Tray autostart uses `HKLM\...\Run` (not `HKCU`) for a per-machine package.
- No feature-level or `ADDLOCAL` change bypasses the service registration custom
  action.

## Sources

- WiX Toolset v4:
  - [WiX v4 documentation](https://wixtoolset.org/docs/intro/)
  - [Built-in UI dialog sets](https://wixtoolset.org/docs/reference/wininstaller/wixui-dialog-library/)
  - [WixUtilExtension / WixQuietExec](https://wixtoolset.org/docs/reference/wininstaller/wixutilextension/)
- Windows Installer:
  - [ADDLOCAL property](https://learn.microsoft.com/en-us/windows/win32/msi/addlocal)
  - [Run and RunOnce registry keys](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys)
- Squid:
  - [Squid Windows service support (`-i`, `-r`)](https://wiki.squid-cache.org/SquidFaq/InstallingSquid#windows)
- This repo:
  - `packaging\wix\Product.wxs` — committed MSI package definition
  - `scripts\installer\Manage-SquidService.ps1` — installed service helper
  - `packaging\wix\README.md` — current installer contract and pending validation
