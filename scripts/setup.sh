#!/usr/bin/env bash
# First-time setup helper for SupplyIQ.
# Usage: bash scripts/setup.sh
set -euo pipefail

echo "=== SupplyIQ setup ==="

if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Install Python 3.11+ first." >&2
    exit 1
fi

echo "-> Installing Python dependencies..."
pip install -r requirements.txt

if [ ! -f .env ]; then
    echo "-> Creating .env from .env.example..."
    cp .env.example .env
else
    echo "-> .env already exists, leaving it untouched."
fi

echo "-> Creating local data directory..."
mkdir -p data

echo ""
echo "Setup complete. Next steps:"
echo "  1. Review and edit .env"
echo "  2. make run-api          # starts FastAPI on :8000 (replenishment/routing/network solve immediately)"
echo "  3. make docker-up        # starts Ollama, needed for /copilot/ask"
echo "  4. make run-ui           # starts the demo UI on :7860"
