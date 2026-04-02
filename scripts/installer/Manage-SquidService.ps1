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
$serviceNameHelperPath = @(
    (Join-Path $PSScriptRoot 'Assert-SquidServiceName.ps1'),
    (Join-Path $PSScriptRoot '..\Assert-SquidServiceName.ps1')
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $serviceNameHelperPath) {
    throw "Unable to locate Assert-SquidServiceName.ps1 next to $PSCommandPath or in its parent directory."
}
. $serviceNameHelperPath

function Get-SquidServiceRegistryPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return (Join-Path 'HKLM:\SOFTWARE\squid-cache.org\Squid' $Name)
}

function Get-SquidServiceCommandLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath
    )

    $normalizedConfigPath = Get-NormalizedPath -Path $ConfigPath
    if ($normalizedConfigPath -match '\s') {
        throw "Squid Windows service command lines do not support config paths containing whitespace because upstream service startup splits the registry CommandLine on whitespace. Use an install root without spaces."
    }

    return "-f $normalizedConfigPath"
}

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

    return $null -ne (Get-SquidServiceInstance -Name $Name)
}

function Get-SquidServiceController {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return Get-Service -Name $Name -ErrorAction SilentlyContinue
}

function Get-SquidServiceInstance {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $escapedName = $Name.Replace("'", "''")
    return Get-CimInstance -ClassName Win32_Service -Filter "Name = '$escapedName'" -ErrorAction SilentlyContinue
}

function Wait-SquidServiceRegistrationState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [bool]$Present,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if ((Test-SquidServiceRegistration -Name $Name) -eq $Present) {
            return
        }

        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    $expectedState = if ($Present) { 'visible' } else { 'absent' }
    throw "The Squid Windows service '$Name' did not become $expectedState within $TimeoutSeconds seconds."
}

function Stop-SquidServiceIfRunning {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [int]$TimeoutSeconds = 30
    )

    $service = Get-SquidServiceController -Name $Name
    if ($null -eq $service) {
        return $false
    }

    try {
        $service.Refresh()
        if ($service.Status -eq [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
            return $false
        }

        if ($service.Status -eq [System.ServiceProcess.ServiceControllerStatus]::StopPending) {
            $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds($TimeoutSeconds))
            return $true
        }

        if (-not $service.CanStop) {
            throw "The Squid Windows service '$Name' is registered but Windows reported that it cannot be stopped."
        }

        if ($PSCmdlet.ShouldProcess($Name, 'Stop Squid Windows service')) {
            Stop-Service -Name $Name -ErrorAction Stop
        }
        $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds($TimeoutSeconds))
        return $true
    }
    finally {
        if ($service -is [System.IDisposable]) {
            $service.Dispose()
        }
    }
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

function Set-SquidServiceRegistryConfiguration {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath
    )

    $normalizedConfigPath = Get-NormalizedPath -Path $ConfigPath
    $normalizedCommandLine = Get-SquidServiceCommandLine -ConfigPath $normalizedConfigPath
    $vendorRegistryPath = 'HKLM:\SOFTWARE\squid-cache.org'
    $productRegistryPath = Join-Path $vendorRegistryPath 'Squid'
    $registryPath = Get-SquidServiceRegistryPath -Name $Name
    if (-not $PSCmdlet.ShouldProcess($registryPath, "Store Squid service registry values for '$Name'")) {
        return
    }

    foreach ($path in @($vendorRegistryPath, $productRegistryPath, $registryPath)) {
        if (-not (Test-Path -LiteralPath $path)) {
            $null = New-Item -Path $path -Force
        }
    }
    New-ItemProperty -Path $registryPath -Name 'ConfigFile' -PropertyType String -Value $normalizedConfigPath -Force | Out-Null
    New-ItemProperty -Path $registryPath -Name 'CommandLine' -PropertyType String -Value $normalizedCommandLine -Force | Out-Null

    $registeredValues = Get-ItemProperty -Path $registryPath -Name 'ConfigFile', 'CommandLine'
    if ($registeredValues.ConfigFile -ne $normalizedConfigPath) {
        throw "The Squid service registry entry '$registryPath' did not retain the expected ConfigFile value '$normalizedConfigPath'."
    }
    if ($registeredValues.CommandLine -ne $normalizedCommandLine) {
        throw "The Squid service registry entry '$registryPath' did not retain the expected CommandLine value '$normalizedCommandLine'."
    }

    Write-Host "Stored Squid service registry values for '$Name' at $registryPath."
}

