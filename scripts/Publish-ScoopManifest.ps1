[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$Tag = ("v{0}" -f $Version),
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository = 'jan-guenter/squid4win',
    [string]$ManifestRoot = (Join-Path $PSScriptRoot '..\artifacts\package-managers'),
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$TargetRepository,
    [string]$BaseBranch = 'master',
    [string]$PackageFileName = 'squid4win.json',
    [string]$WorkingRoot = (Join-Path $PSScriptRoot '..\artifacts\publication\scoop')
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
$scoopManifestPath = Join-Path $resolvedManifestRoot "scoop\$PackageFileName"

if (-not (Test-Path -LiteralPath $scoopManifestPath -PathType Leaf)) {
    throw "The Scoop manifest '$scoopManifestPath' was not found."
}

$sanitizedVersion = $Version -replace '[^A-Za-z0-9._-]', '-'
$destinationPath = Join-Path 'bucket' $PackageFileName
$releaseUrl = "https://github.com/$Repository/releases/tag/$Tag"
$pullRequestBody = @(
    "Automated Scoop manifest update for Squid4Win $Version.",
    '',
    "- Source repository: $Repository",
    "- Release tag: $Tag",
    "- Release URL: $releaseUrl",
    '',
    'Generated from the published portable zip by `.github\workflows\package-managers.yml`.'
) -join [Environment]::NewLine

$result = & (Join-Path $PSScriptRoot 'Submit-GitHubPullRequest.ps1') `
    -SourcePath $scoopManifestPath `
    -DestinationRepository $TargetRepository `
    -DestinationPath $destinationPath `
    -BranchName "automation/scoop/$sanitizedVersion" `
    -CommitMessage "Add squid4win $Version" `
    -PullRequestTitle "Add squid4win $Version" `
    -PullRequestBody $pullRequestBody `
    -BaseBranch $BaseBranch `
    -WorkingRoot $WorkingRoot

[PSCustomObject]@{
    Changed = $result.Changed
    PullRequestUrl = $result.PullRequestUrl
    HeadRepository = $result.HeadRepository
    BaseRepository = $result.BaseRepository
    BranchName = $result.BranchName
    ManifestPath = $scoopManifestPath
    DestinationPath = $destinationPath
}
