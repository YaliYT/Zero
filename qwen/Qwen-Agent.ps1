param(
    [Parameter(Position=0)][string]$Project,
    [ValidateSet('normal','acceptEdits','plan')][string]$Mode = 'normal',
    [switch]$Continue
)
$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'Qwen Code - CPU + GPU'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
Clear-Host
$serverReady = $false
try {
    $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
    $serverReady = $true
} catch {}
if (-not $serverReady) {
    Write-Host 'מפעיל Ollama...'
    $ollamaExecutable = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (-not (Test-Path -LiteralPath $ollamaExecutable)) { throw 'Ollama is not installed at the expected location.' }
    $serverProcess = Start-Process -FilePath $ollamaExecutable -ArgumentList 'serve' -WindowStyle Hidden -PassThru
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
            $serverReady = $true
            break
        } catch {}
        if ($serverProcess.HasExited) { break }
    }
    if (-not $serverReady) { throw 'Ollama did not become available at localhost:11434.' }
}
$pythonExecutable = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) { $pythonExecutable = (Get-Command python -ErrorAction Stop).Source }
$agentArguments = @('-u', (Join-Path $PSScriptRoot 'Qwen-Agent.py'), '--mode', $Mode)
if ($Project) { $agentArguments += @('--project', $Project) }
if ($Continue) { $agentArguments += '--continue' }
& $pythonExecutable @agentArguments
if ($LASTEXITCODE -ne 0) { throw "The Qwen agent exited with code $LASTEXITCODE." }
