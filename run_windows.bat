@echo off
REM Double-click me. First run installs the packages (needs internet), later runs start straight away.
cd /d "%~dp0"
if not exist .venv (
  echo Setting up for the first time - this takes a few minutes...
  python -m venv .venv || (echo Python was not found. Install it from https://www.python.org/downloads/ and tick "Add to PATH". & pause & exit /b 1)
  call .venv\Scripts\activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate
)
streamlit run app.py
pause
