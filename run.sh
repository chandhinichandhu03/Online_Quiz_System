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


# Run the Flask application
echo "Starting Online Quiz System on http://localhost:5001..."
python app.py
