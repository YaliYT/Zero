$ErrorActionPreference = 'Stop'
$target = $PSScriptRoot
$manifest = Get-Content (Join-Path $target 'token-speed-tests-v4-20261011\installation.json') -Raw | ConvertFrom-Json
$agentPath = Join-Path $target 'Qwen-Agent.py'
if (Get-CimInstance Win32_Process -Filter "name = 'python.exe'" | Where-Object { $_.CommandLine -like ('*' + $agentPath + '*') }) {
    throw 'Close the Qwen agent before restoring.'
}
$original = Get-Content (Join-Path $manifest.backup 'original-files-sha256.json') -Raw | ConvertFrom-Json
foreach ($property in $manifest.changed_files.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $target $property.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) {
        throw "Source was edited after installation; refusing to overwrite: $($property.Name)"
    }
}
foreach ($property in $original.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $manifest.backup $property.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) {
        throw "Backup hash differs: $($property.Name)"
    }
}
foreach ($property in $original.PSObject.Properties) {
    Copy-Item -LiteralPath (Join-Path $manifest.backup $property.Name) -Destination (Join-Path $target $property.Name) -Force
    if ((Get-FileHash -LiteralPath (Join-Path $target $property.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) {
        throw "Restore hash differs: $($property.Name)"
    }
}
Write-Output 'Restored the two v4 source/settings files to the preceding verified profile.'
