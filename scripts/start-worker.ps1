param(
    [Parameter(Mandatory = $true)][string]$Config,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try {
    $configPath = (Resolve-Path -LiteralPath $Config).ProviderPath
    $settings = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $allowed = @('repository_path', 'python_executable', 'test_command', 'publish_pr', 'poll_interval', 'skip_discord')
    $names = @($settings.PSObject.Properties.Name)
    foreach ($name in $names) {
        if ($name -notin $allowed) { throw 'Unknown configuration field' }
    }
    foreach ($name in @('repository_path', 'python_executable', 'test_command', 'publish_pr')) {
        if ($name -notin $names) { throw 'Missing configuration field' }
    }
    if ($settings.publish_pr -isnot [bool] -or -not $settings.publish_pr) { throw 'Explicit publishing approval required' }
    if ($settings.repository_path -isnot [string] -or $settings.python_executable -isnot [string] -or
        $settings.test_command -isnot [string] -or [string]::IsNullOrWhiteSpace($settings.test_command)) {
        throw 'Invalid worker configuration types'
    }
    $repo = (Resolve-Path -LiteralPath $settings.repository_path).ProviderPath
    $python = (Resolve-Path -LiteralPath $settings.python_executable).ProviderPath
    if (-not (Test-Path -LiteralPath $repo -PathType Container) -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'Invalid worker paths'
    }
    $directory = Split-Path -Parent $configPath
    $comparison = [System.StringComparison]::OrdinalIgnoreCase
    $repoPrefix = $repo.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if ($directory.Equals($repo, $comparison) -or $directory.StartsWith($repoPrefix, $comparison)) {
        throw 'Worker configuration and logs must be outside the target repository'
    }
    $interval = 60.0
    if ('poll_interval' -in $names) { $interval = [double]$settings.poll_interval }
    if ([double]::IsNaN($interval) -or [double]::IsInfinity($interval) -or $interval -lt 10 -or $interval -gt 86400) {
        throw 'Invalid polling interval'
    }
    if ('skip_discord' -in $names -and $settings.skip_discord -isnot [bool]) { throw 'Invalid notification option' }
    if ($ValidateOnly) {
        Write-Output 'Worker configuration valid; no worker started and no network calls made.'
        exit 0
    }

    # Refresh existing User variables in a scheduled-task session. No values
    # are printed, placed in argv, or written into this configuration file.
    foreach ($name in @('FOXFORGE_ALLOWED_GITHUB_USER_IDS', 'FOXFORGE_GITHUB_APP_ID', 'FOXFORGE_GITHUB_INSTALLATION_ID', 'FOXFORGE_GITHUB_PRIVATE_KEY', 'DISCORD_WEBHOOK_URL')) {
        $value = [Environment]::GetEnvironmentVariable($name, 'User')
        if ($null -ne $value) { [Environment]::SetEnvironmentVariable($name, $value, 'Process') }
    }
    $arguments = @('-I', '-m', 'foxforge', 'watch', '--repo', $repo, '--test-command', $settings.test_command,
                   '--publish-pr', '--poll-interval', $interval.ToString([Globalization.CultureInfo]::InvariantCulture))
    if ('skip_discord' -in $names -and $settings.skip_discord) { $arguments += '--skip-discord' }
    # Isolated Python and an external working directory prevent target-local
    # Python modules/PYTHONPATH from replacing the installed worker at startup.
    Set-Location -LiteralPath $directory
    & $python @arguments *>> (Join-Path $directory 'worker.log')
    exit $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine('FoxForge worker configuration/startup failed. Inspect external RunState, worker.log, and Task Scheduler history. Configuration values were not printed.')
    exit 1
}
