[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [switch]$UseTrayEditable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$conanCommand = Get-Command conan -ErrorAction SilentlyContinue

if ($null -eq $conanCommand) {
    throw 'The conan CLI is not available on PATH. Install requirements-automation.txt first.'
}

function Invoke-ConanCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$FailureDescription
    )

    & $conanCommand.Source @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureDescription failed with exit code $LASTEXITCODE."
    }
}

function Get-ConanEditableMap {
    $editableListJson = (& $conanCommand.Source editable list -f json | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "conan editable list failed with exit code $LASTEXITCODE."
    }

    if ([string]::IsNullOrWhiteSpace($editableListJson)) {
        return @{}
    }

    $editableList = ConvertFrom-Json -InputObject $editableListJson -AsHashtable
    if ($null -eq $editableList) {
        return @{}
    }

    return $editableList
}

$sharedRecipe = @{
    Path = Join-Path $resolvedRepositoryRoot 'conan\python_requires\squid4win_recipe_base'
    Label = 'shared python_requires recipe'
}
$trayRecipe = @{
    Path = Join-Path $resolvedRepositoryRoot 'conan\recipes\tray-app'
    Label = 'tray app recipe'
    Reference = 'squid4win_tray/0.1'
}

foreach ($workspaceRecipe in @($sharedRecipe, $trayRecipe)) {
    if (-not (Test-Path -LiteralPath $workspaceRecipe.Path)) {
        throw "Expected the $($workspaceRecipe.Label) at $($workspaceRecipe.Path)."
    }
}

Invoke-ConanCommand `
    -Arguments @('export', $sharedRecipe.Path) `
    -FailureDescription "conan export for $($sharedRecipe.Path)"

$editables = Get-ConanEditableMap
$trayEditable = $editables[$trayRecipe.Reference]
$expectedEditablePath = [System.IO.Path]::GetFullPath(
    (Join-Path $trayRecipe.Path 'conanfile.py')
)
$trayEditablePath = if ($null -ne $trayEditable) {
    [System.IO.Path]::GetFullPath([string]$trayEditable['path'])
} else {
    $null
}
$trayEditableOutputFolder = if ($null -ne $trayEditable) {
    [string]$trayEditable['output_folder']
} else {
    $null
}

if ($null -ne $trayEditable -and (
        ($trayEditablePath -ne $expectedEditablePath) -or
        (-not [string]::IsNullOrWhiteSpace($trayEditableOutputFolder)) -or
        (-not $UseTrayEditable)
    )) {
    Invoke-ConanCommand `
        -Arguments @('editable', 'remove', "--refs=$($trayRecipe.Reference)") `
        -FailureDescription "conan editable remove for $($trayRecipe.Reference)"
    $trayEditable = $null
}

if ($UseTrayEditable) {
    if ($null -eq $trayEditable) {
        Invoke-ConanCommand `
            -Arguments @('editable', 'add', $trayRecipe.Path) `
            -FailureDescription "conan editable add for $($trayRecipe.Path)"
    }
} else {
    Invoke-ConanCommand `
        -Arguments @('export', $trayRecipe.Path) `
        -FailureDescription "conan export for $($trayRecipe.Path)"
}

$exportedRecipes = [System.Collections.Generic.List[string]]::new()
$exportedRecipes.Add($sharedRecipe.Path)
if (-not $UseTrayEditable) {
    $exportedRecipes.Add($trayRecipe.Path)
}

[PSCustomObject]@{
    RepositoryRoot = $resolvedRepositoryRoot
    ExportedRecipes = $exportedRecipes.ToArray()
    TrayRecipeMode = if ($UseTrayEditable) { 'Editable' } else { 'Cache' }
    TrayRecipePath = $trayRecipe.Path
    TrayRecipeReference = $trayRecipe.Reference
}

