# Online Quiz System with Dynamic AI Generation 🎯

A fully-featured, full-stack Flask web application for creating, taking, and sharing multiple-choice quizzes on any topic. 

It comes with a robust authentication system, real-time grading, personal dashboards, and PDF result exports. Best of all, it features an **AI Custom Generator** that builds quizzes on the fly for whatever topic you type in!

## Features
- **User Authentication**: Secure registration and login using hashed passwords.
- **Dynamic Quiz Generation**: Type in any topic (e.g., "Space Race") and it creates a quiz immediately! Works completely without an API key using dynamic fallback templates, and natively hooks into Google's Gemini LLM if you provide a key.
- **Save to PDF**: At the end of a quiz, you can download a print-ready, formatted PDF displaying your score and an itemized answer review.
- **Leaderboards & History**: See how you stack up globally and view past quizzes.
- **Admin Dashboard**: Manage and manually create quizzes.

## Setup & Running the Code

The easiest way to run the application is to use the provided automated startup scripts. These scripts automate setting up a Python virtual environment (`venv`), installing dependencies, and starting the Flask server.

### 🚀 Quick Start with Startup Scripts

#### 🍏 macOS and Linux
1. Open your terminal and navigate to the project directory.
2. Make the script executable (only needed once):
   ```bash
   chmod +x run.sh
   ```
3. Run the script:
   ```bash
   ./run.sh
   ```

#### 🪟 Windows
Simply double-click the `run.bat` file in the project folder, or run it in your Command Prompt / PowerShell:
```cmd
run.bat
```

---

### 💻 Startup Script Source Code

If you need to recreate the startup scripts, you can copy the code directly from below:

#### 🍏 macOS/Linux (`run.sh`)
```bash
#!/bin/bash

# Navigate to the script's directory
cd "$(dirname "$0")"

echo "=================================================="
echo "  Online Quiz System - Startup Script (macOS/Linux) "
echo "=================================================="

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed or not in PATH."
    echo "Please install Python 3.9 or higher."
    exit 1
fi

# Check if virtual environment is valid
ENV_DIR="venv"
if [ -d "$ENV_DIR" ]; then
    # Try running python inside the venv to check if it's functional
    if ! "$ENV_DIR/bin/python" -c "import sys" &> /dev/null; then
        echo "⚠️  Existing virtual environment is broken or has a Python version mismatch."
        echo "   Re-creating virtual environment..."
        rm -rf "$ENV_DIR"
    fi
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$ENV_DIR" ]; then
    echo "Creating virtual environment (venv)..."
    python3 -m venv "$ENV_DIR"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment."
        exit 1
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
source "$ENV_DIR/bin/activate"
if [ $? -ne 0 ]; then
    echo "Error: Failed to activate virtual environment."
    exit 1
fi

# Install dependencies using python -m pip
echo "Installing/updating dependencies from requirements.txt..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Error: Failed to install requirements."
    exit 1
fi

# Inform about API Key
if [ -z "$GEMINI_API_KEY" ]; then
    echo ""
    echo "⚠️  Note: GEMINI_API_KEY environment variable is not set."
    echo "   The application will run using local fallback questions."
    echo "   To enable AI quiz generation, set the environment variable:"
    echo "   export GEMINI_API_KEY='your_api_key_here'"
    echo ""
fi

# Run the Flask application
echo "Starting Online Quiz System on http://localhost:5001..."
python app.py
```

#### 🪟 Windows (`run.bat`)
```cmd
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
    :: Try running python inside the venv to check if it's functional
    venv\Scripts\python.exe -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo WARNING: Existing virtual environment is broken or has a Python version mismatch.
        echo          Re-creating virtual environment...
        rmdir /s /q venv
    )
)

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment (venv)...
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

:: Inform about API Key
if "%GEMINI_API_KEY%"=="" (
    echo.
    echo WARNING: GEMINI_API_KEY environment variable is not set.
    echo          The application will run using local fallback questions.
    echo          To enable AI quiz generation, set the environment variable:
    echo          set GEMINI_API_KEY=your_api_key_here
    echo.
)

:: Run the Flask application
echo Starting Online Quiz System on http://localhost:5001...
python app.py

pause
```

---

### 🔧 Manual Setup (Optional Alternative)

If you prefer not to use the automated scripts, you can set up manually with these commands:

#### 1. Create and Activate Virtual Environment
* **macOS/Linux**:
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```
* **Windows**:
  ```cmd
  python -m venv venv
  call venv\Scripts\activate.bat
  ```

#### 2. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 3. Run the App
```bash
python app.py
```

### 🔑 (Optional) Provide your AI API Key
The application operates with built-in offline quiz fallbacks so you do not need an API key to test the app. However, to leverage full dynamic AI generation, provide a Gemini API Key:

* **macOS/Linux**:
  ```bash
  export GEMINI_API_KEY="your-key-here"
  ```
* **Windows (Command Prompt)**:
  ```cmd
  set GEMINI_API_KEY=your-key-here
  ```
* **Windows (PowerShell)**:
  ```powershell
  $env:GEMINI_API_KEY="your-key-here"
  ```

### 🌐 Accessing the App
Head to **`http://localhost:5001`** in your browser.

> **Demo Login Credentials**
> If you don't want to make an account, log in with:
> - **Username**: `admin`
> - **Password**: `admin123`

## Architecture Snapshot
- **Backend:** Python + Flask + SQLAlchemy  
- **Database:** SQLite3 (Stored automatically in `database.db`)  
- **Frontend:** Vanilla HTML/CSS/JS with modern glassmorphism styling  
- **PDF Export:** Browser-native `@media print` engine  
- **AI Engine:** Google Generative AI (`gemini-1.5-flash`)




run code in terminal

.\run.bat
