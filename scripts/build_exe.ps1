# Builds dist\ScreenSyncRGB\ScreenSyncRGB.exe (and a zip) with uv + PyInstaller.
#   powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
uv run python scripts/make_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }
uv run pytest -q
if ($LASTEXITCODE -ne 0) { throw "tests failed - not packaging" }
uv run pyinstaller packaging/ScreenSyncRGB.spec --noconfirm --clean --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

$exe = "dist\ScreenSyncRGB\ScreenSyncRGB.exe"
if (-not (Test-Path $exe)) { throw "executable missing" }
# licence texts travel with the binaries
Copy-Item LICENSE, THIRD-PARTY-NOTICES.md -Destination "dist\ScreenSyncRGB\" -Force
$zip = "dist\ScreenSyncRGB-1.0.0-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\ScreenSyncRGB\*" -DestinationPath $zip
Write-Host "Built $exe"
Write-Host "Archive $zip"
