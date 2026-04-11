@echo off
REM Jack V2 — Start Backend + Frontend

echo Starting Jack V2...
echo.

REM Start backend
echo [1/2] Starting FastAPI backend on :8000...
start "Jack V2 Backend" cmd /k "cd /d %~dp0 && python -m uvicorn jack.api.main:app --reload --port 8000"

REM Wait for backend to be ready
timeout /t 3 /nobreak >nul

REM Start frontend
echo [2/2] Starting Vite dev server on :5173...
cd /d %~dp0\ui
start "Jack V2 Frontend" cmd /k "npm run dev"

echo.
echo ========================================
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo ========================================
echo.
echo Press any key to exit this launcher...
pause >nul
