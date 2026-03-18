param(
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not $PythonExe) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $PythonExe = $pythonCommand.Source
    } else {
        throw "python was not found. Use -PythonExe to point at your venv or conda python.exe."
    }
}

if (-not (Test-Path $PythonExe)) {
    throw "Python executable was not found: $PythonExe"
}

$RequiredSidecars = @(
    "bin\ffmpeg.exe",
    "bin\ffprobe.exe",
    "bin\yt-dlp.exe"
)

$MissingSidecars = @()
foreach ($RelativePath in $RequiredSidecars) {
    $FullPath = Join-Path $ProjectRoot $RelativePath
    if (-not (Test-Path $FullPath)) {
        $MissingSidecars += $RelativePath
    }
}

if ($MissingSidecars.Count -gt 0) {
    $MissingText = ($MissingSidecars | ForEach-Object { " - $_" }) -join "`n"
    throw "Missing release sidecars:`n$MissingText`nSee bin\README.md for the required files."
}

Write-Host "==> Installing build dependency"
& $PythonExe -m pip install -r requirements.build.txt

Write-Host "==> Cleaning old artifacts"
foreach ($Folder in @("build", "dist")) {
    $Target = Join-Path $ProjectRoot $Folder
    if (Test-Path $Target) {
        Remove-Item $Target -Recurse -Force
    }
}

Write-Host "==> Running PyInstaller"
& $PythonExe -m PyInstaller --noconfirm .\subforge.release.spec

$DistRoot = Join-Path $ProjectRoot "dist\SubForge"
if (-not (Test-Path $DistRoot)) {
    throw "Build finished but dist\SubForge was not created."
}

$ConfigTarget = Join-Path $DistRoot "config.json"
if (-not (Test-Path $ConfigTarget)) {
    Copy-Item (Join-Path $ProjectRoot "config.example.json") $ConfigTarget
}

Write-Host "Done: $DistRoot"
