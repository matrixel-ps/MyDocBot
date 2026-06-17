#!/usr/bin/env bash
set -euo pipefail

echo "=== ruff ==="
python -m ruff check .

echo ""
echo "=== mypy ==="
python -m mypy main.py core/ tests/ || true

echo ""
echo "=== tests ==="
python -m pytest tests/ -q
