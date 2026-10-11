@echo off
chcp 65001 >nul
cd /d "%~dp0"
"C:\Users\nagor\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Qwen-Agent.ps1" %*
if errorlevel 1 (
    echo.
    echo Agent could not start. The error is shown above.
    pause
)
