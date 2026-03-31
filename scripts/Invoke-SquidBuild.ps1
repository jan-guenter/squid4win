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
$metadata = Get-Content -Raw -LiteralPath $resolvedMetadataPath | ConvertFrom-Json
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

$configurationLabel = $Configuration.ToLowerInvariant()
$installRoot = [string]$layout.StageRoot
$conanOutputRoot = [string]$layout.ConanOutputRoot
$buildLockPath = [string]$layout.BuildLockPath
$repoLockfilePath = [string]$layout.RepoLockfilePath
$resolvedLockfilePath = if ($LockfilePath) {
    Get-AbsolutePath -Path $LockfilePath -BasePath $resolvedRepositoryRoot
} elseif (Test-Path -LiteralPath $repoLockfilePath) {
    $repoLockfilePath
} else {
    Join-Path $conanOutputRoot "lockfiles\$([string]$buildProfile.conanProfileName)-$configurationLabel.lock"
}
$buildLock = $null
$hadMakeJobs = Test-Path Env:SQUID4WIN_MAKE_JOBS
$previousMakeJobs = $env:SQUID4WIN_MAKE_JOBS
$hadConfigureArgs = Test-Path Env:SQUID4WIN_CONFIGURE_ARGS_JSON
$previousConfigureArgs = $env:SQUID4WIN_CONFIGURE_ARGS_JSON

try {
    $buildLock = Enter-BuildLock -LockPath $buildLockPath -WorkRoot $conanOutputRoot

    if ($Clean) {
        $sourceRoot = Join-Path $resolvedRepositoryRoot "sources\squid-$([string]$metadata.version)"
        Remove-Item -Path $conanOutputRoot, $installRoot, ([string]$layout.WorkRoot), $sourceRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    $null = New-Item -ItemType Directory -Path $resolvedBuildRoot, $conanOutputRoot, (Split-Path -Parent $resolvedLockfilePath) -Force

    & (Join-Path $PSScriptRoot 'Export-ConanWorkspaceRecipes.ps1') -RepositoryRoot $resolvedRepositoryRoot | Out-Null

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

    & $conanCommand.Source source $resolvedRepositoryRoot
    if ($LASTEXITCODE -ne 0) {
        throw "conan source failed with exit code $LASTEXITCODE."
    }

    $conanBuildArguments = @(
        'build',
        $resolvedRepositoryRoot,
        '-of', $conanOutputRoot,
        '-pr:h', $toolchainState.EffectiveProfilePath,
        '-pr:b', $toolchainState.EffectiveProfilePath,
        '--lockfile', $resolvedLockfilePath,
        '-s:h', "build_type=$Configuration",
        '-s:b', "build_type=$Configuration",
        '--build=missing'
    )

    $env:SQUID4WIN_MAKE_JOBS = [string]$MakeJobs
    if ($AdditionalConfigureArgs.Count -gt 0) {
        $env:SQUID4WIN_CONFIGURE_ARGS_JSON = ConvertTo-Json -Compress -InputObject @($AdditionalConfigureArgs)
    } else {
        Remove-Item Env:SQUID4WIN_CONFIGURE_ARGS_JSON -ErrorAction SilentlyContinue
    }

    & $conanCommand.Source @conanBuildArguments
    if ($LASTEXITCODE -ne 0) {
        throw "conan build failed with exit code $LASTEXITCODE."
    }

    if (-not (Test-Path -LiteralPath $installRoot)) {
        throw "The Conan build finished without materializing the staged bundle at $installRoot."
    }

    Write-Host "Build completed successfully."
    Write-Host "Staged bundle root: $installRoot"
    Write-Host "Conan output root: $conanOutputRoot"
    Write-Host "Conan home: $($toolchainState.ConanHome)"
    Write-Host "Conan profile: $($toolchainState.EffectiveProfilePath)"
    Write-Host "Lockfile: $resolvedLockfilePath"
}
finally {
    if ($hadMakeJobs) {
        $env:SQUID4WIN_MAKE_JOBS = $previousMakeJobs
    } else {
        Remove-Item Env:SQUID4WIN_MAKE_JOBS -ErrorAction SilentlyContinue
    }

    if ($hadConfigureArgs) {
        $env:SQUID4WIN_CONFIGURE_ARGS_JSON = $previousConfigureArgs
    } else {
        Remove-Item Env:SQUID4WIN_CONFIGURE_ARGS_JSON -ErrorAction SilentlyContinue
    }

    if ($null -ne $buildLock) {
        $buildLock.Dispose()
        Remove-Item -LiteralPath $buildLockPath -Force -ErrorAction SilentlyContinue
    }
}
