[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [string]$BuildRoot = 'build',
    [string]$ArtifactRoot = (Join-Path $PSScriptRoot '..\artifacts'),
    [string]$ServiceName,
    [string]$ServiceNamePrefix = 'Squid4WinRunner',
    [string]$InstallRoot,
    [int]$ServiceTimeoutSeconds = 60,
    [switch]$AllowNonRunnerExecution
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')
. (Join-Path $PSScriptRoot 'Assert-SquidServiceName.ps1')

function Get-NormalizedPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Test-IsAdministrator {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($currentIdentity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-RunnerValidationPrerequisite {
    param(
        [switch]$AllowNonRunnerExecution
    )

    if (-not $IsWindows) {
        throw 'Service runner validation is only supported on Windows.'
    }

    if (-not $AllowNonRunnerExecution -and $env:GITHUB_ACTIONS -ne 'true') {
        throw 'Service runner validation performs MSI install and Windows service control. Run it on an isolated GitHub Actions runner or pass -AllowNonRunnerExecution only when the environment is explicitly dedicated to this validation.'
    }

    if (-not (Test-IsAdministrator)) {
        throw 'Service runner validation requires administrator privileges because it installs an MSI and controls a Windows service.'
    }
}

function Get-ValidationToken {
    $segments = [System.Collections.Generic.List[string]]::new()
    foreach ($value in @($env:GITHUB_RUN_ID, $env:GITHUB_RUN_ATTEMPT, $env:GITHUB_JOB, [Guid]::NewGuid().ToString('N').Substring(0, 8))) {
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $segments.Add([string]$value)
        }
    }

    $token = (($segments -join '-') -replace '[^A-Za-z0-9-]', '-') -replace '-{2,}', '-'
    $token = $token.Trim('-')
    if ([string]::IsNullOrWhiteSpace($token)) {
        $token = [Guid]::NewGuid().ToString('N').Substring(0, 16)
    }

    if ($token.Length -gt 48) {
        $token = $token.Substring(0, 48).TrimEnd('-')
    }

    return $token
}

function Get-ValidationServiceName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prefix,
        [Parameter(Mandatory = $true)]
        [string]$Token
    )

    $normalizedPrefix = ($Prefix -replace '[^A-Za-z0-9]', '')
    if ([string]::IsNullOrWhiteSpace($normalizedPrefix)) {
        throw 'The service name prefix must contain at least one letter or number.'
    }

    $minimumTokenLength = 8
    $maxNameLength = 32
    $maxPrefixLength = $maxNameLength - $minimumTokenLength
    if ($normalizedPrefix.Length -gt $maxPrefixLength) {
        throw "The service name prefix '$Prefix' is too long. Leave at least $minimumTokenLength characters for the unique suffix so the final Squid service name stays within Squid's 32-character limit."
    }

    $maxTokenLength = $maxNameLength - $normalizedPrefix.Length
    $normalizedToken = ($Token -replace '[^A-Za-z0-9]', '')
    if ([string]::IsNullOrWhiteSpace($normalizedToken)) {
        $normalizedToken = [Guid]::NewGuid().ToString('N')
    }
    if ($normalizedToken.Length -gt $maxTokenLength) {
        $normalizedToken = $normalizedToken.Substring($normalizedToken.Length - $maxTokenLength)
    }

    return Assert-SquidServiceName -Name ('{0}{1}' -f $normalizedPrefix, $normalizedToken) -ParameterName 'GeneratedServiceName'
}

function Get-SquidServiceController {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return Get-Service -Name $Name -ErrorAction SilentlyContinue
}

function Test-SquidServiceRegistration {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return $null -ne (Get-SquidServiceInstance -Name $Name)
}

function Wait-SquidServiceRegistrationState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [bool]$Present,
        [int]$TimeoutSeconds = 60
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

