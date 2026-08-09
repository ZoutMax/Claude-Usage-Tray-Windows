# Install Claude Usage Tray: copy the built exe to a stable location, register
# it to start at login, and launch it now.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$src = Join-Path $PSScriptRoot "dist\ClaudeUsageTray.exe"
if (-not (Test-Path $src)) {
    throw "dist\ClaudeUsageTray.exe not found - run build.ps1 first."
}

$dstDir = Join-Path $env:LOCALAPPDATA "ClaudeUsageTray"
New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
$dst = Join-Path $dstDir "ClaudeUsageTray.exe"

# Stop a running instance so the file isn't locked, then copy.
Get-Process ClaudeUsageTray -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 400
Copy-Item $src $dst -Force

# Autostart via the per-user Run key.
$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Set-ItemProperty -Path $run -Name "ClaudeUsageTray" -Value "`"$dst`""

Start-Process $dst
Write-Host "Installed to $dst" -ForegroundColor Green
Write-Host "It will start automatically at login and is running now (check the system tray)."
