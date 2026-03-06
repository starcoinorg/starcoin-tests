#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <intent-file> [extra args]"
  echo "Example: $0 intents/02-node-down.md --node-count 2 --fault-duration 20"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

INTENT_FILE="$1"
shift

python3 -m framework.cli run "$INTENT_FILE" \
  --starcoin-bin /Users/simon/starcoin-projects/starcoin/target/debug/starcoin \
  "$@"
