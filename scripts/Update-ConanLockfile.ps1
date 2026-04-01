[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$BuildRoot = 'build',
    [string]$HostProfilePath = (Join-Path $PSScriptRoot '..\conan\profiles\msys2-mingw-x64'),
    [string]$BuildProfile = 'default',
    [string]$LockfilePath,
    [switch]$WithTray,
    [switch]$WithRuntimeDlls,
    [switch]$WithPackagingSupport,
    [switch]$UseTrayEditable
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$state = & (Join-Path $PSScriptRoot 'Invoke-ConanRootRecipe.ps1') `
    -Operation LockCreate `
    -Configuration $Configuration `
    -RepositoryRoot $RepositoryRoot `
    -BuildRoot $BuildRoot `
    -HostProfilePath $HostProfilePath `
    -BuildProfile $BuildProfile `
    -LockfilePath $LockfilePath `
    -WithTray:$WithTray `
    -WithRuntimeDlls:$WithRuntimeDlls `
    -WithPackagingSupport:$WithPackagingSupport `
    -UseTrayEditable:$UseTrayEditable
Write-Output $state.LockfilePath
