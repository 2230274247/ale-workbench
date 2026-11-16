# 临时开启公网（Cloudflare 快速隧道）：手机临时访问本机工作台，用完 Ctrl+C 关闭。
# 无需 Cloudflare 账号/域名。用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\开启临时公网.ps1 [-Port 8001]
param(
  [ValidateRange(1,65535)][int]$Port = 8002
)

$ErrorActionPreference = 'Stop'
$backendUrl = "http://127.0.0.1:$Port"

# 1) 定位 cloudflared
$cfPath = $null
$cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($cmd) { $cfPath = $cmd.Source }
else {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\cloudflared.exe'),
    (Join-Path $env:ProgramFiles 'cloudflared\cloudflared.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'cloudflared\cloudflared.exe')
  )
  foreach ($c in $candidates) {
    if ($c -and (Test-Path $c)) { $cfPath = $c; break }
  }
}
if (-not $cfPath) {
  Write-Host ''
  Write-Host '未找到 cloudflared。请先安装（一次即可）：' -ForegroundColor Yellow
  Write-Host '  winget install --id Cloudflare.cloudflared --accept-package-agreements --accept-source-agreements' -ForegroundColor Cyan
  Write-Host '  或下载：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/' -ForegroundColor Cyan
  Write-Host '安装后重新打开终端，再运行本脚本。' -ForegroundColor Yellow
  exit 1
}

# 2) 检查后端是否在运行
Write-Host "检查后端 $backendUrl ..."
try {
  $health = Invoke-RestMethod -Uri "$backendUrl/health" -TimeoutSec 5
  Write-Host ("后端正常：{0} / 数据库 {1}" -f $health.data.status, $health.data.database) -ForegroundColor Green
} catch {
  Write-Host ''
  Write-Host '后端未运行（/health 不通）。请先启动工作台：' -ForegroundColor Red
  Write-Host '  H:\ALE_AI\启动工作台.cmd' -ForegroundColor Cyan
  Write-Host '启动成功后再运行本脚本。' -ForegroundColor Yellow
  exit 1
}

# 3) 后台启动临时隧道，轮询 stderr 拿临时网址
$errLog = Join-Path $env:TEMP "ale-cloudflared-$Port.err.log"
$outLog = Join-Path $env:TEMP "ale-cloudflared-$Port.out.log"
Remove-Item $errLog, $outLog -ErrorAction SilentlyContinue

Write-Host '正在开启临时公网隧道…' -ForegroundColor Green
$p = Start-Process -FilePath $cfPath `
  -ArgumentList @('tunnel','--url',"http://127.0.0.1:$Port",'--no-autoupdate') `
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
  $entry = "$url/m/quick"
  Write-Host ''
  Write-Host '==================================================' -ForegroundColor Cyan
  Write-Host '  手机打开（或把链接发到手机微信）：' -ForegroundColor White
  Write-Host "  $entry" -ForegroundColor Yellow
  Write-Host '  已复制到剪贴板，并已在电脑浏览器打开。' -ForegroundColor White
  Write-Host '  用完按 Ctrl+C 关闭，公网网址随即失效。' -ForegroundColor White
  Write-Host '==================================================' -ForegroundColor Cyan
  try { Set-Clipboard -Value $entry } catch {}
  Start-Process $entry
  try {
    Wait-Process -Id $p.Id
  } finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
    Write-Host '隧道已关闭。' -ForegroundColor Green
  }
} else {
  Write-Host '未能取得临时网址。' -ForegroundColor Red
  Write-Host "  cloudflared 日志：$errLog" -ForegroundColor Yellow
  if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
  exit 1
}
