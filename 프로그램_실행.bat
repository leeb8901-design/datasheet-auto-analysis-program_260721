@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" main.py
if errorlevel 1 (
    echo.
    echo [ERROR] The program crashed. See the message above.
    pause
)
