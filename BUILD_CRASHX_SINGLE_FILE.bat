@echo off
setlocal
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\build_exchange_onefile_windows.ps1" --% %*
exit /b %errorlevel%
