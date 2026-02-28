@echo off
call venv\Scripts\activate.bat

echo.
echo   Bunny Clip Tool starting...
echo   Open http://localhost:5050 in your browser.
echo   Press Ctrl+C to stop.
echo.

:: Open browser automatically
start http://localhost:5050

python app.py
