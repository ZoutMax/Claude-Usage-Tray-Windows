# Builds ClaudeUsageTray-Setup-<version>.exe — a per-user Windows installer that
# bundles the app with Python's official *embeddable* runtime (no PyInstaller/
# Nuitka packed exe, so no antivirus false-positives). Output lands in
# installer\dist-installer.
#
# Requires: Python 3.12 on PATH (to fetch the matching dependency wheels) and
# Inno Setup 6 (ISCC.exe). Install Inno Setup with:  winget install JRSoftware.InnoSetup
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$PyEmbedUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"

Write-Host "1/5  Fetching official embeddable Python..."
if (-not (Test-Path embed.zip)) { Invoke-WebRequest -Uri $PyEmbedUrl -OutFile embed.zip }

Write-Host "2/5  Assembling payload..."
if (Test-Path payload) { Remove-Item -Recurse -Force payload }
New-Item -ItemType Directory -Force payload\python | Out-Null
Expand-Archive -Path embed.zip -DestinationPath payload\python -Force
# enable site-packages imports in the embeddable runtime
@"
python312.zip
.
Lib\site-packages
import site
"@ | Set-Content -Encoding ASCII payload\python\python312._pth

Write-Host "3/5  Installing runtime dependencies into the payload..."
python -m pip install --quiet --disable-pip-version-check --target payload\python\Lib\site-packages pystray pillow

Write-Host "4/5  Copying app source..."
Copy-Item ..\claude_usage_tray.py payload\
New-Item -ItemType Directory -Force payload\assets | Out-Null
Copy-Item ..\assets\app.ico payload\assets\

Write-Host "5/5  Compiling installer with Inno Setup..."
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "ISCC.exe not found. Install Inno Setup 6: winget install JRSoftware.InnoSetup" }
& $iscc ClaudeUsageTray.iss

Get-ChildItem dist-installer\*.exe | ForEach-Object {
    Write-Host "`nBuilt: $($_.FullName)" -ForegroundColor Green
}
