[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build',
    [string]$BuildProfilePath = (Join-Path $PSScriptRoot '..\config\build-profile.json'),
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json'),
    [string]$Msys2Root,
    [string]$EffectiveProfilePath,
    [string]$LockfilePath,
    [string[]]$AdditionalConfigureArgs = @(),
    [ValidateRange(1, 1024)]
    [int]$MakeJobs = 1,
    [switch]$BootstrapOnly,
    [switch]$AllowMissingPrerequisites,
    [switch]$RefreshLockfile,
    [switch]$Clean
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

function Convert-ToMsysPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $resolvedPath = [System.IO.Path]::GetFullPath($Path)

    if ($resolvedPath -match '^(?<drive>[A-Za-z]):(?<rest>.*)$') {
        $drive = $Matches.drive.ToLowerInvariant()
        $rest = ($Matches.rest -replace '\\', '/')
        return "/$drive$rest"
    }

    return ($resolvedPath -replace '\\', '/')
}

function Convert-ToBashLiteral {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $escapedValue = $Value.Replace('\', '\\').Replace('"', '\"').Replace('$', '\$').Replace('`', '\`')
    return '"' + $escapedValue + '"'
}

function Get-GeneratedScriptPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$FileName,
        [string[]]$PreferredRoots = @(),
        [switch]$Required
    )

    foreach ($preferredRoot in @($PreferredRoots)) {
        if ([string]::IsNullOrWhiteSpace($preferredRoot) -or -not (Test-Path -LiteralPath $preferredRoot)) {
            continue
        }

        $candidatePath = Join-Path $preferredRoot $FileName
        if (Test-Path -LiteralPath $candidatePath) {
            return $candidatePath
        }
    }

    $generatedScriptMatches = @(Get-ChildItem -Path $Root -Recurse -Filter $FileName -File -ErrorAction SilentlyContinue | Sort-Object FullName)
    if ($generatedScriptMatches.Count -eq 0) {
        if ($Required) {
            $searchedRoots = @($PreferredRoots | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            if ($searchedRoots.Count -gt 0) {
                throw "Unable to locate generated Conan script '$FileName' under $Root. Preferred locations: $($searchedRoots -join ', ')"
            }

            throw "Unable to locate generated Conan script '$FileName' under $Root."
        }

        return $null
    }

    return $generatedScriptMatches[0].FullName
}

