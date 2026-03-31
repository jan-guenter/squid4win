[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [switch]$EnsureExists,
    [switch]$SetEnvironment
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedRepositoryRoot = [System.IO.Path]::GetFullPath($RepositoryRoot)
$conanHome = Join-Path $resolvedRepositoryRoot '.conan2'

if ($EnsureExists -and -not (Test-Path -LiteralPath $conanHome)) {
    $null = New-Item -ItemType Directory -Path $conanHome -Force
}

if ($SetEnvironment) {
    $env:CONAN_HOME = $conanHome
}

$conanHome
