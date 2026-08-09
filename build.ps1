# Build ClaudeUsageTray.exe - a standalone Windows executable (no Python needed
# on the target machine). Output: dist\ClaudeUsageTray.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Installing build dependencies..."
python -m pip install --upgrade --quiet pyinstaller pystray pillow

Write-Host "Building..."
python -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name ClaudeUsageTray `
    --icon assets\app.ico `
    --hidden-import pystray._win32 `
    claude_usage_tray.py

$exe = Join-Path $PSScriptRoot "dist\ClaudeUsageTray.exe"
if (Test-Path $exe) {
    Write-Host "`nBuilt: $exe" -ForegroundColor Green
    Write-Host "Run install.ps1 to add it to autostart, or just double-click the exe."
} else {
    throw "Build failed: $exe not found"
}
