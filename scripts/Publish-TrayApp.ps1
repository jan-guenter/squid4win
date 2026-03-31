[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$RecipePath = (Join-Path $PSScriptRoot '..\conan\recipes\tray-app'),
    [string]$OutputRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')

function Get-TrayPackageReference {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConanExecutable,
        [Parameter(Mandatory = $true)]
        [string]$Configuration
    )

    $listJson = & $ConanExecutable list 'squid4win_tray/0.1:*' `
        -c `
        -f json `
        -fs 'os=Windows' `
        -fs 'arch=x86_64' `
        -fs "build_type=$Configuration"
    if ($LASTEXITCODE -ne 0) {
        throw "conan list failed while resolving the packaged tray app with exit code $LASTEXITCODE."
    }

    function Get-ObjectMemberValue {
        param(
            [Parameter(Mandatory = $true)]
            [AllowNull()]
            [object]$InputObject,
            [Parameter(Mandatory = $true)]
            [string]$Name
        )

        if ($null -eq $InputObject) {
            return $null
        }

        if ($InputObject -is [System.Collections.IDictionary]) {
            return $InputObject[$Name]
        }

        $property = $InputObject.PSObject.Properties[$Name]
        if ($null -ne $property) {
            return $property.Value
        }

        return $null
    }

    function Get-ObjectEntry {
        param(
            [Parameter(Mandatory = $true)]
            [AllowNull()]
            [object]$InputObject
        )

        if ($null -eq $InputObject) {
            return @()
        }

        if ($InputObject -is [System.Collections.IDictionary]) {
            return @($InputObject.GetEnumerator() | ForEach-Object {
                [PSCustomObject]@{
                    Key = [string]$_.Key
                    Value = $_.Value
                }
            })
        }

        return @($InputObject.PSObject.Properties | ForEach-Object {
            [PSCustomObject]@{
                Key = [string]$_.Name
                Value = $_.Value
            }
        })
    }

    $listData = $listJson | ConvertFrom-Json -AsHashtable
    $localCache = Get-ObjectMemberValue -InputObject $listData -Name 'Local Cache'
    $recipeEntry = Get-ObjectMemberValue -InputObject $localCache -Name 'squid4win_tray/0.1'

    if ($null -eq $recipeEntry) {
        throw 'Unable to find squid4win_tray/0.1 in the local Conan cache after conan create.'
    }

    $latestRevision = Get-ObjectEntry -InputObject (Get-ObjectMemberValue -InputObject $recipeEntry -Name 'revisions') |
        Sort-Object { [double]$_.Value.timestamp } -Descending |
        Select-Object -First 1

    if ($null -eq $latestRevision) {
        throw 'The tray recipe exists in the local Conan cache, but no recipe revision was returned.'
    }

    $packageEntries = Get-ObjectEntry -InputObject (Get-ObjectMemberValue -InputObject $latestRevision.Value -Name 'packages')
    $packageId = @($packageEntries.Key | Sort-Object)[0]
    if ([string]::IsNullOrWhiteSpace($packageId)) {
        throw "The tray recipe revision $($latestRevision.Key) does not expose a package ID for $Configuration."
    }

    return "squid4win_tray/0.1#$($latestRevision.Key):$packageId"
}

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedRecipePath = Get-AbsolutePath -Path $RecipePath -BasePath $resolvedRepositoryRoot
$configurationLabel = $Configuration.ToLowerInvariant()
$resolvedOutputRoot = if ($OutputRoot) {
    Get-AbsolutePath -Path $OutputRoot -BasePath $resolvedRepositoryRoot
} else {
    Get-AbsolutePath -Path "build\tray\$configurationLabel\publish" -BasePath $resolvedRepositoryRoot
}
$conanCommand = Get-Command conan -ErrorAction SilentlyContinue

if ($null -eq $conanCommand) {
    throw 'The conan CLI is not available on PATH. Install requirements-automation.txt first.'
}

if (-not (Test-Path -LiteralPath $resolvedRecipePath)) {
    throw "Expected the tray recipe at $resolvedRecipePath."
}

$conanHome = & (Join-Path $PSScriptRoot 'Resolve-ConanHome.ps1') -RepositoryRoot $resolvedRepositoryRoot -EnsureExists
$env:CONAN_HOME = $conanHome
& (Join-Path $PSScriptRoot 'Export-ConanWorkspaceRecipes.ps1') -RepositoryRoot $resolvedRepositoryRoot | Out-Null

& $conanCommand.Source create $resolvedRecipePath `
    -s:h os=Windows `
    -s:h arch=x86_64 `
    -s:h "build_type=$Configuration" `
    -s:b os=Windows `
    -s:b arch=x86_64 `
    -s:b "build_type=$Configuration" `
    --build=missing | Out-Host
$conanCreateExitCode = $LASTEXITCODE

if ($conanCreateExitCode -ne 0) {
    throw "conan create failed for the tray recipe with exit code $conanCreateExitCode."
}

$trayPackageReference = Get-TrayPackageReference -ConanExecutable $conanCommand.Source -Configuration $Configuration
$trayPackageRoot = (& $conanCommand.Source cache path $trayPackageReference).Trim()

if ($LASTEXITCODE -ne 0) {
    throw "conan cache path failed for $trayPackageReference with exit code $LASTEXITCODE."
}

$packagedBinRoot = Join-Path $trayPackageRoot 'bin'
if (-not (Test-Path -LiteralPath $packagedBinRoot)) {
    throw "Expected the packaged tray payload under $packagedBinRoot."
}

if (Test-Path -LiteralPath $resolvedOutputRoot) {
    Remove-Item -LiteralPath $resolvedOutputRoot -Recurse -Force
}

$null = New-Item -ItemType Directory -Path $resolvedOutputRoot -Force
Copy-Item -Path (Join-Path $packagedBinRoot '*') -Destination $resolvedOutputRoot -Recurse -Force

$trayExecutablePath = Join-Path $resolvedOutputRoot 'Squid4Win.Tray.exe'
if (-not (Test-Path -LiteralPath $trayExecutablePath)) {
    throw "Expected the packaged tray executable at $trayExecutablePath."
}

Write-Host "Materialized Conan-packaged tray application to $resolvedOutputRoot"
Write-Host "Tray package reference: $trayPackageReference"
$resolvedOutputRoot
