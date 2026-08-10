#!/usr/bin/env bash
set -e
if [ ! -x .venv/bin/python ]; then
  echo "No existe .venv. Ejecuta primero: python -m venv .venv"
  exit 1
fi
exec .venv/bin/python main.py
