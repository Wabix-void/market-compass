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

echo [1/2] Collecting real data from Suning public search pages ...
echo       (rate limit 3s per request, about 15 seconds)
echo.
python scripts\collect_suning.py
echo.
echo [2/2] Rebuilding metrics ...
python scripts\bootstrap.py --sources suning
echo.
pause