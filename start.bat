@echo off
call venv\Scripts\activate.bat

echo 🐰 Starting Bunny Clip Tool...
echo    Processor will open in a new window
echo    Bot runs in this window
echo.

:: Start processor in new window
start "Bunny Processor" cmd /k "call venv\Scripts\activate.bat && python main.py"

:: Wait then start bot
timeout /t 2 /nobreak >NUL
python run_bot.py
