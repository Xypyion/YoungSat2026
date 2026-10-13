@echo off
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
python sunseek_gs.py
if errorlevel 1 pause
