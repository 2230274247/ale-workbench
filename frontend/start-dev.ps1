$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force -Path '.runtime' | Out-Null
& npm.cmd install --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
$process = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm run dev > .runtime\vite.log 2>&1' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
$process.Id | Set-Content '.runtime\vite.pid'
Write-Output 'Vite: http://localhost:5173/login'
Write-Output "Log: $PSScriptRoot\.runtime\vite.log"
