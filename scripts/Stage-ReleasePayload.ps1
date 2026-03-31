[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build',
    [string]$SquidStageRoot,
    [string]$ArtifactRoot = (Join-Path $PSScriptRoot '..\artifacts'),
    [switch]$CreatePortableZip,
    [switch]$RequireTray,
    [switch]$RequireNotices
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')
function Copy-DirectoryContent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )
    $items = @(Get-ChildItem -LiteralPath $Source -Force)
    foreach ($item in $items) {
        Copy-Item -LiteralPath $item.FullName -Destination $Destination -Recurse -Force
    }
}
$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedBuildRoot = Get-AbsolutePath -Path $BuildRoot -BasePath $resolvedRepositoryRoot
$resolvedArtifactRoot = Get-AbsolutePath -Path $ArtifactRoot -BasePath $resolvedRepositoryRoot
$layout = & (Join-Path $PSScriptRoot 'Resolve-SquidBuildLayout.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $resolvedRepositoryRoot `
    -BuildRoot $resolvedBuildRoot
$resolvedSquidStageRoot = if ($SquidStageRoot) {
    Get-AbsolutePath -Path $SquidStageRoot -BasePath $resolvedRepositoryRoot
} else {
    [string]$layout.StageRoot
}
if (-not (Test-Path -LiteralPath $resolvedSquidStageRoot)) {
    throw "The staged Conan bundle root '$resolvedSquidStageRoot' does not exist."
}
$installPayloadRoot = Join-Path $resolvedArtifactRoot 'install-root'
$portableZipPath = Join-Path $resolvedArtifactRoot 'squid4win-portable.zip'
$noticesPath = Join-Path $installPayloadRoot 'THIRD-PARTY-NOTICES.txt'
if (Test-Path -LiteralPath $installPayloadRoot) {
    Remove-Item -LiteralPath $installPayloadRoot -Recurse -Force
}
$null = New-Item -ItemType Directory -Path $resolvedArtifactRoot, $installPayloadRoot -Force
Copy-DirectoryContent -Source $resolvedSquidStageRoot -Destination $installPayloadRoot
$trayExecutablePath = Join-Path $installPayloadRoot 'Squid4Win.Tray.exe'
if ($RequireTray -and -not (Test-Path -LiteralPath $trayExecutablePath)) {
    throw "Expected the staged tray executable at $trayExecutablePath."
}
$squidExecutableCandidates = @(
    (Join-Path $installPayloadRoot 'sbin\squid.exe'),
    (Join-Path $installPayloadRoot 'bin\squid.exe')
)
$stagedSquidExecutablePath = $squidExecutableCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $stagedSquidExecutablePath) {
    throw "Expected squid.exe under $installPayloadRoot."
}
if ($RequireNotices -and -not (Test-Path -LiteralPath $noticesPath)) {
    throw "Expected THIRD-PARTY-NOTICES.txt under $installPayloadRoot."
}
if ($CreatePortableZip) {
    if (Test-Path -LiteralPath $portableZipPath) {
        Remove-Item -LiteralPath $portableZipPath -Force
    }
    $previousProgressPreference = $global:ProgressPreference
    try {
        $global:ProgressPreference = 'SilentlyContinue'
        Compress-Archive -Path (Join-Path $installPayloadRoot '*') -DestinationPath $portableZipPath
    }
    finally {
        $global:ProgressPreference = $previousProgressPreference
    }
}
[PSCustomObject]@{
    ArtifactRoot = $resolvedArtifactRoot
    InstallPayloadRoot = $installPayloadRoot
    PortableZipPath = if ($CreatePortableZip) { $portableZipPath } else { $null }
    NoticesPath = if (Test-Path -LiteralPath $noticesPath) { $noticesPath } else { $null }
    SquidExecutablePath = $stagedSquidExecutablePath
}
