function Assert-SquidServiceName {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Name,
        [string]$ParameterName = 'ServiceName'
    )

    $resolvedName = $Name.Trim()
    if ([string]::IsNullOrWhiteSpace($resolvedName)) {
        throw "$ParameterName must contain at least one alphanumeric character."
    }

    if ($resolvedName.Length -gt 32) {
        throw "$ParameterName '$resolvedName' must be 32 characters or fewer because Squid's -n option rejects longer Windows service names."
    }

    if ($resolvedName -notmatch '^[A-Za-z0-9]+$') {
        throw "$ParameterName '$resolvedName' must be alphanumeric because Squid's -n option rejects punctuation characters such as '-'."
    }

    return $resolvedName
}
