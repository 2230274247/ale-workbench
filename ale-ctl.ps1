# ALE Workbench control script: safe stop / status query.
# Shares the exact process-identity + launch-provenance verification logic
# with start-workbench.ps1. The functions below (Get-Listeners,
# Test-UvicornCommand, Get-ManualAdvice, Get-ProjectListener, Get-TrustedRecord,
# Test-HttpReady) are copied verbatim from start-workbench.ps1 as the single
# source of truth; if the upstream checks change, mirror them here.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File ale-ctl.ps1 -Action status [-Port 8001]
#   powershell -NoProfile -ExecutionPolicy Bypass -File ale-ctl.ps1 -Action stop   [-Port 8001]
# Output is one line of compact JSON.
param(
    [ValidateSet('status','stop')][string]$Action = 'status',
    [ValidateRange(1,65535)][int]$Port = 8001,
    [string]$ProjectRoot = ''
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$projectRoot = if ($ProjectRoot) { [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') } else { [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') }
$backendRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'backend')).TrimEnd('\')
$runtimePath = Join-Path $projectRoot 'backend\.runtime'
$pythonPath = Join-Path $projectRoot 'python\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = Join-Path $projectRoot 'backend\.venv-win\Scripts\python.exe'
}
$expectedVersion = '1.9.0'
$statePath = Join-Path $runtimePath "server-$Port.json"
$baseUrl = "http://127.0.0.1:$Port"

