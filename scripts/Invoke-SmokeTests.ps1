[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build',
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json'),
    [string]$BinaryPath
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
function Get-InstallRootFromBinaryPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    $binaryDirectory = Split-Path -Path $Path -Parent
    $binaryDirectoryLeaf = Split-Path -Path $binaryDirectory -Leaf
    if ($binaryDirectoryLeaf -in @('sbin', 'bin')) {
        return Split-Path -Path $binaryDirectory -Parent
    }
    throw "Unable to infer the staged install root from binary path '$Path'. Expected squid.exe under a bin\ or sbin\ directory."
}
$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedBuildRoot = Get-AbsolutePath -Path $BuildRoot -BasePath $resolvedRepositoryRoot
$resolvedMetadataPath = Get-AbsolutePath -Path $MetadataPath -BasePath $resolvedRepositoryRoot
$layout = & (Join-Path $PSScriptRoot 'Resolve-SquidBuildLayout.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $resolvedRepositoryRoot `
    -BuildRoot $resolvedBuildRoot
$metadata = Get-Content -Raw -LiteralPath $resolvedMetadataPath | ConvertFrom-Json
$installRoot = [string]$layout.StageRoot
$runtimeValidationRoot = $installRoot
if ($BinaryPath) {
    $resolvedBinaryPath = Get-AbsolutePath -Path $BinaryPath -BasePath $resolvedRepositoryRoot
    $runtimeValidationRoot = Get-InstallRootFromBinaryPath -Path $resolvedBinaryPath
} else {
    $candidatePaths = @(
        (Join-Path $installRoot 'sbin\squid.exe'),
        (Join-Path $installRoot 'bin\squid.exe')
    )
    $resolvedBinaryPath = $candidatePaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $resolvedBinaryPath) {
        $discoveredBinary = Get-ChildItem -Path $installRoot -Recurse -Filter 'squid.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $discoveredBinary) {
            $resolvedBinaryPath = $discoveredBinary.FullName
        }
    }
}
if (-not $resolvedBinaryPath -or -not (Test-Path -LiteralPath $resolvedBinaryPath)) {
    throw "Unable to find squid.exe under $installRoot."
}
$runtimeDlls = @()
$sourceManifestPath = Join-Path $runtimeValidationRoot 'licenses\source-manifest.json'
if (Test-Path -LiteralPath $sourceManifestPath) {
    $sourceManifest = Get-Content -Raw -LiteralPath $sourceManifestPath | ConvertFrom-Json
    $runtimeDlls = @($sourceManifest.windows_runtime.dlls | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}
$executableDirectories = @(
    Get-ChildItem -LiteralPath $runtimeValidationRoot -Recurse -Filter '*.exe' -File -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty DirectoryName -Unique |
        Sort-Object
)
if ($executableDirectories.Count -eq 0) {
    throw "Expected native executables under $runtimeValidationRoot."
}
if ($runtimeDlls.Count -gt 0) {
    $missingRuntimeDllEntries = [System.Collections.Generic.List[string]]::new()
    foreach ($executableDirectory in $executableDirectories) {
        $missingRuntimeDlls = @(
            foreach ($runtimeDll in $runtimeDlls) {
                if (-not (Test-Path -LiteralPath (Join-Path $executableDirectory $runtimeDll))) {
                    $runtimeDll
                }
            }
        )
        if ($missingRuntimeDlls.Count -gt 0) {
            $relativeDirectory = [System.IO.Path]::GetRelativePath($runtimeValidationRoot, $executableDirectory)
            if ([string]::IsNullOrWhiteSpace($relativeDirectory) -or $relativeDirectory -eq '.') {
                $relativeDirectory = '.'
            }
            $missingRuntimeDllEntries.Add(('{0}: {1}' -f $relativeDirectory, ($missingRuntimeDlls -join ', ')))
        }
    }
    if ($missingRuntimeDllEntries.Count -gt 0) {
        throw "Missing staged runtime DLLs: $($missingRuntimeDllEntries -join '; ')"
    }
}
$versionOutput = (& $resolvedBinaryPath -v 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "squid.exe -v failed with exit code $LASTEXITCODE."
}
if ($versionOutput -notmatch [Regex]::Escape([string]$metadata.version)) {
    throw "Expected squid version $($metadata.version) but version output was: $versionOutput"
}
$securityFileCertgenPath = Join-Path $runtimeValidationRoot 'libexec\security_file_certgen.exe'
if (Test-Path -LiteralPath $securityFileCertgenPath) {
    $securityFileCertgenOutput = (& $securityFileCertgenPath -h 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "security_file_certgen.exe -h failed with exit code $LASTEXITCODE."
    }
    if ($securityFileCertgenOutput -notmatch 'usage:\s+security_file_certgen') {
        throw "security_file_certgen.exe -h returned unexpected output: $securityFileCertgenOutput"
    }
}
$runtimeDllSummary = if ($runtimeDlls.Count -gt 0) {
    $runtimeDlls -join ', '
} else {
    'skipped (no source-manifest runtime DLL contract present)'
}
$summaryLines = @(
    '## Smoke test',
    '',
    ('- Binary: `{0}`' -f $resolvedBinaryPath),
    ('- Install root: `{0}`' -f $runtimeValidationRoot),
    ('- Version: `{0}`' -f $metadata.version),
    ('- Runtime DLLs: `{0}`' -f $runtimeDllSummary),
    ('- Executable directories: `{0}`' -f (($executableDirectories | ForEach-Object { [System.IO.Path]::GetRelativePath($runtimeValidationRoot, $_) }) -join ', '))
)
if (Test-Path -LiteralPath $securityFileCertgenPath) {
    $summaryLines += ('- security_file_certgen: `{0}`' -f $securityFileCertgenPath)
}
if ($env:GITHUB_STEP_SUMMARY) {
    $summaryLines -join [Environment]::NewLine | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
}
Write-Host "Smoke tests passed for $resolvedBinaryPath"
