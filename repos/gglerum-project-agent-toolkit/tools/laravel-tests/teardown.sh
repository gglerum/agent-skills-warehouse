#!/usr/bin/env bash
# Keep ownership receipts in the common Git directory, even if worktree removal fails.
set -euo pipefail
adapter_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$adapter_dir/session_database.py" teardown "$1" "$2"
