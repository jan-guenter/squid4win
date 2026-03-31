@{
    Severity = @(
        'Error',
        'Warning'
    )
    ExcludeRules = @(
        'PSAvoidUsingWriteHost',
        'PSUseConsistentIndentation',
        'PSPlaceCloseBrace',
        'PSUseConsistentWhitespace'
    )
    Rules = @{
        PSUseConsistentIndentation = @{
            Enable = $true
            Kind = 'space'
            IndentationSize = 4
            PipelineIndentation = 'IncreaseIndentationForFirstPipeline'
        }
        PSUseConsistentWhitespace = @{
            Enable = $true
            CheckInnerBrace = $true
            CheckOpenBrace = $true
            CheckOpenParen = $true
            CheckOperator = $true
            CheckPipe = $true
            CheckSeparator = $true
        }
        PSUseConsistentBraceStyle = @{
            Enable = $true
            CheckOpenBrace = $true
            CheckOpenParen = $true
            CheckKeyword = $true
        }
        PSPlaceOpenBrace = @{
            Enable = $true
            OnSameLine = $true
            NewLineAfter = $true
            IgnoreOneLineBlock = $true
        }
        PSPlaceCloseBrace = @{
            Enable = $true
            NoEmptyLineBefore = $true
            IgnoreOneLineBlock = $true
            NewLineAfter = $true
        }
    }
}
