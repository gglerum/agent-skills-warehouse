#!/usr/bin/env bash
# Clone the third-party source repositories listed in repos.lock into repos/.
# Each checkout is pinned to the recorded commit (detached HEAD) so the
# warehouse review fingerprints stay valid.
#
# Usage: scripts/fetch-repos.sh [--latest] [name ...]
#   --latest   check out the remote default branch instead of the pinned commit
#              (the catalog will then need a fresh review)
#   name ...   only fetch the named directories
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lock="$root/repos.lock"
latest=0
only=()

for arg in "$@"; do
  case "$arg" in
    --latest) latest=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) only+=("$arg") ;;
  esac
done

wanted() {
  [ "${#only[@]}" -eq 0 ] && return 0
  local n
  for n in "${only[@]}"; do [ "$n" = "$1" ] && return 0; done
  return 1
}

while read -r name url commit; do
  case "$name" in ''|'#'*) continue ;; esac
  wanted "$name" || continue
  dest="$root/repos/$name"

  if [ -d "$dest/.git" ]; then
    echo "[$name] exists, fetching"
    git -C "$dest" fetch --quiet origin
  else
    echo "[$name] cloning $url"
    mkdir -p "$root/repos"
    git clone --quiet "$url" "$dest"
  fi

  if [ "$latest" -eq 1 ]; then
    git -C "$dest" checkout --quiet "$(git -C "$dest" symbolic-ref --short refs/remotes/origin/HEAD | sed 's|^origin/||')"
    git -C "$dest" merge --quiet --ff-only '@{u}'
  else
    git -C "$dest" checkout --quiet --detach "$commit"
  fi
  echo "[$name] at $(git -C "$dest" rev-parse --short HEAD)"
done < "$lock"
