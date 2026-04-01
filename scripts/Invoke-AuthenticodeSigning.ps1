[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string[]]$Path,
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [switch]$Recurse,
    [switch]$RequireMatches,
    [string]$CertificatePath = $env:SQUID4WIN_SIGNING_CERTIFICATE_PATH,
    [string]$CertificateBase64 = $env:SQUID4WIN_SIGNING_CERTIFICATE_PFX_BASE64,
    [string]$CertificateSecret = $env:SQUID4WIN_SIGNING_CERTIFICATE_PASSWORD,
    [string]$TimestampServer = $env:SQUID4WIN_SIGNING_TIMESTAMP_URL,
    [string]$SignToolPath = $env:SQUID4WIN_SIGNTOOL_PATH,
    [string[]]$SignableExtensions = @('.dll', '.exe', '.msi', '.ps1', '.psm1', '.psd1')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Get-AbsolutePath.ps1')

function Resolve-SignToolPath {
    param(
        [string]$ExplicitPath
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $resolvedExplicitPath = Get-AbsolutePath -Path $ExplicitPath -BasePath $resolvedRepositoryRoot
        if (-not (Test-Path -LiteralPath $resolvedExplicitPath -PathType Leaf)) {
            throw "The configured signtool path '$resolvedExplicitPath' does not exist."
        }

        return $resolvedExplicitPath
    }

    $signToolCommand = Get-Command 'signtool.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $signToolCommand) {
        return $signToolCommand.Source
    }

    $programFilesX86 = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::ProgramFilesX86)
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        $windowsKitsBinRoot = Join-Path $programFilesX86 'Windows Kits\10\bin'
        if (Test-Path -LiteralPath $windowsKitsBinRoot -PathType Container) {
            foreach ($sdkDirectory in Get-ChildItem -LiteralPath $windowsKitsBinRoot -Directory | Sort-Object Name -Descending) {
                $candidatePath = Join-Path $sdkDirectory.FullName 'x64\signtool.exe'
                if (Test-Path -LiteralPath $candidatePath -PathType Leaf) {
                    return $candidatePath
                }
            }
        }

        $appCertificationKitPath = Join-Path $programFilesX86 'Windows Kits\10\App Certification Kit\signtool.exe'
        if (Test-Path -LiteralPath $appCertificationKitPath -PathType Leaf) {
            return $appCertificationKitPath
        }
    }

    throw 'Unable to locate signtool.exe. Set SQUID4WIN_SIGNTOOL_PATH or install the Windows SDK signing tools.'
}

