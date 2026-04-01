[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build',
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json'),
    [string]$HostProfilePath = (Join-Path $PSScriptRoot '..\conan\profiles\msys2-mingw-x64'),
    [string]$BuildProfile = 'default',
    [string]$LockfilePath,
    [string[]]$AdditionalConfigureArgs = @(),
    [ValidateRange(1, 1024)]
    [int]$MakeJobs = 1,
    [switch]$BootstrapOnly,
    [switch]$RefreshLockfile,
    [switch]$Clean,
    [switch]$WithTray,
    [switch]$WithRuntimeDlls,
    [switch]$WithPackagingSupport,
    [switch]$UseTrayEditable
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')
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
$resolvedMetadataPath = Get-AbsolutePath -Path $MetadataPath -BasePath $resolvedRepositoryRoot
$resolvedHostProfilePath = Get-AbsolutePath -Path $HostProfilePath -BasePath $resolvedRepositoryRoot
$metadata = Get-Content -Raw -LiteralPath $resolvedMetadataPath | ConvertFrom-Json
$layout = & (Join-Path $PSScriptRoot 'Resolve-SquidBuildLayout.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $resolvedRepositoryRoot `
    -BuildRoot $resolvedBuildRoot
$bootstrapState = & (Join-Path $PSScriptRoot 'Invoke-ConanRootRecipe.ps1') `
    -Operation Bootstrap `
    -Configuration $Configuration `
    -RepositoryRoot $resolvedRepositoryRoot `
    -BuildRoot $resolvedBuildRoot `
    -HostProfilePath $resolvedHostProfilePath `
    -BuildProfile $BuildProfile `
    -WithTray:$WithTray `
    -WithRuntimeDlls:$WithRuntimeDlls `
    -WithPackagingSupport:$WithPackagingSupport `
    -UseTrayEditable:$UseTrayEditable
if ($BootstrapOnly) {
    $bootstrapState
    return
}
$configurationLabel = $Configuration.ToLowerInvariant()
$installRoot = [string]$layout.StageRoot
$conanOutputRoot = [string]$layout.ConanOutputRoot
$buildLockPath = [string]$layout.BuildLockPath
$repoLockfilePath = [string]$layout.RepoLockfilePath
$lockfileName = Split-Path -Leaf $repoLockfilePath
$resolvedLockfilePath = if ($LockfilePath) {
    Get-AbsolutePath -Path $LockfilePath -BasePath $resolvedRepositoryRoot
} elseif ($UseTrayEditable) {
    Join-Path $conanOutputRoot ("lockfiles\$lockfileName")
} elseif (Test-Path -LiteralPath $repoLockfilePath) {
    $repoLockfilePath
} else {
    Join-Path $conanOutputRoot ("lockfiles\$lockfileName")
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
        if ($UseTrayEditable) {
            Remove-Item `
                -Path (
                    Join-Path $resolvedRepositoryRoot 'conan\recipes\tray-app\build'
                ), (
                    Join-Path $resolvedRepositoryRoot 'conan\recipes\tray-app\source'
                ) `
                -Recurse `
                -Force `
                -ErrorAction SilentlyContinue
        }
    }
    $null = New-Item -ItemType Directory -Path $resolvedBuildRoot, $conanOutputRoot, (Split-Path -Parent $resolvedLockfilePath) -Force
    if ($RefreshLockfile -or -not (Test-Path -LiteralPath $resolvedLockfilePath)) {
        & (Join-Path $PSScriptRoot 'Invoke-ConanRootRecipe.ps1') `
            -Operation LockCreate `
            -Configuration $Configuration `
            -RepositoryRoot $resolvedRepositoryRoot `
            -BuildRoot $resolvedBuildRoot `
            -HostProfilePath $resolvedHostProfilePath `
            -BuildProfile $BuildProfile `
            -LockfilePath $resolvedLockfilePath `
            -SkipBootstrap `
            -WithTray:$WithTray `
            -WithRuntimeDlls:$WithRuntimeDlls `
            -WithPackagingSupport:$WithPackagingSupport `
            -UseTrayEditable:$UseTrayEditable | Out-Null
    }
    & (Join-Path $PSScriptRoot 'Invoke-ConanRootRecipe.ps1') `
        -Operation Source `
        -Configuration $Configuration `
        -RepositoryRoot $resolvedRepositoryRoot `
        -BuildRoot $resolvedBuildRoot `
        -SkipBootstrap `
        -WithTray:$WithTray `
        -WithRuntimeDlls:$WithRuntimeDlls `
        -WithPackagingSupport:$WithPackagingSupport `
        -UseTrayEditable:$UseTrayEditable | Out-Null
    $env:SQUID4WIN_MAKE_JOBS = [string]$MakeJobs
    if ($AdditionalConfigureArgs.Count -gt 0) {
        $env:SQUID4WIN_CONFIGURE_ARGS_JSON = ConvertTo-Json -Compress -InputObject @($AdditionalConfigureArgs)
    } else {
        Remove-Item Env:SQUID4WIN_CONFIGURE_ARGS_JSON -ErrorAction SilentlyContinue
    }
    & (Join-Path $PSScriptRoot 'Invoke-ConanRootRecipe.ps1') `
        -Operation Build `
        -Configuration $Configuration `
        -RepositoryRoot $resolvedRepositoryRoot `
        -BuildRoot $resolvedBuildRoot `
        -HostProfilePath $resolvedHostProfilePath `
        -BuildProfile $BuildProfile `
        -LockfilePath $resolvedLockfilePath `
        -OutputRoot $conanOutputRoot `
        -SkipBootstrap `
        -WithTray:$WithTray `
        -WithRuntimeDlls:$WithRuntimeDlls `
        -WithPackagingSupport:$WithPackagingSupport `
        -UseTrayEditable:$UseTrayEditable | Out-Null
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
