@echo off
chcp 65001 >nul
title copilot
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run.py
pause
