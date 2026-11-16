# ALE Workbench — local MySQL provisioning (idempotent).
# Reuses the existing database/apply_schema.py + database/migrate.py for DB creation
# and schema migration; never reimplements schema logic and never overwrites existing data.
#
# Modes:
#   * Detect an existing MySQL on $Port  -> verify and reuse; apply pending migrations
#     idempotently (never recreates tables or touches data).
#   * No existing MySQL + bundled mysqld -> deploy a standalone instance (data dir
#     kept OUTSIDE the install dir), create DB + accounts, apply migrations.
#
# Usage (from the installed project root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File launcher\deploy\deploy-mysql.ps1 `
#       -ProjectRoot "<install>" -MysqlDir "<install>\mysql" -Port 3307
param(
    [string]$ProjectRoot = '',
    [ValidateRange(1,65535)][int]$Port = 3307,
    [string]$DataDir = '',
    [string]$MysqlDir = '',
    [switch]$NoService
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$projectRoot = if ($ProjectRoot) { [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') }
               else { [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\') }
if (-not $DataDir) { $DataDir = Join-Path $env:PROGRAMDATA 'ALE Workbench\mysql-data' }
if (-not $MysqlDir) { $MysqlDir = Join-Path $projectRoot 'mysql-server' }

$mysqld = Join-Path $MysqlDir 'bin\mysqld.exe'
$mysqlExe = Join-Path $MysqlDir 'bin\mysql.exe'
$deployLog = Join-Path $projectRoot 'deploy-mysql.log'
$credsFile = Join-Path $projectRoot 'database\.dbcreds'
$appCredsFile = Join-Path $projectRoot 'database\.appcreds'
$migrateScript = Join-Path $projectRoot 'database\migrate.py'
$python = Join-Path $projectRoot 'python\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $projectRoot 'backend\.venv-win\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python)) { $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }

function Write-Result([bool]$ok, [string]$state, [string]$message) {
    [pscustomobject]@{ ok = $ok; state = $state; message = $message } | ConvertTo-Json -Compress
}

function Test-PortListening([int]$port) {
    try { return @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -eq $port }).Count -gt 0 }
    catch { return $false }
}

function Test-MysqlUsable([int]$port) {
    # Existing .appcreds holds the app account; if absent, try the admin creds file.
    # Read-only SELECT 1; never logs credentials.
    $creds = @()
    foreach ($f in @($appCredsFile, $credsFile)) {
        if (Test-Path -LiteralPath $f) {
            $text = Get-Content -LiteralPath $f -Raw -ErrorAction SilentlyContinue
            if ($text -match '(?ms)user\s*=\s*([^\r\n]+)') { $u = $Matches[1].Trim() }
            if ($text -match '(?ms)password\s*=\s*([^\r\n]+)') { $p = $Matches[1].Trim() }
            if ($u) { $creds += [pscustomobject]@{ user = $u; password = $p } }
        }
    }
    $env:MYSQL_PWD = ''
    foreach ($c in $creds) {
        try {
            $env:MYSQL_PWD = $c.password
            $out = & $mysqlExe --protocol=tcp -h 127.0.0.1 -P $port -u $c.user --connect-timeout=4 -N -e 'SELECT 1' 2>$null
            if ($LASTEXITCODE -eq 0) { return $true }
        } catch { }
    }
    return $false
}

# ---- Detect existing ----
if (Test-PortListening $Port) {
    if (Test-MysqlUsable $Port) {
        # Reuse the existing instance, but apply any pending migrations so a reinstall
        # (upgrade) picks up new schema changes. Idempotent and data-preserving.
        $env:ALE_DB_HOST = '127.0.0.1'
        $env:ALE_DB_PORT = "$Port"
        $env:PYTHONUTF8 = '1'
        if ($python -and (Test-Path -LiteralPath $migrateScript) -and (Test-Path -LiteralPath $credsFile)) {
            & $python $migrateScript --confirm-production 2>&1 | Out-File -FilePath $deployLog -Append -Encoding utf8
            if ($LASTEXITCODE -ne 0) {
                Write-Result $false 'upgrade-migrate-failed' "Existing MySQL reused, but migrate.py failed; pending schema changes were not applied. See $deployLog"
                exit 1
            }
        }
        Write-Result $true 'existing' "MySQL already running on port $Port and reachable; reused (pending migrations applied)."
        exit 0
    }
    # Port occupied but not a usable MySQL: do not overwrite or kill it.
    Write-Result $false 'conflict' "Port $Port is occupied by a non-workbench service. No MySQL was deployed or changed."
    exit 1
}

# ---- Deploy path: require a bundled mysqld ----
if (-not (Test-Path -LiteralPath $mysqld)) {
    Write-Result $false 'missing-runtime' "No existing MySQL and no bundled mysqld found at $mysqld. Install the MySQL runtime component."
    exit 1
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$dataMarker = Join-Path $DataDir 'auto.cnf'
$needsInit = -not (Test-Path -LiteralPath $dataMarker)

if ($needsInit) {
    Write-Host "Initializing standalone MySQL data directory at $DataDir ..."
    & $mysqld --initialize-insecure --datadir="$DataDir" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Result $false 'init-failed' 'MySQL data directory initialization failed. See installer log for details.'
        exit 1
    }
}

# Config file (bind loopback only; data dir kept outside install dir)
$ini = Join-Path $MysqlDir 'ale-my.ini'
@"
[mysqld]
datadir=$DataDir
port=$Port
bind-address=127.0.0.1
character-set-server=utf8mb4
"@ | Set-Content -LiteralPath $ini -Encoding ASCII

if ($NoService) {
    $proc = Start-Process -FilePath $mysqld -ArgumentList @("--defaults-file=`"$ini`"", '--console') -WindowStyle Hidden -PassThru
} else {
    # Install/start as a Windows service if not already present (idempotent).
    $svc = Get-CimInstance Win32_Service -Filter "Name='ALEWorkbenchMySQL'" -ErrorAction SilentlyContinue
    if (-not $svc) {
        & $mysqld --install ALEWorkbenchMySQL --defaults-file="$ini" 2>&1 | Out-Null
    }
    Start-Service ALEWorkbenchMySQL -ErrorAction SilentlyContinue
}

# Wait for the port to listen
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    if (Test-PortListening $Port) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    Write-Result $false 'start-timeout' 'MySQL did not start listening within the timeout.'
    exit 1
}

# ---- Create DB + app accounts (reuse existing apply_schema.py), then migrate ----
$dbScript = Join-Path $projectRoot 'database\apply_schema.py'
if (-not $python) {
    Write-Result $false 'no-python' 'Python runtime not found; cannot run apply_schema.py.'
    exit 1
}

if ($needsInit) {
    # Fresh insecure init: admin account is root with empty password. Write a creds file
    # only for this first-time bootstrap; apply_schema.py then generates real app accounts.
    @"
user=root
password=
"@ | Set-Content -LiteralPath $credsFile -Encoding ASCII
}

# Point the schema/migration scripts at THIS instance (they honor ALE_DB_HOST/PORT),
# and force UTF-8 so ✓/中文字符 don't crash on a GBK console.
$env:ALE_DB_HOST = '127.0.0.1'
$env:ALE_DB_PORT = "$Port"
$env:PYTHONUTF8 = '1'

& $python $dbScript 2>&1 | Out-File -FilePath $deployLog -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) {
    Write-Result $false 'schema-create-failed' "apply_schema.py failed; database was not created. See $deployLog"
    exit 1
}
& $python $migrateScript --confirm-production 2>&1 | Out-File -FilePath $deployLog -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) {
    Write-Result $false 'migrate-failed' "migrate.py failed; schema is incomplete. See $deployLog"
    exit 1
}

# Backend signing secret — created fresh if missing, never overwritten on upgrade.
$envFile = Join-Path $projectRoot 'backend\.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 32
    $rng.GetBytes($bytes)
    $secret = -join ($bytes | ForEach-Object { $_.ToString('x2') })
    @"
ALE_JWT_SECRET=$secret
ALE_COOKIE_SECURE=false
"@ | Set-Content -LiteralPath $envFile -Encoding ASCII
}

# One-time setup code — created fresh if missing, never overwritten on upgrade.
# Fallback bootstrap: used to create the first administrator when no preset admin is
# shipped (see seed_admin.py below). No plaintext value is ever logged.
$setupCodeFile = Join-Path $projectRoot 'backend\.setup-code'
if (-not (Test-Path -LiteralPath $setupCodeFile)) {
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 24
    $rng.GetBytes($bytes)
    $code = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    Set-Content -LiteralPath $setupCodeFile -Value $code -Encoding ASCII -NoNewline
}

# Preset administrator — when the installer ships a .admin-password file, seed an
# admin account so the workstation opens directly (no setup-code flow). Idempotent:
# seed_admin.py never overwrites an existing admin. The plaintext file is removed on
# success; it is never committed to version control.
$seedScript = Join-Path $projectRoot 'database\seed_admin.py'
$adminPwFile = Join-Path $projectRoot 'database\.admin-password'
if ((Test-Path -LiteralPath $seedScript) -and (Test-Path -LiteralPath $adminPwFile)) {
    $env:ALE_ADMIN_PASSWORD = (Get-Content -LiteralPath $adminPwFile -Raw).Trim()
    & $python $seedScript 2>&1 | Out-File -FilePath $deployLog -Append -Encoding utf8
    $seedExit = $LASTEXITCODE
    Remove-Item Env:ALE_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    if ($seedExit -ne 0) {
        Write-Result $false 'seed-admin-failed' "seed_admin.py failed; preset administrator was not created. See $deployLog"
        exit 1
    }
    Remove-Item -LiteralPath $adminPwFile -Force -ErrorAction SilentlyContinue
}

Write-Result $true 'deployed' "MySQL deployed on port $Port; database and schema ready."
exit 0
