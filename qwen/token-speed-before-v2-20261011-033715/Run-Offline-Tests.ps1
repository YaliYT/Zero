<#
 Offline tests: no model, no llama-server, no real memory purge (every test uses fake Windows/API objects).
 -Label  names the result set  (verification\<Label>\ ; default: latest)
 -OriginalOnly runs just the eight historical scripts.
#>
param([string]$Python, [string]$Label = 'latest', [switch]$OriginalOnly)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
if (-not $Python) {
    $Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (-not (Test-Path -LiteralPath $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
}
$logPath = Join-Path (Join-Path $PSScriptRoot 'verification') $Label
New-Item -ItemType Directory -Path $logPath -Force | Out-Null
$tests = @('test_memory_guard.py','test_memory_target.py','test_active_cleanup.py',
           'test_request_paging.py','test_native_stream.py','test_coding_features.py',
           'test_command_completion.py','test_hebrew_console.py')
if (-not $OriginalOnly) { $tests += @('test_memory_hysteresis.py','test_progress_guards.py','test_agent_loop.py','test_link_boundaries.py') }
$results = @()
foreach ($name in $tests) {
    $script = Join-Path $PSScriptRoot ('work\' + $name)
    if (-not (Test-Path -LiteralPath $script)) { $results += [pscustomobject]@{test=$name;exit_code=-1;seconds=0;note='missing'}; continue }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $logFile = Join-Path $logPath ($name + '.log')
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    cmd /c "`"$Python`" -u `"$script`" > `"$logFile`" 2>&1"
    $ErrorActionPreference = $prev
    $code = $LASTEXITCODE
    $watch.Stop()
    $results += [pscustomobject]@{test=$name;exit_code=$code;seconds=[Math]::Round($watch.Elapsed.TotalSeconds,3)}
}
$report = [pscustomobject]@{label=$Label;checked_at=(Get-Date).ToString('o');python=$Python;
    all_passed=(@($results | Where-Object { $_.exit_code -ne 0 }).Count -eq 0);tests=$results}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $logPath 'offline-tests.json') -Encoding UTF8
$report | ConvertTo-Json -Depth 5
if (-not $report.all_passed) { exit 1 }
