[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build',
    [string]$BuildProfilePath = (Join-Path $PSScriptRoot '..\config\build-profile.json')
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

function Get-ConfigurationPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$ConfigurationLabel
    )

    $configuredPath = [System.Text.RegularExpressions.Regex]::Replace(
        $Path,
        '\{configuration\}',
        $ConfigurationLabel,
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )

    if ($configuredPath -ne $Path) {
        return $configuredPath
    }

    $leafName = Split-Path -Path $configuredPath -Leaf
    if ($leafName -match '^(debug|release)$') {
        $parentPath = Split-Path -Path $configuredPath -Parent
        if ([string]::IsNullOrWhiteSpace($parentPath)) {
            return $ConfigurationLabel
        }

        return Join-Path $parentPath $ConfigurationLabel
    }

    return $configuredPath
}

function Resolve-BuildScopedPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedBuildRoot,
        [Parameter(Mandatory = $true)]
        [string]$ConfigurationLabel
    )

    $defaultBuildRoot = Get-AbsolutePath -Path 'build' -BasePath $RepositoryRoot
    $pathForConfiguration = Get-ConfigurationPath -Path $Path -ConfigurationLabel $ConfigurationLabel
    $resolvedConfiguredPath = Get-AbsolutePath -Path $pathForConfiguration -BasePath $RepositoryRoot

    if ($resolvedConfiguredPath.Equals($defaultBuildRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $ResolvedBuildRoot
    }

    $defaultBuildRootWithSeparator = $defaultBuildRoot.TrimEnd('\') + '\'
    if ($resolvedConfiguredPath.StartsWith($defaultBuildRootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relativePath = $resolvedConfiguredPath.Substring($defaultBuildRootWithSeparator.Length)
        return Join-Path $ResolvedBuildRoot $relativePath
    }

    return $resolvedConfiguredPath
}

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedBuildRoot = Get-AbsolutePath -Path $BuildRoot -BasePath $resolvedRepositoryRoot
$resolvedBuildProfilePath = Get-AbsolutePath -Path $BuildProfilePath -BasePath $resolvedRepositoryRoot
$buildProfile = & (Join-Path $PSScriptRoot 'Get-SquidBuildProfile.ps1') -ConfigPath $resolvedBuildProfilePath
$configurationLabel = $Configuration.ToLowerInvariant()
$profileStem = '{0}-{1}' -f [string]$buildProfile.conanProfileName, $configurationLabel
$stageRoot = Resolve-BuildScopedPath `
    -Path ([string]$buildProfile.stageRoot) `
    -RepositoryRoot $resolvedRepositoryRoot `
    -ResolvedBuildRoot $resolvedBuildRoot `
    -ConfigurationLabel $configurationLabel

[PSCustomObject]@{
    RepositoryRoot = $resolvedRepositoryRoot
    BuildRoot = $resolvedBuildRoot
    BuildProfilePath = $resolvedBuildProfilePath
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
