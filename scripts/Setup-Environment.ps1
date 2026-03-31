[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildProfilePath = (Join-Path $PSScriptRoot '..\config\build-profile.json'),
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json'),
    [string]$VersionConfigPath = (Join-Path $PSScriptRoot '..\config\squid-version.json'),
    [string]$Msys2Root,
    [switch]$AllowMissingPrerequisites
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$state = & (Join-Path $PSScriptRoot 'Initialize-NativeToolchain.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $RepositoryRoot `
    -BuildProfilePath $BuildProfilePath `
    -MetadataPath $MetadataPath `
    -VersionConfigPath $VersionConfigPath `
    -Msys2Root $Msys2Root `
    -AllowMissingPrerequisites:$AllowMissingPrerequisites

if ($state.Ready) {
    Write-Host 'Native environment bootstrap succeeded.'
} elseif ($AllowMissingPrerequisites) {
    Write-Host 'Native environment bootstrap found missing prerequisites.'
}

if ($state.SuggestedMsys2PackageInstallCommand) {
    Write-Host "Install missing MSYS2 packages with:"
    Write-Host $state.SuggestedMsys2PackageInstallCommand
}

$state
