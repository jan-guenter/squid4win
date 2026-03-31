[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build',
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json'),
    [string]$BinaryPath,
    [switch]$RequireNotices
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')
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
$runtimeNoticePackages = @()
$trayNoticePackages = @()
$sourceManifestPath = Join-Path $runtimeValidationRoot 'licenses\source-manifest.json'
$noticesPath = Join-Path $runtimeValidationRoot 'THIRD-PARTY-NOTICES.txt'
if (Test-Path -LiteralPath $sourceManifestPath) {
    $sourceManifest = Get-Content -Raw -LiteralPath $sourceManifestPath | ConvertFrom-Json
    $windowsRuntime = if ($sourceManifest.PSObject.Properties['windows_runtime']) {
        $sourceManifest.windows_runtime
    } else {
        $null
    }
    if ($null -ne $windowsRuntime -and $windowsRuntime.PSObject.Properties['dlls']) {
        $runtimeDlls = @($windowsRuntime.dlls | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    }
    if ($null -ne $windowsRuntime -and $windowsRuntime.PSObject.Properties['packages']) {
        $runtimeNoticePackages = @($windowsRuntime.packages | Where-Object { $null -ne $_ })
    }
    if ($sourceManifest.PSObject.Properties['tray']) {
        $traySection = $sourceManifest.tray
        if ($null -ne $traySection -and $traySection.PSObject.Properties['third_party_packages']) {
            $trayNoticePackages = @($traySection.third_party_packages | Where-Object { $null -ne $_ })
        }
    }
    if ($RequireNotices -and -not (Test-Path -LiteralPath $noticesPath)) {
        throw "Expected THIRD-PARTY-NOTICES.txt under $runtimeValidationRoot whenever source-manifest.json is present."
    }
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

    if ($RequireNotices -and $runtimeNoticePackages.Count -eq 0) {
        throw "Expected source-manifest.json to declare packaged notice files for the bundled runtime DLLs."
    }

    if ($RequireNotices) {
        $runtimeNoticeDlls = @(
            $runtimeNoticePackages |
                ForEach-Object {
                    @($_.dlls | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
                } |
                Sort-Object -Unique
        )
        $missingRuntimeNoticeDlls = @($runtimeDlls | Where-Object { $_ -notin $runtimeNoticeDlls })
        $extraRuntimeNoticeDlls = @($runtimeNoticeDlls | Where-Object { $_ -notin $runtimeDlls })
        if ($missingRuntimeNoticeDlls.Count -gt 0 -or $extraRuntimeNoticeDlls.Count -gt 0) {
            throw "Runtime notice metadata does not match the bundled runtime DLL contract. Missing: $($missingRuntimeNoticeDlls -join ', '); Extra: $($extraRuntimeNoticeDlls -join ', ')"
        }
    }
}
function Assert-NoticeFilesPresent {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Packages,
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )
    $missingNoticeFiles = [System.Collections.Generic.List[string]]::new()
    foreach ($package in $Packages) {
        $packageName = if ($package.PSObject.Properties['id']) {
            [string]($package.id)
        } elseif ($package.PSObject.Properties['name']) {
            [string]($package.name)
        } else {
            $Label
        }
        foreach ($noticeFile in @($package.notice_files | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
            $noticePath = Join-Path $Root $noticeFile.Replace('/', '\')
            if (-not (Test-Path -LiteralPath $noticePath)) {
                $missingNoticeFiles.Add(('{0}: {1}' -f $packageName, $noticeFile))
            }
        }
    }
    if ($missingNoticeFiles.Count -gt 0) {
        throw "Missing $Label notice files: $($missingNoticeFiles -join '; ')"
    }
}
if ($RequireNotices -and $runtimeNoticePackages.Count -gt 0) {
    Assert-NoticeFilesPresent -Packages $runtimeNoticePackages -Root $runtimeValidationRoot -Label 'runtime'
}
if ($RequireNotices -and (Test-Path -LiteralPath (Join-Path $runtimeValidationRoot 'System.ServiceProcess.ServiceController.dll')) -and $trayNoticePackages.Count -eq 0) {
    throw "Expected source-manifest.json to declare tray-package notice metadata for the shipped System.ServiceProcess.ServiceController.dll."
}
if ($RequireNotices -and $trayNoticePackages.Count -gt 0) {
    Assert-NoticeFilesPresent -Packages $trayNoticePackages -Root $runtimeValidationRoot -Label 'tray-package'
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
$runtimeNoticeSummary = if ($runtimeNoticePackages.Count -gt 0) {
    ($runtimeNoticePackages | ForEach-Object {
        if ($_.PSObject.Properties['name']) {
            [string]($_.name)
        } elseif ($_.PSObject.Properties['id']) {
            [string]($_.id)
        } else {
            'runtime-package'
        }
    } | Sort-Object) -join ', '
} elseif ($RequireNotices) {
    'required'
} else {
    'not required'
}
$trayNoticeSummary = if ($trayNoticePackages.Count -gt 0) {
    ($trayNoticePackages | ForEach-Object {
        if ($_.PSObject.Properties['id']) {
            [string]($_.id)
        } elseif ($_.PSObject.Properties['name']) {
            [string]($_.name)
        } else {
            'tray-package'
        }
    } | Sort-Object) -join ', '
} elseif ($RequireNotices) {
    'required'
} else {
    'not required'
}
$summaryLines = @(
    '## Smoke test',
    '',
    ('- Binary: `{0}`' -f $resolvedBinaryPath),
    ('- Install root: `{0}`' -f $runtimeValidationRoot),
    ('- Version: `{0}`' -f $metadata.version),
    ('- Runtime DLLs: `{0}`' -f $runtimeDllSummary),
    ('- Runtime notice packages: `{0}`' -f $runtimeNoticeSummary),
    ('- Tray notice packages: `{0}`' -f $trayNoticeSummary),
    ('- Executable directories: `{0}`' -f (($executableDirectories | ForEach-Object { [System.IO.Path]::GetRelativePath($runtimeValidationRoot, $_) }) -join ', '))
)
if (Test-Path -LiteralPath $noticesPath) {
    $summaryLines += ('- Notices bundle: `{0}`' -f $noticesPath)
}
if (Test-Path -LiteralPath $securityFileCertgenPath) {
    $summaryLines += ('- security_file_certgen: `{0}`' -f $securityFileCertgenPath)
}
if ($env:GITHUB_STEP_SUMMARY) {
    $summaryLines -join [Environment]::NewLine | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
}
Write-Host "Smoke tests passed for $resolvedBinaryPath"
