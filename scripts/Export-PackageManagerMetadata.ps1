[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$Tag = ("v{0}" -f $Version),
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository = 'jan-guenter/squid4win',
    [string]$MsiPath = (Join-Path $PSScriptRoot '..\artifacts\squid4win.msi'),
    [string]$PortableZipPath = (Join-Path $PSScriptRoot '..\artifacts\squid4win-portable.zip'),
    [string]$OutputRoot = (Join-Path $PSScriptRoot '..\artifacts\package-managers'),
    [string]$PackageIdentifier = 'JanGuenter.Squid4Win',
    [string]$PackageName = 'Squid4Win',
    [string]$Publisher = 'Jan Guenter',
    [string]$PublisherUrl = 'https://github.com/jan-guenter',
    [string]$PackageUrl,
    [string]$MsiUrl,
    [string]$PortableZipUrl
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-AbsolutePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$BasePath
    )

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
}

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$resolvedMsiPath = Get-AbsolutePath -Path $MsiPath -BasePath $repositoryRoot
$resolvedPortableZipPath = Get-AbsolutePath -Path $PortableZipPath -BasePath $repositoryRoot
$resolvedOutputRoot = Get-AbsolutePath -Path $OutputRoot -BasePath $repositoryRoot

if (-not (Test-Path -LiteralPath $resolvedMsiPath)) {
    throw "The MSI artifact '$resolvedMsiPath' was not found."
}

if (-not (Test-Path -LiteralPath $resolvedPortableZipPath)) {
    throw "The portable zip artifact '$resolvedPortableZipPath' was not found."
}

if (-not $PackageUrl) {
    $PackageUrl = "https://github.com/$Repository"
}

if (-not $MsiUrl) {
    $MsiUrl = "$PackageUrl/releases/download/$Tag/squid4win.msi"
}

if (-not $PortableZipUrl) {
    $PortableZipUrl = "$PackageUrl/releases/download/$Tag/squid4win-portable.zip"
}

$licenseUrl = "$PackageUrl/blob/main/LICENSE"
$issuesUrl = "$PackageUrl/issues"
$releaseNotesUrl = "$PackageUrl/releases/tag/$Tag"
$manifestVersion = '1.9.0'
$msiSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedMsiPath).Hash.ToUpperInvariant()
$portableZipSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedPortableZipPath).Hash.ToUpperInvariant()

$wingetRoot = Join-Path $resolvedOutputRoot "winget\$Version"
$chocoRoot = Join-Path $resolvedOutputRoot 'chocolatey'
$chocoToolsRoot = Join-Path $chocoRoot 'tools'
$scoopRoot = Join-Path $resolvedOutputRoot 'scoop'
$scoopManifestPath = Join-Path $scoopRoot 'squid4win.json'

$null = New-Item -ItemType Directory -Path $wingetRoot, $chocoToolsRoot, $scoopRoot -Force

$wingetVersionPath = Join-Path $wingetRoot "$PackageIdentifier.yaml"
$wingetLocalePath = Join-Path $wingetRoot "$PackageIdentifier.locale.en-US.yaml"
$wingetInstallerPath = Join-Path $wingetRoot "$PackageIdentifier.installer.yaml"

$wingetVersionContent = @(
    "PackageIdentifier: $PackageIdentifier",
    "PackageVersion: $Version",
    'DefaultLocale: en-US',
    'ManifestType: version',
    "ManifestVersion: $manifestVersion"
) -join [Environment]::NewLine
Set-Content -LiteralPath $wingetVersionPath -Value ($wingetVersionContent + [Environment]::NewLine) -Encoding ascii

$wingetLocaleContent = @(
    "PackageIdentifier: $PackageIdentifier",
    "PackageVersion: $Version",
    'PackageLocale: en-US',
    "Publisher: $Publisher",
    "PublisherUrl: $PublisherUrl",
    "PublisherSupportUrl: $issuesUrl",
    "PackageName: $PackageName",
    "PackageUrl: $PackageUrl",
    'ShortDescription: Windows-first native Squid packaging with an MSI installer and tray application.',
    'License: MIT',
    "LicenseUrl: $licenseUrl",
    "ReleaseNotesUrl: $releaseNotesUrl",
    'ManifestType: defaultLocale',
    "ManifestVersion: $manifestVersion"
) -join [Environment]::NewLine
Set-Content -LiteralPath $wingetLocalePath -Value ($wingetLocaleContent + [Environment]::NewLine) -Encoding ascii

