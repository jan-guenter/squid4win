[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build',
    [string]$BuildProfilePath = (Join-Path $PSScriptRoot '..\config\build-profile.json'),
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json'),
    [string]$BinaryPath
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
$resolvedBuildRoot = Get-AbsolutePath -Path $BuildRoot -BasePath $resolvedRepositoryRoot
$resolvedBuildProfilePath = Get-AbsolutePath -Path $BuildProfilePath -BasePath $resolvedRepositoryRoot
$resolvedMetadataPath = Get-AbsolutePath -Path $MetadataPath -BasePath $resolvedRepositoryRoot
$layout = & (Join-Path $PSScriptRoot 'Resolve-SquidBuildLayout.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $resolvedRepositoryRoot `
    -BuildRoot $resolvedBuildRoot `
    -BuildProfilePath $resolvedBuildProfilePath
$metadata = Get-Content -Raw -LiteralPath $resolvedMetadataPath | ConvertFrom-Json
$installRoot = [string]$layout.StageRoot

if ($BinaryPath) {
    $resolvedBinaryPath = Get-AbsolutePath -Path $BinaryPath -BasePath $resolvedRepositoryRoot
} else {
    $candidatePaths = @(
        (Join-Path $installRoot 'sbin\squid.exe'),
        (Join-Path $installRoot 'bin\squid.exe')
    )

    $resolvedBinaryPath = $candidatePaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

    if (-not $resolvedBinaryPath) {
        $discoveredBinary = Get-ChildItem -Path $installRoot -Recurse -Filter 'squid.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $discoveredBinary) {
            $resolvedBinaryPath = $discoveredBinary.FullName
        }
    }
}

if (-not $resolvedBinaryPath -or -not (Test-Path -LiteralPath $resolvedBinaryPath)) {
    throw "Unable to find squid.exe under $installRoot."
}

$versionOutput = (& $resolvedBinaryPath -v 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "squid.exe -v failed with exit code $LASTEXITCODE."
}

if ($versionOutput -notmatch [Regex]::Escape([string]$metadata.version)) {
    throw "Expected squid version $($metadata.version) but version output was: $versionOutput"
}

$summaryLines = @(
    '## Smoke test',
    '',
    ('- Binary: `{0}`' -f $resolvedBinaryPath),
    ('- Version: `{0}`' -f $metadata.version)
)

if ($env:GITHUB_STEP_SUMMARY) {
    $summaryLines -join [Environment]::NewLine | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
}

Write-Host "Smoke tests passed for $resolvedBinaryPath"
