$ErrorActionPreference = 'Stop'
$manifest = Get-Content (Join-Path $PSScriptRoot 'token-speed-tests-v2-20261011\installation.json') -Raw | ConvertFrom-Json
if (Get-CimInstance Win32_Process -Filter "name = 'llama-server.exe'") { throw 'Close the agent/model first.' }
$original = Get-Content (Join-Path $manifest.backup 'original-files-sha256.json') -Raw | ConvertFrom-Json
foreach ($item in $original.PSObject.Properties) {
    if ($null -ne $item.Value) {
        $source = Join-Path $manifest.backup $item.Name
        if ((Get-FileHash $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.Value) { throw "Backup hash differs: $($item.Name)" }
    }
}
foreach ($item in $original.PSObject.Properties) {
    if ($null -ne $item.Value) { Copy-Item -LiteralPath (Join-Path $manifest.backup $item.Name) -Destination (Join-Path $PSScriptRoot $item.Name) -Force }
}
'Restored previous agent code and settings. Sessions, model weights and isolated runtime files were preserved.'
