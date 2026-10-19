@echo off
rem One-time setup on Windows: puts `inventory` on your PATH and starts the system.
rem Works from cmd, PowerShell or a double-click (no execution-policy change needed).
set "LAUNCHER=%~dp0inventory.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" install || exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" start || exit /b 1
echo.
echo Installed. Open a new terminal and type: inventory
