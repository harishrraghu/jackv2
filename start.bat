@echo off
setlocal

REM Jack V2 -- Start Backend + Frontend
REM ---------------------------------------------------------------------------

echo.
echo ===========================================================================
echo   JACK V2 LAUNCHER
echo ===========================================================================
echo.

REM Kill any existing processes on port 8001 (FastAPI)
echo [1/4] Checking for existing backend on :8001...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001.*LISTENING"') do (
    echo   - Found existing backend (PID %%a). Killing...
    taskkill /PID %%a /F >nul 2>&1
)

REM Kill any existing processes on port 5173 (Vite)
echo [2/4] Checking for existing frontend on :5173...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173.*LISTENING"') do (
    echo   - Found existing frontend (PID %%a). Killing...
    taskkill /PID %%a /F >nul 2>&1
)

timeout /t 2 /nobreak >nul

REM Start backend (FastAPI on :8001)
echo [3/4] Starting FastAPI backend on :8001...
start "Jack Backend" cmd /k "cd /d %~dp0jack && python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8001"

REM Wait for backend to be ready
echo [4/4] Starting Vite dev server on :5173...
timeout /t 4 /nobreak >nul

REM Start frontend (Vite on :5173)
start "Jack Frontend" cmd /k "cd /d %~dp0ui && npm run dev"

echo.
echo ===========================================================================
echo   SYSTEM READY
echo ===========================================================================
echo   Backend (API):  http://localhost:8001
echo   Frontend (UI):   http://localhost:5173
echo   API Docs:       http://localhost:8001/docs
echo ===========================================================================
echo.
echo   NOTE: Agents (Learner, Trader, Builder) are virtual participants. 
echo   They start when you run a "Single Day" simulation in the UI.
echo.
echo   Historical Backtest (Engine 1) Result: +7.05L Profit (sim.py)
echo   Current Data Range: CSV data ends on 2024-04-12.
echo.
echo Press any key to close this launcher window...
pause >nul
