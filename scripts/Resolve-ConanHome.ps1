[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [switch]$EnsureExists
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$conanHome = Join-Path $resolvedRepositoryRoot '.conan2'

if ($EnsureExists -and -not (Test-Path -LiteralPath $conanHome)) {
    $null = New-Item -ItemType Directory -Path $conanHome -Force
}

$conanHome
