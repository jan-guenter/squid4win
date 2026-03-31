[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build',
    [string]$BuildProfilePath = (Join-Path $PSScriptRoot '..\config\build-profile.json'),
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json'),
    [string]$SquidStageRoot,
    [string]$TrayPublishRoot,
    [string]$ArtifactRoot = (Join-Path $PSScriptRoot '..\artifacts'),
    [switch]$CreatePortableZip
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

function Copy-DirectoryContents {
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
$resolvedBuildProfilePath = Get-AbsolutePath -Path $BuildProfilePath -BasePath $resolvedRepositoryRoot
$resolvedMetadataPath = Get-AbsolutePath -Path $MetadataPath -BasePath $resolvedRepositoryRoot
$resolvedArtifactRoot = Get-AbsolutePath -Path $ArtifactRoot -BasePath $resolvedRepositoryRoot
$layout = & (Join-Path $PSScriptRoot 'Resolve-SquidBuildLayout.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $resolvedRepositoryRoot `
    -BuildRoot $resolvedBuildRoot `
    -BuildProfilePath $resolvedBuildProfilePath
$metadata = Get-Content -Raw -LiteralPath $resolvedMetadataPath | ConvertFrom-Json
$configurationLabel = $Configuration.ToLowerInvariant()
$resolvedSquidStageRoot = if ($SquidStageRoot) {
    Get-AbsolutePath -Path $SquidStageRoot -BasePath $resolvedRepositoryRoot
} else {
    [string]$layout.StageRoot
}
$resolvedTrayPublishRoot = if ($TrayPublishRoot) {
    Get-AbsolutePath -Path $TrayPublishRoot -BasePath $resolvedRepositoryRoot
} else {
    & (Join-Path $PSScriptRoot 'Publish-TrayApp.ps1') -Configuration $Configuration -RepositoryRoot $resolvedRepositoryRoot
}

if (-not (Test-Path -LiteralPath $resolvedSquidStageRoot)) {
    throw "The Squid stage root '$resolvedSquidStageRoot' does not exist."
}

if (-not (Test-Path -LiteralPath $resolvedTrayPublishRoot)) {
    throw "The tray publish root '$resolvedTrayPublishRoot' does not exist."
}

$installPayloadRoot = Join-Path $resolvedArtifactRoot 'install-root'
$portableZipPath = Join-Path $resolvedArtifactRoot 'squid4win-portable.zip'
$noticesPath = Join-Path $installPayloadRoot 'THIRD-PARTY-NOTICES.txt'
$licensesRoot = Join-Path $installPayloadRoot 'licenses'
$installerSupportRoot = Join-Path $installPayloadRoot 'installer'
$configDirectory = Join-Path $installPayloadRoot 'etc'

if (Test-Path -LiteralPath $installPayloadRoot) {
    Remove-Item -LiteralPath $installPayloadRoot -Recurse -Force
}

$null = New-Item -ItemType Directory -Path $resolvedArtifactRoot, $installPayloadRoot -Force
Copy-DirectoryContents -Source $resolvedSquidStageRoot -Destination $installPayloadRoot
Copy-DirectoryContents -Source $resolvedTrayPublishRoot -Destination $installPayloadRoot

foreach ($directoryPath in @(
        $licensesRoot,
        $installerSupportRoot,
        $configDirectory,
        (Join-Path $installPayloadRoot 'var\cache'),
        (Join-Path $installPayloadRoot 'var\logs'),
        (Join-Path $installPayloadRoot 'var\run')
    )) {
    $null = New-Item -ItemType Directory -Path $directoryPath -Force
}

$serviceHelperSourcePath = Join-Path $resolvedRepositoryRoot 'scripts\installer\Manage-SquidService.ps1'
$serviceHelperDestinationPath = Join-Path $installerSupportRoot 'svc.ps1'
Copy-Item -LiteralPath $serviceHelperSourcePath -Destination $serviceHelperDestinationPath -Force

$configTemplateSourcePath = Join-Path $resolvedRepositoryRoot 'packaging\defaults\squid.conf.template'
$configTemplateDestinationPath = Join-Path $configDirectory 'squid.conf.template'
Copy-Item -LiteralPath $configTemplateSourcePath -Destination $configTemplateDestinationPath -Force

$mimeConfigDestinationPath = Join-Path $configDirectory 'mime.conf'
if (-not (Test-Path -LiteralPath $mimeConfigDestinationPath)) {
    $mimeCandidates = @(
        (Join-Path $configDirectory 'mime.conf.default'),
        (Join-Path $resolvedSquidStageRoot 'etc\mime.conf'),
        (Join-Path $resolvedSquidStageRoot 'etc\mime.conf.default'),
        (Join-Path ([string]$layout.SourcesRoot) "squid-$($metadata.version)\src\mime.conf.default")
    )

    $mimeSourcePath = $mimeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $mimeSourcePath) {
        throw "Unable to locate mime.conf for the staged payload."
    }

    Copy-Item -LiteralPath $mimeSourcePath -Destination $mimeConfigDestinationPath -Force
}

$repositoryLicensePath = Join-Path $resolvedRepositoryRoot 'LICENSE'
Copy-Item -LiteralPath $repositoryLicensePath -Destination (Join-Path $licensesRoot 'Repository-LICENSE.txt') -Force

$sourceRoot = Join-Path ([string]$layout.SourcesRoot) "squid-$($metadata.version)"
if (-not (Test-Path -LiteralPath $sourceRoot)) {
    $sourceDirectory = Get-ChildItem -LiteralPath ([string]$layout.SourcesRoot) -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'squid-*' } |
        Sort-Object Name -Descending |
        Select-Object -First 1

    if ($null -ne $sourceDirectory) {
        $sourceRoot = $sourceDirectory.FullName
    }
}

$squidCopyingPath = if (Test-Path -LiteralPath (Join-Path $sourceRoot 'COPYING')) {
    Join-Path $sourceRoot 'COPYING'
} else {
    $null
}

if ($squidCopyingPath) {
    Copy-Item -LiteralPath $squidCopyingPath -Destination (Join-Path $licensesRoot 'Squid-COPYING.txt') -Force
}

$sourceManifest = [ordered]@{
    generated_at = (Get-Date).ToString('o')
    configuration = $configurationLabel
    squid = [ordered]@{
        version = [string]$metadata.version
        tag = [string]$metadata.tag
        source_archive = [string]$metadata.assets.source_archive
        source_archive_sha256 = [string]$metadata.assets.source_archive_sha256
    }
    repository = [ordered]@{
        name = 'squid4win'
        license = 'MIT'
    }
}

$sourceManifestPath = Join-Path $licensesRoot 'source-manifest.json'
$sourceManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $sourceManifestPath -Encoding ascii

$noticesContent = @(
    'Squid4Win third-party notice bundle',
    '',
    "This payload stages Squid $($metadata.version) from the upstream source archive listed in licenses\source-manifest.json.",
    'Repository-local automation and packaging code in this project are MIT-licensed; see licenses\Repository-LICENSE.txt.',
    '',
    'Current bundled notice set:',
    '- licenses\source-manifest.json',
    '- licenses\Repository-LICENSE.txt',
    '- licenses\Squid-COPYING.txt (when the upstream source tree is available locally)',
    '',
    'Before a signed production release, audit the final harvested runtime DLL set and expand this notice bundle with any additional third-party runtime licenses that ship in the installer.'
) -join [Environment]::NewLine
Set-Content -LiteralPath $noticesPath -Value $noticesContent -Encoding ascii

$trayExecutablePath = Join-Path $installPayloadRoot 'Squid4Win.Tray.exe'
if (-not (Test-Path -LiteralPath $trayExecutablePath)) {
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
    NoticesPath = $noticesPath
    TrayExecutablePath = $trayExecutablePath
    SquidExecutablePath = $stagedSquidExecutablePath
    SourceManifestPath = $sourceManifestPath
}