function Wait-SquidServiceStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [System.ServiceProcess.ServiceControllerStatus]$DesiredStatus,
        [int]$TimeoutSeconds = 60
    )

    $service = Get-SquidServiceController -Name $Name
    if ($null -eq $service) {
        throw "The Squid Windows service '$Name' is not registered."
    }

    try {
        $service.WaitForStatus($DesiredStatus, [TimeSpan]::FromSeconds($TimeoutSeconds))
        $service.Refresh()
        if ($service.Status -ne $DesiredStatus) {
            throw "The Squid Windows service '$Name' did not reach status '$DesiredStatus' within $TimeoutSeconds seconds."
        }
    }
    finally {
        if ($service -is [System.IDisposable]) {
            $service.Dispose()
        }
    }
}

function Stop-SquidServiceIfPresent {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [int]$TimeoutSeconds = 60
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
            Wait-SquidServiceStatus -Name $Name -DesiredStatus ([System.ServiceProcess.ServiceControllerStatus]::Stopped) -TimeoutSeconds $TimeoutSeconds
            return $true
        }

        if (-not $service.CanStop) {
            throw "The Squid Windows service '$Name' is registered but Windows reported that it cannot be stopped."
        }

        if ($PSCmdlet.ShouldProcess($Name, 'Stop Squid Windows service')) {
            Stop-Service -Name $Name -ErrorAction Stop
        }
        Wait-SquidServiceStatus -Name $Name -DesiredStatus ([System.ServiceProcess.ServiceControllerStatus]::Stopped) -TimeoutSeconds $TimeoutSeconds
        return $true
    }
    finally {
        if ($service -is [System.IDisposable]) {
            $service.Dispose()
        }
    }
}

function Invoke-MsiExec {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$LogPath,
        [int[]]$AcceptableExitCodes = @(0)
    )

    $resolvedLogPath = $null
    $effectiveArguments = @($Arguments)
    if ($LogPath) {
        $resolvedLogPath = Get-NormalizedPath -Path $LogPath
        $logDirectory = Split-Path -Parent $resolvedLogPath
        if ($logDirectory) {
            $null = New-Item -ItemType Directory -Path $logDirectory -Force
        }
        $effectiveArguments += @('/L*V', $resolvedLogPath)
    }

    $process = Start-Process -FilePath 'msiexec.exe' -ArgumentList $effectiveArguments -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -notin $AcceptableExitCodes) {
        $logHint = if ($resolvedLogPath) { " See $resolvedLogPath." } else { '' }
        throw "msiexec.exe $($effectiveArguments -join ' ') failed with exit code $($process.ExitCode).$logHint"
    }

    return $process.ExitCode
}

function Get-SquidServiceInstance {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $escapedName = $Name.Replace("'", "''")
    return Get-CimInstance -ClassName Win32_Service -Filter "Name = '$escapedName'" -ErrorAction SilentlyContinue
}

function Invoke-ServiceHelperUninstall {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $serviceHelperPath = Join-Path $Root 'installer\svc.ps1'
    if (-not (Test-Path -LiteralPath $serviceHelperPath)) {
        return $false
    }

    & $serviceHelperPath -Action Uninstall -InstallRoot $Root -ServiceName $Name
    return $true
}

