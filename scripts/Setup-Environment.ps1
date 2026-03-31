[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$state = & (Join-Path $PSScriptRoot 'Invoke-SquidBuild.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $RepositoryRoot `
    -BootstrapOnly
Write-Host 'Conan workspace bootstrap succeeded.'
$state
