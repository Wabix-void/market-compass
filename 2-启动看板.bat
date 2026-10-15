@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH.
    pause
    exit /b 1
)

echo ============================================================
echo  MarketCompass - dashboard
echo  URL: http://127.0.0.1:8787
echo  Keep this window open; close it to stop the server.
echo ============================================================
echo.

start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8787"
python scripts\run_server.py

pause