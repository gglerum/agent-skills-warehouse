#!/usr/bin/env bash
# Called by utils/shared/scripts/new_session.sh inside a fresh worktree: $1 = worktree dir, $2 = topic.
# Installs dependencies, copies .env, builds the Vite assets the tests need and creates a per-worktree test database.
set -euo pipefail
dir="$1"
topic="$2"
cd "$dir"

# Xdebug (enabled in the devcontainer) makes composer and artisan several times slower.
export XDEBUG_MODE=off

[ -e .env ] || cp "$MAIN_ROOT/.env" .env
composer install --no-interaction --no-progress --quiet

# Feature tests render Filament pages, which need public/build/manifest.json (git-ignored).
npm ci --ignore-scripts --silent --no-audit --no-fund
npm run build --silent

# Per-worktree test database, so parallel sessions don't wipe each other's test data.
# The database user may create databases named testing* (docker/mariadb/create-testing-database.sh).
if grep -qsF '.testing-database' tests/bootstrap.php; then
    python3 "$(dirname "$0")/session_database.py" setup "$dir" "$topic"
else
    echo "Test bootstrap must read .testing-database; refusing shared test state" >&2
    exit 1
fi
