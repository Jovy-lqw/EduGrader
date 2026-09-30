@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Python virtual environment is missing.
  echo Run: py -3 -m venv .venv
  echo Then: .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)

if not exist "frontend\dist\index.html" (
  echo Frontend build is missing.
  echo Run: cd frontend
  echo Then: npm install ^&^& npm run build
  exit /b 1
)

if "%EDUGRADER_HOST%"=="" set "EDUGRADER_HOST=127.0.0.1"
if "%EDUGRADER_PORT%"=="" set "EDUGRADER_PORT=8000"

".venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host "%EDUGRADER_HOST%" --port "%EDUGRADER_PORT%"
