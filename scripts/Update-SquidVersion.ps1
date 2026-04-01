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

if ($PublishedAt) {
    $publishedAtTimestamp = [System.DateTimeOffset]::MinValue
    $dateParseStyles = [System.Globalization.DateTimeStyles]::AllowWhiteSpaces -bor [System.Globalization.DateTimeStyles]::AssumeUniversal
    $publishedAtText = [string]$PublishedAt
    if (
        [System.DateTimeOffset]::TryParse($publishedAtText, [System.Globalization.CultureInfo]::InvariantCulture, $dateParseStyles, [ref]$publishedAtTimestamp) -or
        [System.DateTimeOffset]::TryParse($publishedAtText, [System.Globalization.CultureInfo]::CurrentCulture, $dateParseStyles, [ref]$publishedAtTimestamp)
    ) {
        $PublishedAt = $publishedAtTimestamp.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ', [System.Globalization.CultureInfo]::InvariantCulture)
    }
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

if (-not (Test-Path -LiteralPath $resolvedConanDataPath)) {
    throw "Expected existing conandata.yml at $resolvedConanDataPath so the Squid version update can preserve the current build metadata."
}

$existingConanDataContent = Get-Content -Raw -LiteralPath $resolvedConanDataPath
$buildAndPatchSectionMatch = [regex]::Match($existingConanDataContent, '(?ms)^build:\r?\n.*$')
if (-not $buildAndPatchSectionMatch.Success) {
    throw "Unable to locate the top-level build section in $resolvedConanDataPath."
}

$newline = if ($existingConanDataContent.Contains("`r`n")) { "`r`n" } else { "`n" }
$newPatchSectionHeader = "patches:$newline  ""$Version"":"
if ($buildAndPatchSectionMatch.Value -notmatch 'patches:\r?\n\s+"[^"]+":') {
    throw "Unable to locate the versioned patches section in $resolvedConanDataPath."
}

$preservedConanDataTail = $buildAndPatchSectionMatch.Value -replace 'patches:\r?\n\s+"[^"]+":', $newPatchSectionHeader
$newConanDataContent = (
    @(
        'sources:'
        "  ""$Version"":"
        "    url: ""$SourceArchive"""
        "    sha256: ""$SourceArchiveSha256"""
        '    strip_root: true'
        ''
    ) -join $newline
) + $newline + $preservedConanDataTail

if (-not $newConanDataContent.EndsWith($newline)) {
    $newConanDataContent += $newline
}

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

$conanDataChanged = $existingConanDataContent.Trim() -ne $newConanDataContent.Trim()

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
