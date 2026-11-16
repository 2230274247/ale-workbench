@echo off
setlocal
cd /d "%~dp0" || exit /b 1
echo ALE source directory: %~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-workbench.ps1" %*
set "ALE_EXIT_CODE=%ERRORLEVEL%"
if not "%ALE_EXIT_CODE%"=="0" pause
exit /b %ALE_EXIT_CODE%
