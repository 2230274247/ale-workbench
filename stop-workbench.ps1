# ALE Workbench safe stop (command-line entry).
# Stops only the backend process managed by this workbench launcher.
# Refuses to stop when the port is occupied by a non-workbench process.
param(
    [ValidateRange(1,65535)][int]$Port = 8002,
    [string]$ProjectRoot = ''
)
$ErrorActionPreference = 'Stop'
$ctl = Join-Path $PSScriptRoot 'ale-ctl.ps1'
$args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ctl, '-Action', 'stop', '-Port', $Port)
if ($ProjectRoot) { $args += @('-ProjectRoot', $ProjectRoot) }
& powershell.exe @args
exit $LASTEXITCODE
