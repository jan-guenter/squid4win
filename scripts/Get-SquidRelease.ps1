[CmdletBinding()]
param(
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository = 'squid-cache/squid',
    [Nullable[int]]$MajorVersion,
    [switch]$IncludePrerelease,
    [switch]$RawResponse
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$headers = @{
    Accept = 'application/vnd.github+json'
    'User-Agent' = 'squid4win-automation'
}

if ($env:GITHUB_TOKEN) {
    $headers.Authorization = "Bearer $($env:GITHUB_TOKEN)"
}

$releases = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases?per_page=20" -Headers $headers -Method Get
$selectedRelease = $null

foreach ($release in $releases) {
    if ($release.draft) {
        continue
    }

    if (-not $IncludePrerelease -and $release.prerelease) {
        continue
    }

    $version = ($release.tag_name -replace '^SQUID_', '') -replace '_', '.'

    if ($null -ne $MajorVersion) {
        $requestedMajorVersion = [int]$MajorVersion
        $releaseMajorVersion = [int]($version.Split('.')[0])
        if ($releaseMajorVersion -ne $requestedMajorVersion) {
            continue
        }
    }

    $selectedRelease = $release
    break
}

if ($null -eq $selectedRelease) {
    throw "No matching release was found for $Repository."
}

$version = ($selectedRelease.tag_name -replace '^SQUID_', '') -replace '_', '.'
$sourceArchive = $selectedRelease.assets | Where-Object { $_.name -eq "squid-$version.tar.xz" } | Select-Object -First 1

if ($null -eq $sourceArchive) {
    throw "Release $($selectedRelease.tag_name) does not contain squid-$version.tar.xz."
}

$sourceSignature = $selectedRelease.assets | Where-Object { $_.name -eq "squid-$version.tar.xz.asc" } | Select-Object -First 1
$sourceArchiveSha256 = $null

if ($sourceArchive.digest -match '^sha256:(?<hash>[0-9a-fA-F]{64})$') {
    $sourceArchiveSha256 = $Matches.hash.ToLowerInvariant()
}

$result = [PSCustomObject]@{
    Repository          = $Repository
    Version             = $version
    Tag                 = $selectedRelease.tag_name
    PublishedAt         = [string]$selectedRelease.published_at
    ReleaseName         = [string]$selectedRelease.name
    SourceArchive       = [string]$sourceArchive.browser_download_url
    SourceSignature     = [string]$sourceSignature.browser_download_url
    SourceArchiveSha256 = $sourceArchiveSha256
    HtmlUrl             = [string]$selectedRelease.html_url
}

if ($RawResponse) {
    $selectedRelease
    return
}

$result
