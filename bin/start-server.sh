#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f "server.py" ]]; then
  echo "Error: server.py not found in project root." >&2
  exit 1
fi

python server.py
