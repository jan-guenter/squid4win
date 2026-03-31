[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Bootstrap', 'LockCreate', 'Source', 'Build')]
    [string]$Operation,
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [string]$BuildRoot = 'build',
    [string]$HostProfilePath = (Join-Path $PSScriptRoot '..\conan\profiles\msys2-mingw-x64'),
    [string]$BuildProfile = 'default',
    [string]$LockfilePath,
    [string]$OutputRoot,
    [switch]$WithTray,
    [switch]$WithRuntimeDlls,
    [switch]$WithPackagingSupport,
    [switch]$SkipBootstrap
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')

function Format-CommandArgument {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Argument
    )

    if ($Argument -match '[\s"]') {
        return '"' + $Argument.Replace('"', '\"') + '"'
    }

    return $Argument
}

function Format-CommandLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    return (@($Command) + @($Arguments | ForEach-Object { Format-CommandArgument -Argument $_ })) -join ' '
}

function Invoke-ConanCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConanExecutable,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$FailureDescription
    )

    Write-Host ('RUN: {0}' -f (Format-CommandLine -Command $ConanExecutable -Arguments $Arguments))
    & $ConanExecutable @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureDescription failed with exit code $LASTEXITCODE."
    }
}

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedHostProfilePath = Get-AbsolutePath -Path $HostProfilePath -BasePath $resolvedRepositoryRoot
$layout = & (Join-Path $PSScriptRoot 'Resolve-SquidBuildLayout.ps1') `
    -Configuration $Configuration `
    -RepositoryRoot $resolvedRepositoryRoot `
    -BuildRoot $BuildRoot
$conanHome = & (Join-Path $PSScriptRoot 'Resolve-ConanHome.ps1') -RepositoryRoot $resolvedRepositoryRoot -EnsureExists
$env:CONAN_HOME = $conanHome
$conanCommand = Get-Command conan -ErrorAction SilentlyContinue
if ($null -eq $conanCommand) {
    throw 'The conan CLI is not available on PATH. Install requirements-automation.txt first.'
}

$conanExecutable = $conanCommand.Source
$resolvedLockfilePath = if ($LockfilePath) {
    Get-AbsolutePath -Path $LockfilePath -BasePath $resolvedRepositoryRoot
} else {
    [string]$layout.RepoLockfilePath
}
$resolvedOutputRoot = if ($OutputRoot) {
    Get-AbsolutePath -Path $OutputRoot -BasePath $resolvedRepositoryRoot
} else {
    [string]$layout.ConanOutputRoot
}
$conanOptionArguments = & (Join-Path $PSScriptRoot 'Get-ConanRecipeOptionArguments.ps1') `
    -RepositoryRoot $resolvedRepositoryRoot `
    -WithTray:$WithTray `
    -WithRuntimeDlls:$WithRuntimeDlls `
    -WithPackagingSupport:$WithPackagingSupport
$state = [PSCustomObject]@{
    Ready = $true
    Operation = $Operation
    RepositoryRoot = $resolvedRepositoryRoot
    BuildRoot = [string]$layout.BuildRoot
    ConanHome = $conanHome
    ConanVersion = (& $conanExecutable --version 2>&1 | Out-String).Trim()
    HostProfilePath = $resolvedHostProfilePath
    BuildProfile = $BuildProfile
    RepoLockfilePath = [string]$layout.RepoLockfilePath
    LockfilePath = $resolvedLockfilePath
    OutputRoot = $resolvedOutputRoot
    StageRoot = [string]$layout.StageRoot
    RecipeOptions = [PSCustomObject]@{
        WithTray = $WithTray.IsPresent
        WithRuntimeDlls = $WithRuntimeDlls.IsPresent
        WithPackagingSupport = $WithPackagingSupport.IsPresent
    }
}

$shouldBootstrapWorkspace = ($Operation -eq 'Bootstrap') -or (-not $SkipBootstrap)
if ($shouldBootstrapWorkspace) {
    Invoke-ConanCommand `
        -ConanExecutable $conanExecutable `
        -Arguments @('profile', 'detect', '--force') `
        -FailureDescription 'conan profile detect'
    & (Join-Path $PSScriptRoot 'Export-ConanWorkspaceRecipes.ps1') -RepositoryRoot $resolvedRepositoryRoot | Out-Null
}

if ($Operation -in @('LockCreate', 'Build') -and -not (Test-Path -LiteralPath $resolvedHostProfilePath)) {
    throw "The Conan host profile '$resolvedHostProfilePath' was not found."
}

switch ($Operation) {
    'Bootstrap' {
        Write-Host 'Conan workspace bootstrap succeeded.'
    }
    'LockCreate' {
        $lockfileDirectory = Split-Path -Parent $resolvedLockfilePath
        $null = New-Item -ItemType Directory -Path $lockfileDirectory -Force
        $conanArguments = @(
            'lock',
            'create',
            $resolvedRepositoryRoot,
            '--profile:host', $resolvedHostProfilePath,
            '--profile:build', $BuildProfile,
            '--lockfile-out', $resolvedLockfilePath,
            '-s:h', "build_type=$Configuration",
            '-s:b', "build_type=$Configuration",
            '--build=missing'
        ) + $conanOptionArguments
        Invoke-ConanCommand `
            -ConanExecutable $conanExecutable `
            -Arguments $conanArguments `
            -FailureDescription 'conan lock create'
        Write-Host "Lockfile refreshed: $resolvedLockfilePath"
    }
    'Source' {
        Invoke-ConanCommand `
            -ConanExecutable $conanExecutable `
            -Arguments @('source', $resolvedRepositoryRoot) `
            -FailureDescription 'conan source'
        Write-Host 'Root Conan recipe sources are ready.'
    }
    'Build' {
        if (-not (Test-Path -LiteralPath $resolvedLockfilePath)) {
            throw "The Conan lockfile '$resolvedLockfilePath' does not exist. Run Invoke-ConanRootRecipe.ps1 -Operation LockCreate first."
        }

        $null = New-Item -ItemType Directory -Path $resolvedOutputRoot, (Split-Path -Parent $resolvedLockfilePath) -Force
        $conanBuildArguments = @(
            'build',
            $resolvedRepositoryRoot,
            '-of', $resolvedOutputRoot,
            '-pr:h', $resolvedHostProfilePath,
            '-pr:b', $BuildProfile,
            '--lockfile', $resolvedLockfilePath,
            '-s:h', "build_type=$Configuration",
            '-s:b', "build_type=$Configuration",
            '--build=missing'
        ) + $conanOptionArguments
        Invoke-ConanCommand `
            -ConanExecutable $conanExecutable `
            -Arguments $conanBuildArguments `
            -FailureDescription 'conan build'
        if (-not (Test-Path -LiteralPath $layout.StageRoot)) {
            throw "The Conan build finished without materializing the staged bundle at $($layout.StageRoot)."
        }

        Write-Host 'Root Conan recipe build completed successfully.'
        Write-Host "Staged bundle root: $($layout.StageRoot)"
        Write-Host "Conan output root: $resolvedOutputRoot"
        Write-Host "Conan home: $conanHome"
        Write-Host "Conan host profile: $resolvedHostProfilePath"
        Write-Host "Conan build profile: $BuildProfile"
        Write-Host "Lockfile: $resolvedLockfilePath"
    }
}

$state
