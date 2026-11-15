#!/usr/bin/env bash
set -euo pipefail

echo "=== ruff ==="
python -m ruff check .

echo ""
echo "=== mypy ==="
python -m mypy main.py mydocbot_app.py discord_bot.py core/ tests/ scripts/ .claude/skills/task/orient.py

echo ""
echo "=== tests ==="
python -m pytest tests/ -q
