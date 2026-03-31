[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$BuildProfilePath = (Join-Path $PSScriptRoot '..\config\build-profile.json'),
    [string]$Msys2Root,
    [string]$EffectiveProfilePath,
    [string]$LockfilePath
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

$repoRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedBuildProfilePath = Get-AbsolutePath -Path $BuildProfilePath -BasePath $repoRoot
$buildProfile = & (Join-Path $PSScriptRoot 'Get-SquidBuildProfile.ps1') -ConfigPath $resolvedBuildProfilePath
$configurationLabel = $Configuration.ToLowerInvariant()
$toolchainState = & (Join-Path $PSScriptRoot 'Initialize-NativeToolchain.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $repoRoot `
    -BuildProfilePath $resolvedBuildProfilePath `
    -Msys2Root $Msys2Root `
    -EffectiveProfilePath $EffectiveProfilePath
$conanCommand = Get-Command conan -ErrorAction SilentlyContinue

if ($null -eq $conanCommand) {
    throw 'Conan is required to refresh lockfiles. Install Conan 2 or use the setup-conan action in CI.'
}

$resolvedLockfilePath = if ($LockfilePath) {
    Get-AbsolutePath -Path $LockfilePath -BasePath $repoRoot
} else {
    Join-Path $repoRoot "conan\lockfiles\$([string]$buildProfile.conanProfileName)-$configurationLabel.lock"
}
$lockfileDirectory = Split-Path -Parent $resolvedLockfilePath

New-Item -ItemType Directory -Force -Path $lockfileDirectory | Out-Null

$conanArguments = @(
    'lock',
    'create',
    $repoRoot,
    '--profile:host', $toolchainState.EffectiveProfilePath,
    '--profile:build', $toolchainState.EffectiveProfilePath,
    '--lockfile-out', $resolvedLockfilePath,
    '-s:h', "build_type=$Configuration",
    '-s:b', "build_type=$Configuration",
    '--build=missing'
)

& $conanCommand.Source @conanArguments
if ($LASTEXITCODE -ne 0) {
    throw "conan lock create failed with exit code $LASTEXITCODE."
}

Write-Host "Lockfile refreshed: $resolvedLockfilePath"

Write-Output $resolvedLockfilePath

