@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0backend"

echo ============================================
echo   AI Video Workflow - Launcher
echo ============================================

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv. Please install Python 3.10+ and add it to PATH.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment found.
)

echo [2/4] Checking dependencies...
.venv\Scripts\python.exe -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo       Installing requirements, this may take a few minutes...
    .venv\Scripts\pip.exe install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        pause
        exit /b 1
    )
) else (
    echo       Dependencies OK.
)

if not exist ".env" (
    echo [3/4] Creating .env from template...
    copy /y ".env.example" ".env" >nul
    echo       .env created. Fill in your API keys to enable real generation.
) else (
    echo [3/4] .env found.
)

echo [4/4] Starting server at http://localhost:8000
start "" http://localhost:8000
.venv\Scripts\python.exe -m app.main

endlocal
pause
