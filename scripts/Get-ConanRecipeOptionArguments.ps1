[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [switch]$WithTray,
    [switch]$WithRuntimeDlls,
    [switch]$WithPackagingSupport
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
$conandataPath = Join-Path $resolvedRepositoryRoot 'conandata.yml'
if (-not (Test-Path -LiteralPath $conandataPath)) {
    throw "The Conan data file '$conandataPath' was not found."
}
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCommand) {
    throw 'Python is required to materialize Conan tool package options from conandata.yml.'
}
$arguments = [System.Collections.Generic.List[string]]::new()
foreach ($optionState in @(
    @{ Name = 'with_tray'; Enabled = $WithTray.IsPresent },
    @{ Name = 'with_runtime_dlls'; Enabled = $WithRuntimeDlls.IsPresent },
    @{ Name = 'with_packaging_support'; Enabled = $WithPackagingSupport.IsPresent }
)) {
    $arguments.Add('-o')
    $arguments.Add("&:$($optionState.Name)=$($optionState.Enabled.ToString())")
}
$dependencyOptionArgumentsJson = & $pythonCommand.Source -c @'
import json
import sys
from pathlib import Path

import yaml

repository_root = Path(sys.argv[1])
conandata = yaml.safe_load((repository_root / "conandata.yml").read_text(encoding="utf-8")) or {}
build_settings = conandata.get("build", {})
arguments = []

msys2_settings = build_settings.get("msys2") or {}
msys2_packages = [str(package).strip() for package in msys2_settings.get("packages", [])]
msys2_packages = [package for package in msys2_packages if package]
if msys2_packages:
    arguments.extend(["-o:b", f"msys2/*:additional_packages={','.join(msys2_packages)}"])

mingw_settings = build_settings.get("mingw_builds") or {}
for option_name in ("threads", "exception", "runtime"):
    option_value = str(mingw_settings.get(option_name, "")).strip()
    if option_value:
        arguments.extend(["-o:b", f"mingw-builds/*:{option_name}={option_value}"])

print(json.dumps(arguments))
'@ $resolvedRepositoryRoot
if ($LASTEXITCODE -ne 0) {
    throw "Failed to materialize the Conan tool package options from '$conandataPath'."
}
$dependencyOptionArguments = @()
if (-not [string]::IsNullOrWhiteSpace($dependencyOptionArgumentsJson)) {
    $dependencyOptionArguments = @((ConvertFrom-Json -InputObject $dependencyOptionArgumentsJson))
}
foreach ($argument in $dependencyOptionArguments) {
    $arguments.Add([string]$argument)
}
$arguments.ToArray()