function Remove-SquidServiceRegistryConfiguration {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $registryPath = Get-SquidServiceRegistryPath -Name $Name
    if (-not (Test-Path -LiteralPath $registryPath)) {
        return $false
    }
    if (-not $PSCmdlet.ShouldProcess($registryPath, "Remove Squid service registry values for '$Name'")) {
        return $false
    }

    Remove-Item -LiteralPath $registryPath -Recurse -Force
    Write-Host "Removed Squid service registry association at $registryPath."
    return $true
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
$resolvedServiceName = Assert-SquidServiceName -Name $ServiceName
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

        if (Test-SquidServiceRegistration -Name $resolvedServiceName) {
            Write-Host "Removing existing service registration for $resolvedServiceName before reinstalling it."
            if (Stop-SquidServiceIfRunning -Name $resolvedServiceName) {
                Write-Host "Stopped Squid Windows service '$resolvedServiceName' before removing the existing registration."
            }
            Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-r', '-n', $resolvedServiceName)
            Wait-SquidServiceRegistrationState -Name $resolvedServiceName -Present $false
            # Squid does not remove the named service registry subtree or CommandLine
            # value on uninstall.
            $null = Remove-SquidServiceRegistryConfiguration -Name $resolvedServiceName
        }

        Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-k', 'parse', '-f', $configPath)
        Write-Host "Initializing Squid cache directories with squid.exe -z before service registration."
        Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-z', '-f', $configPath)
        try {
            Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-i', '-n', $resolvedServiceName, '-f', $configPath)
            Wait-SquidServiceRegistrationState -Name $resolvedServiceName -Present $true
            Set-SquidServiceRegistryConfiguration -Name $resolvedServiceName -ConfigPath $configPath
        }
        catch {
            $originalErrorMessage = $_.Exception.Message
            try {
                if (Test-SquidServiceRegistration -Name $resolvedServiceName) {
                    if (Stop-SquidServiceIfRunning -Name $resolvedServiceName) {
                        Write-Host "Stopped partially installed Squid Windows service '$resolvedServiceName' during rollback."
                    }
                    Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-r', '-n', $resolvedServiceName)
                    Wait-SquidServiceRegistrationState -Name $resolvedServiceName -Present $false
                }
                $null = Remove-SquidServiceRegistryConfiguration -Name $resolvedServiceName
            }
            catch {
                throw "Failed to install Squid Windows service '$resolvedServiceName' cleanly. Original error: $originalErrorMessage Cleanup error: $($_.Exception.Message)"
            }

            throw
        }
        Write-Host "Installed Squid Windows service '$resolvedServiceName' using $configPath."
    }

    'Uninstall' {
        if (-not (Test-SquidServiceRegistration -Name $resolvedServiceName)) {
            $null = Remove-SquidServiceRegistryConfiguration -Name $resolvedServiceName
            Write-Host "Squid Windows service '$resolvedServiceName' is already absent."
            return
        }

        if (Stop-SquidServiceIfRunning -Name $resolvedServiceName) {
            Write-Host "Stopped Squid Windows service '$resolvedServiceName' before removal."
        }
        Invoke-SquidCommand -ExecutablePath $resolvedSquidExecutable -Arguments @('-r', '-n', $resolvedServiceName)
        Wait-SquidServiceRegistrationState -Name $resolvedServiceName -Present $false
        $null = Remove-SquidServiceRegistryConfiguration -Name $resolvedServiceName
        Write-Host "Removed Squid Windows service '$resolvedServiceName'."
    }
}
