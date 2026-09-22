#!/usr/bin/env bash
set -euo pipefail

echo "=== ruff ==="
python -m ruff check .

echo ""
echo "=== mypy ==="
python -m mypy main.py mydocbot_app.py core/ tests/

echo ""
echo "=== tests ==="
python -m pytest tests/ -q