function Enter-BuildLock {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LockPath,
        [Parameter(Mandatory = $true)]
        [string]$WorkRoot
    )

    $lockDirectory = Split-Path -Parent $LockPath
    $null = New-Item -ItemType Directory -Path $lockDirectory -Force

    try {
        $lockStream = [System.IO.File]::Open(
            $LockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        throw "Another Invoke-SquidBuild.ps1 instance is already using '$WorkRoot'. Wait for it to finish or remove the stale lock at '$LockPath' after verifying that no build is running."
    }

    $lockStream.SetLength(0)
    $lockWriter = [System.IO.StreamWriter]::new($lockStream, [System.Text.Encoding]::ASCII, 1024, $true)
    try {
        $lockWriter.NewLine = "`n"
        $lockWriter.WriteLine("pid=$PID")
        $lockWriter.WriteLine("started_at=$((Get-Date).ToString('o'))")
        $lockWriter.WriteLine("work_root=$WorkRoot")
        $lockWriter.Flush()
        $lockStream.Flush()
    }
    finally {
        $lockWriter.Dispose()
    }

    return $lockStream
}

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedBuildRoot = Get-AbsolutePath -Path $BuildRoot -BasePath $resolvedRepositoryRoot
$resolvedBuildProfilePath = Get-AbsolutePath -Path $BuildProfilePath -BasePath $resolvedRepositoryRoot
$resolvedMetadataPath = Get-AbsolutePath -Path $MetadataPath -BasePath $resolvedRepositoryRoot
$buildProfile = & (Join-Path $PSScriptRoot 'Get-SquidBuildProfile.ps1') -ConfigPath $resolvedBuildProfilePath
$layout = & (Join-Path $PSScriptRoot 'Resolve-SquidBuildLayout.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $resolvedRepositoryRoot `
    -BuildRoot $resolvedBuildRoot `
    -BuildProfilePath $resolvedBuildProfilePath
$toolchainState = & (Join-Path $PSScriptRoot 'Initialize-NativeToolchain.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $resolvedRepositoryRoot `
    -BuildProfilePath $resolvedBuildProfilePath `
    -MetadataPath $resolvedMetadataPath `
    -Msys2Root $Msys2Root `
    -EffectiveProfilePath $EffectiveProfilePath `
    -AllowMissingPrerequisites:$AllowMissingPrerequisites

if ($BootstrapOnly) {
    $toolchainState
    return
}

if (-not $toolchainState.Ready) {
    throw 'Native toolchain bootstrap did not complete successfully. Rerun with -BootstrapOnly -AllowMissingPrerequisites to inspect prerequisites.'
}

$conanCommand = Get-Command conan -ErrorAction SilentlyContinue
if ($null -eq $conanCommand) {
    throw 'The conan CLI is not available on PATH. Install requirements-automation.txt first.'
}

$conanHome = $toolchainState.ConanHome
$bashPath = [string]$toolchainState.BashPath
$metadata = Get-Content -Raw -LiteralPath $resolvedMetadataPath | ConvertFrom-Json
$configurationLabel = $Configuration.ToLowerInvariant()
$downloadsRoot = [string]$layout.DownloadsRoot
$sourcesRoot = [string]$layout.SourcesRoot
$installRoot = [string]$layout.StageRoot
$workRoot = [string]$layout.WorkRoot
$conanOutputRoot = [string]$layout.ConanOutputRoot
$conanGeneratorsRoot = [string]$layout.ConanGeneratorsRoot
$buildLockPath = [string]$layout.BuildLockPath
$bootstrapMarkerPath = Join-Path $workRoot 'squid4win-bootstrap-ran'
$lockfileBaseName = '{0}-{1}.lock' -f [string]$buildProfile.conanProfileName, $configurationLabel
$repoLockfilePath = [string]$layout.RepoLockfilePath
$resolvedLockfilePath = if ($LockfilePath) {
    Get-AbsolutePath -Path $LockfilePath -BasePath $resolvedRepositoryRoot
} elseif (Test-Path -LiteralPath $repoLockfilePath) {
    $repoLockfilePath
} else {
    Join-Path $conanOutputRoot "lockfiles\$lockfileBaseName"
}
$archiveName = Split-Path -Leaf $metadata.assets.source_archive
$archivePath = Join-Path $downloadsRoot $archiveName
$sourceRoot = Join-Path $sourcesRoot "squid-$($metadata.version)"
$buildLock = $null
try {
    $buildLock = Enter-BuildLock -LockPath $buildLockPath -WorkRoot $workRoot

    if ($Clean) {
        Remove-Item -Path $conanOutputRoot, $installRoot, $workRoot -Recurse -Force -ErrorAction SilentlyContinue

        if (Test-Path -LiteralPath $sourceRoot) {
            & $bashPath -lc ("rm -rf $(Convert-ToBashLiteral -Value (Convert-ToMsysPath -Path $sourceRoot))")
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to clean extracted Squid source directory at $sourceRoot."
            }
        }

        Remove-Item -Path $sourceRoot -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $sourceRoot) {
            throw "Clean requested, but the extracted Squid source directory still exists at $sourceRoot."
        }
    }

    $null = New-Item -ItemType Directory -Path $downloadsRoot, $sourcesRoot, $installRoot, $workRoot, $conanOutputRoot, (Split-Path -Parent $resolvedLockfilePath) -Force

    if ([string]::IsNullOrWhiteSpace([string]$toolchainState.EffectiveProfilePath) -or -not (Test-Path -LiteralPath $toolchainState.EffectiveProfilePath)) {
        throw "Expected a generated Conan profile at $($toolchainState.EffectiveProfilePath), but it was not found."
    }

    if ($RefreshLockfile -or -not (Test-Path -LiteralPath $resolvedLockfilePath)) {
        & (Join-Path $PSScriptRoot 'Update-ConanLockfile.ps1') `
            -Configuration $Configuration `
            -RepositoryRoot $resolvedRepositoryRoot `
            -BuildProfilePath $resolvedBuildProfilePath `
            -Msys2Root $toolchainState.Msys2Root `
            -EffectiveProfilePath $toolchainState.EffectiveProfilePath `
            -LockfilePath $resolvedLockfilePath | Out-Null
    }

    $conanInstallArguments = @(
        'install',
        $resolvedRepositoryRoot,
        '-of', $conanOutputRoot,
        '-pr:h', $toolchainState.EffectiveProfilePath,
        '-pr:b', $toolchainState.EffectiveProfilePath,
        '--lockfile', $resolvedLockfilePath,
        '-s:h', "build_type=$Configuration",
        '-s:b', "build_type=$Configuration",
        '--build=missing'
    )

    & $conanCommand.Source @conanInstallArguments
    if ($LASTEXITCODE -ne 0) {
        throw "conan install failed with exit code $LASTEXITCODE."
    }

    $autotoolsScript = Get-GeneratedScriptPath -Root $conanOutputRoot -PreferredRoots @($conanGeneratorsRoot) -FileName 'conanautotoolstoolchain.sh' -Required
    $releaseScript = Get-GeneratedScriptPath -Root $conanOutputRoot -PreferredRoots @($conanGeneratorsRoot) -FileName 'squid-release.sh'

    if (-not (Test-Path -LiteralPath $archivePath)) {
        Invoke-WebRequest -Uri $metadata.assets.source_archive -OutFile $archivePath
    }

    $expectedHash = [string]$metadata.assets.source_archive_sha256
    if ($expectedHash) {
        $actualHash = (Get-FileHash -Path $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash.ToLowerInvariant()) {
            throw "SHA256 mismatch for $archiveName. Expected $expectedHash but found $actualHash."
        }
    }

    if (-not (Test-Path -LiteralPath $sourceRoot)) {
        $archivePathMsys = Convert-ToMsysPath -Path $archivePath
        $sourcesRootMsys = Convert-ToMsysPath -Path $sourcesRoot
        $extractLines = @(
            "export MSYSTEM=$($toolchainState.Msys2Env)",
            'export CHERE_INVOKING=1',
            'source /etc/profile',
            'set -o pipefail',
            "mkdir -p $(Convert-ToBashLiteral -Value $sourcesRootMsys)",
            "tar -xf $(Convert-ToBashLiteral -Value $archivePathMsys) -C $(Convert-ToBashLiteral -Value $sourcesRootMsys)"
        )

        & $bashPath -lc ($extractLines -join '; ')
        if ($LASTEXITCODE -ne 0) {
            throw "tar extraction failed with exit code $LASTEXITCODE."
        }

        if (-not (Test-Path -LiteralPath $sourceRoot)) {
            $fallbackSourceDirectory = Get-ChildItem -Path $sourcesRoot -Directory | Where-Object { $_.Name -like 'squid-*' } | Sort-Object Name -Descending | Select-Object -First 1
            if ($null -ne $fallbackSourceDirectory) {
                $sourceRoot = $fallbackSourceDirectory.FullName
            }
        }
    }

    if (-not (Test-Path -LiteralPath $sourceRoot)) {
        throw "Expected extracted source directory at $sourceRoot."
    }

    $appliedSourcePatches = & (Join-Path $PSScriptRoot 'Apply-SquidSourcePatches.ps1') -SourceRoot $sourceRoot
    foreach ($appliedSourcePatch in @($appliedSourcePatches)) {
        if ($appliedSourcePatch.Applied) {
            Write-Host "Applied Squid source patch: $($appliedSourcePatch.Name)"
        }
    }

    $configureArguments = [System.Collections.Generic.List[string]]::new()
    $configureCacheEntries = [System.Collections.Generic.List[PSCustomObject]]::new()
    $msys2EnvDirectory = ([string]$buildProfile.msys2Env).ToLowerInvariant()
    $pkgConfigBinaryPath = "/$msys2EnvDirectory/bin/pkg-config"
    $pkgConfigLibDir = "/$msys2EnvDirectory/lib/pkgconfig:/$msys2EnvDirectory/share/pkgconfig"

    if ($buildProfile.PSObject.Properties.Name -contains 'configureCache' -and $null -ne $buildProfile.configureCache) {
        foreach ($cacheProperty in $buildProfile.configureCache.PSObject.Properties) {
            $cacheName = [string]$cacheProperty.Name
            $cacheValue = [string]$cacheProperty.Value

            if ([string]::IsNullOrWhiteSpace($cacheName) -or [string]::IsNullOrWhiteSpace($cacheValue)) {
                continue
            }

            $configureCacheEntries.Add([PSCustomObject]@{
                Name = $cacheName
                Value = $cacheValue
            })
        }
    }

    $configureSitePath = $null
    if ($configureCacheEntries.Count -gt 0) {
        $configureSitePath = Join-Path $workRoot 'config.site'
        $configureSiteDirectory = Split-Path -Parent $configureSitePath
        $configureSiteLines = [System.Collections.Generic.List[string]]::new()
        $configureSiteLines.Add('# Generated by Invoke-SquidBuild.ps1 to stabilize native MSYS2/MinGW-w64 configure checks.')

        foreach ($configureCacheEntry in $configureCacheEntries) {
            $configureSiteLines.Add("$($configureCacheEntry.Name)=$($configureCacheEntry.Value)")
        }

        $null = New-Item -ItemType Directory -Path $configureSiteDirectory -Force
        Set-Content -LiteralPath $configureSitePath -Value $configureSiteLines -Encoding ascii
    }

    foreach ($configureArgument in @(
        "--prefix=$(Convert-ToMsysPath -Path $installRoot)",
        "--build=$([string]$buildProfile.hostTriplet)",
        "--host=$([string]$buildProfile.hostTriplet)"
    ) + @($buildProfile.configureArgs) + $AdditionalConfigureArgs) {
        if ([string]::IsNullOrWhiteSpace([string]$configureArgument)) {
            continue
        }

        if (-not $configureArguments.Contains([string]$configureArgument)) {
            $configureArguments.Add([string]$configureArgument)
        }
    }

    $configureArgumentText = ($configureArguments | ForEach-Object { Convert-ToBashLiteral -Value $_ }) -join ' '
    $sourceRootMsys = Convert-ToMsysPath -Path $sourceRoot
    $workRootMsys = Convert-ToMsysPath -Path $workRoot
    $bootstrapMarkerPathMsys = Convert-ToMsysPath -Path $bootstrapMarkerPath
    $bashCommonLines = @(
        "export MSYSTEM=$($toolchainState.Msys2Env)",
        'export CHERE_INVOKING=1',
        'source /etc/profile',
        'set -o pipefail',
        "export PATH=""/$msys2EnvDirectory/bin:/usr/bin:/usr/bin/core_perl:`$PATH"""
    )

    # Keep the reviewed Conan metadata and autotools exports, but do not source
    # the generic Conan build env because it can override the selected MSYS2
    # linker/binutils with tool-requirement binaries.
    foreach ($generatedScript in @($autotoolsScript, $releaseScript)) {
        if ($generatedScript) {
            $bashCommonLines += "source $(Convert-ToBashLiteral -Value (Convert-ToMsysPath -Path $generatedScript))"
        }
    }

    $bashCommonLines += "export PKG_CONFIG=$(Convert-ToBashLiteral -Value $pkgConfigBinaryPath)"
    $bashCommonLines += "export PKG_CONFIG_LIBDIR=$(Convert-ToBashLiteral -Value $pkgConfigLibDir)"
    if ($configureSitePath) {
        $bashCommonLines += "export CONFIG_SITE=$(Convert-ToBashLiteral -Value (Convert-ToMsysPath -Path $configureSitePath))"
    }

    $configureBashLines = @($bashCommonLines)
    $configureBashLines += "mkdir -p $(Convert-ToBashLiteral -Value $workRootMsys)"
    $configureBashLines += "rm -f $(Convert-ToBashLiteral -Value $bootstrapMarkerPathMsys)"
    $configureBashLines += "cd $(Convert-ToBashLiteral -Value $sourceRootMsys)"
    $configureBashLines += (
        'if [ -f ./bootstrap.sh ] && { [ ! -x ./configure ] || [ ! -f ./Makefile.in ] || [ ! -f ./src/Makefile.in ] || [ ! -f ./libltdl/Makefile.in ] || [ ! -f ./cfgaux/ltmain.sh ] || [ ! -f ./cfgaux/compile ] || [ ! -f ./cfgaux/config.guess ] || [ ! -f ./cfgaux/config.sub ] || [ ! -f ./cfgaux/missing ] || [ ! -f ./cfgaux/install-sh ]; }; then ./bootstrap.sh || exit $?; touch ' +
        (Convert-ToBashLiteral -Value $bootstrapMarkerPathMsys) +
        '; fi'
    )
    $configureBashLines += "cd $(Convert-ToBashLiteral -Value $workRootMsys)"
    $configureBashLines += 'echo "Configuring Squid..."'
    $configureBashLines += "$(Convert-ToBashLiteral -Value ($sourceRootMsys + '/configure')) $configureArgumentText || exit `$?"
    $configureBashLines += 'if [ -f confdefs.h ]; then cp confdefs.h squid4win-confdefs.h; fi'

    & $bashPath -lc ($configureBashLines -join '; ')
    if ($LASTEXITCODE -ne 0) {
        throw "Squid configure failed with exit code $LASTEXITCODE."
    }

    if (Test-Path -LiteralPath $bootstrapMarkerPath) {
        $reappliedSourcePatches = & (Join-Path $PSScriptRoot 'Apply-SquidSourcePatches.ps1') -SourceRoot $sourceRoot
        foreach ($reappliedSourcePatch in @($reappliedSourcePatches)) {
            if ($reappliedSourcePatch.Applied) {
                Write-Host "Reapplied Squid source patch after bootstrap: $($reappliedSourcePatch.Name)"
            }
        }

        Remove-Item -LiteralPath $bootstrapMarkerPath -Force -ErrorAction SilentlyContinue
    }

    $autoconfRepair = & (Join-Path $PSScriptRoot 'Repair-SquidAutoconfHeader.ps1') `
        -GeneratedHeaderPath (Join-Path $workRoot 'include\autoconf.h') `
        -ConfdefsPath (Join-Path $workRoot 'squid4win-confdefs.h') `
        -ConfigLogPath (Join-Path $workRoot 'config.log')

    if ($autoconfRepair.RepairedCount -gt 0) {
        Write-Host "Repaired generated autoconf header macros: $($autoconfRepair.RepairedCount)"
    }

    $buildBashLines = @($bashCommonLines)
    $buildBashLines += "cd $(Convert-ToBashLiteral -Value $workRootMsys)"
    $buildBashLines += 'echo "Building Squid..."'
    $buildBashLines += "make -j$MakeJobs || exit `$?"
    $buildBashLines += "cd $(Convert-ToBashLiteral -Value $workRootMsys)"
    $buildBashLines += 'echo "Installing Squid..."'
    $buildBashLines += 'make install || exit $?'

    & $bashPath -lc ($buildBashLines -join '; ')
    if ($LASTEXITCODE -ne 0) {
        throw "MSYS2 build failed with exit code $LASTEXITCODE."
    }

    Write-Host "Build completed successfully."
    Write-Host "Installed files: $installRoot"
    Write-Host "Work root: $workRoot"
    Write-Host "Conan output root: $conanOutputRoot"
    Write-Host "Conan home: $conanHome"
    Write-Host "Conan profile: $($toolchainState.EffectiveProfilePath)"
    Write-Host "Lockfile: $resolvedLockfilePath"
}
finally {
    if ($null -ne $buildLock) {
        $buildLock.Dispose()
        Remove-Item -LiteralPath $buildLockPath -Force -ErrorAction SilentlyContinue
    }
}