function Invoke-BestEffortCleanup {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$PackagePath,
        [bool]$InstallAttempted,
        [bool]$UninstallCompleted,
        [int]$TimeoutSeconds = 60
    )

    $actions = [System.Collections.Generic.List[string]]::new()
    $issues = [System.Collections.Generic.List[string]]::new()

    if ($InstallAttempted -and -not $UninstallCompleted -and (Test-Path -LiteralPath $PackagePath)) {
        try {
            Invoke-MsiExec -Arguments @('/x', $PackagePath, '/qn', '/norestart') -AcceptableExitCodes @(0, 1605, 1614) | Out-Null
            $actions.Add('Requested MSI uninstall during cleanup.')
        }
        catch {
            $issues.Add("MSI cleanup uninstall failed: $($_.Exception.Message)")
        }
    }

    if (Test-SquidServiceRegistration -Name $Name) {
        try {
            if (Stop-SquidServiceIfPresent -Name $Name -TimeoutSeconds $TimeoutSeconds) {
                $actions.Add("Stopped leftover service '$Name'.")
            }
        }
        catch {
            $issues.Add("Stopping leftover service '$Name' failed: $($_.Exception.Message)")
        }
    }

    if ((Test-SquidServiceRegistration -Name $Name) -and (Test-Path -LiteralPath $Root)) {
        try {
            if (Invoke-ServiceHelperUninstall -Root $Root -Name $Name) {
                Wait-SquidServiceRegistrationState -Name $Name -Present $false -TimeoutSeconds $TimeoutSeconds
                $actions.Add("Invoked installer helper cleanup for '$Name'.")
            }
        }
        catch {
            $issues.Add("Installer helper cleanup for '$Name' failed: $($_.Exception.Message)")
        }
    }

    if (Test-SquidServiceRegistration -Name $Name) {
        try {
            $null = Stop-SquidServiceIfPresent -Name $Name -TimeoutSeconds $TimeoutSeconds
            $scProcess = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\sc.exe') -ArgumentList @('delete', $Name) -Wait -PassThru -NoNewWindow
            if ($scProcess.ExitCode -ne 0) {
                throw "sc.exe delete returned exit code $($scProcess.ExitCode)."
            }

            Wait-SquidServiceRegistrationState -Name $Name -Present $false -TimeoutSeconds $TimeoutSeconds
            $actions.Add("Deleted leftover service '$Name' with sc.exe.")
        }
        catch {
            $issues.Add("Final service deletion for '$Name' failed: $($_.Exception.Message)")
        }
    }

    if (Test-SquidServiceRegistration -Name $Name) {
        $issues.Add("The Squid Windows service '$Name' is still registered after cleanup.")
    }

    if (Test-Path -LiteralPath $Root) {
        try {
            Remove-Item -LiteralPath $Root -Recurse -Force
            $actions.Add("Removed isolated install root '$Root'.")
        }
        catch {
            $issues.Add("Removing isolated install root '$Root' failed: $($_.Exception.Message)")
        }
    }

    return [PSCustomObject]@{
        Actions = @($actions)
        Issues = @($issues)
        Clean = $issues.Count -eq 0
    }
}

Test-RunnerValidationPrerequisite -AllowNonRunnerExecution:$AllowNonRunnerExecution

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path
$resolvedArtifactBaseRoot = Get-AbsolutePath -Path $ArtifactRoot -BasePath $resolvedRepositoryRoot
$validationToken = Get-ValidationToken
$resolvedServiceName = if ($ServiceName) {
    Assert-SquidServiceName -Name $ServiceName
} else {
    Get-ValidationServiceName -Prefix $ServiceNamePrefix -Token $validationToken
}
$resolvedValidationRoot = Join-Path $resolvedArtifactBaseRoot "service-validation\$validationToken"
$resolvedInstallRoot = if ($InstallRoot) {
    Get-NormalizedPath -Path (Get-AbsolutePath -Path $InstallRoot -BasePath $resolvedRepositoryRoot)
} else {
    Join-Path $resolvedValidationRoot 'installed'
}

$stageResult = $null
$buildResult = $null
$resolvedMsiPath = $null
$serviceCommandLine = $null
$cleanupResult = $null
$caughtError = $null
$installAttempted = $false
$uninstallCompleted = $false