function Get-SigningCertificate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CertificateFilePath,
        [string]$CertificateSecret
    )

    $storageFlags = `
        [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet

    try {
        return [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
            $CertificateFilePath,
            $CertificateSecret,
            $storageFlags
        )
    }
    catch {
        throw "Failed to load the signing certificate '$CertificateFilePath'. $($_.Exception.Message)"
    }
}

function Get-TargetFile {
    param(
        [string[]]$InputPath,
        [string[]]$AllowedExtensions,
        [bool]$IncludeDescendants
    )

    $resolvedPaths = [System.Collections.Generic.List[string]]::new()
    foreach ($candidatePath in $InputPath) {
        $resolvedCandidatePath = Get-AbsolutePath -Path $candidatePath -BasePath $resolvedRepositoryRoot
        if (-not (Test-Path -LiteralPath $resolvedCandidatePath)) {
            throw "The signing target '$resolvedCandidatePath' does not exist."
        }

        $resolvedItem = Get-Item -LiteralPath $resolvedCandidatePath
        if ($resolvedItem.PSIsContainer) {
            $items = if ($IncludeDescendants) {
                Get-ChildItem -LiteralPath $resolvedCandidatePath -File -Recurse
            } else {
                Get-ChildItem -LiteralPath $resolvedCandidatePath -File
            }

            foreach ($item in $items) {
                if ($AllowedExtensions -contains $item.Extension.ToLowerInvariant()) {
                    $resolvedPaths.Add($item.FullName)
                }
            }

            continue
        }

        $extension = $resolvedItem.Extension.ToLowerInvariant()
        if (-not ($AllowedExtensions -contains $extension)) {
            throw "The signing target '$resolvedCandidatePath' does not use a supported signable extension."
        }

        $resolvedPaths.Add($resolvedItem.FullName)
    }

    return @($resolvedPaths | Sort-Object -Unique)
}

$resolvedRepositoryRoot = Get-AbsolutePath -Path $RepositoryRoot -BasePath (Get-Location).Path

if (-not [string]::IsNullOrWhiteSpace($CertificatePath) -and -not [string]::IsNullOrWhiteSpace($CertificateBase64)) {
    throw 'Specify either CertificatePath or CertificateBase64, but not both.'
}

if ([string]::IsNullOrWhiteSpace($CertificatePath) -and [string]::IsNullOrWhiteSpace($CertificateBase64)) {
    return [PSCustomObject]@{
        SigningEnabled = $false
        SigningReason = 'Signing material not configured.'
        CertificateSource = $null
        SignToolPath = $null
        TimestampServer = if ([string]::IsNullOrWhiteSpace($TimestampServer)) { $null } else { $TimestampServer }
        MatchedFileCount = 0
        SignedFileCount = 0
        SkippedFileCount = 0
        MatchedFiles = @()
        SignedFiles = @()
        SkippedFiles = @()
    }
}

$targetFiles = @(Get-TargetFile -InputPath $Path -AllowedExtensions $SignableExtensions -IncludeDescendants $Recurse.IsPresent)
if ($RequireMatches -and ($targetFiles.Count -eq 0)) {
    throw 'No signable files matched the requested signing targets.'
}

$materializedCertificatePath = $null
$resolvedCertificatePath = $null
$resolvedSignToolPath = $null
$signingCertificate = $null
$certificateSource = if (-not [string]::IsNullOrWhiteSpace($CertificatePath)) { 'path' } else { 'base64' }
$powerShellScriptExtensions = @('.ps1', '.psm1', '.psd1')

try {
    if ($certificateSource -eq 'path') {
        $resolvedCertificatePath = Get-AbsolutePath -Path $CertificatePath -BasePath $resolvedRepositoryRoot
        if (-not (Test-Path -LiteralPath $resolvedCertificatePath -PathType Leaf)) {
            throw "The signing certificate '$resolvedCertificatePath' does not exist."
        }
    } else {
        $signingRoot = Join-Path $resolvedRepositoryRoot 'build\signing'
        $null = New-Item -ItemType Directory -Path $signingRoot -Force
        $materializedCertificatePath = Join-Path $signingRoot ("signing-certificate-{0}.pfx" -f ([Guid]::NewGuid().ToString('N')))
        $certificateBytes = [System.Convert]::FromBase64String(($CertificateBase64 -replace '\s', ''))
        [System.IO.File]::WriteAllBytes($materializedCertificatePath, $certificateBytes)
        $resolvedCertificatePath = $materializedCertificatePath
    }

    if ($targetFiles | Where-Object { $powerShellScriptExtensions -contains ([System.IO.Path]::GetExtension($_).ToLowerInvariant()) }) {
        $signingCertificate = Get-SigningCertificate `
            -CertificateFilePath $resolvedCertificatePath `
            -CertificateSecret $CertificateSecret
    }

    if ($targetFiles | Where-Object { -not ($powerShellScriptExtensions -contains ([System.IO.Path]::GetExtension($_).ToLowerInvariant())) }) {
        $resolvedSignToolPath = Resolve-SignToolPath -ExplicitPath $SignToolPath
    }

    $signedFiles = [System.Collections.Generic.List[string]]::new()
    $skippedFiles = [System.Collections.Generic.List[string]]::new()
    foreach ($targetFile in $targetFiles) {
        $currentSignature = $null
        try {
            $currentSignature = Get-AuthenticodeSignature -FilePath $targetFile -ErrorAction Stop
        }
        catch {
            $currentSignature = $null
        }

        if (($null -ne $currentSignature) -and ($currentSignature.Status -eq [System.Management.Automation.SignatureStatus]::Valid)) {
            $skippedFiles.Add($targetFile)
            continue
        }

        $extension = [System.IO.Path]::GetExtension($targetFile).ToLowerInvariant()
        if ($powerShellScriptExtensions -contains $extension) {
            $signatureResult = if ([string]::IsNullOrWhiteSpace($TimestampServer)) {
                Set-AuthenticodeSignature `
                    -FilePath $targetFile `
                    -Certificate $signingCertificate `
                    -HashAlgorithm SHA256
            } else {
                Set-AuthenticodeSignature `
                    -FilePath $targetFile `
                    -Certificate $signingCertificate `
                    -HashAlgorithm SHA256 `
                    -TimestampServer $TimestampServer
            }

            if ($signatureResult.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
                throw "Set-AuthenticodeSignature returned status '$($signatureResult.Status)' for '$targetFile'."
            }
        } else {
            $signToolArguments = @(
                'sign',
                '/fd', 'SHA256',
                '/f', $resolvedCertificatePath
            )

            if (-not [string]::IsNullOrWhiteSpace($CertificateSecret)) {
                $signToolArguments += @('/p', $CertificateSecret)
            }

            if (-not [string]::IsNullOrWhiteSpace($TimestampServer)) {
                $signToolArguments += @('/tr', $TimestampServer, '/td', 'SHA256')
            }

            $signToolArguments += $targetFile

            & $resolvedSignToolPath @signToolArguments | Out-Host
            $signToolExitCode = $LASTEXITCODE
            if ($signToolExitCode -ne 0) {
                throw "signtool.exe failed with exit code $signToolExitCode while signing '$targetFile'."
            }
        }

        $signedFiles.Add($targetFile)
    }

    return [PSCustomObject]@{
        SigningEnabled = $true
        SigningReason = 'Signing material configured.'
        CertificateSource = $certificateSource
        SignToolPath = $resolvedSignToolPath
        TimestampServer = if ([string]::IsNullOrWhiteSpace($TimestampServer)) { $null } else { $TimestampServer }
        MatchedFileCount = $targetFiles.Count
        SignedFileCount = $signedFiles.Count
        SkippedFileCount = $skippedFiles.Count
        MatchedFiles = $targetFiles
        SignedFiles = @($signedFiles)
        SkippedFiles = @($skippedFiles)
    }
}
finally {
    if ($null -ne $signingCertificate) {
        $signingCertificate.Reset()
    }
    if ($materializedCertificatePath -and (Test-Path -LiteralPath $materializedCertificatePath)) {
        Remove-Item -LiteralPath $materializedCertificatePath -Force
    }
}
