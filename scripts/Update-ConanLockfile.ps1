[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$HostProfilePath = (Join-Path $PSScriptRoot '..\conan\profiles\msys2-mingw-x64'),
    [string]$BuildProfile = 'default',
    [string]$LockfilePath,
    [switch]$WithTray,
    [switch]$WithRuntimeDlls,
    [switch]$WithPackagingSupport
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')
$repoRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$conanHome = & (Join-Path $PSScriptRoot 'Resolve-ConanHome.ps1') -RepositoryRoot $repoRoot -EnsureExists
$env:CONAN_HOME = $conanHome
$resolvedHostProfilePath = Get-AbsolutePath -Path $HostProfilePath -BasePath $repoRoot
$layout = & (Join-Path $PSScriptRoot 'Resolve-SquidBuildLayout.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $repoRoot
$conanCommand = Get-Command conan -ErrorAction SilentlyContinue
if ($null -eq $conanCommand) {
    throw 'Conan is required to refresh lockfiles. Install requirements-automation.txt or use scripts\Setup-Environment.ps1 first.'
}
if (-not (Test-Path -LiteralPath $resolvedHostProfilePath)) {
    throw "The Conan host profile '$resolvedHostProfilePath' was not found."
}
& $conanCommand.Source profile detect --force
if ($LASTEXITCODE -ne 0) {
    throw "conan profile detect failed with exit code $LASTEXITCODE."
}
& (Join-Path $PSScriptRoot 'Export-ConanWorkspaceRecipes.ps1') -RepositoryRoot $repoRoot | Out-Null
$resolvedLockfilePath = if ($LockfilePath) {
    Get-AbsolutePath -Path $LockfilePath -BasePath $repoRoot
} else {
    [string]$layout.RepoLockfilePath
}
$lockfileDirectory = Split-Path -Parent $resolvedLockfilePath
$conanOptionArguments = & (Join-Path $PSScriptRoot 'Get-ConanRecipeOptionArguments.ps1') `
    -RepositoryRoot $repoRoot `
    -WithTray:$WithTray `
    -WithRuntimeDlls:$WithRuntimeDlls `
    -WithPackagingSupport:$WithPackagingSupport
New-Item -ItemType Directory -Force -Path $lockfileDirectory | Out-Null
$conanArguments = @(
    'lock',
    'create',
    $repoRoot,
    '--profile:host', $resolvedHostProfilePath,
    '--profile:build', $BuildProfile,
    '--lockfile-out', $resolvedLockfilePath,
    '-s:h', "build_type=$Configuration",
    '-s:b', "build_type=$Configuration",
    '--build=missing'
) + $conanOptionArguments
& $conanCommand.Source @conanArguments
if ($LASTEXITCODE -ne 0) {
    throw "conan lock create failed with exit code $LASTEXITCODE."
}
Write-Host "Lockfile refreshed: $resolvedLockfilePath"
Write-Output $resolvedLockfilePath
