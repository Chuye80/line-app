@echo off
setlocal

cd /d "C:\ATE\py_tools\line_app"

if not exist "C:\ATE\py_tools\line_app\.venv\Scripts\python.exe" (
    echo Could not find .venv at C:\ATE\py_tools\line_app\.venv
    pause
    exit /b 1
)

if not exist "C:\ATE\py_tools\line_app\frontend\package.json" (
    echo Could not find the frontend folder.
    pause
    exit /b 1
)

start "LineApp Backend" cmd /k "cd /d C:\ATE\py_tools\line_app && .venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000"

start "LineApp Frontend" cmd /k "cd /d C:\ATE\py_tools\line_app\frontend && set PATH=C:\Program Files\nodejs;%PATH% && npm run dev"

ping 127.0.0.1 -n 5 >nul
start "" "http://localhost:5173"
