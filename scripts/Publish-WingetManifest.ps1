[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$Tag = ("v{0}" -f $Version),
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository = 'jan-guenter/squid4win',
    [string]$ManifestRoot = (Join-Path $PSScriptRoot '..\artifacts\package-managers'),
    [string]$PackageIdentifier = 'JanGuenter.Squid4Win',
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$TargetRepository = 'microsoft/winget-pkgs',
    [string]$BaseBranch = 'master',
    [string]$WorkingRoot = (Join-Path $PSScriptRoot '..\artifacts\publication\winget')
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

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$resolvedManifestRoot = Get-AbsolutePath -Path $ManifestRoot -BasePath $repositoryRoot
$wingetManifestRoot = Join-Path $resolvedManifestRoot "winget\$Version"

if (-not (Test-Path -LiteralPath $wingetManifestRoot -PathType Container)) {
    throw "The winget manifest root '$wingetManifestRoot' was not found."
}

$identifierSegments = $PackageIdentifier.Split('.')
if ($identifierSegments.Count -lt 2) {
    throw "The package identifier '$PackageIdentifier' must contain at least two segments."
}

$destinationPath = Join-Path 'manifests' ([string][char]::ToLowerInvariant($PackageIdentifier[0]))
foreach ($segment in $identifierSegments) {
    $destinationPath = Join-Path $destinationPath $segment
}
$destinationPath = Join-Path $destinationPath $Version
$sanitizedVersion = $Version -replace '[^A-Za-z0-9._-]', '-'
$releaseUrl = "https://github.com/$Repository/releases/tag/$Tag"
$pullRequestBody = @(
    "Automated submission for $PackageIdentifier $Version.",
    '',
    "- Source repository: $Repository",
    "- Release tag: $Tag",
    "- Release URL: $releaseUrl",
    '',
    'Generated from the published MSI by `.github\workflows\package-managers.yml`.'
) -join [Environment]::NewLine

$result = & (Join-Path $PSScriptRoot 'Submit-GitHubPullRequest.ps1') `
    -SourcePath $wingetManifestRoot `
    -DestinationRepository $TargetRepository `
    -DestinationPath $destinationPath `
    -BranchName "automation/winget/$sanitizedVersion" `
    -CommitMessage "Add $PackageIdentifier $Version" `
    -PullRequestTitle "Add $PackageIdentifier $Version" `
    -PullRequestBody $pullRequestBody `
    -BaseBranch $BaseBranch `
    -WorkingRoot $WorkingRoot

[PSCustomObject]@{
    Changed = $result.Changed
    PullRequestUrl = $result.PullRequestUrl
    HeadRepository = $result.HeadRepository
    BaseRepository = $result.BaseRepository
    BranchName = $result.BranchName
    ManifestRoot = $wingetManifestRoot
    DestinationPath = $destinationPath
}
