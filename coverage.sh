#!/usr/bin/env bash
# Coverage report for the test suite (report only: never fails on a
# percentage). lint.sh stays the gate. Needs requirements-dev.txt.
#   bash coverage.sh          # per-file table with missing lines
#   bash coverage.sh --html   # also writes htmlcov/index.html
set -euo pipefail

reports=(--cov-report=term-missing)
if [[ "${1:-}" == "--html" ]]; then
    reports+=(--cov-report=html)
fi

python -m pytest tests/ -q --cov "${reports[@]}"
