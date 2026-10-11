$ErrorActionPreference = 'Stop'
$target = 'C:\Users\nagor\Downloads\Qwen-Agent-work'
$delivery = Join-Path $PSScriptRoot 'v4-delivery'
$before = Get-Content (Join-Path $delivery 'before-sha256.json') -Raw | ConvertFrom-Json
$expected = Get-Content (Join-Path $delivery 'tested-files-sha256.json') -Raw | ConvertFrom-Json
$old = Get-Content (Join-Path $target 'token-speed-tests-v2-20261011\installation.json') -Raw | ConvertFrom-Json
$offline = Get-Content (Join-Path $delivery 'app\verification\token500-v4-verified\offline-tests.json') -Raw | ConvertFrom-Json
$live = Get-Content (Join-Path $PSScriptRoot 'run-entrypoint-v4\results.json') -Raw | ConvertFrom-Json
if (-not $offline.all_passed -or -not $live.verified) { throw 'Candidate tests did not pass.' }
foreach ($property in $old.files.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $target $property.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) {
        throw "Installed source changed while testing: $($property.Name)"
    }
}
foreach ($property in $expected.PSObject.Properties) {
    $name = $property.Name
    if ((Get-FileHash -LiteralPath (Join-Path $delivery ('app\' + $name)) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) {
        throw "Tested candidate changed: $name"
    }
    if ((Get-FileHash -LiteralPath (Join-Path $target $name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $before.$name) {
        throw "Target changed: $name"
    }
    if ($name.EndsWith('.py') -and $live.source_sha256.$name -ne $property.Value) {
        throw "Real agent test used different source: $name"
    }
}
if (Get-CimInstance Win32_Process -Filter "name = 'llama-server.exe'") { throw 'A model is running; installation postponed.' }
$agentPath = Join-Path $target 'Qwen-Agent.py'
if (Get-CimInstance Win32_Process -Filter "name = 'python.exe'" | Where-Object { $_.CommandLine -like ('*' + $agentPath + '*') }) {
    throw 'A user agent is running; do not replace its source.'
}
$backup = Join-Path $target ('token-speed-before-v4-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($property in $before.PSObject.Properties) {
    Copy-Item -LiteralPath (Join-Path $target $property.Name) -Destination (Join-Path $backup $property.Name)
}
$before | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $backup 'original-files-sha256.json') -Encoding utf8
try {
    foreach ($property in $expected.PSObject.Properties) {
        Copy-Item -LiteralPath (Join-Path $delivery ('app\' + $property.Name)) -Destination (Join-Path $target $property.Name) -Force
        if ((Get-FileHash -LiteralPath (Join-Path $target $property.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) {
            throw "Installed hash differs: $($property.Name)"
        }
    }
    $merged = [ordered]@{}
    foreach ($property in $old.files.PSObject.Properties) { $merged[$property.Name] = $property.Value }
    foreach ($property in $expected.PSObject.Properties) { $merged[$property.Name] = $property.Value }
    $summary = Get-Content (Join-Path $delivery 'summary.json') -Raw | ConvertFrom-Json
    $manifest = [ordered]@{installed_at=(Get-Date).ToString('o');target=$target;backup=$backup;files=$merged;changed_files=$expected;verified_hashes=$true;target_achieved=$false;measurements=$summary.selected}
    $manifest | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $delivery 'installation.json') -Encoding utf8
    $manifest | ConvertTo-Json -Depth 10
} catch {
    foreach ($property in $before.PSObject.Properties) {
        Copy-Item -LiteralPath (Join-Path $backup $property.Name) -Destination (Join-Path $target $property.Name) -Force
        if ((Get-FileHash -LiteralPath (Join-Path $target $property.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) {
            throw "Rollback verification failed: $($property.Name)"
        }
    }
    throw
}
