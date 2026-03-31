[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$ProjectPath = (Join-Path $PSScriptRoot '..\src\tray\Squid4Win.Tray\Squid4Win.Tray.csproj'),
    [string]$OutputRoot
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
$configurationLabel = $Configuration.ToLowerInvariant()
$resolvedOutputRoot = if ($OutputRoot) {
    Get-AbsolutePath -Path $OutputRoot -BasePath $resolvedRepositoryRoot
} else {
    Get-AbsolutePath -Path "build\tray\$configurationLabel\publish" -BasePath $resolvedRepositoryRoot
}

if (Test-Path -LiteralPath $resolvedOutputRoot) {
    Remove-Item -LiteralPath $resolvedOutputRoot -Recurse -Force
}

& dotnet publish $resolvedProjectPath `
    -c $Configuration `
    -o $resolvedOutputRoot `
    --nologo `
    -p:SelfContained=false `
    -p:PublishSingleFile=false | Out-Host

$dotnetPublishExitCode = $LASTEXITCODE

if ($dotnetPublishExitCode -ne 0) {
    throw "dotnet publish failed with exit code $dotnetPublishExitCode."
}

$trayExecutablePath = Join-Path $resolvedOutputRoot 'Squid4Win.Tray.exe'
if (-not (Test-Path -LiteralPath $trayExecutablePath)) {
    throw "Expected the published tray executable at $trayExecutablePath."
}

Write-Host "Published tray application to $resolvedOutputRoot"
$resolvedOutputRoot
