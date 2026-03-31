[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json')
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

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedMetadataPath = Get-AbsolutePath -Path $MetadataPath -BasePath $resolvedRepositoryRoot
$metadata = Get-Content -Raw -LiteralPath $resolvedMetadataPath | ConvertFrom-Json
$numericParts = [System.Collections.Generic.List[int]]::new()

foreach ($part in ([string]$metadata.version -split '[^0-9]+')) {
    if ([string]::IsNullOrWhiteSpace($part)) {
        continue
    }

    $numericParts.Add([int]$part)
}

if ($numericParts.Count -eq 0) {
    throw "Unable to derive an installer version from '$($metadata.version)'."
}

while ($numericParts.Count -lt 3) {
    $numericParts.Add(0)
}

$revision = 0
if ($env:GITHUB_RUN_NUMBER -and [int]::TryParse($env:GITHUB_RUN_NUMBER, [ref]$revision)) {
    $revision = [Math]::Min($revision, 65535)
}

while ($numericParts.Count -lt 4) {
    $numericParts.Add(0)
}

$numericParts[3] = $revision
($numericParts[0..3] -join '.')