$wingetInstallerContent = @(
    "PackageIdentifier: $PackageIdentifier",
    "PackageVersion: $Version",
    'InstallerType: wix',
    'Scope: machine',
    'UpgradeBehavior: install',
    'InstallModes:',
    '  - interactive',
    '  - silent',
    '  - silentWithProgress',
    'Commands:',
    '  - squid',
    'Installers:',
    '  - Architecture: x64',
    '    InstallerLocale: en-US',
    "    InstallerUrl: $MsiUrl",
    "    InstallerSha256: $msiSha256",
    'ManifestType: installer',
    "ManifestVersion: $manifestVersion"
) -join [Environment]::NewLine
Set-Content -LiteralPath $wingetInstallerPath -Value ($wingetInstallerContent + [Environment]::NewLine) -Encoding ascii

$nuspecPath = Join-Path $chocoRoot 'squid4win.nuspec'
$nuspecContent = @"
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2015/06/nuspec.xsd">
  <metadata>
    <id>squid4win</id>
    <version>$Version</version>
    <title>$PackageName</title>
    <authors>$Publisher</authors>
    <owners>$Publisher</owners>
    <projectUrl>$PackageUrl</projectUrl>
    <licenseUrl>$licenseUrl</licenseUrl>
    <projectSourceUrl>$PackageUrl</projectSourceUrl>
    <docsUrl>$PackageUrl</docsUrl>
    <bugTrackerUrl>$issuesUrl</bugTrackerUrl>
    <requireLicenseAcceptance>false</requireLicenseAcceptance>
    <summary>Windows-first native Squid packaging.</summary>
    <description>Installs the Squid4Win MSI built from the upstream Squid release and companion tray application.</description>
    <tags>squid proxy windows msi tray</tags>
  </metadata>
</package>
"@
Set-Content -LiteralPath $nuspecPath -Value $nuspecContent -Encoding utf8

$chocoInstallPath = Join-Path $chocoToolsRoot 'chocolateyinstall.ps1'
$chocoInstallContent = @(
    '$ErrorActionPreference = ''Stop''',
    '',
    '$packageArgs = @{',
    "    packageName    = 'squid4win'",
    "    fileType       = 'msi'",
    "    softwareName   = 'Squid4Win*'",
    "    url64bit       = '$MsiUrl'",
    "    checksum64     = '$msiSha256'",
    "    checksumType64 = 'sha256'",
    "    silentArgs     = '/qn /norestart'",
    "    validExitCodes = @(0, 3010, 1641)",
    '}',
    '',
    'Install-ChocolateyPackage @packageArgs'
) -join [Environment]::NewLine
Set-Content -LiteralPath $chocoInstallPath -Value ($chocoInstallContent + [Environment]::NewLine) -Encoding ascii

$scoopManifestContent = @(
    '{',
    ('  "version": "{0}",' -f $Version),
    '  "description": "Windows-first native Squid packaging with a portable zip and tray application.",',
    ('  "homepage": "{0}",' -f $PackageUrl),
    '  "license": "MIT",',
    ('  "url": "{0}",' -f $PortableZipUrl),
    ('  "hash": "{0}",' -f $portableZipSha256),
    '  "bin": [',
    '    "Squid4Win.Tray.exe",',
    '    [',
    '      "sbin\\squid.exe",',
    '      "squid"',
    '    ]',
    '  ],',
    '  "shortcuts": [',
    '    [',
    '      "Squid4Win.Tray.exe",',
    '      "Squid4Win Tray"',
    '    ]',
    '  ],',
    '  "checkver": {',
    ('    "github": "{0}"' -f $PackageUrl),
    '  },',
    '  "autoupdate": {',
    ('    "url": "{0}"' -f "$PackageUrl/releases/download/v`$version/squid4win-portable.zip"),
    '  }',
    '}'
) -join [Environment]::NewLine
Set-Content -LiteralPath $scoopManifestPath -Value ($scoopManifestContent + [Environment]::NewLine) -Encoding ascii

[PSCustomObject]@{
    OutputRoot = $resolvedOutputRoot
    WingetRoot = $wingetRoot
    ChocolateyRoot = $chocoRoot
    ScoopManifestPath = $scoopManifestPath
    MsiSha256 = $msiSha256
    PortableZipSha256 = $portableZipSha256
    MsiUrl = $MsiUrl
    PortableZipUrl = $PortableZipUrl
}
