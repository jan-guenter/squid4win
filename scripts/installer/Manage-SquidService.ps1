[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Install', 'Uninstall')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,
    [string]$ServiceName = 'Squid4Win'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NormalizedPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Resolve-SquidExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    foreach ($candidate in @(
            (Join-Path $Root 'sbin\squid.exe'),
            (Join-Path $Root 'bin\squid.exe')
        )) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "Unable to find squid.exe under $Root."
}

function Test-SquidServiceRegistration {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return $null -ne (Get-Service -Name $Name -ErrorAction SilentlyContinue)
}

function Initialize-SquidConfiguration {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $configDirectory = Join-Path $Root 'etc'
    $configPath = Join-Path $configDirectory 'squid.conf'
    if (Test-Path -LiteralPath $configPath) {
        return $configPath
    }

    $templatePath = Join-Path $configDirectory 'squid.conf.template'
    if (-not (Test-Path -LiteralPath $templatePath)) {
        throw "Unable to create squid.conf because the template was not found at $templatePath."
    }

    $normalizedInstallRoot = (Get-NormalizedPath -Path $Root).Replace('\', '/')
    $templateContent = Get-Content -Raw -LiteralPath $templatePath
    $resolvedContent = $templateContent.Replace('__SQUID4WIN_INSTALL_ROOT__', $normalizedInstallRoot)
    Set-Content -LiteralPath $configPath -Value $resolvedContent -Encoding ascii
    return $configPath
}

function Invoke-SquidCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $ExecutablePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "squid.exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

$resolvedInstallRoot = Get-NormalizedPath -Path $InstallRoot
$resolvedSquidExecutable = Resolve-SquidExecutable -Root $resolvedInstallRoot

switch ($Action) {
    'Install' {
        foreach ($directoryPath in @(
                (Join-Path $resolvedInstallRoot 'etc'),
                (Join-Path $resolvedInstallRoot 'var\cache'),
                (Join-Path $resolvedInstallRoot 'var\logs'),
                (Join-Path $resolvedInstallRoot 'var\run')
            )) {
            $null = New-Item -ItemType Directory -Path $directoryPath -Force
        }

        $configPath = Initialize-SquidConfiguration -Root $resolvedInstallRoot

        if (Test-SquidServiceRegistration -Name $ServiceName) {
            Write-Host "Removing existing service registration for $ServiceName before reinstalling it."
            Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-r', '-n', $ServiceName)
        }

        Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-k', 'parse', '-f', $configPath)
        Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-z', '-f', $configPath)
        Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-i', '-n', $ServiceName, '-f', $configPath)

        if (-not (Test-SquidServiceRegistration -Name $ServiceName)) {
            throw "The Squid Windows service '$ServiceName' was not visible after installation."
        }

        Write-Host "Installed Squid Windows service '$ServiceName' using $configPath."
    }

    'Uninstall' {
        if (-not (Test-SquidServiceRegistration -Name $ServiceName)) {
            Write-Host "Squid Windows service '$ServiceName' is already absent."
            return
        }

        Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-r', '-n', $ServiceName)
        Write-Host "Removed Squid Windows service '$ServiceName'."
    }
}
