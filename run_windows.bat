@echo off
setlocal
if not exist .venv\Scripts\python.exe (
  echo No existe .venv. Ejecuta primero: python -m venv .venv
  pause
  exit /b 1
)
.venv\Scripts\python.exe main.py
pause
