@echo off
rem Starts the API (which serves the web app) and the two-ESP32 simulator. Close the windows to stop.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo Virtual environment not found. Create it first by running: python -m venv .venv
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
start "AstroMed API" cmd /k python -m uvicorn api.main:app --env-file .env.example --host 0.0.0.0 --port 8000
timeout /t 4 /nobreak >nul
start "AstroMed simulator" cmd /k python -m simulator.simulate
