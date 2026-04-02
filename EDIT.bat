@echo off
set "TARGET=%~dp0engine\game_main.py"
if not exist "%TARGET%" (
    echo Error: the main game script file was not found in:
    echo "%TARGET%"
    pause
    exit /b
)
start pythonw -m idlelib -e "%TARGET%"