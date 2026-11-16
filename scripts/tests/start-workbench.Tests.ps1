# Standalone Windows regression checks. No backend, database or real process is started/stopped.
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'start-workbench.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($node in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    Invoke-Expression $node.Extent.Text
}
$script:checks = 0
function Assert($Condition, [string]$Name) {
    if (!$Condition) { throw "FAIL: $Name" }
    $script:checks++
    Write-Output "PASS: $Name"
}
$Port = 8001
$script:rows = @(); $script:endpoints = @(); $script:queryFails = $false
function Get-TcpListenEndpoints { $script:endpoints }
function Get-NetTCPConnection {
    param($LocalPort, $ErrorAction)
    if ($script:queryFails) { throw 'Inspection unavailable' }
    $script:rows
}
function Row($State, $RemotePort = 0, $Address = '127.0.0.1', $Owner = 42) {
    [pscustomobject]@{ LocalAddress=$Address; LocalPort=8001; RemotePort=$RemotePort; State=$State; OwningProcess=$Owner }
}
Assert (@(Get-Listeners).Count -eq 0) 'vacant port returns no listeners'
$script:endpoints = @([Net.IPEndPoint]::new([Net.IPAddress]::Loopback, 8001))
$script:rows = @(Row '' 0; Row 'Established' 53000)
Assert (@(Get-Listeners).Count -eq 1) 'empty State listener retained; established peer excluded'
$script:rows = @(Row 'Closed' 0; Row 'TimeWait' 53000)
Assert (@(Get-Listeners).Count -eq 1) 'OS-confirmed listener retained despite Closed CIM State'
$script:endpoints = @()
Assert (@(Get-Listeners).Count -eq 1) 'remote-less Closed row remains occupied even when OS endpoint list is empty'
$script:rows = @(Row $null 0; Row 'Established' 53000)
Assert (@(Get-Listeners).Count -eq 1) 'real regression: null CIM State and empty OS endpoint list still retain owner'
$script:queryFails = $true
$failed = $false
try { $null = Get-Listeners } catch { $failed = $true }
Assert $failed 'TCP inspection failure never becomes a free port'
$script:queryFails = $false
$script:endpoints = @([Net.IPEndPoint]::new([Net.IPAddress]::Loopback, 8001))
$script:rows = @()
$failed = $false
try { $null = Get-Listeners } catch { $failed = $true }
Assert $failed 'OS listener without PID information fails closed'
$script:endpoints = @([Net.IPEndPoint]::new([Net.IPAddress]::Any, 8001))
$script:rows = @(Row 'Listen' 0 '0.0.0.0')
$failed = $false
try { $null = Get-ProjectListener } catch { $failed = $true }
Assert $failed 'non-loopback listener is refused before querying process identity'
$backendRoot = 'C:\test\backend'
$validCommand = '"C:\test\backend\.venv-win\Scripts\python.exe" -m uvicorn app.main:app --app-dir "C:\test\backend" --host 127.0.0.1 --port 8001 --no-access-log'
Assert (Test-UvicornCommand $validCommand) 'expected explicit project invocation accepted'
Assert (!(Test-UvicornCommand ($validCommand.Replace('C:\test\backend" --host', 'C:\other\backend" --host')))) 'another checkout invocation refused'
Assert (!(Test-UvicornCommand ($validCommand + ' --reload'))) 'reload or unknown flags refused'
$temp = Join-Path ([IO.Path]::GetTempPath()) ('ale-launcher-' + [Guid]::NewGuid().ToString('N'))
try {
    $projectRoot = $temp
    New-Item -ItemType Directory -Force (Join-Path $temp 'frontend\src'), (Join-Path $temp 'frontend\dist') | Out-Null
    Set-Content (Join-Path $temp 'frontend\src\app.ts') 'version one' -Encoding UTF8
    Set-Content (Join-Path $temp 'frontend\package.json') '{}' -Encoding UTF8
    Set-Content (Join-Path $temp 'frontend\dist\index.html') '<html>one</html>' -Encoding UTF8
    $sourceBefore = Get-FrontendSourceFingerprint
    $distBefore = Get-FrontendDistFingerprint
    Set-Content (Join-Path $temp 'frontend\src\app.ts') 'version two' -Encoding UTF8
    Assert ((Get-FrontendSourceFingerprint) -cne $sourceBefore) 'source edit invalidates frontend build marker'
    Set-Content (Join-Path $temp 'frontend\dist\index.html') '<html>two</html>' -Encoding UTF8
    Assert ((Get-FrontendDistFingerprint) -cne $distBefore) 'changed build output invalidates frontend marker'
    $final = Join-Path $temp 'record.json'
    Set-Content $final 'old' -Encoding UTF8
    $pending = Join-Path $temp 'record.json.tmp'
    Set-Content $pending 'new' -Encoding UTF8
    Save-StateRecord $pending $final
    Assert ((Get-Content $final -Raw).Trim() -eq 'new') 'atomic record replacement works in Windows PowerShell'
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
Write-Output "Launcher regression checks: $script:checks passed"
