@echo off
setlocal
title SiteView Atlas

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\atlas\setup-windows.ps1" -AtlasRoot "C:\3dcamera"
if errorlevel 1 (
    echo.
    echo Atlas setup failed. Keep this window open and share the error report.
    pause
    exit /b 1
)

echo.
echo Atlas laptop checks completed successfully.
echo The queue worker will start from this same launcher when Task 11 is complete.
pause
