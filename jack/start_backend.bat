@echo off
echo Starting Jack Backend...
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8001
pause
