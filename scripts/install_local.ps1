# Installs (or updates) the built app for the current user - no admin rights.
#   powershell -ExecutionPolicy Bypass -File scripts\install_local.ps1 [-NoDesktopShortcut]
#
# - copies dist\ScreenSyncRGB to %LOCALAPPDATA%\Programs\ScreenSyncRGB
# - creates Start Menu and (optionally) Desktop shortcuts
# - if "Start with Windows" is enabled, points it at the installed copy
# Settings and profiles (%APPDATA%\ScreenSyncRGB) are not touched.
param([switch]$NoDesktopShortcut)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$source = Resolve-Path "dist\ScreenSyncRGB"
if (-not (Test-Path "$source\ScreenSyncRGB.exe")) { throw "Build first: scripts\build_exe.ps1" }
$target = Join-Path $env:LOCALAPPDATA "Programs\ScreenSyncRGB"
$exe = Join-Path $target "ScreenSyncRGB.exe"

# ask a running instance to quit cleanly (restores lighting, releases the HID device)
if (Get-Process ScreenSyncRGB -ErrorAction SilentlyContinue) {
    & "$source\ScreenSyncRGB.exe" --quit
    for ($i = 0; $i -lt 40 -and (Get-Process ScreenSyncRGB -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 250 }
    if (Get-Process ScreenSyncRGB -ErrorAction SilentlyContinue) { throw "ScreenSync RGB is still running; quit it from the tray and retry" }
}

New-Item -ItemType Directory -Force $target | Out-Null
robocopy "$source" "$target" /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copy failed (robocopy exit $LASTEXITCODE)" }

$shell = New-Object -ComObject WScript.Shell
function New-Shortcut([string]$path) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $target
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = "ScreenSync RGB - keyboard ambient lighting"
    $lnk.Save()
}
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "ScreenSync RGB.lnk"
New-Shortcut $startMenu
Write-Host "Start Menu shortcut: $startMenu"
if (-not $NoDesktopShortcut) {
    $desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "ScreenSync RGB.lnk"
    New-Shortcut $desktop
    Write-Host "Desktop shortcut:    $desktop"
}

$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
if (Get-ItemProperty -Path $run -Name ScreenSyncRGB -ErrorAction SilentlyContinue) {
    Set-ItemProperty -Path $run -Name ScreenSyncRGB -Value "`"$exe`" --tray"
    Write-Host "Start with Windows now points to the installed copy"
}
Write-Host "Installed to $target"
