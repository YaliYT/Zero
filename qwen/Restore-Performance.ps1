param([string]$Backup)
$ErrorActionPreference = 'Stop'
$files = @('Qwen-Agent.py','qwen_coding.py','qwen_memory_guard.py','qwen_cpu_runner.py','qwen-agent-settings.json')
if (-not $Backup) {
    $installation = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'performance-20261011\installation.json') -Raw | ConvertFrom-Json
    $Backup = $installation.backup
}
$backupRoot = (Resolve-Path -LiteralPath $Backup).Path
foreach ($name in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $backupRoot $name) -PathType Leaf)) { throw "Missing backup: $name" }
}
$preserve = Join-Path $PSScriptRoot ('performance-before-restore-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $preserve | Out-Null
foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $preserve }
foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $backupRoot $name) -Destination (Join-Path $PSScriptRoot $name) -Force }
Write-Output "Restored five agent files. Previous versions preserved in $preserve."
