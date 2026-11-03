param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path -LiteralPath $RepoPath).Path
$source = Join-Path (Join-Path $PSScriptRoot "..") "templates/qwen-agents"
if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    # Wheel layout: share/foxforge/{scripts,qwen-agents}.
    $source = Join-Path (Join-Path $PSScriptRoot "..") "qwen-agents"
}
if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "FoxForge agent templates were not found"
}
$target = Join-Path (Join-Path $repo ".qwen") "agents"
$templates = @(Get-ChildItem -LiteralPath $source -Filter "*.md" -File)
foreach ($template in $templates) {
    if ((Test-Path -LiteralPath (Join-Path $target $template.Name)) -and -not $Force) {
        throw "Agent already exists: $($template.Name). Review customizations or explicitly pass -Force."
    }
}

New-Item -ItemType Directory -Force -Path $target | Out-Null
foreach ($template in $templates) {
    Copy-Item -LiteralPath $template.FullName -Destination $target -Force:$Force
}

$settingsSource = Join-Path (Split-Path -Parent $source) "qwen-settings.json"
$settingsTarget = Join-Path (Join-Path $repo ".qwen") "settings.json"
if (-not (Test-Path -LiteralPath $settingsTarget)) {
    Copy-Item -LiteralPath $settingsSource -Destination $settingsTarget
}

$gitignore = Join-Path $repo ".gitignore"

if (-not (Test-Path $gitignore)) {
    New-Item -ItemType File -Path $gitignore | Out-Null
}

$content = [string](Get-Content -LiteralPath $gitignore -Raw)

if ($content -notmatch "(?m)^\.foxforge/[\t ]*\r?$") {
    Add-Content -LiteralPath $gitignore -Value "`n# FoxForge runtime`n.foxforge/" -Encoding utf8
}

Write-Host "Installed FoxForge Qwen agents into: $target"
Write-Host "Ensured .foxforge/ is ignored in: $gitignore"
