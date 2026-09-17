@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-DailyAIBriefBrowserTask.ps1"
if errorlevel 1 (
  echo.
  echo Browser delivery setup: FAILED
  pause
  exit /b 1
)
echo.
pause
