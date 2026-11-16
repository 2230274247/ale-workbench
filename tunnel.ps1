# ALE Workbench public tunnel control: cloudflared quick-tunnel start/stop/status.
# Same layer as start-workbench.ps1 / ale-ctl.ps1; invoked by the desktop launcher
# when the backend starts and when it exits. No Cloudflare account/domain needed.
# The temporary URL changes each time (*.trycloudflare.com).
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tunnel.ps1 -Action start  -Port 8001
#   powershell -NoProfile -ExecutionPolicy Bypass -File tunnel.ps1 -Action stop   -Port 8001
#   powershell -NoProfile -ExecutionPolicy Bypass -File tunnel.ps1 -Action status -Port 8001
# Output is one line of compact JSON.
param(
    [ValidateSet('start','stop','status')][string]$Action = 'status',
    [ValidateRange(1,65535)][int]$Port = 8002
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$runtimePath = Join-Path $projectRoot 'backend\.runtime'
New-Item -ItemType Directory -Force $runtimePath | Out-Null
$statePath = Join-Path $runtimePath "tunnel-$Port.json"
$backendUrl = "http://127.0.0.1:$Port"

function Find-Cloudflared {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\cloudflared.exe'),
        (Join-Path $env:ProgramFiles 'cloudflared\cloudflared.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'cloudflared\cloudflared.exe')
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    return $null
}

function Get-TunnelState {
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    try { $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } catch { return $null }
    if (-not $state -or -not $state.pid) { return $null }
    $proc = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
    if (-not $proc -or $proc.HasExited) { return $null }
    return $state
}

function Stop-TunnelProcess($state) {
    if (-not $state) { return }
    try {
        $proc = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
        if ($proc) { & taskkill /PID ([int]$state.pid) /T /F 2>$null | Out-Null }
    } catch { }
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
}

$result = $null
try {
    if ($Action -eq 'stop') {
        $state = Get-TunnelState
        Stop-TunnelProcess $state
        $result = [pscustomobject]@{ ok=$true; action='stop'; state='stopped'; port=$Port }
    }
    elseif ($Action -eq 'status') {
        $state = Get-TunnelState
        if ($state) {
            $result = [pscustomobject]@{ ok=$true; action='status'; state='running'; port=$Port; pid=[int]$state.pid; url=$state.url }
        } else {
            $result = [pscustomobject]@{ ok=$true; action='status'; state='stopped'; port=$Port }
        }
    }
    else {
        # start: reuse if already running; otherwise confirm backend health first.
        $existing = Get-TunnelState
        if ($existing) {
            $result = [pscustomobject]@{ ok=$true; action='start'; state='running'; port=$Port; pid=[int]$existing.pid; url=$existing.url }
        } else {
            $cfPath = Find-Cloudflared
            if (-not $cfPath) {
                $result = [pscustomobject]@{ ok=$false; action='start'; state='error'; port=$Port; message='cloudflared not found. Install once: winget install --id Cloudflare.cloudflared' }
            } else {
                $healthy = $false
                try {
                    $health = Invoke-RestMethod "$backendUrl/health" -TimeoutSec 5
                    $healthy = ($health.code -eq 0 -and $health.data.status -eq 'ok' -and $health.data.database -eq 'ok')
                } catch { }
                if (-not $healthy) {
                    $result = [pscustomobject]@{ ok=$false; action='start'; state='error'; port=$Port; message="Backend not healthy at $backendUrl. Start the workstation first." }
                } else {
                    $errLog = Join-Path $env:TEMP "ale-cloudflared-$Port.err.log"
                    $outLog = Join-Path $env:TEMP "ale-cloudflared-$Port.out.log"
                    Remove-Item $errLog, $outLog -ErrorAction SilentlyContinue
                    $p = Start-Process -FilePath $cfPath `
                        -ArgumentList @('tunnel','--url',$backendUrl,'--no-autoupdate') `
                        -RedirectStandardError $errLog -RedirectStandardOutput $outLog `
                        -WindowStyle Hidden -PassThru
                    $url = $null
                    for ($i = 0; $i -lt 90; $i++) {
                        Start-Sleep -Milliseconds 500
                        if ($p.HasExited) { break }
                        $m = Select-String -Path $errLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches -ErrorAction SilentlyContinue | Select-Object -First 1
                        if ($m) { $url = $m.Matches[0].Value; break }
                    }
                    if ($url) {
                        [ordered]@{ pid = $p.Id; url = $url; port = $Port; startedAt = [DateTime]::UtcNow.ToString('o') } |
                            ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
                        $result = [pscustomobject]@{ ok=$true; action='start'; state='running'; port=$Port; pid=$p.Id; url=$url }
                    } else {
                        if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
                        $result = [pscustomobject]@{ ok=$false; action='start'; state='error'; port=$Port; message="Failed to obtain tunnel URL. See $errLog" }
                    }
                }
            }
        }
    }
} catch {
    $result = [pscustomobject]@{ ok=$false; action=$Action; state='error'; port=$Port; message="Tunnel script failed: $($_.Exception.Message)" }
}

$result | ConvertTo-Json -Compress
exit 0
