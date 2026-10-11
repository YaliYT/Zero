<#
 Rollback.ps1 - restore the ORIGINAL code files from a timestamped backup, never touching state\ (sessions,
 checkpoints, notes, input history), vendor\, logs or backup-* folders.

 Default target : the folder this script lives in (the work copy).
 Default backup : newest sibling folder named Qwen-Agent-backup-*.
 Safety         : every file that is about to be overwritten/moved is first copied to
                  <target>\rollback-saved-<timestamp>\ ; nothing is deleted. Use -WhatIf to preview.

 Examples:
   .\Rollback.ps1 -WhatIf
   .\Rollback.ps1
   .\Rollback.ps1 -Backup C:\Users\nagor\Downloads\Qwen-Agent-backup-20261010-101500 -Target C:\Users\nagor\Downloads\Qwen-Agent
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Backup,
    [string]$Target = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'
$Target = (Resolve-Path -LiteralPath $Target).Path
if (-not $Backup) {
    $parent = Split-Path -Parent $Target
    $latest = Get-ChildItem -LiteralPath $parent -Directory -Filter 'Qwen-Agent-backup-*' |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $latest) { throw 'No Qwen-Agent-backup-* folder found next to the target; pass -Backup.' }
    $Backup = $latest.FullName
}
$Backup = (Resolve-Path -LiteralPath $Backup).Path
if ($Backup -eq $Target) { throw 'Backup and target are the same folder.' }
if (-not (Test-Path -LiteralPath (Join-Path $Backup 'qwen_coding.py'))) { throw "Not a code backup: $Backup" }

# Code + configuration files only (top level). Logs, jsonl telemetry, state\ and vendor\ are never touched.
$patterns = @('*.py', '*.ps1', '*.bat', 'qwen-agent-settings.json', 'qwen-cpu-runner-paths.json', 'Qwen-Code-README.md')
$originals = foreach ($pattern in $patterns) { Get-ChildItem -LiteralPath $Backup -File -Filter $pattern }
$originals = $originals | Sort-Object FullName -Unique
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$saved = Join-Path $Target "rollback-saved-$stamp"
$summary = [ordered]@{ restored = @(); unchanged = @(); moved_new_code = @() }

foreach ($file in $originals) {
    $destination = Join-Path $Target $file.Name
    $same = (Test-Path -LiteralPath $destination) -and
            ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash)
    if ($same) { $summary.unchanged += $file.Name; continue }
    if ($PSCmdlet.ShouldProcess($destination, "restore from $($file.FullName)")) {
        if (Test-Path -LiteralPath $destination) {
            New-Item -ItemType Directory -Path $saved -Force | Out-Null
            Copy-Item -LiteralPath $destination -Destination (Join-Path $saved $file.Name) -Force
        }
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
    }
    $summary.restored += $file.Name
}

# Code files that exist only in the target (added after the backup) are moved aside, not deleted.
$originalNames = @($originals | ForEach-Object Name)
foreach ($pattern in @('*.py')) {
    foreach ($file in Get-ChildItem -LiteralPath $Target -File -Filter $pattern) {
        if ($originalNames -notcontains $file.Name) {
            if ($PSCmdlet.ShouldProcess($file.FullName, 'move aside (not in backup)')) {
                New-Item -ItemType Directory -Path $saved -Force | Out-Null
                Move-Item -LiteralPath $file.FullName -Destination (Join-Path $saved $file.Name) -Force
            }
            $summary.moved_new_code += $file.Name
        }
    }
}
Get-ChildItem -LiteralPath $Target -Filter '__pycache__' -Directory -ErrorAction SilentlyContinue | Out-Null
[pscustomobject]@{
    target = $Target; backup = $Backup; saved_copy_of_replaced_files = $saved
    state_folder_touched = $false; restored = $summary.restored; unchanged = $summary.unchanged
    moved_aside_new_code = $summary.moved_new_code
} | ConvertTo-Json -Depth 4
