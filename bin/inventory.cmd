@echo off
rem Lets cmd and PowerShell find `inventory` on the PATH. The logic is in scripts\inventory.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\inventory.ps1" %*
exit /b %ERRORLEVEL%
