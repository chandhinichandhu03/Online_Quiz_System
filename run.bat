@echo off
:: Navigate to the script's directory
cd /d "%~dp0"

echo ==================================================
echo   Online Quiz System - Startup Script (Windows)
echo ==================================================

:: Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH.
    echo Please install Python 3.9 or higher and check "Add Python to PATH".
    pause
    exit /b 1
)

:: Check if virtual environment is valid
if exist "venv" (
    rem Try running python inside the venv to check if it's functional
    venv\Scripts\python.exe -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo WARNING: Existing virtual environment is broken or has a Python version mismatch.
        echo          Re-creating virtual environment...
        rmdir /s /q venv
    )
)

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment [venv]...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo Error: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo Error: Failed to activate virtual environment.
    pause
    exit /b 1
)

:: Install dependencies using python -m pip
echo Installing/updating dependencies from requirements.txt...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Error: Failed to install requirements.
    pause
    exit /b 1
)


:: Run the Flask application
echo Starting Online Quiz System on http://localhost:5001...
python app.py

pause
