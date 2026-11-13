param([switch]$Install, [ValidateRange(1,65535)][int]$Port = 8001)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$backendRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'backend')).TrimEnd('\')
Set-Location $projectRoot
$runtimePath = Join-Path $projectRoot 'backend\.runtime'
New-Item -ItemType Directory -Force $runtimePath | Out-Null
$pythonPath = Join-Path $projectRoot 'backend\.venv-win\Scripts\python.exe'
$expectedVersion = '1.9.0'
$statePath = Join-Path $runtimePath "server-$Port.json"
$baseUrl = "http://127.0.0.1:$Port"

function Get-Listeners {
    # Do not treat an unavailable TCP inspection API as a free port.
    # Python 3.14 (uvicorn) reports its listening socket with an empty State here,
    # so -State Listen silently misses it. Match by port and keep the listening
    # side only: State Listen/Bound, or an empty State with no remote peer
    # (RemotePort 0); an in-flight connection always has a remote port.
    # A vacant port legitimately returns no rows (NotFound); any other failure
    # must surface instead of being mistaken for a free port.
    try {
        $rows = @(Get-NetTCPConnection -LocalPort $Port -ErrorAction Stop)
    } catch {
        if ($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound*') { return @() }
        throw
    }
    @($rows | Where-Object {
        $s = [string]$_.State
        ($s -in 'Listen','Bound') -or ($s -eq '' -and [int]$_.RemotePort -eq 0)
    })
}
function Get-BackendFingerprint {
    # Only public source/build inputs; never read .env, keys, data or uploads.
    $files = @(Get-ChildItem (Join-Path $projectRoot 'backend\app') -Recurse -File -Filter '*.py')
    $files += Get-Item (Join-Path $projectRoot 'backend\requirements.txt')
    $files += Get-Item (Join-Path $projectRoot 'api\openapi\openapi.bundled.yaml')
    $files += Get-Item (Join-Path $projectRoot 'frontend\package.json')
    $files += Get-Item (Join-Path $projectRoot 'frontend\package-lock.json')
    $files += @(Get-ChildItem (Join-Path $projectRoot 'frontend\dist') -Recurse -File)
    $lines = @($files | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($projectRoot.Length) + ':' + (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    })
    $sha = [Security.Cryptography.SHA256]::Create()
    try { ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))))).Replace('-','') }
    finally { $sha.Dispose() }
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
    "One-time legacy/untrusted listener: no automatic reuse or stop. Inspect Get-NetTCPConnection and Get-CimInstance Win32_Process (PID, ParentProcessId, CreationDate, ExecutablePath, CommandLine). Executable path does not prove working directory. Use Ctrl+C in the known original project window; otherwise manually confirm launch context before a targeted stop. See startup instructions, or use -Port 8001."
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
function Save-StateRecord($TempPath, $FinalPath) {
    if (Test-Path -LiteralPath $FinalPath) {
        # Windows PowerShell converts a $null argument to "" for .NET string
        # parameters, and File.Replace rejects that as an invalid path. Use a real
        # backup path so the swap stays atomic, then discard the backup.
        $backup = "$FinalPath.bak"
        if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue }
        [IO.File]::Replace($TempPath, $FinalPath, $backup)
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    }
    else { [IO.File]::Move($TempPath, $FinalPath) }
}
function Get-InterruptedRecord($Identity) {
    # A launcher can die after the backend is verified but before the record is
    # promoted (for example a .NET argument error). A leftover temp record is
    # adopted only when it proves the same project, port and live process chain;
    # otherwise it is ignored and the normal "untrusted listener" refusal applies.
    $candidates = @(Get-ChildItem -Path (Join-Path $runtimePath "server-$Port.json.*.tmp") -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending)
    $identityExecutable = ([string]$Identity.Executable).TrimEnd('\')
    $identityLauncher = ([string]$Identity.LauncherExecutable).TrimEnd('\')
    foreach ($file in $candidates) {
        $state = $null
        try { $state = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction Stop | ConvertFrom-Json } catch { continue }
        $nonce = [Guid]::Empty
        # Require a completed readiness check from the interrupted launch.
        $verifiedUtc = [DateTime]::MinValue
        $verified = [DateTime]::TryParse([string]$state.verifiedUtc, [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind, [ref]$verifiedUtc)
        if (!$verified -or !$state.version -or
            $state.schema -ne 2 -or
            ![Guid]::TryParse([string]$state.launchNonce, [ref]$nonce) -or $nonce -eq [Guid]::Empty -or
            $state.projectRoot -ine $projectRoot -or $state.backendRoot -ine $backendRoot -or
            $state.port -ne $Port -or $state.pid -ne $Identity.Id -or
            $state.createdUtc -cne $Identity.CreatedUtc -or
            ([string]$state.executable).TrimEnd('\') -ine $identityExecutable -or
            $state.commandLine -cne $Identity.CommandLine -or
            $state.launcherPid -ne $Identity.LauncherId -or
            $state.launcherCreatedUtc -cne $Identity.LauncherCreatedUtc -or
            ([string]$state.launcherExecutable).TrimEnd('\') -ine $identityLauncher -or
            $state.launcherCommandLine -cne $Identity.LauncherCommandLine -or
            $state.fingerprint -cnotmatch '^[A-Fa-f0-9]{64}$') { continue }
        try { Save-StateRecord $file.FullName $statePath } catch { continue }
        Write-Host "Recovered interrupted launcher record for verified PID=$($Identity.Id), created=$($Identity.CreatedUtc)."
        return $state
    }
    return $null
}
function Test-HttpReady {
    try {
        $health = Invoke-RestMethod "$baseUrl/health" -TimeoutSec 3
        if ($health.code -ne 0 -or $health.data.status -ne 'ok' -or $health.data.database -ne 'ok') { return $false }
        $spec = Invoke-RestMethod "$baseUrl/openapi.json" -TimeoutSec 3
        if ($spec.info.version -cne $expectedVersion -or $spec.info.title -cne "ALE Workbench $expectedVersion") { return $false }
        $routes = @{
            '/api/v1/lifecycle/{kind}/{id}/impact' = @('get')
            '/api/v1/lifecycle/{kind}/{id}/apply' = @('post')
            '/api/v1/workflow/plans' = @('post')
            '/api/v1/workflow/processes' = @('post')
            '/api/v1/workflow/state' = @('get')
            '/api/v1/dashboard/todo' = @('get')
            '/api/v1/dashboard/recent-experiments' = @('get')
            '/api/v1/dashboard/recent-data' = @('get')
            '/api/v1/analysis/calculate' = @('post')
            '/api/v1/analysis/pair' = @('post')
            '/api/v1/analysis/save' = @('post')
            '/api/v1/analysis/saved/{result_id}' = @('get')
            '/api/v1/analysis/measurements' = @('get')
            '/api/v1/plans/{id}/process-grid' = @('put')
            '/api/v1/processes/{id}/process-grid' = @('put')
            '/api/v1/samples/{id}/void' = @('post')
            '/api/v1/ai/status' = @('get')
            '/api/v1/ai/config' = @('get','put')
            '/api/v1/ai/models' = @('get')
            '/api/v1/ai/test' = @('post')
            '/api/v1/ai/chat' = @('post')
            '/api/v1/ai/usage' = @('get')
            '/api/v1/ai/requests' = @('get')
            '/api/v1/ai/requests/{request_id}' = @('get')
            '/api/v1/ai/recover' = @('post')
            '/api/v1/ai/requests/{request_id}/reconcile' = @('post')
        }
        foreach ($path in $routes.Keys) {
            $entry = $spec.paths.PSObject.Properties[$path]
            if (!$entry) { return $false }
            foreach ($method in $routes[$path]) { if (!$entry.Value.PSObject.Properties[$method]) { return $false } }
        }
        $contract = Invoke-RestMethod "$baseUrl/api-contract" -TimeoutSec 3
        if ($contract.info.version -cne $expectedVersion) { return $false }
        return $true
    } catch { return $false }
}
function Stop-VerifiedListener($Identity) {
    $again = Get-ProjectListener
    $null = Get-TrustedRecord $again
    if ($again.Id -ne $Identity.Id -or $again.CreatedUtc -cne $Identity.CreatedUtc -or
        $again.Executable -ine $Identity.Executable -or $again.CommandLine -cne $Identity.CommandLine) {
        throw 'Listener identity changed before restart. No process was stopped.'
    }
    $handle = [Diagnostics.Process]::GetProcessById($Identity.Id)
    try {
        # Pin the OS process handle before checking time, then kill through that handle.
        # This prevents a recycled PID from selecting a different process.
        $null = $handle.Handle
        if ($handle.StartTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.ffffffZ') -cne $Identity.CreatedUtc) {
            throw 'Process creation time changed. No process was stopped.'
        }
        Write-Output "Restarting verified project backend PID=$($Identity.Id), created=$($Identity.CreatedUtc)."
        $handle.Kill()
        if (!$handle.WaitForExit(10000)) { throw 'Verified backend did not exit; startup aborted.' }
    } finally { $handle.Dispose() }
    for ($i = 0; $i -lt 20; $i++) {
        if (@(Get-Listeners).Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "Port $Port is still occupied. No additional process was stopped."
}

# Serialize launchers for this project/port; the OS releases the lock on interruption.
$launchLock = $null
try {
    try { $launchLock = [IO.File]::Open((Join-Path $runtimePath "launcher-$Port.lock"), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw "Another launcher may be active for port $Port. Retry after it finishes." }
    # Identify any listener before installing dependencies or changing the environment.
    $existingIdentity = $null
    if (@(Get-Listeners).Count) {
        $existingIdentity = Get-ProjectListener
        try { $null = Get-TrustedRecord $existingIdentity }
        catch { $null = Get-InterruptedRecord $existingIdentity }
    }
    if (!(Test-Path $pythonPath)) {
        if (Get-Command py.exe -ErrorAction SilentlyContinue) {
            & py.exe -3 -m venv (Join-Path $projectRoot 'backend\.venv-win')
        } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
            & python.exe -m venv (Join-Path $projectRoot 'backend\.venv-win')
        } else { throw 'Python 3.10+ is required. Install Python and run this script again.' }
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python environment.' }
        $Install = $true
    }
    $forceRestart = [bool]$Install
    $requirementsPath = Join-Path $projectRoot 'backend\requirements.txt'
    $markerPath = Join-Path $runtimePath 'dependencies.sha256'
    $requirementsHash = (Get-FileHash -Algorithm SHA256 $requirementsPath).Hash
    $installedHash = ''
    if (Test-Path $markerPath) { $installedHash = (Get-Content -Raw $markerPath).Trim() }
    $probe = 'import fastapi, pydantic, uvicorn, sqlalchemy, pymysql, jwt, argon2, dotenv, yaml, email_validator, httpx, pytest, jsonschema, openpyxl, defusedxml, multipart'
    if (!$Install -and $installedHash -eq $requirementsHash) {
        & $pythonPath -c $probe 2>$null
        if ($LASTEXITCODE -ne 0) { $Install = $true }
        if (!$Install) {
            & $pythonPath -m pip check
            if ($LASTEXITCODE -ne 0) { $Install = $true }
        }
    } else { $Install = $true }
    if ($Install) {
        $forceRestart = $true
        # Invalidate before installation: an interrupted attempt must retry next launch.
        Set-Content -Path $markerPath -Value 'pending' -Encoding ASCII
        Write-Output 'Installing compatible prebuilt Python packages. Interrupted installs retry automatically.'
        & $pythonPath -m pip install --upgrade '--only-binary=:all:' pip
        if ($LASTEXITCODE -ne 0) { throw 'Could not update pip. Check network access and run this launcher again.' }
        & $pythonPath -m pip install --upgrade '--only-binary=:all:' -r $requirementsPath
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. No C++ compilation was attempted. Rerun this launcher to retry.' }
        & $pythonPath -m pip check
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency consistency check failed.' }
        & $pythonPath -c $probe
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency import check failed.' }
        Set-Content -Path $markerPath -Value $requirementsHash -Encoding ASCII
    }
    if (!(Test-Path (Join-Path $projectRoot 'frontend\dist\index.html'))) { throw 'Missing frontend build.' }
    $env:ALE_DB_HOST = '127.0.0.1'
    $env:ALE_DB_PORT = '3307'
    # Read-only current-code readiness: DB connection + required tables/columns.
    # Do not print exception text (it can contain connection details); never migrate here.
    $readinessProbe = @'
import sys
try:
    from app.db import metadata
    metadata()
except Exception:
    sys.exit(1)
'@
    Push-Location (Join-Path $projectRoot 'backend')
    try { & $pythonPath -c $readinessProbe 2>$null; $readyExit = $LASTEXITCODE }
    finally { Pop-Location }
    if ($readyExit -ne 0) { throw 'Database/schema readiness failed. Check MySQL 3307 and migration status using the documented backup procedure. No backend was stopped; no migration was run.' }
    $fingerprint = Get-BackendFingerprint
    if ($existingIdentity) {
        $state = Get-TrustedRecord $existingIdentity
        $sameBuild = $state.version -ceq $expectedVersion -and $state.fingerprint -ceq $fingerprint
        if (!$forceRestart -and $sameBuild -and (Test-HttpReady)) {
            $currentIdentity = Get-ProjectListener
            $null = Get-TrustedRecord $currentIdentity
            if ($currentIdentity.Id -ne $existingIdentity.Id -or $currentIdentity.CreatedUtc -cne $existingIdentity.CreatedUtc -or
                (Get-BackendFingerprint) -cne $fingerprint) { throw 'Backend/source changed during reuse checks. Rerun launcher.' }
            Write-Output "Reusing verified $expectedVersion backend PID=$($existingIdentity.Id), created=$($existingIdentity.CreatedUtc)."
            Start-Process "$baseUrl/login"
            return
        }
        # A matched trusted record permits restarting an older build; missing/mismatched records already refused.
        Stop-VerifiedListener $existingIdentity
    }
    if (@(Get-Listeners).Count) { throw "Port $Port was occupied during startup. No process was stopped." }
    $launchNonce = [Guid]::NewGuid().ToString('D')
    $process = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','app.main:app','--app-dir',('"' + $backendRoot + '"'),'--host','127.0.0.1','--port',"$Port",'--no-access-log') -WorkingDirectory $backendRoot -RedirectStandardOutput (Join-Path $runtimePath "server-$Port.stdout.log") -RedirectStandardError (Join-Path $runtimePath "server-$Port.stderr.log") -PassThru
    $null = $process.Handle
    $launchedCreatedUtc = $process.StartTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.ffffffZ')
    $process.Id | Set-Content (Join-Path $runtimePath 'server.pid')
    $healthy = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        $process.Refresh()
        if ($process.HasExited) { throw "Service exited. See $runtimePath\server-$Port.stderr.log" }
        if (Test-HttpReady) { $healthy = $true; break }
    }
    if (!$healthy) { throw "Service did not pass version/routes/health checks. See $runtimePath\server-$Port.stderr.log. No ready fingerprint was recorded." }
    $newIdentity = Get-ProjectListener
    if ($newIdentity.LauncherId -ne $process.Id -or $newIdentity.LauncherCreatedUtc -cne $launchedCreatedUtc) {
        throw 'Ready listener is not the process just launched. No ready fingerprint was recorded.'
    }
    if ((Get-BackendFingerprint) -cne $fingerprint) { throw 'Source/build changed during startup. Rerun launcher; no ready fingerprint was recorded.' }
    $record = [ordered]@{ schema=2; launchNonce=$launchNonce; projectRoot=$projectRoot; backendRoot=$backendRoot; executable=$newIdentity.Executable; commandLine=$newIdentity.CommandLine; launcherPid=$newIdentity.LauncherId; launcherCreatedUtc=$newIdentity.LauncherCreatedUtc; launcherExecutable=$newIdentity.LauncherExecutable; launcherCommandLine=$newIdentity.LauncherCommandLine; port=$Port; pid=$newIdentity.Id; createdUtc=$newIdentity.CreatedUtc; version=$expectedVersion; fingerprint=$fingerprint; verifiedUtc=[DateTime]::UtcNow.ToString('o') }
    $tempState = "$statePath.$launchNonce.tmp"
    $record | ConvertTo-Json | Set-Content -LiteralPath $tempState -Encoding UTF8
    Save-StateRecord $tempState $statePath
    Write-Output "Verified $expectedVersion backend PID=$($newIdentity.Id), created=$($newIdentity.CreatedUtc)."
    Write-Output "Workbench: $baseUrl/login"
    Write-Output 'First visit: use backend\.setup-code to create your administrator. No default password.'
    Start-Process "$baseUrl/login"
} finally {
    if ($launchLock) { $launchLock.Dispose() }
}
