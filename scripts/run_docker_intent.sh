#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <intent-file> [extra args]"
  echo "Example: $0 intents/01-baseline.md --compose-file docker/starcoin-3node.compose.yml --duration-override 60"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

INTENT_FILE="$1"
shift

python3 -m framework.cli run-docker "$INTENT_FILE" "$@"
