@echo off
chcp 65001 >nul
title 听课助手
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run.py
pause