function Get-TcpListenEndpoints {
    @([Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
        Where-Object { $_.Port -eq $Port })
}
function Get-Listeners {
    # Windows can expose a live Python socket with an empty or Closed CIM State.
    # Cross-check remote-less rows against the OS listener endpoint API instead
    # of trusting the State label. Never treat an inspection error as a free port.
    $endpoints = @(Get-TcpListenEndpoints)
    try {
        $rows = @(Get-NetTCPConnection -LocalPort $Port -ErrorAction Stop)
    } catch {
        if ($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound*' -and !$endpoints.Count) { return @() }
        throw
    }
    $listeners = @($rows | Where-Object {
        $row = $_
        $matched = @($endpoints | Where-Object { $_.Address.ToString() -eq $row.LocalAddress }).Count -gt 0
        ([string]$row.State -in 'Listen','Bound') -or ([int]$row.RemotePort -eq 0 -and $matched)
    })
    foreach ($endpoint in $endpoints) {
        if (!@($listeners | Where-Object { $_.LocalAddress -eq $endpoint.Address.ToString() }).Count) {
            throw "Port $Port listener ownership could not be inspected. No process was stopped. Retry the launcher."
        }
    }
    $listeners
}
function Test-UvicornCommand($CommandLine) {
    # Accept only the single-worker loopback invocation used by this launcher/manual instructions.
    # Unknown flags, reload/workers, another module or an implicit port fail closed.
    if (!$CommandLine) { return $false }
    $tokens = @([regex]::Matches($CommandLine, '"[^"]*"|\S+') | ForEach-Object { $_.Value.Trim('"') })
    if ($tokens.Count -lt 8 -or $tokens[1] -cne '-m' -or $tokens[2] -cne 'uvicorn' -or $tokens[3] -cne 'app.main:app') { return $false }
    if ([IO.Path]::GetFileName($tokens[0]) -ine 'python.exe') { return $false }
    $seenHost = $false; $seenPort = $false; $seenLog = $false; $seenAppDir = $false
    for ($i = 4; $i -lt $tokens.Count; $i++) {
        switch -Exact ($tokens[$i]) {
            '--host' {
                if ($seenHost -or ++$i -ge $tokens.Count -or $tokens[$i] -cne '127.0.0.1') { return $false }
                $seenHost = $true
            }
            '--port' {
                if ($seenPort -or ++$i -ge $tokens.Count -or $tokens[$i] -cne "$Port") { return $false }
                $seenPort = $true
            }
            '--app-dir' {
                if ($seenAppDir -or ++$i -ge $tokens.Count -or $tokens[$i] -ine $backendRoot) { return $false }
                $seenAppDir = $true
            }
            '--no-access-log' { if ($seenLog) { return $false }; $seenLog = $true }
            default { return $false }
        }
    }
    return ($seenHost -and $seenPort -and $seenAppDir)
}
function Get-ManualAdvice {
    'No automatic reuse or stop of an unverified process. Check the PID, creation time and --app-dir with Get-NetTCPConnection and Get-CimInstance Win32_Process. Close the known original server with Ctrl+C, or choose a different free port (for example -Port 8002). See startup instructions.'
}
function Get-ProjectListener {
    $listeners = @(Get-Listeners)
    $ids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($ids.Count -ne 1 -or @($listeners | Where-Object { $_.LocalAddress -ne '127.0.0.1' }).Count) {
        throw "Port $Port has an unrecognized listener. No process was stopped. $(Get-ManualAdvice)"
    }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($ids[0])" -ErrorAction Stop
    if (!$proc -or !$proc.ExecutablePath -or !$proc.CreationDate -or !(Test-UvicornCommand $proc.CommandLine)) {
        throw "Port $Port process identity cannot be verified. No process was stopped. $(Get-ManualAdvice)"
    }
    $launcher = $proc
    $owned = $proc.ExecutablePath -ieq $pythonPath
    if (!$owned) {
        # Windows venv redirectors may launch the base interpreter as their child.
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.ParentProcessId)" -ErrorAction Stop
        $venvConfig = Join-Path $projectRoot 'backend\.venv-win\pyvenv.cfg'
        $baseExecutable = ''
        if (Test-Path -LiteralPath $venvConfig) {
            foreach ($line in (Get-Content -LiteralPath $venvConfig)) {
                if ($line -match '^executable\s*=\s*(.+)$') { $baseExecutable = $Matches[1].Trim() }
            }
        }
        $owned = $parent -and $parent.ExecutablePath -ieq $pythonPath -and
            (Test-UvicornCommand $parent.CommandLine) -and $parent.CreationDate -le $proc.CreationDate -and
            $baseExecutable -and $proc.ExecutablePath -ieq $baseExecutable
    }
    if (!$owned) { throw "Port $Port belongs to an unrecognized executable/parent chain. No process was stopped. $(Get-ManualAdvice)" }
    if ($owned -and $proc.ExecutablePath -ine $pythonPath) { $launcher = $parent }
    [pscustomobject]@{
        LauncherId = [int]$launcher.ProcessId
        LauncherCreatedUtc = $launcher.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.ffffffZ')
        LauncherExecutable = $launcher.ExecutablePath
        LauncherCommandLine = $launcher.CommandLine
        Id = [int]$proc.ProcessId
        CreatedUtc = $proc.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.ffffffZ')
        Executable = $proc.ExecutablePath
        CommandLine = $proc.CommandLine
    }
}
function Get-TrustedRecord($Identity) {
    # User-owned launcher file is trusted only with complete launch provenance.
    # Never infer project ownership from a shared interpreter or HTTP responses.
    $state = $null
    try { $state = Get-Content -LiteralPath $statePath -Raw -ErrorAction Stop | ConvertFrom-Json } catch {}
    $nonce = [Guid]::Empty
    if (!$state -or $state.schema -ne 2 -or
        ![Guid]::TryParse([string]$state.launchNonce, [ref]$nonce) -or $nonce -eq [Guid]::Empty -or
        $state.projectRoot -ine $projectRoot -or $state.backendRoot -ine $backendRoot -or
        $state.port -ne $Port -or $state.pid -ne $Identity.Id -or
        $state.createdUtc -cne $Identity.CreatedUtc -or $state.executable -ine $Identity.Executable -or
        $state.commandLine -cne $Identity.CommandLine -or
        $state.launcherPid -ne $Identity.LauncherId -or
        $state.launcherCreatedUtc -cne $Identity.LauncherCreatedUtc -or
        $state.launcherExecutable -ine $Identity.LauncherExecutable -or
        $state.launcherCommandLine -cne $Identity.LauncherCommandLine -or
        !$state.version -or $state.fingerprint -cnotmatch '^[A-Fa-f0-9]{64}$') {
        throw "Port $Port has no matching trusted launcher record. No process was stopped. $(Get-ManualAdvice)"
    }
    return $state
}
function Test-Health {
    # Lightweight health gate: the running backend must report both service and DB OK.
    try {
        $health = Invoke-RestMethod "$baseUrl/health" -TimeoutSec 3
        return ($health.code -eq 0 -and $health.data.status -eq 'ok' -and $health.data.database -eq 'ok')
    } catch { return $false }
}

function Get-IdentitySafe {
    # Return the verified managed listener identity, or $null when the port is free,
    # or throw when the port is occupied by something unrecognized (never touch it).
    if (@(Get-Listeners).Count -eq 0) { return $null }
    $identity = Get-ProjectListener
    $null = Get-TrustedRecord $identity
    return $identity
}

function Stop-VerifiedBackend($Identity) {
    # Same verified-process termination as the existing restart path: re-verify the
    # listener identity and its trusted record, pin the OS handle, check creation
    # time, then terminate only that one PID and confirm the port is released.
    $again = Get-ProjectListener
    $null = Get-TrustedRecord $again
    if ($again.Id -ne $Identity.Id -or $again.CreatedUtc -cne $Identity.CreatedUtc -or
        $again.Executable -ine $Identity.Executable -or $again.CommandLine -cne $Identity.CommandLine) {
        throw 'Listener identity changed before stop. No process was stopped.'
    }
    $handle = [Diagnostics.Process]::GetProcessById($Identity.Id)
    try {
        $null = $handle.Handle
        if ($handle.StartTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.ffffffZ') -cne $Identity.CreatedUtc) {
            throw 'Process creation time changed. No process was stopped.'
        }
        $handle.Kill()
        if (!$handle.WaitForExit(10000)) { throw 'Verified backend did not exit; stop aborted.' }
    } finally { $handle.Dispose() }
    for ($i = 0; $i -lt 20; $i++) {
        if (@(Get-Listeners).Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Port $Port is still occupied after stop. No additional process was stopped."
}

# ------------------------------------------------------------
$result = $null
try {
    if ($Action -eq 'stop') {
        try {
            $identity = Get-IdentitySafe
            if ($null -eq $identity) {
                $result = [pscustomobject]@{ ok=$true; action='stop'; state='already_stopped'; port=$Port; healthy=$false; message='Backend is not running.' }
            } else {
                Stop-VerifiedBackend $identity | Out-Null
                $result = [pscustomobject]@{ ok=$true; action='stop'; state='stopped'; port=$Port; pid=$identity.Id; healthy=$false; message="Stopped managed backend PID=$($identity.Id)." }
            }
        } catch {
            $result = [pscustomobject]@{ ok=$true; action='stop'; state='refused'; port=$Port; healthy=$false; message="Port $Port is occupied by a non-workbench process; stop refused, no process was killed."; detail=$_.Exception.Message }
        }
    } else {
        # status
        $listenerCount = @(Get-Listeners).Count
        if ($listenerCount -eq 0) {
            $result = [pscustomobject]@{ ok=$true; action='status'; state='stopped'; port=$Port; healthy=$false; database='unknown'; baseUrl=$baseUrl; message='Backend is not running.' }
        } else {
            try {
                $identity = Get-IdentitySafe
                $healthy = Test-Health
                $db = 'unknown'
                $msg = "Backend process exists but health check failed (PID=$($identity.Id))."
                if ($healthy) { $db = 'ok'; $msg = "Backend running and healthy (PID=$($identity.Id))." }
                $result = [pscustomobject]@{ ok=$true; action='status'; state='running'; port=$Port; healthy=$healthy; database=$db; pid=$identity.Id; baseUrl=$baseUrl; message=$msg }
            } catch {
                $result = [pscustomobject]@{ ok=$true; action='status'; state='foreign'; port=$Port; healthy=$false; database='unknown'; baseUrl=$baseUrl; message="Port $Port is occupied by a non-workbench process."; detail=$_.Exception.Message }
            }
        }
    }
} catch {
    $result = [pscustomobject]@{ ok=$false; action=$Action; state='error'; port=$Port; healthy=$false; database='unknown'; baseUrl=$baseUrl; message="Control script failed: $($_.Exception.Message)" }
}

$result | ConvertTo-Json -Compress
exit 0
