@echo off
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\pythonw.exe"

if not exist "%PY%" (
    echo [ERROR] Python environment not found: %PY%
    echo Please run: powershell -ExecutionPolicy Bypass -File .\setup.ps1
    pause
    exit /b 1
)

start "" "%PY%" app\main_qt.py
exit /b 0