[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildProfilePath = (Join-Path $PSScriptRoot '..\config\build-profile.json'),
    [string]$MetadataPath = (Join-Path $PSScriptRoot '..\conan\squid-release.json'),
    [string]$VersionConfigPath = (Join-Path $PSScriptRoot '..\config\squid-version.json'),
    [string]$ConanDataPath = (Join-Path $PSScriptRoot '..\conandata.yml'),
    [string]$Msys2Root,
    [string]$EffectiveProfilePath,
    [switch]$AllowMissingPrerequisites
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

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedBuildProfilePath = Get-AbsolutePath -Path $BuildProfilePath -BasePath $resolvedRepositoryRoot
$resolvedMetadataPath = Get-AbsolutePath -Path $MetadataPath -BasePath $resolvedRepositoryRoot
$resolvedVersionConfigPath = Get-AbsolutePath -Path $VersionConfigPath -BasePath $resolvedRepositoryRoot
$resolvedConanDataPath = Get-AbsolutePath -Path $ConanDataPath -BasePath $resolvedRepositoryRoot
$buildProfile = & (Join-Path $PSScriptRoot 'Get-SquidBuildProfile.ps1') -ConfigPath $resolvedBuildProfilePath
$configurationLabel = $Configuration.ToLowerInvariant()
$warnings = [System.Collections.Generic.List[string]]::new()
$errors = [System.Collections.Generic.List[string]]::new()
$conanHome = & (Join-Path $PSScriptRoot 'Resolve-ConanHome.ps1') -RepositoryRoot $resolvedRepositoryRoot -EnsureExists -SetEnvironment
$requiredConanHome = Join-Path $resolvedRepositoryRoot '.conan2'
$configuredConanHome = Get-AbsolutePath -Path ([string]$buildProfile.conanHome) -BasePath $resolvedRepositoryRoot
$metadataSynchronized = $true
$toolchain = $null
$effectiveProfile = $null
$installedConanVersion = $null
$pinnedConanVersion = $null
$missingPackages = [System.Collections.Generic.List[string]]::new()
$conanCommand = Get-Command conan -ErrorAction SilentlyContinue
$wixCommand = Get-Command wix -ErrorAction SilentlyContinue
$dotnetCommand = Get-Command dotnet -ErrorAction SilentlyContinue
$resolvedEffectiveProfilePath = if ($EffectiveProfilePath) {
    Get-AbsolutePath -Path $EffectiveProfilePath -BasePath $resolvedRepositoryRoot
} else {
    Join-Path $conanHome "profiles\$([string]$buildProfile.conanProfileName)-$configurationLabel"
}

if ($configuredConanHome -ne $requiredConanHome) {
    $errors.Add("config\build-profile.json must keep conanHome set to .\.conan2.")
}

$requirementsPath = Join-Path $resolvedRepositoryRoot 'requirements-automation.txt'
if (Test-Path -LiteralPath $requirementsPath) {
    $pinnedConanVersionLine = Select-String -Path $requirementsPath -Pattern '^conan==(?<version>\d+\.\d+\.\d+)$' | Select-Object -First 1
    if ($null -ne $pinnedConanVersionLine -and $pinnedConanVersionLine.Matches.Count -gt 0) {
        $pinnedConanVersion = $pinnedConanVersionLine.Matches[0].Groups['version'].Value
    }
}

if ($null -eq $conanCommand) {
    $errors.Add('Conan 2 is required but the conan CLI is not available on PATH.')
} else {
    $conanVersionText = ((& $conanCommand.Source --version) 2>&1 | Out-String).Trim()
    if ($conanVersionText -match 'Conan version (?<version>\d+\.\d+\.\d+)') {
        $installedConanVersion = $Matches.version
    } else {
        $warnings.Add("Unable to parse the installed Conan version from: $conanVersionText")
    }

    if ($installedConanVersion -and ([version]$installedConanVersion -lt [version]'2.0.0')) {
        $errors.Add("Conan 2 is required but found $installedConanVersion.")
    }

    if ($installedConanVersion -and $pinnedConanVersion -and $installedConanVersion -ne $pinnedConanVersion) {
        $warnings.Add("Installed Conan version $installedConanVersion differs from requirements-automation.txt pin $pinnedConanVersion.")
    }

    & $conanCommand.Source remote add conancenter https://center2.conan.io --force *> $null
    if ($LASTEXITCODE -ne 0) {
        $errors.Add('Unable to configure the repo-local conancenter remote.')
    }
}

$metadata = Get-Content -Raw -LiteralPath $resolvedMetadataPath | ConvertFrom-Json
$versionConfig = Get-Content -Raw -LiteralPath $resolvedVersionConfigPath | ConvertFrom-Json
$conanDataContent = if (Test-Path -LiteralPath $resolvedConanDataPath) {
    Get-Content -Raw -LiteralPath $resolvedConanDataPath
} else {
    ''
}
$expectedConanDataContent = @"
sources:
  "$([string]$metadata.version)":
    url: "$([string]$metadata.assets.source_archive)"
    sha256: "$([string]$metadata.assets.source_archive_sha256)"
    strip_root: true

patches:
  "$([string]$metadata.version)":
    - patch_file: "conan/patches/squid/0001-mingw-compat-core-shims.patch"
      patch_description: "Provide foundational MinGW POSIX compatibility shims."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0002-mingw-build-system-flags.patch"
      patch_description: "Adjust Squid build-system flags and MinGW link libraries."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0003-mingw-disk-io-compat.patch"
      patch_description: "Teach Squid DiskIO backends to build and run under MinGW."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0004-mingw-socket-and-ipc-compat.patch"
      patch_description: "Add MinGW-safe Winsock and IPC wrappers."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0005-mingw-win32-runtime-support.patch"
      patch_description: "Expose the Win32 runtime helpers needed by the MinGW port."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0006-mingw-cert-generator-compat.patch"
      patch_description: "Fix MinGW certificate helper and certificate DB support."
      base_path: "."
      strip: 2
    - patch_file: "conan/patches/squid/0007-mingw-main-and-service-integration.patch"
      patch_description: "Wire MinGW into Squid runtime startup and Windows service paths."
      base_path: "."
      strip: 2
"@ + [Environment]::NewLine
$configuredRepository = '{0}/{1}' -f [string]$versionConfig.owner, [string]$versionConfig.repo

if (
    ([string]$metadata.repository -ne $configuredRepository) -or
    ([string]$metadata.version -ne [string]$versionConfig.version) -or
    ([string]$metadata.tag -ne [string]$versionConfig.tag) -or
    ([string]$metadata.assets.source_archive -ne [string]$versionConfig.sourceArchiveUrl) -or
    ($conanDataContent.Trim() -ne $expectedConanDataContent.Trim())
) {
    $metadataSynchronized = $false
    $errors.Add('config\squid-version.json, conan\squid-release.json, and conandata.yml are out of sync. Run scripts\Update-SquidVersion.ps1 to refresh them together.')
}

try {
    $toolchain = & (Join-Path $PSScriptRoot 'Resolve-Msys2Root.ps1') -RepositoryRoot $resolvedRepositoryRoot -BuildProfilePath $resolvedBuildProfilePath -Msys2Root $Msys2Root
} catch {
    if ($AllowMissingPrerequisites) {
        $errors.Add($_.Exception.Message)
    } else {
        throw
    }
}

if ($null -ne $toolchain) {
    foreach ($packageName in @($buildProfile.requiredMsys2Packages)) {
        & $toolchain.PacmanPath -Q ([string]$packageName) *> $null
        if ($LASTEXITCODE -ne 0) {
            $missingPackages.Add([string]$packageName)
        }
    }

    if ($missingPackages.Count -gt 0) {
        $errors.Add("MSYS2 root $($toolchain.Root) is missing required packages: $($missingPackages -join ', ').")
    }

    if ($missingPackages.Count -eq 0) {
        try {
            $effectiveProfile = & (Join-Path $PSScriptRoot 'Write-ConanMsys2Profile.ps1') `
                -Configuration $Configuration `
                -RepositoryRoot $resolvedRepositoryRoot `
                -BuildProfilePath $resolvedBuildProfilePath `
                -Msys2Root $toolchain.Root `
                -OutputPath $resolvedEffectiveProfilePath
        } catch {
            if ($AllowMissingPrerequisites) {
                $errors.Add($_.Exception.Message)
            } else {
                throw
            }
        }
    }
}

$dotnetVersion = if ($null -ne $dotnetCommand) {
    ((& $dotnetCommand.Source --version) 2>&1 | Out-String).Trim()
} else {
    $warnings.Add('dotnet CLI not found; tray app and Windows packaging validation were not attempted.')
    $null
}

$wixVersion = if ($null -ne $wixCommand) {
    ((& $wixCommand.Source --version) 2>&1 | Out-String).Trim()
} else {
    $warnings.Add('WiX CLI not found; MSI packaging is not locally runnable yet.')
    $null
}

$state = [PSCustomObject]@{
    Ready = ($errors.Count -eq 0)
    CanBuildNative = ($errors.Count -eq 0)
    CanPackageInstaller = ($errors.Count -eq 0) -and -not [string]::IsNullOrWhiteSpace($wixVersion)
    ConanHome = $conanHome
    ConanVersion = $installedConanVersion
    PinnedConanVersion = $pinnedConanVersion
    EffectiveProfilePath = if ($null -ne $effectiveProfile) { $effectiveProfile.OutputPath } else { $null }
    PlannedEffectiveProfilePath = $resolvedEffectiveProfilePath
    Msys2Root = if ($null -ne $toolchain) { $toolchain.Root } else { $null }
    BashPath = if ($null -ne $toolchain) { $toolchain.BashPath } else { $null }
    PacmanPath = if ($null -ne $toolchain) { $toolchain.PacmanPath } else { $null }
    Msys2Env = if ($null -ne $toolchain) { $toolchain.Msys2Env } else { ([string]$buildProfile.msys2Env).ToUpperInvariant() }
    MissingMsys2Packages = @($missingPackages)
    SuggestedMsys2PackageInstallCommand = if (($null -ne $toolchain) -and ($missingPackages.Count -gt 0)) {
        '& "{0}" -S --needed {1}' -f $toolchain.PacmanPath, ($missingPackages -join ' ')
    } else {
        $null
    }
    MetadataSynchronized = $metadataSynchronized
    DotNetVersion = $dotnetVersion
    WixVersion = $wixVersion
    Warnings = @($warnings)
    Errors = @($errors)
}

Write-Host "Native toolchain ready: $($state.Ready)"
Write-Host "Conan home: $($state.ConanHome)"
Write-Host "Conan version: $(if ($state.ConanVersion) { $state.ConanVersion } else { 'missing' })"
Write-Host "MSYS2 root: $(if ($state.Msys2Root) { $state.Msys2Root } else { 'missing' })"
Write-Host "Effective Conan profile: $(if ($state.EffectiveProfilePath) { $state.EffectiveProfilePath } else { 'not generated yet' })"

if ($missingPackages.Count -gt 0) {
    Write-Host "Missing MSYS2 packages: $($missingPackages -join ', ')"
    if ($state.SuggestedMsys2PackageInstallCommand) {
        Write-Host "Suggested pacman command: $($state.SuggestedMsys2PackageInstallCommand)"
    }
}

if ($warnings.Count -gt 0) {
    Write-Host "Warnings: $($warnings -join '; ')"
}

if ($errors.Count -gt 0 -and -not $AllowMissingPrerequisites) {
    throw ($errors -join [Environment]::NewLine)
}

$state
