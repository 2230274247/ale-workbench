; ALE Workbench — one-click Windows installer.
; Bundles: WPF launcher (self-contained), portable Python 3.14, Vue build output,
; MySQL 8.4 (binaries), project backend/scripts, and provisions the local database.
; Requires Inno Setup 6.x. Build via launcher/installer/build-installer.ps1.

#define MyAppName "ALE Workbench"
#define MyAppVersion "1.9.0"
#define MyAppPublisher "ALE Workbench"
#define MyAppExeName "ALE-Workbench-Launcher.exe"
#ifndef StageRoot
  #define StageRoot "..\staging"
#endif

[Setup]
AppId={{A1E0B0C0-0000-4000-8000-000000000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ALE Workbench
DefaultGroupName=ALE Workbench
DisableProgramGroupPage=yes
OutputBaseFilename=ALE-Workbench-Setup-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\ALE-Workbench-Launcher\Assets\app.ico
; The installer owns the app + project files, but data/credentials live OUTSIDE {app}:
;   - MySQL data dir:  {commonappdata}\ALE Workbench\mysql-data
;   - Launcher config: {userappdata}\ALE Workbench Launcher
; Uninstall must NOT remove those (see [UninstallDelete]).
SetupLogging=yes
VersionInfoVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: checkedonce

[Files]
; The complete staged runtime tree -> install dir. Files keep relative layout so the
; launcher auto-detects the project root next to its own exe.
Source: "{#StageRoot}\*"; DestDir: "{app}"; Excludes: ".env,.dbcreds,.appcreds,.admin-password,.setup-code,.ai-master-key"; Flags: ignoreversion recursesubdirs createallsubdirs
; All credentials are generated or entered on the target machine.
; No developer preset administrator password belongs in a distributable installer.

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; First launch offered after install (the launcher itself is safe to open immediately).
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove only what the installer laid down. Keep user config + MySQL data.
Type: filesandordirs; Name: "{app}\backend\.runtime"
Type: files; Name: "{app}\install.log"

[Code]
// Best-effort local MySQL provisioning after files are installed. Idempotent: reuses
// an existing MySQL on port 3307, otherwise deploys the bundled mysqld into a data dir
// OUTSIDE {app}. Failures are logged and surfaced but do not roll back the install —
// the database can be (re)provisioned later by relaunching the installer's script.
procedure LogInstall(const S: string);
var
  LogPath: string;
begin
  LogPath := ExpandConstant('{app}\install.log');
  SaveStringToFile(LogPath, S + #13#10, True);
end;

procedure DeployLocalMySQL;
var
  PS, Args, AppDir: string;
  ResultCode: Integer;
begin
  AppDir := ExpandConstant('{app}');
  PS := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  Args := '-NoProfile -ExecutionPolicy Bypass -File "' + AppDir +
          '\launcher\deploy\deploy-mysql.ps1" -ProjectRoot "' + AppDir + '" -Port 3307 -DataDir "' + ExpandConstant('{commonappdata}\ALE Workbench\mysql-data') + '"';
  LogInstall('Running: powershell.exe ' + Args);
  if Exec(PS, Args, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    LogInstall('deploy-mysql.ps1 exited with code ' + IntToStr(ResultCode));
    if ResultCode <> 0 then
      MsgBox('数据库自动部署未完成（退出码 ' + IntToStr(ResultCode) + '）。' + #13#10 +
             '你可以稍后在启动器中重新部署，或查看 ' + AppDir + '\install.log。',
             mbError, MB_OK);
  end
  else
  begin
    LogInstall('Failed to launch deploy-mysql.ps1');
    MsgBox('无法启动数据库部署脚本。请查看 ' + AppDir + '\install.log。', mbError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    DeployLocalMySQL;
end;
