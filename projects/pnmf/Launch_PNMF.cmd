@echo off
setlocal
cd /d "%~dp0"
title PNMF Launcher

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0pnmf.ps1" %*
set "PNMF_EXIT=%ERRORLEVEL%"

if not "%PNMF_EXIT%"=="0" (
    echo.
    echo PNMF could not start. Review the error above, then press any key.
    pause >nul
)

exit /b %PNMF_EXIT%
