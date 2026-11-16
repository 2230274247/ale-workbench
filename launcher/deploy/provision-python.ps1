# ALE Workbench -- portable Python runtime provisioning (build-time helper).
#
# Produces a self-contained CPython tree at <Target> that does NOT depend on the
# build machine's installed Python, registry keys, or a .venv-win. It is used by
# the installer so a clean machine can run the FastAPI backend without any Python.
#
# Approach:
#   1. Copy the base CPython install (python.exe + python314.dll + stdlib).
#   2. Drop the base install's site-packages (unrelated global packages) and
#      build-time / test-only directories to keep the bundle clean.
#   3. Overlay the already-verified wheel set from the development venv's
#      site-packages (same ABI 3.14.x), excluding the test-only "playwright".
#
# This script does NOT touch the database, does NOT read credentials, and only
# copies public Python runtime + dependency files.
param(
    [string]$Target = '',
    [string]$SourcePythonDir = '',   # base CPython install (contains python.exe + python314.dll)
    [string]$VenvDir = ''            # dev venv (contains Lib/site-packages)
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')  # launcher/deploy
$projectRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot '..\..')).TrimEnd('\')
if (-not $Target) { $Target = Join-Path $projectRoot 'python' }
$Target = [IO.Path]::GetFullPath($Target).TrimEnd('\')

# Locate the venv.
if (-not $VenvDir) { $VenvDir = Join-Path $projectRoot 'backend\.venv-win' }
if (-not (Test-Path -LiteralPath (Join-Path $VenvDir 'Lib\site-packages'))) {
    throw "Development venv not found at $VenvDir (Lib\site-packages)."
}

# Locate the base CPython install, preferring an explicit value, then the venv's
# pyvenv.cfg 'home', then the well-known 3.14 location.
if (-not $SourcePythonDir) {
    $cfg = Join-Path $VenvDir 'pyvenv.cfg'
    if (Test-Path -LiteralPath $cfg) {
        foreach ($line in (Get-Content -LiteralPath $cfg)) {
            if ($line -match '^home\s*=\s*(.+)$') { $SourcePythonDir = $Matches[1].Trim(); break }
        }
    }
}
if (-not $SourcePythonDir -or -not (Test-Path -LiteralPath (Join-Path $SourcePythonDir 'python.exe'))) {
    throw "Base CPython install not found. Pass -SourcePythonDir <dir>."
}
$SourcePythonDir = [IO.Path]::GetFullPath($SourcePythonDir).TrimEnd('\')

$venvSite = Join-Path $VenvDir 'Lib\site-packages'

Write-Host "Copying base CPython from $SourcePythonDir ..."
if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -Path (Join-Path $SourcePythonDir '*') -Destination $Target -Recurse -Force

# Drop unrelated global packages and build-time directories from the base copy.
foreach ($drop in @('Lib\site-packages', 'Lib\test', 'Doc', 'Tools', 'include', 'libs', 'tcl')) {
    $p = Join-Path $Target $drop
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
}

Write-Host "Overlaying verified dependency wheels from $venvSite ..."
$dstSite = Join-Path $Target 'Lib\site-packages'
New-Item -ItemType Directory -Force -Path $dstSite | Out-Null
Copy-Item -Path (Join-Path $venvSite '*') -Destination $dstSite -Recurse -Force
# playwright is a browser-automation test dependency, not a runtime backend dep.
$pw = Join-Path $dstSite 'playwright'
if (Test-Path -LiteralPath $pw) { Remove-Item -LiteralPath $pw -Recurse -Force }

# Verification: import every runtime dependency the backend uses. Rely on the exit
# code only (no print statement — PowerShell mangles embedded quotes for native args).
$tgtPython = Join-Path $Target 'python.exe'
Write-Host "Verifying portable runtime imports ..."
$probe = 'import fastapi, pydantic, uvicorn, sqlalchemy, pymysql, jwt, argon2, dotenv, yaml, email_validator, httpx, pytest, jsonschema, openpyxl, defusedxml, multipart, cryptography'
$errFile = Join-Path $env:TEMP 'ale-python-probe.err'
$prevPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'   # native stderr must not abort verification
& $tgtPython -c $probe 1>$null 2>$errFile
$exit = $LASTEXITCODE
$ErrorActionPreference = $prevPref
if ($exit -ne 0) {
    $err = Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue
    Write-Error "Portable runtime verification failed:`n$err"
    exit 1
}
Write-Host "Portable Python ready at $Target (imports verified)."
exit 0
