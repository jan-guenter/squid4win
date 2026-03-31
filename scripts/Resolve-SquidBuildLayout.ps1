[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')
$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedBuildRoot = Get-AbsolutePath -Path $BuildRoot -BasePath $resolvedRepositoryRoot
$configurationLabel = $Configuration.ToLowerInvariant()
$profileName = 'msys2-mingw-x64'
$profileStem = '{0}-{1}' -f $profileName, $configurationLabel
$stageRoot = Join-Path $resolvedBuildRoot "install\$configurationLabel"
[PSCustomObject]@{
    RepositoryRoot = $resolvedRepositoryRoot
    BuildRoot = $resolvedBuildRoot
    Configuration = $Configuration
    ConfigurationLabel = $configurationLabel
    StageRoot = $stageRoot
    DownloadsRoot = Join-Path $resolvedBuildRoot 'downloads'
    SourcesRoot = Join-Path (Join-Path $resolvedBuildRoot 'sources') $profileStem
    WorkRoot = Join-Path $resolvedBuildRoot $profileStem
    ConanOutputRoot = Join-Path (Join-Path $resolvedBuildRoot 'conan') $profileStem
    ConanGeneratorsRoot = Join-Path (Join-Path (Join-Path $resolvedBuildRoot 'conan') $profileStem) "build-$configurationLabel\conan"
    RepoLockfilePath = Join-Path $resolvedRepositoryRoot "conan\lockfiles\$profileStem.lock"
    BuildLockPath = Join-Path (Join-Path $resolvedBuildRoot 'locks') "$profileStem.lock"
}
