# Installs (or updates) the built app for the current user - no admin rights.
#   powershell -ExecutionPolicy Bypass -File scripts\install_local.ps1 [-NoDesktopShortcut]
#
# - copies dist\Refletseher to %LOCALAPPDATA%\Programs\Refletseher
# - creates Start Menu and (optionally) Desktop shortcuts
# - if "Start with Windows" is enabled, points it at the installed copy
# Settings and profiles (%APPDATA%\Refletseher) are not touched.
param([switch]$NoDesktopShortcut)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$source = Resolve-Path "dist\Refletseher"
if (-not (Test-Path "$source\Refletseher.exe")) { throw "Build first: scripts\build_exe.ps1" }
$target = Join-Path $env:LOCALAPPDATA "Programs\Refletseher"
$exe = Join-Path $target "Refletseher.exe"

# v1.0.x was installed as "ScreenSync RGB": stop it and remove its files/shortcuts
$legacyName = "ScreenSync" + "RGB"
$legacyDir = Join-Path $env:LOCALAPPDATA "Programs\$legacyName"
if (Get-Process $legacyName -ErrorAction SilentlyContinue) {
    $legacyExe = Join-Path $legacyDir "$legacyName.exe"
    if (Test-Path $legacyExe) { & $legacyExe --quit }
    for ($i = 0; $i -lt 40 -and (Get-Process $legacyName -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 250 }
}
if ((Test-Path $legacyDir) -and -not (Get-Process $legacyName -ErrorAction SilentlyContinue)) {
    Remove-Item -Recurse -Force $legacyDir
    Write-Host "Removed old install: $legacyDir"
}
foreach ($old in @((Join-Path ([Environment]::GetFolderPath("Programs")) "ScreenSync RGB.lnk"),
                   (Join-Path ([Environment]::GetFolderPath("Desktop")) "ScreenSync RGB.lnk"))) {
    if (Test-Path $old) { Remove-Item -Force $old; Write-Host "Removed old shortcut: $old" }
}

# ask a running instance to quit cleanly (restores lighting, releases the HID device)
if (Get-Process Refletseher -ErrorAction SilentlyContinue) {
    & "$source\Refletseher.exe" --quit
    for ($i = 0; $i -lt 40 -and (Get-Process Refletseher -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 250 }
    if (Get-Process Refletseher -ErrorAction SilentlyContinue) { throw "Refletseher is still running; quit it from the tray and retry" }
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
    $lnk.Description = "Refletseher - keyboard ambient lighting"
    $lnk.Save()
}
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "Refletseher.lnk"
New-Shortcut $startMenu
Write-Host "Start Menu shortcut: $startMenu"
if (-not $NoDesktopShortcut) {
    $desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "Refletseher.lnk"
    New-Shortcut $desktop
    Write-Host "Desktop shortcut:    $desktop"
}

$run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$hadLegacy = [bool](Get-ItemProperty -Path $run -Name $legacyName -ErrorAction SilentlyContinue)
if ($hadLegacy) { Remove-ItemProperty -Path $run -Name $legacyName }
if ($hadLegacy -or (Get-ItemProperty -Path $run -Name Refletseher -ErrorAction SilentlyContinue)) {
    Set-ItemProperty -Path $run -Name Refletseher -Value "`"$exe`" --tray"
    Write-Host "Start with Windows now points to the installed copy"
}
Write-Host "Installed to $target"
