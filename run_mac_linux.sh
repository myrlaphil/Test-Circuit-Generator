#!/usr/bin/env bash
# Run with:  bash run_mac_linux.sh
# First run installs the packages (needs internet), later runs start straight away.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Setting up for the first time - this takes a few minutes..."
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
else
  source .venv/bin/activate
fi
streamlit run app.py
