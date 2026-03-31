[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildProfilePath = (Join-Path $PSScriptRoot '..\config\build-profile.json'),
    [string]$Msys2Root
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

function Get-RootFromToolPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ToolPath,
        [Parameter(Mandatory = $true)]
        [string]$Suffix
    )

    $resolvedToolPath = [System.IO.Path]::GetFullPath($ToolPath).Replace('/', '\')
    $normalizedSuffix = $Suffix.Replace('/', '\')

    if ($resolvedToolPath.EndsWith($normalizedSuffix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $resolvedToolPath.Substring(0, $resolvedToolPath.Length - $normalizedSuffix.Length).TrimEnd('\')
    }

    return $null
}

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedBuildProfilePath = Get-AbsolutePath -Path $BuildProfilePath -BasePath $resolvedRepositoryRoot
$buildProfile = & (Join-Path $PSScriptRoot 'Get-SquidBuildProfile.ps1') -ConfigPath $resolvedBuildProfilePath
$msys2EnvDirectory = ([string]$buildProfile.msys2Env).ToLowerInvariant()
$msys2EnvName = ([string]$buildProfile.msys2Env).ToUpperInvariant()
$candidateRoots = [System.Collections.Generic.List[string]]::new()
$candidateRootSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

function Add-CandidateRoot {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    try {
        $resolvedPath = if ([System.IO.Path]::IsPathRooted($Path)) {
            [System.IO.Path]::GetFullPath($Path)
        } else {
            [System.IO.Path]::GetFullPath((Join-Path $resolvedRepositoryRoot $Path))
        }

        if ($candidateRootSet.Add($resolvedPath)) {
            $null = $candidateRoots.Add($resolvedPath)
        }
    } catch {
    }
}

function Add-DriveRelativeCandidateRoots {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$RelativePaths
    )

    foreach ($drive in @(Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue | Sort-Object Name)) {
        foreach ($relativePath in $RelativePaths) {
            Add-CandidateRoot -Path (Join-Path $drive.Root $relativePath)
        }
    }
}

Add-CandidateRoot -Path $Msys2Root
Add-CandidateRoot -Path $env:MSYS2_ROOT
Add-CandidateRoot -Path $env:MSYS2_LOCATION

if ($buildProfile.PSObject.Properties.Name -contains 'msys2RootHints') {
    foreach ($hint in @($buildProfile.msys2RootHints)) {
        Add-CandidateRoot -Path ([string]$hint)
    }
}

if ($env:RUNNER_TEMP) {
    Add-CandidateRoot -Path (Join-Path $env:RUNNER_TEMP 'msys64')
}

Add-DriveRelativeCandidateRoots -RelativePaths @(
    'msys64',
    'tools\msys64'
)

if ($env:LOCALAPPDATA) {
    Add-CandidateRoot -Path (Join-Path $env:LOCALAPPDATA 'Programs\MSYS2')
}

if ($env:ProgramFiles) {
    Add-CandidateRoot -Path (Join-Path $env:ProgramFiles 'MSYS2')
}

if ($env:ChocolateyInstall) {
    Add-CandidateRoot -Path (Join-Path $env:ChocolateyInstall 'lib\msys2\tools\msys64')
}

if ($HOME) {
    Add-CandidateRoot -Path (Join-Path $HOME 'scoop\apps\msys2\current')
}

$bashCommand = Get-Command bash.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $bashCommand) {
    $bashCommand = Get-Command bash -ErrorAction SilentlyContinue | Select-Object -First 1
}

if ($null -ne $bashCommand) {
    Add-CandidateRoot -Path (Get-RootFromToolPath -ToolPath $bashCommand.Source -Suffix 'usr\bin\bash.exe')
}

$gccCommand = Get-Command gcc.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $gccCommand) {
    $gccCommand = Get-Command gcc -ErrorAction SilentlyContinue | Select-Object -First 1
}

if ($null -ne $gccCommand) {
    Add-CandidateRoot -Path (Get-RootFromToolPath -ToolPath $gccCommand.Source -Suffix "$msys2EnvDirectory\bin\gcc.exe")
}

foreach ($candidateRoot in $candidateRoots) {
    $bashPath = Join-Path $candidateRoot 'usr\bin\bash.exe'
    $pacmanPath = Join-Path $candidateRoot 'usr\bin\pacman.exe'

    if ((Test-Path -LiteralPath $bashPath) -and (Test-Path -LiteralPath $pacmanPath)) {
        $mingwRoot = Join-Path $candidateRoot $msys2EnvDirectory
        $mingwBinPath = Join-Path $mingwRoot 'bin'

        [PSCustomObject]@{
            Root = $candidateRoot
            BashPath = $bashPath
            PacmanPath = $pacmanPath
            MakePath = Join-Path $candidateRoot 'usr\bin\make.exe'
            Msys2Env = $msys2EnvName
            Msys2EnvDirectory = $msys2EnvDirectory
            MingwRoot = $mingwRoot
            MingwBinPath = $mingwBinPath
            GccPath = Join-Path $mingwBinPath 'gcc.exe'
            GppPath = Join-Path $mingwBinPath 'g++.exe'
            ArPath = Join-Path $mingwBinPath 'ar.exe'
            RanlibPath = Join-Path $mingwBinPath 'ranlib.exe'
            StripPath = Join-Path $mingwBinPath 'strip.exe'
        }
        return
    }
}

$searchedRoots = if ($candidateRoots.Count -gt 0) {
    $candidateRoots -join ', '
} else {
    'none'
}

throw "Unable to locate an MSYS2 installation with usr\bin\bash.exe and usr\bin\pacman.exe. Searched: $searchedRoots. Install MSYS2 first or pass -Msys2Root to point at the msys64 root."
