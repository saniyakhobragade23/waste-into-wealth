@echo off
setlocal
cd /d "%~dp0"
python app.py
if errorlevel 1 (
    echo.
    echo CROP CYCLE did not start. If Flask is missing, run:
    echo python -m pip install -r requirements.txt
    pause
)
