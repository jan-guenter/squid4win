[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\config\build-profile.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
if (-not (Test-Path -LiteralPath $resolvedConfigPath)) {
    throw "Build profile config was not found at $resolvedConfigPath."
}

$buildProfile = Get-Content -Raw -LiteralPath $resolvedConfigPath | ConvertFrom-Json
$requiredProperties = @(
    'toolchain',
    'msys2Env',
    'conanHome',
    'conanProfileName',
    'conanToolRequirements',
    'conanRequirements',
    'stageRoot',
    'requiredMsys2Packages',
    'hostTriplet',
    'compilerCppStd',
    'compilerLibCxx',
    'configureArgs'
)
$missingProperties = foreach ($propertyName in $requiredProperties) {
    if (-not ($buildProfile.PSObject.Properties.Name -contains $propertyName)) {
        $propertyName
    }
}

if ($missingProperties) {
    throw "Build profile config at $resolvedConfigPath is missing required properties: $($missingProperties -join ', ')."
}

if ([string]$buildProfile.toolchain -ne 'native-msys2') {
    throw "Build profile config at $resolvedConfigPath must keep toolchain set to native-msys2."
}

$buildProfile
