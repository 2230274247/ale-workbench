# Build from one checkout. RuntimeRoot supplies only installed Python/MySQL binaries.
# Credentials, database files, original files and WebView2 profiles are never staged.
param(
    [Alias('MainRepoRoot')][string]$RuntimeRoot = '',
    [string]$Stage = '',
    [string]$Iscc = '',
    [switch]$SkipBuild,
    [switch]$SkipProvision,
    [switch]$SkipMySql
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
if (!$RuntimeRoot) { $RuntimeRoot = $root }
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd('\')
if (!$Stage) { $Stage = Join-Path $root 'launcher\staging' }
$Stage = [IO.Path]::GetFullPath($Stage).TrimEnd('\')
$stageParent = [IO.Path]::GetFullPath((Join-Path $root 'launcher')).TrimEnd('\') + '\'
if (!$Stage.StartsWith($stageParent, [StringComparison]::OrdinalIgnoreCase) -or
    $Stage -ieq (Join-Path $root 'launcher')) {
    throw 'Stage must be a dedicated subdirectory of this checkout/launcher.'
}
if (!$Iscc) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $Iscc = $command.Source }
    else { $Iscc = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe' }
}
Write-Output "Source checkout: $root"
Write-Output "Runtime binaries: $RuntimeRoot"

# Import only build/fingerprint helpers, without running startup or connecting to DB.
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'start-workbench.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Startup script does not parse.' }
$helperNames = @('Get-PublicFilesFingerprint','Get-FrontendSourceFingerprint','Get-FrontendDistFingerprint','Ensure-FrontendBuild','Save-StateRecord')
foreach ($node in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($node.Name -in $helperNames) { Invoke-Expression $node.Extent.Text }
}
$projectRoot = $root
Ensure-FrontendBuild
$proj = Join-Path $root 'launcher\ALE-Workbench-Launcher\ALE-Workbench-Launcher.csproj'
if (!$SkipBuild) {
    & dotnet publish $proj -c Release -o (Join-Path $root 'launcher\ALE-Workbench-Launcher\publish')
    if ($LASTEXITCODE -ne 0) { throw 'dotnet publish failed.' }
}
$launcherExe = Join-Path $root 'launcher\ALE-Workbench-Launcher\publish\ALE-Workbench-Launcher.exe'
if (!(Test-Path -LiteralPath $launcherExe)) { throw 'Publish the launcher before staging.' }
if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
New-Item -ItemType Directory -Force $Stage | Out-Null
Copy-Item -LiteralPath $launcherExe -Destination $Stage
foreach ($name in @('start-workbench.ps1','ale-ctl.ps1','stop-workbench.ps1','启动工作台.cmd')) {
    Copy-Item -LiteralPath (Join-Path $root $name) -Destination $Stage
}
New-Item -ItemType Directory -Force (Join-Path $Stage 'backend') | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'backend\app') -Destination (Join-Path $Stage 'backend\app') -Recurse
foreach ($name in @('requirements.txt','pytest.ini')) {
    Copy-Item -LiteralPath (Join-Path $root "backend\$name") -Destination (Join-Path $Stage 'backend')
}
New-Item -ItemType Directory -Force (Join-Path $Stage 'frontend') | Out-Null
foreach ($name in @('src','public','scripts','dist')) {
    $source = Join-Path $root "frontend\$name"
    if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $Stage "frontend\$name") -Recurse }
}
Get-ChildItem -LiteralPath (Join-Path $root 'frontend') -File | Where-Object {
    $_.Name -match '^(package(-lock)?\.json|index\.html|vite\.config\.[cm]?[jt]s|tsconfig.*\.json)$'
} | Copy-Item -Destination (Join-Path $Stage 'frontend')
New-Item -ItemType Directory -Force (Join-Path $Stage 'frontend\.runtime') | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'frontend\.runtime\build.json') -Destination (Join-Path $Stage 'frontend\.runtime\build.json')
Copy-Item -LiteralPath (Join-Path $root 'api') -Destination (Join-Path $Stage 'api') -Recurse
New-Item -ItemType Directory -Force (Join-Path $Stage 'database') | Out-Null
foreach ($name in @('apply_schema.py','migrate.py','seed_admin.py','p0_utils.py','backup_db.py','restore_db.py','pre_upgrade_check.py')) {
    Copy-Item -LiteralPath (Join-Path $root "database\$name") -Destination (Join-Path $Stage 'database')
}
foreach ($name in @('sql','migrations')) {
    Copy-Item -LiteralPath (Join-Path $root "database\$name") -Destination (Join-Path $Stage "database\$name") -Recurse
}
New-Item -ItemType Directory -Force (Join-Path $Stage 'launcher\deploy') | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'launcher\deploy\deploy-mysql.ps1') -Destination (Join-Path $Stage 'launcher\deploy')
if (!$SkipProvision) {
    & powershell.exe -NoProfile -File (Join-Path $root 'launcher\deploy\provision-python.ps1') -Target (Join-Path $Stage 'python') -VenvDir (Join-Path $RuntimeRoot 'backend\.venv-win')
    if ($LASTEXITCODE -ne 0) { throw 'Portable Python provisioning failed.' }
}
if (!$SkipMySql) {
    $mysql = Join-Path $RuntimeRoot 'mysql-server'
    if (!(Test-Path -LiteralPath (Join-Path $mysql 'bin\mysqld.exe'))) { throw 'MySQL runtime binaries not found.' }
    Copy-Item -LiteralPath $mysql -Destination (Join-Path $Stage 'mysql-server') -Recurse
}
$forbiddenNames = @('.env','.dbcreds','.appcreds','.admin-password','.setup-code','.ai-master-key')
$forbidden = @(Get-ChildItem -LiteralPath $Stage -Recurse -File | Where-Object { $_.Name -in $forbiddenNames })
if ($forbidden.Count) { throw 'Credential file detected in staging. Installer build refused.' }
if (!(Test-Path -LiteralPath $Iscc)) { throw 'Set -Iscc to your Inno Setup compiler executable.' }
$dist = Join-Path $root 'launcher\dist'
New-Item -ItemType Directory -Force $dist | Out-Null
& $Iscc "/O$dist" "/DStageRoot=$Stage" (Join-Path $PSScriptRoot 'ale-workbench.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup build failed.' }
Write-Output "Installer: $dist\ALE-Workbench-Setup-x64.exe"
