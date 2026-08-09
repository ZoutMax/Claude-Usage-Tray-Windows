# Remove Claude Usage Tray: stop it, remove the autostart entry, delete files.
$ErrorActionPreference = "SilentlyContinue"

Get-Process ClaudeUsageTray | Stop-Process -Force
$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Remove-ItemProperty -Path $run -Name "ClaudeUsageTray"
$dstDir = Join-Path $env:LOCALAPPDATA "ClaudeUsageTray"
Remove-Item -Recurse -Force $dstDir

Write-Host "Claude Usage Tray removed (autostart entry and installed files deleted)."
