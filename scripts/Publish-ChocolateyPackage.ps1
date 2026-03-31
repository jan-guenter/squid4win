[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$PackageRoot = (Join-Path $PSScriptRoot '..\artifacts\package-managers\chocolatey'),
    [string]$PackageId = 'squid4win',
    [string]$PushSource = 'https://push.chocolatey.org/',
    [string]$QuerySource = 'https://community.chocolatey.org/api/v2/',
    [string]$OutputRoot = (Join-Path $PSScriptRoot '..\artifacts\publication\chocolatey')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')

function Test-ChocolateyPackageVersionPresence {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FeedUrl,
        [Parameter(Mandatory = $true)]
        [string]$PackageId,
        [Parameter(Mandatory = $true)]
        [string]$Version
    )

    if ([string]::IsNullOrWhiteSpace($FeedUrl)) {
        return $false
    }

    $normalizedFeedUrl = if ($FeedUrl.EndsWith('/')) { $FeedUrl } else { "$FeedUrl/" }
    $filter = [Uri]::EscapeDataString("Id eq '$PackageId' and Version eq '$Version'")
    $requestUri = "{0}Packages()?`$filter={1}" -f $normalizedFeedUrl, $filter

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $requestUri -Headers @{ Accept = 'application/atom+xml' }
        $readerSettings = New-Object System.Xml.XmlReaderSettings
        $readerSettings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
        $readerSettings.XmlResolver = $null
        $stringReader = New-Object System.IO.StringReader($response.Content)
        try {
            $xmlReader = $null
            $xmlReader = [System.Xml.XmlReader]::Create($stringReader, $readerSettings)
            try {
                $feed = New-Object System.Xml.XmlDocument
                $feed.XmlResolver = $null
                $feed.Load($xmlReader)
            } finally {
                $xmlReader.Dispose()
            }
        } finally {
            $stringReader.Dispose()
        }

        $namespaceManager = New-Object System.Xml.XmlNamespaceManager($feed.NameTable)
        $namespaceManager.AddNamespace('atom', 'http://www.w3.org/2005/Atom')
        return ($feed.SelectNodes('//atom:entry', $namespaceManager).Count -gt 0)
    } catch {
        Write-Warning "Unable to query Chocolatey feed '$FeedUrl' for $PackageId $Version. The publish step will continue. $($_.Exception.Message)"
        return $false
    }
}

function Publish-ChocolateyPackageToSource {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$Package,
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$ApiKey,
        [Parameter(Mandatory = $true)]
        [string]$QuerySource,
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot
    )

    $isHttpSource = $false
    $sourceUri = $null
    if ([System.Uri]::TryCreate($Source, [System.UriKind]::Absolute, [ref]$sourceUri)) {
        $isHttpSource = ($sourceUri.Scheme -in @('http', 'https'))
    }

    if (-not $isHttpSource) {
        $resolvedSourcePath = Get-AbsolutePath -Path $Source -BasePath $RepositoryRoot
        $null = New-Item -ItemType Directory -Path $resolvedSourcePath -Force
        $destinationPath = Join-Path $resolvedSourcePath $Package.Name
        Copy-Item -LiteralPath $Package.FullName -Destination $destinationPath -Force
        return [PSCustomObject]@{
            AlreadyPublished = $false
            PackagePath = $destinationPath
            PushSource = $Source
            QuerySource = $QuerySource
        }
    }

    $httpClient = New-Object System.Net.Http.HttpClient
    $httpClient.Timeout = [TimeSpan]::FromMinutes(45)
    $httpClient.DefaultRequestHeaders.Add('X-NuGet-ApiKey', $ApiKey)

    try {
        $packageStream = [System.IO.File]::OpenRead($Package.FullName)
        try {
            $multipartContent = $null
            $packageContent = $null
            $multipartContent = New-Object System.Net.Http.MultipartFormDataContent
            $packageContent = New-Object System.Net.Http.StreamContent($packageStream)
            $packageContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('application/octet-stream')
            $multipartContent.Add($packageContent, 'package', $Package.Name)
            $response = $httpClient.PostAsync($Source, $multipartContent).GetAwaiter().GetResult()
            $responseBody = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        } finally {
            if ($multipartContent) {
                $multipartContent.Dispose()
            }

            if ($packageContent) {
                $packageContent.Dispose()
            }

            $packageStream.Dispose()
        }
    } finally {
        $httpClient.Dispose()
    }

    if (($response.StatusCode -eq [System.Net.HttpStatusCode]::Created) -or ($response.StatusCode -eq [System.Net.HttpStatusCode]::Accepted)) {
        return [PSCustomObject]@{
            AlreadyPublished = $false
            PackagePath = $Package.FullName
            PushSource = $Source
            QuerySource = $QuerySource
        }
    }

    if ($response.StatusCode -eq [System.Net.HttpStatusCode]::Conflict) {
        return [PSCustomObject]@{
            AlreadyPublished = $true
            PackagePath = $Package.FullName
            PushSource = $Source
            QuerySource = $QuerySource
        }
    }

    throw "Chocolatey push failed with status code '$([int]$response.StatusCode) $($response.StatusCode)'. $responseBody"
}

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$resolvedPackageRoot = Get-AbsolutePath -Path $PackageRoot -BasePath $repositoryRoot
$resolvedOutputRoot = Get-AbsolutePath -Path $OutputRoot -BasePath $repositoryRoot
$nuspecPath = Join-Path $resolvedPackageRoot "$PackageId.nuspec"

if (-not (Test-Path -LiteralPath $nuspecPath -PathType Leaf)) {
    throw "The Chocolatey nuspec '$nuspecPath' was not found."
}

if ([string]::IsNullOrWhiteSpace($env:CHOCO_API_KEY)) {
    throw 'CHOCO_API_KEY must be set before publishing Chocolatey packages.'
}

Get-Command choco -ErrorAction Stop | Out-Null

$alreadyPublished = Test-ChocolateyPackageVersionPresence -FeedUrl $QuerySource -PackageId $PackageId -Version $Version
if ($alreadyPublished) {
    return [PSCustomObject]@{
        AlreadyPublished = $true
        PackagePath = ''
        PushSource = $PushSource
        QuerySource = $QuerySource
    }
}

$packageOutputRoot = Join-Path $resolvedOutputRoot $Version
$null = New-Item -ItemType Directory -Path $packageOutputRoot -Force

& choco pack $nuspecPath --outputdirectory $packageOutputRoot --limit-output
if ($LASTEXITCODE -ne 0) {
    throw "Chocolatey pack failed for '$nuspecPath'."
}

$package = Get-ChildItem -LiteralPath $packageOutputRoot -Filter "$PackageId*.nupkg" -File |
    Where-Object { $_.Name -notlike '*.symbols.nupkg' } |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1

if (-not $package) {
    throw "Chocolatey pack did not produce a package in '$packageOutputRoot'."
}

$publishResult = Publish-ChocolateyPackageToSource `
    -Package $package `
    -Source $PushSource `
    -ApiKey $env:CHOCO_API_KEY `
    -QuerySource $QuerySource `
    -RepositoryRoot $repositoryRoot

[PSCustomObject]@{
    AlreadyPublished = $publishResult.AlreadyPublished
    PackagePath = $publishResult.PackagePath
    PushSource = $publishResult.PushSource
    QuerySource = $publishResult.QuerySource
}
