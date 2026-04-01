[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$ProjectPath = (Join-Path $PSScriptRoot '..\packaging\wix\Squid4Win.Installer.wixproj'),
    [string]$InstallerPayloadRoot = (Join-Path $PSScriptRoot '..\artifacts\install-root'),
    [string]$ArtifactRoot = (Join-Path $PSScriptRoot '..\artifacts'),
    [string]$ProductVersion,
    [string]$ServiceName = 'Squid4Win',
    [switch]$SignMsi,
    [string]$SigningCertificatePath = $env:SQUID4WIN_SIGNING_CERTIFICATE_PATH,
    [string]$SigningCertificateBase64 = $env:SQUID4WIN_SIGNING_CERTIFICATE_PFX_BASE64,
    [string]$SigningCertificateSecret = $env:SQUID4WIN_SIGNING_CERTIFICATE_PASSWORD,
    [string]$SigningTimestampServer = $env:SQUID4WIN_SIGNING_TIMESTAMP_URL,
    [string]$SignToolPath = $env:SQUID4WIN_SIGNTOOL_PATH
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')
. (Join-Path $PSScriptRoot 'Assert-SquidServiceName.ps1')
$resolvedServiceName = Assert-SquidServiceName -Name $ServiceName
$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedProjectPath = Get-AbsolutePath -Path $ProjectPath -BasePath $resolvedRepositoryRoot
$resolvedInstallerPayloadRoot = Get-AbsolutePath -Path $InstallerPayloadRoot -BasePath $resolvedRepositoryRoot
$resolvedArtifactRoot = Get-AbsolutePath -Path $ArtifactRoot -BasePath $resolvedRepositoryRoot
$resolvedProductVersion = if ($ProductVersion) {
    $ProductVersion
} else {
    & (Join-Path $PSScriptRoot 'Get-InstallerVersion.ps1') -RepositoryRoot $resolvedRepositoryRoot
}
if (-not (Test-Path -LiteralPath $resolvedInstallerPayloadRoot)) {
    throw "Installer payload root '$resolvedInstallerPayloadRoot' does not exist."
}
$projectDirectoryPath = Split-Path -Parent $resolvedProjectPath
$msiArtifactPath = Join-Path $resolvedArtifactRoot 'squid4win.msi'
$buildStartTime = Get-Date
$configurationOutputRoot = Join-Path $projectDirectoryPath "bin\$Configuration"
$configurationIntermediateRoot = Join-Path $projectDirectoryPath "obj\$Configuration"
foreach ($pathToClear in @($configurationOutputRoot, $configurationIntermediateRoot)) {
    if (Test-Path -LiteralPath $pathToClear) {
        Remove-Item -LiteralPath $pathToClear -Recurse -Force
    }
}
& dotnet build $resolvedProjectPath `
    -c $Configuration `
    -t:Rebuild `
    --nologo `
    "-p:InstallerPayloadRoot=$resolvedInstallerPayloadRoot" `
    "-p:ProductVersion=$resolvedProductVersion" `
    "-p:SquidServiceName=$resolvedServiceName" | Out-Host
$dotnetBuildExitCode = $LASTEXITCODE
if ($dotnetBuildExitCode -ne 0) {
    throw "dotnet build failed with exit code $dotnetBuildExitCode while building the installer."
}
$msiPath = Get-ChildItem -Path (Join-Path $projectDirectoryPath 'bin') -Recurse -Filter '*.msi' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -ge $buildStartTime.AddSeconds(-5) } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $msiPath) {
    $msiPath = Get-ChildItem -Path (Join-Path $projectDirectoryPath 'bin') -Recurse -Filter '*.msi' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}
if ($null -eq $msiPath) {
    throw "Unable to locate the built MSI under $(Join-Path $projectDirectoryPath 'bin')."
}
$null = New-Item -ItemType Directory -Path $resolvedArtifactRoot -Force
Copy-Item -LiteralPath $msiPath.FullName -Destination $msiArtifactPath -Force
$msiSigning = [PSCustomObject]@{
    SigningEnabled = $false
    SignedFileCount = 0
    SignedFiles = @()
    SkippedFileCount = 0
    SkippedFiles = @()
}
if ($SignMsi) {
    $msiSigning = & (Join-Path $PSScriptRoot 'Invoke-AuthenticodeSigning.ps1') `
        -Path $msiArtifactPath `
        -RepositoryRoot $resolvedRepositoryRoot `
        -RequireMatches `
        -CertificatePath $SigningCertificatePath `
        -CertificateBase64 $SigningCertificateBase64 `
        -CertificateSecret $SigningCertificateSecret `
        -TimestampServer $SigningTimestampServer `
        -SignToolPath $SignToolPath
}
[PSCustomObject]@{
    ProductVersion = $resolvedProductVersion
    ServiceName = $resolvedServiceName
    MsiPath = $msiArtifactPath
    BuildOutputPath = $msiPath.FullName
    SigningEnabled = [bool]$msiSigning.SigningEnabled
    SignedFileCount = [int]$msiSigning.SignedFileCount
    SignedFiles = @($msiSigning.SignedFiles)
    SkippedFileCount = [int]$msiSigning.SkippedFileCount
    SkippedFiles = @($msiSigning.SkippedFiles)
}
