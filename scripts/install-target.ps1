param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path $RepoPath).Path
$source = Join-Path $PSScriptRoot "..\templates\qwen-agents"
$target = Join-Path $repo ".qwen\agents"

New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $source "*.md") -Destination $target -Force

$gitignore = Join-Path $repo ".gitignore"

if (-not (Test-Path $gitignore)) {
    New-Item -ItemType File -Path $gitignore | Out-Null
}

$content = Get-Content $gitignore -Raw

if ($content -notmatch "(?m)^\.foxforge/$") {
    Add-Content -Path $gitignore -Value "`n# FoxForge runtime`n.foxforge/"
}

Write-Host "Installed FoxForge Qwen agents into: $target"
Write-Host "Ensured .foxforge/ is ignored in: $gitignore"
