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
    [switch]$WithPackagingSupport
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
$resolvedMetadataPath = Get-AbsolutePath -Path $MetadataPath -BasePath $resolvedRepositoryRoot
$resolvedHostProfilePath = Get-AbsolutePath -Path $HostProfilePath -BasePath $resolvedRepositoryRoot
$metadata = Get-Content -Raw -LiteralPath $resolvedMetadataPath | ConvertFrom-Json
$layout = & (Join-Path $PSScriptRoot 'Resolve-SquidBuildLayout.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $resolvedRepositoryRoot `
    -BuildRoot $resolvedBuildRoot
$conanHome = & (Join-Path $PSScriptRoot 'Resolve-ConanHome.ps1') -RepositoryRoot $resolvedRepositoryRoot -EnsureExists
$conanCommand = Get-Command conan -ErrorAction SilentlyContinue
if ($null -eq $conanCommand) {
    throw 'The conan CLI is not available on PATH. Install requirements-automation.txt first.'
}
if (-not (Test-Path -LiteralPath $resolvedHostProfilePath)) {
    throw "The Conan host profile '$resolvedHostProfilePath' was not found."
}
$env:CONAN_HOME = $conanHome
& $conanCommand.Source profile detect --force
if ($LASTEXITCODE -ne 0) {
    throw "conan profile detect failed with exit code $LASTEXITCODE."
}
& (Join-Path $PSScriptRoot 'Export-ConanWorkspaceRecipes.ps1') -RepositoryRoot $resolvedRepositoryRoot | Out-Null
$conanVersion = (& $conanCommand.Source --version 2>&1 | Out-String).Trim()
$bootstrapState = [PSCustomObject]@{
    Ready = $true
    ConanHome = $conanHome
    ConanVersion = $conanVersion
    HostProfilePath = $resolvedHostProfilePath
    BuildProfile = $BuildProfile
    RecipeOptions = [PSCustomObject]@{
        WithTray = $WithTray.IsPresent
        WithRuntimeDlls = $WithRuntimeDlls.IsPresent
        WithPackagingSupport = $WithPackagingSupport.IsPresent
    }
}
if ($BootstrapOnly) {
    Write-Host 'Conan workspace bootstrap succeeded.'
    $bootstrapState
    return
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
    Join-Path $conanOutputRoot "lockfiles\msys2-mingw-x64-$configurationLabel.lock"
}
$conanOptionArguments = & (Join-Path $PSScriptRoot 'Get-ConanRecipeOptionArguments.ps1') `
    -RepositoryRoot $resolvedRepositoryRoot `
    -WithTray:$WithTray `
    -WithRuntimeDlls:$WithRuntimeDlls `
    -WithPackagingSupport:$WithPackagingSupport
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
    if ($RefreshLockfile -or -not (Test-Path -LiteralPath $resolvedLockfilePath)) {
        & (Join-Path $PSScriptRoot 'Update-ConanLockfile.ps1') `
            -Configuration $Configuration `
            -RepositoryRoot $resolvedRepositoryRoot `
            -HostProfilePath $resolvedHostProfilePath `
            -BuildProfile $BuildProfile `
            -LockfilePath $resolvedLockfilePath `
            -WithTray:$WithTray `
            -WithRuntimeDlls:$WithRuntimeDlls `
            -WithPackagingSupport:$WithPackagingSupport | Out-Null
    }
    & $conanCommand.Source source $resolvedRepositoryRoot
    if ($LASTEXITCODE -ne 0) {
        throw "conan source failed with exit code $LASTEXITCODE."
    }
    $conanBuildArguments = @(
        'build',
        $resolvedRepositoryRoot,
        '-of', $conanOutputRoot,
        '-pr:h', $resolvedHostProfilePath,
        '-pr:b', $BuildProfile,
        '--lockfile', $resolvedLockfilePath,
        '-s:h', "build_type=$Configuration",
        '-s:b', "build_type=$Configuration",
        '--build=missing'
    ) + $conanOptionArguments
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
    Write-Host 'Build completed successfully.'
    Write-Host "Staged bundle root: $installRoot"
    Write-Host "Conan output root: $conanOutputRoot"
    Write-Host "Conan home: $conanHome"
    Write-Host "Conan host profile: $resolvedHostProfilePath"
    Write-Host "Conan build profile: $BuildProfile"
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
