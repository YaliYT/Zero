# Read-only environment capture -> environment.json. Does not load the model or change any setting.
param([string]$Root = (Split-Path -Parent $PSScriptRoot), [string]$Backup = '')
$ErrorActionPreference = 'Continue'
function Try-Run([scriptblock]$block) { try { & $block } catch { "ERROR: $($_.Exception.Message)" } }
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = (Get-Command python -ErrorAction SilentlyContinue).Source }
$paths = Get-Content -LiteralPath (Join-Path $Root 'qwen-cpu-runner-paths.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$settings = Get-Content -LiteralPath (Join-Path $Root 'qwen-agent-settings.json') -Raw -Encoding UTF8 | ConvertFrom-Json
function FileFacts($p) { if ($p -and (Test-Path -LiteralPath $p)) { $i = Get-Item -LiteralPath $p; [ordered]@{path=$p;bytes=$i.Length;modified=$i.LastWriteTime.ToString('o');product_version=$i.VersionInfo.ProductVersion} } else { [ordered]@{path=$p;exists=$false} } }
# llama-server --version only prints build info (no model argument => nothing is loaded).
$llamaVersion = Try-Run {
    $exe = $paths.executable
    $old = $env:PATH; $env:PATH = (Split-Path -Parent $exe) + ';' + (Split-Path -Parent $paths.cuda_library) + ';' + $old
    $env:GGML_BACKEND_PATH = $paths.cuda_library
    $job = Start-Job { param($e,$p,$g) $env:PATH=$p; $env:GGML_BACKEND_PATH=$g; & $e --version 2>&1 | Out-String } -ArgumentList $exe,$env:PATH,$paths.cuda_library
    if (Wait-Job $job -Timeout 25) { (Receive-Job $job) } else { Stop-Job $job; 'timeout' }
    Remove-Job $job -Force; $env:PATH = $old
}
$nvidia = Try-Run { & nvidia-smi 2>&1 | Out-String }
$nvidiaQuery = Try-Run { & nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,power.limit,clocks.max.sm --format=csv 2>&1 | Out-String }
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$codeFiles = Get-ChildItem -LiteralPath $Root -File | Where-Object { $_.Extension -in '.py','.ps1','.bat' -or $_.Name -like 'qwen-*.json' -and $_.Name -notlike '*verification*' -and $_.Name -notlike '*benchmark*' -and $_.Name -notlike '*status*' }
$env = [ordered]@{
    captured_at = (Get-Date).ToString('o'); hostname = $env:COMPUTERNAME
    os = [ordered]@{caption=$os.Caption;version=$os.Version;build=$os.BuildNumber}
    python = [ordered]@{exe=$python; version=(Try-Run { & $python -VV 2>&1 | Out-String }).Trim()
        psutil = (Try-Run { & $python -c "import psutil;print(psutil.__version__)" 2>&1 | Out-String }).Trim()}
    vendor = Get-ChildItem -LiteralPath (Join-Path $Root 'vendor') -Directory -ErrorAction SilentlyContinue | ForEach-Object Name
    llama_server = [ordered]@{runner_paths=$paths; executable=(FileFacts $paths.executable); version_output=$llamaVersion}
    model_files = [ordered]@{model=(FileFacts $paths.model); projector=(FileFacts $paths.projector); cuda_library=(FileFacts $paths.cuda_library)}
    nvidia_smi = [ordered]@{query=$nvidiaQuery; full_output=$nvidia
        cuda_version=([regex]::Match([string]$nvidia,'CUDA Version:\s*([0-9.]+)').Groups[1].Value)
        driver_version=([regex]::Match([string]$nvidia,'Driver Version:\s*([0-9.]+)').Groups[1].Value)}
    power = [ordered]@{active_scheme=(Try-Run { (& powercfg /getactivescheme 2>&1 | Out-String).Trim() })
        on_battery=(Try-Run { Add-Type -AssemblyName System.Windows.Forms; [string][Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus })}
    cpu = Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,L3CacheSize
    gpu = Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM
    ram = [ordered]@{total_mib=[Math]::Round($cs.TotalPhysicalMemory/1MB,0); free_physical_mib_now=[Math]::Round($os.FreePhysicalMemory/1KB,0)
        modules=(Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,ConfiguredClockSpeed,Manufacturer)}
    pagefile = Get-CimInstance Win32_PageFileUsage | Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage
    processes_now = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'llama-server|ollama|python|Qwen' } |
        Select-Object ProcessName,Id,@{n='ws_mib';e={[Math]::Round($_.WorkingSet64/1MB,0)}}
    agent_settings = $settings
    code_sha256_at_capture = [ordered]@{}
}
foreach ($f in $codeFiles) { $env.code_sha256_at_capture[$f.Name] = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash }
if ($Backup) { $env.backup_folder = $Backup }
$env | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Root 'environment.json') -Encoding UTF8
"environment.json written: " + (Join-Path $Root 'environment.json')
