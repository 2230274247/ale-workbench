# Register (or remove) the daily ALE Workbench backup as a Windows scheduled task.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File database\install_daily_backup.ps1
#   ... -Time 02:30 -BackupRoot D:\ALE_Backups -KeepDays 30
#   ... -Unregister
#
# The task runs database\backup_db.py non-interactively; it never migrates and never
# writes to the database. Credentials stay in database\.dbcreds and are read by the
# script at run time. Nothing is scheduled until this file is executed by a human.

param(
    [string]$Time = '02:30',
    [string]$BackupRoot = '',
    [int]$KeepDays = 30,
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$taskName = 'ALE-Workbench-Daily-Backup'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv-win\Scripts\python.exe'
$script = Join-Path $PSScriptRoot 'backup_db.py'

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Output "Removed scheduled task $taskName"
    } else {
        Write-Output "Scheduled task $taskName was not registered"
    }
    return
}

if (!(Test-Path $python)) { throw "Python interpreter not found: $python" }
if (!(Test-Path $script)) { throw "Backup script not found: $script" }

$arguments = "`"$script`" --reason daily --keep $KeepDays"
if ($BackupRoot) { $arguments += " --backup-root `"$BackupRoot`"" }

$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description 'ALE Workbench: verified daily backup of database and originals' -Force | Out-Null

Write-Output "Registered task $taskName at $Time every day"
Write-Output "  python     $python"
Write-Output "  arguments  $arguments"
Write-Output "  log        see <backup root>\backup.log (default H:\ALE_Backups)"
Write-Output "Run it once now with:  Start-ScheduledTask -TaskName $taskName"
Write-Output "Remove it with:        .\database\install_daily_backup.ps1 -Unregister"
