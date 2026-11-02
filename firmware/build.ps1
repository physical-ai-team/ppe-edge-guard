# Compile / upload firmware/ppe_cam with the arduino-cli bundled in Arduino IDE.
# Run from repo root:
#   powershell -File firmware/build.ps1                 # compile only
#   powershell -File firmware/build.ps1 -Port <PORT>    # compile + upload (e.g. COM5)
# Comments are ASCII on purpose: Windows PowerShell 5.1 misreads BOM-less UTF-8 scripts.
param([string]$Port = "")
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot/..").Path
$fqbn = "esp32:esp32:XIAO_ESP32S3:PSRAM=opi"
$sketch = Join-Path $root "firmware/ppe_cam"
$buildPath = "C:\ppe_build"   # ASCII path outside the repo

$cli = (Get-Command arduino-cli -ErrorAction SilentlyContinue).Source
if (-not $cli) { $cli = "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" }
if (-not (Test-Path $cli)) { throw "arduino-cli not found (install Arduino IDE 2.x or put arduino-cli on PATH)" }

# Non-ASCII user folder (e.g. Korean): the ESP32 core under AppData fails to link
# (cannot find -lxtensa). Reach core and libraries through temporary subst drives.
$drives = @()
$data = Join-Path $env:LOCALAPPDATA "Arduino15"
$user = Join-Path $env:USERPROFILE "Documents\Arduino"
if ($data -match '[^\x00-\x7F]') {
    $used = (Get-PSDrive -PSProvider FileSystem).Name
    $free = 'W','V','U','T','S','R' | Where-Object { $used -notcontains $_ }
    $dd = $free[0] + ':'; $ud = $free[1] + ':'
    subst $dd $data; subst $ud $user; $drives = @($dd, $ud)
    $env:ARDUINO_DIRECTORIES_DATA = "$dd\"; $env:ARDUINO_DIRECTORIES_USER = "$ud\"
}
try {
    & $cli compile --fqbn $fqbn --build-path $buildPath $sketch
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($Port) {
        & $cli upload --fqbn $fqbn --build-path $buildPath -p $Port $sketch
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
} finally {
    foreach ($d in $drives) { subst $d /D }
}
