@echo off
title Qwen3-TTS Installer
echo.
echo  ============================================
echo    Qwen3-TTS Plugin Installer for Sapphire
echo  ============================================
echo.

:: Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found! Please install Python 3.10+ first.
    echo  Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: Run the Python installer script
python "%~dp0install.py"

echo.
pause
