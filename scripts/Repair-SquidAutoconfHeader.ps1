[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$GeneratedHeaderPath,
    [string]$ConfdefsPath,
    [string]$ConfigLogPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$resolvedGeneratedHeaderPath = [System.IO.Path]::GetFullPath($GeneratedHeaderPath)
$resolvedConfdefsPath = if ($ConfdefsPath) { [System.IO.Path]::GetFullPath($ConfdefsPath) } else { $null }
$resolvedConfigLogPath = if ($ConfigLogPath) { [System.IO.Path]::GetFullPath($ConfigLogPath) } else { $null }

if (-not (Test-Path -LiteralPath $resolvedGeneratedHeaderPath)) {
    throw "Generated autoconf header was not found at $resolvedGeneratedHeaderPath."
}

$headerText = [System.IO.File]::ReadAllText($resolvedGeneratedHeaderPath)
$newline = if ($headerText.Contains("`r`n")) { "`r`n" } else { "`n" }
$hasTrailingNewline = $headerText.EndsWith($newline)

$definitionSourceLabel = $null
$definitionLines = $null

if ($resolvedConfdefsPath -and (Test-Path -LiteralPath $resolvedConfdefsPath)) {
    $definitionSourceLabel = 'confdefs.h'
    $definitionLines = [System.IO.File]::ReadAllText($resolvedConfdefsPath) -split "`r?`n"
} elseif ($resolvedConfigLogPath -and (Test-Path -LiteralPath $resolvedConfigLogPath)) {
    $definitionSourceLabel = 'config.log'
    $definitionLines = ([System.IO.File]::ReadAllText($resolvedConfigLogPath) -split "`r?`n") | ForEach-Object {
        $_ -replace '^\s*\|\s?', ''
    }
} else {
    $missingSources = @()
    if ($resolvedConfdefsPath) {
        $missingSources += $resolvedConfdefsPath
    }
    if ($resolvedConfigLogPath) {
        $missingSources += $resolvedConfigLogPath
    }

    if ($missingSources.Count -eq 0) {
        throw 'Neither confdefs.h nor config.log was provided for autoconf header repair.'
    }

    throw "No autoconf definition source was found. Checked: $($missingSources -join ', ')"
}

$definitions = [System.Collections.Generic.Dictionary[string, PSCustomObject]]::new([System.StringComparer]::Ordinal)

function Add-Definition {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.Dictionary[string, PSCustomObject]]$Map,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [string]$ParameterText,
        [Parameter(Mandatory = $true)]
        [System.Collections.Generic.List[string]]$ValueLines,
        [Parameter(Mandatory = $true)]
        [string]$LineSeparator
    )

    $Map[$Name] = [PSCustomObject]@{
        Name = $Name
        ParameterText = $ParameterText
        Value = [string]::Join($LineSeparator, @($ValueLines))
    }
}

$currentName = $null
$currentParameterText = ''
$currentValueLines = [System.Collections.Generic.List[string]]::new()

foreach ($confdefsLine in $definitionLines) {
    if ($null -ne $currentName) {
        $currentValueLines.Add($confdefsLine)
        if (-not $confdefsLine.TrimEnd().EndsWith('\')) {
            Add-Definition -Map $definitions -Name $currentName -ParameterText $currentParameterText -ValueLines $currentValueLines -LineSeparator $newline
            $currentName = $null
            $currentParameterText = ''
            $currentValueLines = [System.Collections.Generic.List[string]]::new()
        }

        continue
    }

    $match = [regex]::Match($confdefsLine, '^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)(\([^)]*\))?(?:\s+(.*))?$')
    if (-not $match.Success) {
        continue
    }

    $currentName = $match.Groups[1].Value
    $currentParameterText = $match.Groups[2].Value
    $currentValueLines.Add($match.Groups[3].Value)

    if (-not $confdefsLine.TrimEnd().EndsWith('\')) {
        Add-Definition -Map $definitions -Name $currentName -ParameterText $currentParameterText -ValueLines $currentValueLines -LineSeparator $newline
        $currentName = $null
        $currentParameterText = ''
        $currentValueLines = [System.Collections.Generic.List[string]]::new()
    }
}

if ($null -ne $currentName) {
    Add-Definition -Map $definitions -Name $currentName -ParameterText $currentParameterText -ValueLines $currentValueLines -LineSeparator $newline
}

$updatedLines = [System.Collections.Generic.List[string]]::new()
$repairedMacros = [System.Collections.Generic.List[string]]::new()

foreach ($headerLine in ($headerText -split "`r?`n")) {
    $macroMatch = [regex]::Match($headerLine, '^\s*/\*\s*#undef\s+([A-Za-z_][A-Za-z0-9_]*)(\([^)]*\))?\s*\*/\s*$')
    if (-not $macroMatch.Success) {
        $macroMatch = [regex]::Match($headerLine, '^\s*#(?:define|undef)\s+([A-Za-z_][A-Za-z0-9_]*)(\([^)]*\))?\b.*$')
    }

    if (-not $macroMatch.Success) {
        $updatedLines.Add($headerLine)
        continue
    }

    $macroName = $macroMatch.Groups[1].Value
    if (-not $definitions.ContainsKey($macroName)) {
        $updatedLines.Add($headerLine)
        continue
    }

    $definition = $definitions[$macroName]
    $replacementLine = if ([string]::IsNullOrEmpty($definition.Value)) {
        "#define $($definition.Name)$($definition.ParameterText)"
    } else {
        "#define $($definition.Name)$($definition.ParameterText) $($definition.Value)"
    }

    if ($headerLine -ne $replacementLine -and -not $repairedMacros.Contains($macroName)) {
        $repairedMacros.Add($macroName)
    }

    $updatedLines.Add($replacementLine)
}

$updatedHeaderText = [string]::Join($newline, @($updatedLines))
if ($hasTrailingNewline) {
    $updatedHeaderText += $newline
}

if ($updatedHeaderText -ne $headerText) {
    [System.IO.File]::WriteAllText(
        $resolvedGeneratedHeaderPath,
        $updatedHeaderText,
        [System.Text.UTF8Encoding]::new($false)
    )
}

[PSCustomObject]@{
    GeneratedHeaderPath = $resolvedGeneratedHeaderPath
    ConfdefsPath = $resolvedConfdefsPath
    ConfigLogPath = $resolvedConfigLogPath
    DefinitionSource = $definitionSourceLabel
    RepairedCount = $repairedMacros.Count
    RepairedMacros = @($repairedMacros)
}
