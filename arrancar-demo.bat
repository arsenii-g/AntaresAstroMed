@echo off
rem Arranca la API (sirve la web) y el simulador de dos ESP32. Cerrar las ventanas para parar.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
start "AstroMed API" cmd /k python -m uvicorn api.main:app --env-file .env.example --host 0.0.0.0 --port 8000
timeout /t 4 /nobreak >nul
start "AstroMed simulador" cmd /k python -m simulator.simulate
