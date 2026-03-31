[CmdletBinding()]
param(
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json'),
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\squid-version.json'),
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
$metadataDirectory = Split-Path -Parent $resolvedMetadataPath
$configDirectory = Split-Path -Parent $resolvedConfigPath

if (-not (Test-Path -LiteralPath $metadataDirectory)) {
    $null = New-Item -ItemType Directory -Path $metadataDirectory -Force
}

if (-not (Test-Path -LiteralPath $configDirectory)) {
    $null = New-Item -ItemType Directory -Path $configDirectory -Force
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

$newMetadataContent = ($updatedMetadata | ConvertTo-Json -Depth 5) + [Environment]::NewLine
$newConfigContent = ($updatedConfig | ConvertTo-Json -Depth 5) + [Environment]::NewLine
$metadataChanged = $true
$configChanged = $true

if (Test-Path -LiteralPath $resolvedMetadataPath) {
    $existingContent = Get-Content -Raw -LiteralPath $resolvedMetadataPath
    $metadataChanged = $existingContent.Trim() -ne $newMetadataContent.Trim()
}

if (Test-Path -LiteralPath $resolvedConfigPath) {
    $existingConfigContent = Get-Content -Raw -LiteralPath $resolvedConfigPath
    $configChanged = $existingConfigContent.Trim() -ne $newConfigContent.Trim()
}

if ($metadataChanged) {
    Set-Content -LiteralPath $resolvedMetadataPath -Value $newMetadataContent -Encoding utf8
}

if ($configChanged) {
    Set-Content -LiteralPath $resolvedConfigPath -Value $newConfigContent -Encoding utf8
}

$hasChanged = $metadataChanged -or $configChanged

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
}
