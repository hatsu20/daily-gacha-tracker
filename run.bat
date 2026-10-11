@echo off
cd /d "%~dp0"
pythonw daily_gacha_tracker.py
if errorlevel 1 python daily_gacha_tracker.py
