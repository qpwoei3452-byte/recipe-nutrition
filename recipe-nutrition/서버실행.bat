@echo off
cd /d "%~dp0backend"
call ..\venv\Scripts\activate.bat
uvicorn main:app --reload --port 8888
pause