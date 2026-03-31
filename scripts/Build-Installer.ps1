[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$ProjectPath = (Join-Path $PSScriptRoot '..\packaging\wix\Squid4Win.Installer.wixproj'),
    [string]$BuildProfilePath = (Join-Path $PSScriptRoot '..\config\build-profile.json'),
    [string]$InstallerPayloadRoot = (Join-Path $PSScriptRoot '..\artifacts\install-root'),
    [string]$ArtifactRoot = (Join-Path $PSScriptRoot '..\artifacts'),
    [string]$ProductVersion
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

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedProjectPath = Get-AbsolutePath -Path $ProjectPath -BasePath $resolvedRepositoryRoot
$resolvedBuildProfilePath = Get-AbsolutePath -Path $BuildProfilePath -BasePath $resolvedRepositoryRoot
$resolvedInstallerPayloadRoot = Get-AbsolutePath -Path $InstallerPayloadRoot -BasePath $resolvedRepositoryRoot
$resolvedArtifactRoot = Get-AbsolutePath -Path $ArtifactRoot -BasePath $resolvedRepositoryRoot
$resolvedProductVersion = if ($ProductVersion) {
    $ProductVersion
} else {
    & (Join-Path $PSScriptRoot 'Get-InstallerVersion.ps1') -RepositoryRoot $resolvedRepositoryRoot
}
$buildProfile = & (Join-Path $PSScriptRoot 'Get-SquidBuildProfile.ps1') -ConfigPath $resolvedBuildProfilePath

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
    "-p:SquidServiceName=$([string]$buildProfile.serviceName)" | Out-Host

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

[PSCustomObject]@{
    ProductVersion = $resolvedProductVersion
    MsiPath = $msiArtifactPath
    BuildOutputPath = $msiPath.FullName
}
