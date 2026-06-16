@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
    echo This launcher needs Windows PowerShell.
    echo Please open this folder in PowerShell and run:
    echo scripts\Start-FilmLog.ps1
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-FilmLog.ps1"
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo.
    echo FilmLog did not start. Please see the message above.
    pause
)
exit /b %EXITCODE%
