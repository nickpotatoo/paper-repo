@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0launch_viewer.ps1"
if errorlevel 1 (
  echo.
  echo Startup failed. See the error above.
  pause
)
