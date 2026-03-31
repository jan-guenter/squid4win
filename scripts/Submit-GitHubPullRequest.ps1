[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$DestinationRepository,
    [Parameter(Mandatory = $true)]
    [string]$DestinationPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^(?!/)(?!.*//)(?!.*\.\.)(?!.*@\{)(?!.*\\)(?!.*\.$)(?!.*\/$)[A-Za-z0-9._/-]+$')]
    [string]$BranchName,
    [Parameter(Mandatory = $true)]
    [string]$CommitMessage,
    [Parameter(Mandatory = $true)]
    [string]$PullRequestTitle,
    [Parameter(Mandatory = $true)]
    [string]$PullRequestBody,
    [string]$BaseBranch = 'main',
    [string]$WorkingRoot = (Join-Path $PSScriptRoot '..\artifacts\publication')
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

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [string[]]$Arguments = @()
    )

    $output = & $Command @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $message = ($output | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($message)) {
            $message = "$Command exited with code $exitCode."
        }

        throw $message
    }

    return ($output | Out-String).Trim()
}

function Test-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [string[]]$Arguments = @()
    )

    & $Command @Arguments *> $null
    return ($LASTEXITCODE -eq 0)
}

function Get-OpenPullRequestUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Repository,
        [Parameter(Mandatory = $true)]
        [string]$Head
    )

    $prUrl = Invoke-NativeCommand -Command 'gh' -Arguments @(
        'pr',
        'list',
        '--repo',
        $Repository,
        '--state',
        'open',
        '--head',
        $Head,
        '--json',
        'url',
        '--jq',
        '.[0].url'
    )

    if (($prUrl -eq 'null') -or [string]::IsNullOrWhiteSpace($prUrl)) {
        return ''
    }

    return $prUrl
}

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$resolvedSourcePath = Get-AbsolutePath -Path $SourcePath -BasePath $repositoryRoot
$resolvedWorkingRoot = Get-AbsolutePath -Path $WorkingRoot -BasePath $repositoryRoot
$destinationRelativePath = $DestinationPath.TrimStart('\', '/')

if (-not (Test-Path -LiteralPath $resolvedSourcePath)) {
    throw "The source path '$resolvedSourcePath' was not found."
}

Get-Command gh -ErrorAction Stop | Out-Null
Get-Command git -ErrorAction Stop | Out-Null

$login = Invoke-NativeCommand -Command 'gh' -Arguments @('api', 'user', '--jq', '.login')
if ([string]::IsNullOrWhiteSpace($login)) {
    throw 'Unable to resolve the authenticated GitHub login from gh.'
}

$targetParts = $DestinationRepository.Split('/', 2)
$targetOwner = $targetParts[0]
$targetRepositoryName = $targetParts[1]
$useFork = $targetOwner -ne $login
$headRepository = if ($useFork) {
    "$login/$targetRepositoryName"
} else {
    $DestinationRepository
}
$headSelector = if ($useFork) {
    ('{0}:{1}' -f $login, $BranchName)
} else {
    $BranchName
}
$cloneName = ($DestinationRepository + '-' + $BranchName) -replace '[^A-Za-z0-9._-]', '-'
$clonePath = Join-Path $resolvedWorkingRoot $cloneName
$result = $null

try {
    if ($useFork -and -not (Test-NativeCommand -Command 'gh' -Arguments @('repo', 'view', $headRepository, '--json', 'nameWithOwner', '--jq', '.nameWithOwner'))) {
        Invoke-NativeCommand -Command 'gh' -Arguments @('repo', 'fork', $DestinationRepository, '--clone=false', '--remote=false') | Out-Null
    }

    if ($useFork) {
        $forkReady = $false
        foreach ($attempt in 1..20) {
            if (Test-NativeCommand -Command 'gh' -Arguments @('repo', 'view', $headRepository, '--json', 'nameWithOwner', '--jq', '.nameWithOwner')) {
                $forkReady = $true
                break
            }

            Start-Sleep -Seconds 3
        }

        if (-not $forkReady) {
            throw "The fork '$headRepository' was not ready after creation."
        }
    }

    $null = New-Item -ItemType Directory -Path $resolvedWorkingRoot -Force
    if (Test-Path -LiteralPath $clonePath) {
        Remove-Item -LiteralPath $clonePath -Recurse -Force
    }

    Invoke-NativeCommand -Command 'gh' -Arguments @('auth', 'setup-git') | Out-Null
    Invoke-NativeCommand -Command 'git' -Arguments @(
        'clone',
        '--quiet',
        '--filter=blob:none',
        '--no-checkout',
        "https://github.com/$DestinationRepository.git",
        $clonePath
    ) | Out-Null

    $sparsePath = if (Test-Path -LiteralPath $resolvedSourcePath -PathType Container) {
        $destinationRelativePath
    } else {
        $parentPath = [System.IO.Path]::GetDirectoryName($destinationRelativePath)
        if ([string]::IsNullOrWhiteSpace($parentPath)) {
            $destinationRelativePath
        } else {
            $parentPath
        }
    }

    Invoke-NativeCommand -Command 'git' -Arguments @('-C', $clonePath, 'sparse-checkout', 'init', '--cone') | Out-Null
    Invoke-NativeCommand -Command 'git' -Arguments @('-C', $clonePath, 'sparse-checkout', 'set', $sparsePath.Replace('\', '/')) | Out-Null
    Invoke-NativeCommand -Command 'git' -Arguments @('-C', $clonePath, 'checkout', $BaseBranch) | Out-Null

    if ($useFork) {
        Invoke-NativeCommand -Command 'git' -Arguments @(
            '-C',
            $clonePath,
            'remote',
            'add',
            'fork',
            "https://github.com/$headRepository.git"
        ) | Out-Null
    }

    Invoke-NativeCommand -Command 'git' -Arguments @('-C', $clonePath, 'config', 'user.name', 'github-actions[bot]') | Out-Null
    Invoke-NativeCommand -Command 'git' -Arguments @(
        '-C',
        $clonePath,
        'config',
        'user.email',
        '41898282+github-actions[bot]@users.noreply.github.com'
    ) | Out-Null
    Invoke-NativeCommand -Command 'git' -Arguments @('-C', $clonePath, 'checkout', '-B', $BranchName) | Out-Null

    $destinationFullPath = Join-Path $clonePath $destinationRelativePath
    $destinationParent = Split-Path -Parent $destinationFullPath
    if (-not [string]::IsNullOrWhiteSpace($destinationParent)) {
        $null = New-Item -ItemType Directory -Path $destinationParent -Force
    }

    if (Test-Path -LiteralPath $resolvedSourcePath -PathType Container) {
        if (Test-Path -LiteralPath $destinationFullPath) {
            Remove-Item -LiteralPath $destinationFullPath -Recurse -Force
        }

        $null = New-Item -ItemType Directory -Path $destinationFullPath -Force
        Get-ChildItem -LiteralPath $resolvedSourcePath -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $destinationFullPath -Recurse -Force
        }
    } else {
        Copy-Item -LiteralPath $resolvedSourcePath -Destination $destinationFullPath -Force
    }

    $gitPathSpec = $destinationRelativePath.Replace('\', '/')
    Invoke-NativeCommand -Command 'git' -Arguments @('-C', $clonePath, 'add', '--all', '--', $gitPathSpec) | Out-Null
    $status = Invoke-NativeCommand -Command 'git' -Arguments @('-C', $clonePath, 'status', '--porcelain', '--', $gitPathSpec)
    $pullRequestUrl = Get-OpenPullRequestUrl -Repository $DestinationRepository -Head $headSelector

    if ([string]::IsNullOrWhiteSpace($status)) {
        $result = [PSCustomObject]@{
            Changed = $false
            PullRequestUrl = $pullRequestUrl
            HeadRepository = $headRepository
            BaseRepository = $DestinationRepository
            BranchName = $BranchName
            DestinationPath = $destinationRelativePath
        }

        return $result
    }

    Invoke-NativeCommand -Command 'git' -Arguments @('-C', $clonePath, 'commit', '--quiet', '-m', $CommitMessage) | Out-Null
    $pushRemote = if ($useFork) { 'fork' } else { 'origin' }
    Invoke-NativeCommand -Command 'git' -Arguments @(
        '-C',
        $clonePath,
        'push',
        '--force-with-lease',
        '--set-upstream',
        $pushRemote,
        $BranchName
    ) | Out-Null

    if ([string]::IsNullOrWhiteSpace($pullRequestUrl)) {
        $pullRequestUrl = Invoke-NativeCommand -Command 'gh' -Arguments @(
            'pr',
            'create',
            '--repo',
            $DestinationRepository,
            '--base',
            $BaseBranch,
            '--head',
            $headSelector,
            '--title',
            $PullRequestTitle,
            '--body',
            $PullRequestBody
        )
    }

    $result = [PSCustomObject]@{
        Changed = $true
        PullRequestUrl = $pullRequestUrl
        HeadRepository = $headRepository
        BaseRepository = $DestinationRepository
        BranchName = $BranchName
        DestinationPath = $destinationRelativePath
    }
} finally {
    if (Test-Path -LiteralPath $clonePath) {
        Remove-Item -LiteralPath $clonePath -Recurse -Force
    }
}

return $result
