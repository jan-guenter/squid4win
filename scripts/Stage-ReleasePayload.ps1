[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build',
    [string]$SquidStageRoot,
    [string]$ArtifactRoot = (Join-Path $PSScriptRoot '..\artifacts'),
    [switch]$CreatePortableZip,
    [switch]$SignPayloadFiles,
    [switch]$RequireTray,
    [switch]$RequireNotices,
    [string]$SigningCertificatePath = $env:SQUID4WIN_SIGNING_CERTIFICATE_PATH,
    [string]$SigningCertificateBase64 = $env:SQUID4WIN_SIGNING_CERTIFICATE_PFX_BASE64,
    [string]$SigningCertificateSecret = $env:SQUID4WIN_SIGNING_CERTIFICATE_PASSWORD,
    [string]$SigningTimestampServer = $env:SQUID4WIN_SIGNING_TIMESTAMP_URL,
    [string]$SignToolPath = $env:SQUID4WIN_SIGNTOOL_PATH
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
$payloadSigning = [PSCustomObject]@{
    SigningEnabled = $false
    SignedFileCount = 0
    SignedFiles = @()
    SkippedFileCount = 0
    SkippedFiles = @()
}
if ($SignPayloadFiles) {
    $payloadSigning = & (Join-Path $PSScriptRoot 'Invoke-AuthenticodeSigning.ps1') `
        -Path $installPayloadRoot `
        -RepositoryRoot $resolvedRepositoryRoot `
        -Recurse `
        -RequireMatches `
        -CertificatePath $SigningCertificatePath `
        -CertificateBase64 $SigningCertificateBase64 `
        -CertificateSecret $SigningCertificateSecret `
        -TimestampServer $SigningTimestampServer `
        -SignToolPath $SignToolPath
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
    SigningEnabled = [bool]$payloadSigning.SigningEnabled
    SignedFileCount = [int]$payloadSigning.SignedFileCount
    SignedFiles = @($payloadSigning.SignedFiles)
    SkippedFileCount = [int]$payloadSigning.SkippedFileCount
    SkippedFiles = @($payloadSigning.SkippedFiles)
}
