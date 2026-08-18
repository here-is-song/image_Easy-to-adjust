@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "image_easy-to-adjust (IEA)" ".venv\Scripts\pythonw.exe" "main.py"
    exit /b 0
)

if exist ".venv\Scripts\python.exe" (
    start "image_easy-to-adjust (IEA)" ".venv\Scripts\python.exe" "main.py"
    exit /b 0
)

where python >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Please install Python or create the project virtual environment.
    pause
    exit /b 1
)

python "main.py"
