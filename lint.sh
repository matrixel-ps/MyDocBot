#!/usr/bin/env bash
set -euo pipefail

echo "=== repo hygiene ==="
# The agent-workflow files belong to the private overlay repo; the public repo
# must never track them (they're ignored only via this checkout's
# .git/info/exclude).
tracked_agent_files=$(git ls-files -- AGENTS.md CLAUDE.md .claude docs/agent-notes docs/tasks .agent.git 2>/dev/null || true)
if [ -n "$tracked_agent_files" ]; then
    echo "Agent workflow files are tracked in the public repo:"
    echo "$tracked_agent_files"
    exit 1
fi
echo "OK"

echo ""
echo "=== ruff ==="
python -m ruff check .

echo ""
echo "=== mypy ==="
# The agent-workflow tools (orient.py and its tests) live in a private overlay
# repo and are only present in the owner's checkout; check them when they are.
AGENT_TOOLS=()
if [ -f .claude/skills/task/orient.py ]; then
    AGENT_TOOLS=(.claude/skills/task/orient.py .claude/skills/task/test_orient.py)
fi
python -m mypy main.py mydocbot_app.py discord_bot.py core/ tests/ scripts/ "${AGENT_TOOLS[@]}"

echo ""
echo "=== tests ==="
python -m pytest tests/ "${AGENT_TOOLS[@]:1}" -q
