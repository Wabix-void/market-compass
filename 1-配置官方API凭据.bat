@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH.
    echo Please install Python 3.10+ and check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

cls
python scripts\setup_openapi.py %*

echo.
pause