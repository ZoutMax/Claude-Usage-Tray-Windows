# Build ClaudeUsageTray.exe - a standalone Windows executable compiled to native
# code with Nuitka (no Python needed on the target machine). Native compilation
# avoids the antivirus / SmartScreen "Virus detected" false-positives that
# PyInstaller one-file exes trigger. Output: dist\ClaudeUsageTray.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Installing build dependencies (Nuitka + runtime libs)..."
python -m pip install --upgrade --quiet nuitka pystray pillow

Write-Host "Compiling to native code (first run downloads a MinGW64 toolchain; takes a few minutes)..."
python -m nuitka --onefile `
    --windows-console-mode=disable `
    --windows-icon-from-ico=assets\app.ico `
    --include-module=pystray._win32 `
    --assume-yes-for-downloads `
    --output-filename=ClaudeUsageTray.exe `
    --output-dir=dist `
    claude_usage_tray.py

$exe = Join-Path $PSScriptRoot "dist\ClaudeUsageTray.exe"
if (Test-Path $exe) {
    Write-Host "`nBuilt: $exe" -ForegroundColor Green
    Write-Host "Run install.ps1 to add it to autostart, or just double-click the exe."
} else {
    throw "Build failed: $exe not found"
}