try {
    $null = New-Item -ItemType Directory -Path $resolvedValidationRoot -Force
    if (Test-Path -LiteralPath $resolvedInstallRoot) {
        Remove-Item -LiteralPath $resolvedInstallRoot -Recurse -Force
    }

    $stageResult = & (Join-Path $PSScriptRoot 'Stage-ReleasePayload.ps1') `
        -Configuration $Configuration `
        -RepositoryRoot $resolvedRepositoryRoot `
        -BuildRoot $BuildRoot `
        -ArtifactRoot $resolvedValidationRoot `
        -RequireTray `
        -RequireNotices
    $stagedPayloadRoot = Get-NormalizedPath -Path ([string]$stageResult.InstallPayloadRoot)
    $stagedServiceHelperPath = Join-Path $stagedPayloadRoot 'installer\svc.ps1'
    if (-not (Test-Path -LiteralPath $stagedServiceHelperPath)) {
        throw "The staged payload '$stagedPayloadRoot' is missing '$stagedServiceHelperPath'."
    }
    $stagedServiceHelperDependencyPath = Join-Path $stagedPayloadRoot 'installer\Assert-SquidServiceName.ps1'
    if (-not (Test-Path -LiteralPath $stagedServiceHelperDependencyPath)) {
        throw "The staged payload '$stagedPayloadRoot' is missing '$stagedServiceHelperDependencyPath'."
    }
    $stagedConfigTemplatePath = Join-Path $stagedPayloadRoot 'etc\squid.conf.template'
    if (-not (Test-Path -LiteralPath $stagedConfigTemplatePath)) {
        throw "The staged payload '$stagedPayloadRoot' is missing '$stagedConfigTemplatePath'."
    }
    $stagedConfigPath = Join-Path $stagedPayloadRoot 'etc\squid.conf'
    if (Test-Path -LiteralPath $stagedConfigPath) {
        throw "The staged payload already contains '$stagedConfigPath'. The installer contract requires shipping squid.conf.template and materializing squid.conf during install."
    }

    $buildResult = & (Join-Path $PSScriptRoot 'Build-Installer.ps1') `
        -Configuration $Configuration `
        -RepositoryRoot $resolvedRepositoryRoot `
        -InstallerPayloadRoot $stagedPayloadRoot `
        -ArtifactRoot $resolvedValidationRoot `
        -ServiceName $resolvedServiceName

    $resolvedMsiPath = Get-NormalizedPath -Path ([string]$buildResult.MsiPath)
    $installAttempted = $true
    Write-Host "Installing $resolvedMsiPath to $resolvedInstallRoot using temporary service name '$resolvedServiceName'."
    $installLogPath = Join-Path $resolvedValidationRoot 'msi-install.log'
    Invoke-MsiExec -Arguments @('/i', $resolvedMsiPath, '/qn', '/norestart', "INSTALLFOLDER=$resolvedInstallRoot") -LogPath $installLogPath | Out-Null

    $expectedPaths = @(
        (Join-Path $resolvedInstallRoot 'installer\svc.ps1'),
        (Join-Path $resolvedInstallRoot 'installer\Assert-SquidServiceName.ps1'),
        (Join-Path $resolvedInstallRoot 'etc\squid.conf'),
        (Join-Path $resolvedInstallRoot 'var\cache'),
        (Join-Path $resolvedInstallRoot 'var\logs'),
        (Join-Path $resolvedInstallRoot 'var\run')
    )
    foreach ($expectedPath in $expectedPaths) {
        if (-not (Test-Path -LiteralPath $expectedPath)) {
            throw "Expected installed path '$expectedPath' was not created by the MSI."
        }
    }

    Wait-SquidServiceRegistrationState -Name $resolvedServiceName -Present $true -TimeoutSeconds $ServiceTimeoutSeconds
    $serviceInstance = Get-SquidServiceInstance -Name $resolvedServiceName
    if ($null -eq $serviceInstance) {
        throw "The temporary Squid Windows service '$resolvedServiceName' was not registered by the MSI."
    }

    $configPath = Join-Path $resolvedInstallRoot 'etc\squid.conf'
    $serviceCommandLine = [string]$serviceInstance.PathName
    if ($serviceCommandLine -notmatch [Regex]::Escape($resolvedServiceName)) {
        throw "The installed service command line did not reference the temporary service name '$resolvedServiceName': $serviceCommandLine"
    }

    if ($serviceCommandLine -notmatch [Regex]::Escape($configPath)) {
        throw "The installed service command line did not reference the installed squid.conf path '$configPath': $serviceCommandLine"
    }

    Start-Service -Name $resolvedServiceName -ErrorAction Stop
    Wait-SquidServiceStatus -Name $resolvedServiceName -DesiredStatus ([System.ServiceProcess.ServiceControllerStatus]::Running) -TimeoutSeconds $ServiceTimeoutSeconds
    $null = Stop-SquidServiceIfPresent -Name $resolvedServiceName -TimeoutSeconds $ServiceTimeoutSeconds

    $uninstallLogPath = Join-Path $resolvedValidationRoot 'msi-uninstall.log'
    Invoke-MsiExec -Arguments @('/x', $resolvedMsiPath, '/qn', '/norestart') -LogPath $uninstallLogPath | Out-Null
    $uninstallCompleted = $true
    Wait-SquidServiceRegistrationState -Name $resolvedServiceName -Present $false -TimeoutSeconds $ServiceTimeoutSeconds
}
catch {
    $caughtError = $_
}
finally {
    if (-not $resolvedMsiPath -and $null -ne $buildResult -and $buildResult.MsiPath) {
        $resolvedMsiPath = Get-NormalizedPath -Path ([string]$buildResult.MsiPath)
    }

    if ($resolvedMsiPath) {
        $cleanupResult = Invoke-BestEffortCleanup `
            -Root $resolvedInstallRoot `
            -Name $resolvedServiceName `
            -PackagePath $resolvedMsiPath `
            -InstallAttempted:$installAttempted `
            -UninstallCompleted:$uninstallCompleted `
            -TimeoutSeconds $ServiceTimeoutSeconds
    } else {
        $cleanupResult = [PSCustomObject]@{
            Actions = @()
            Issues = @()
            Clean = $true
        }
    }

    $validationStatus = if ($null -eq $caughtError -and $cleanupResult.Clean) { 'passed' } else { 'failed' }
    $summaryLines = @(
        '## Service runner validation',
        '',
        ('- Status: `{0}`' -f $validationStatus),
        ('- Service name: `{0}`' -f $resolvedServiceName),
        ('- Validation root: `{0}`' -f $resolvedValidationRoot),
        ('- Install root: `{0}`' -f $resolvedInstallRoot),
        ('- MSI: `{0}`' -f $resolvedMsiPath)
    )

    if ($serviceCommandLine) {
        $summaryLines += ('- Service command line: `{0}`' -f $serviceCommandLine)
    }

    if ($cleanupResult.Actions.Count -gt 0) {
        $summaryLines += ('- Cleanup actions: `{0}`' -f ($cleanupResult.Actions -join '; '))
    }

    if ($cleanupResult.Issues.Count -gt 0) {
        $summaryLines += ('- Cleanup issues: `{0}`' -f ($cleanupResult.Issues -join '; '))
    }

    if ($null -ne $caughtError) {
        $summaryLines += ('- Failure: `{0}`' -f $caughtError.Exception.Message)
    }

    if ($env:GITHUB_STEP_SUMMARY) {
        $summaryLines -join [Environment]::NewLine | Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
    }
}

if ($null -ne $caughtError) {
    throw $caughtError
}

if (-not $cleanupResult.Clean) {
    throw "Service runner validation cleanup failed: $($cleanupResult.Issues -join '; ')"
}

Write-Host "Service runner validation passed for temporary service '$resolvedServiceName'."
[PSCustomObject]@{
    ValidationRoot = $resolvedValidationRoot
    MsiPath = $resolvedMsiPath
    InstallRoot = $resolvedInstallRoot
    ServiceName = $resolvedServiceName
    ServiceCommandLine = $serviceCommandLine
    CleanupActions = @($cleanupResult.Actions)
}
