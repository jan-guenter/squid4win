[CmdletBinding()]
param(
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json'),
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\squid-version.json'),
    [string]$ConanDataPath = (Join-Path $PSScriptRoot '..\conandata.yml'),
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository = 'squid-cache/squid',
    [Nullable[int]]$MajorVersion,
    [string]$Version,
    [string]$Tag,
    [string]$PublishedAt,
    [string]$SourceArchive,
    [string]$SourceSignature,
    [string]$SourceArchiveSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedMetadataPath = [System.IO.Path]::GetFullPath($MetadataPath)
$resolvedConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
$resolvedConanDataPath = [System.IO.Path]::GetFullPath($ConanDataPath)
$metadataDirectory = Split-Path -Parent $resolvedMetadataPath
$configDirectory = Split-Path -Parent $resolvedConfigPath
$conanDataDirectory = Split-Path -Parent $resolvedConanDataPath

if (-not (Test-Path -LiteralPath $metadataDirectory)) {
    $null = New-Item -ItemType Directory -Path $metadataDirectory -Force
}

if (-not (Test-Path -LiteralPath $configDirectory)) {
    $null = New-Item -ItemType Directory -Path $configDirectory -Force
}

if (-not (Test-Path -LiteralPath $conanDataDirectory)) {
    $null = New-Item -ItemType Directory -Path $conanDataDirectory -Force
}

if (-not $Version) {
    $releaseParameters = @{
        Repository = $Repository
    }

    if ($null -ne $MajorVersion) {
        $releaseParameters.MajorVersion = [int]$MajorVersion
    }

    $release = & (Join-Path $PSScriptRoot 'Get-SquidRelease.ps1') @releaseParameters
    $Version = $release.Version
    $Tag = $release.Tag
    $PublishedAt = $release.PublishedAt
    $SourceArchive = $release.SourceArchive
    $SourceSignature = $release.SourceSignature
    $SourceArchiveSha256 = $release.SourceArchiveSha256
}

$updatedMetadata = [ordered]@{
    repository = $Repository
    version = $Version
    tag = $Tag
    published_at = $PublishedAt
    assets = [ordered]@{
        source_archive = $SourceArchive
        source_signature = $SourceSignature
        source_archive_sha256 = $SourceArchiveSha256
    }
}

$configRepositoryParts = $Repository.Split('/', 2)
$updatedConfig = [ordered]@{
    owner = $configRepositoryParts[0]
    repo = $configRepositoryParts[1]
    track = 'stable'
    version = $Version
    tag = $Tag
    sourceArchiveUrl = $SourceArchive
}

$newConanDataContent = @"
sources:
  "$Version":
    url: "$SourceArchive"
    sha256: "$SourceArchiveSha256"
    strip_root: true

patches:
  "$Version":
    - patch_file: "conan/patches/squid/0001-mingw-compat-core-shims.patch"
      patch_description: "Provide foundational MinGW POSIX compatibility shims."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0002-mingw-build-system-flags.patch"
      patch_description: "Adjust Squid build-system flags and MinGW link libraries."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0003-mingw-disk-io-compat.patch"
      patch_description: "Teach Squid DiskIO backends to build and run under MinGW."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0004-mingw-socket-and-ipc-compat.patch"
      patch_description: "Add MinGW-safe Winsock and IPC wrappers."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0005-mingw-win32-runtime-support.patch"
      patch_description: "Expose the Win32 runtime helpers needed by the MinGW port."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0006-mingw-cert-generator-compat.patch"
      patch_description: "Fix MinGW certificate helper and certificate DB support."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0007-mingw-main-and-service-integration.patch"
      patch_description: "Wire MinGW into Squid runtime startup and Windows service paths."
      base_path: "."
      strip: 2
"@ + [Environment]::NewLine

$newMetadataContent = ($updatedMetadata | ConvertTo-Json -Depth 5) + [Environment]::NewLine
$newConfigContent = ($updatedConfig | ConvertTo-Json -Depth 5) + [Environment]::NewLine
$metadataChanged = $true
$configChanged = $true
$conanDataChanged = $true

if (Test-Path -LiteralPath $resolvedMetadataPath) {
    $existingContent = Get-Content -Raw -LiteralPath $resolvedMetadataPath
    $metadataChanged = $existingContent.Trim() -ne $newMetadataContent.Trim()
}

if (Test-Path -LiteralPath $resolvedConfigPath) {
    $existingConfigContent = Get-Content -Raw -LiteralPath $resolvedConfigPath
    $configChanged = $existingConfigContent.Trim() -ne $newConfigContent.Trim()
}

if (Test-Path -LiteralPath $resolvedConanDataPath) {
    $existingConanDataContent = Get-Content -Raw -LiteralPath $resolvedConanDataPath
    $conanDataChanged = $existingConanDataContent.Trim() -ne $newConanDataContent.Trim()
}

if ($metadataChanged) {
    Set-Content -LiteralPath $resolvedMetadataPath -Value $newMetadataContent -Encoding utf8
}

if ($configChanged) {
    Set-Content -LiteralPath $resolvedConfigPath -Value $newConfigContent -Encoding utf8
}

if ($conanDataChanged) {
    Set-Content -LiteralPath $resolvedConanDataPath -Value $newConanDataContent -Encoding utf8
}

$hasChanged = $metadataChanged -or $configChanged -or $conanDataChanged

if ($env:GITHUB_OUTPUT) {
    "changed=$($hasChanged.ToString().ToLowerInvariant())" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
    "version=$Version" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
    "tag=$Tag" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
}

[PSCustomObject]@{
    Changed = $hasChanged
    Repository = $Repository
    Version = $Version
    Tag = $Tag
    MetadataPath = $resolvedMetadataPath
    ConfigPath = $resolvedConfigPath
    ConanDataPath = $resolvedConanDataPath
}
