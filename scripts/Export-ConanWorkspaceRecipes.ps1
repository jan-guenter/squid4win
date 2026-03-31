[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$conanCommand = Get-Command conan -ErrorAction SilentlyContinue

if ($null -eq $conanCommand) {
    throw 'The conan CLI is not available on PATH. Install requirements-automation.txt first.'
}

$workspaceRecipes = @(
    @{
        Path = Join-Path $resolvedRepositoryRoot 'conan\python_requires\squid4win_recipe_base'
        Label = 'shared python_requires recipe'
    },
    @{
        Path = Join-Path $resolvedRepositoryRoot 'conan\recipes\tray-app'
        Label = 'tray app recipe'
    }
)

foreach ($workspaceRecipe in $workspaceRecipes) {
    if (-not (Test-Path -LiteralPath $workspaceRecipe.Path)) {
        throw "Expected the $($workspaceRecipe.Label) at $($workspaceRecipe.Path)."
    }

    & $conanCommand.Source export $workspaceRecipe.Path
    if ($LASTEXITCODE -ne 0) {
        throw "conan export failed for $($workspaceRecipe.Path) with exit code $LASTEXITCODE."
    }
}

[PSCustomObject]@{
    RepositoryRoot = $resolvedRepositoryRoot
    ExportedRecipes = @($workspaceRecipes.Path)
}

