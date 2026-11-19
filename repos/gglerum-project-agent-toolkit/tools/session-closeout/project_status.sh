#!/usr/bin/env bash
# Project status printed from tools only: nothing here is typed by hand, so nothing can go stale in git. Read-only.
# Needs git; `gh` (logged in) for the GitHub sections. Configuration: closeout.conf (STATUS_SECTIONS, STATUS_BOARD_CMD).
#
#   project_status.sh           full status: git, pull requests, board, configured sections
#   project_status.sh --short   branch, board counts and the newest handoff (for a session-start hook)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${CLOSEOUT_CONF:-$SCRIPT_DIR/closeout.conf}"
STATUS_SECTIONS=()          # "Title|command" entries, run through bash -c
STATUS_BOARD_CMD=""         # e.g. "bash tools/board.sh"; used for the next and waiting lists when set
STATUS_HANDOFF_DIR="docs/handoffs"
STATUS_BASE="origin/main"
# shellcheck disable=SC1090
[[ -f "$CONF" ]] && source "$CONF"

short=0
case "${1:-}" in
    "") ;;
    --short) short=1 ;;
    *) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
git rev-parse --show-toplevel >/dev/null 2>&1 || { echo "not inside a git work tree" >&2; exit 2; }
cd "$(git rev-parse --show-toplevel)"

section() { printf '\n== %s ==\n' "$1"; }
have_gh() { command -v gh >/dev/null && gh auth status >/dev/null 2>&1; }

if [[ $short -eq 1 ]]; then
    echo "Branch: $(git branch --show-current)"
    last_handoff=$(find "$STATUS_HANDOFF_DIR" -name '*.md' 2>/dev/null | sort | tail -1)
    if [[ -n "$last_handoff" ]]; then
        echo "Last handoff (read it before you start; $last_handoff):"
        head -30 "$last_handoff"
    fi
    exit 0
fi

section "Git"
echo "Branch: $(git branch --show-current)"
main_ref=$STATUS_BASE
git rev-parse --verify -q "$main_ref" >/dev/null || main_ref=${STATUS_BASE#*/}
echo "$main_ref: $(git log -1 --format='%h %cs' "$main_ref" 2>/dev/null || echo 'not found')"
git log --first-parent "$main_ref" -5 --format='  %h %cs %s' 2>/dev/null

section "GitHub"
if have_gh; then
    echo "Open pull requests:"
    gh pr list --state open --json number,title,headRefName --jq '.[] | "  #\(.number) \(.title) (\(.headRefName))"'
    if [[ -n "$STATUS_BOARD_CMD" ]]; then
        echo "Next (ready, unblocked):"
        bash -c "$STATUS_BOARD_CMD next" | sed 's/^/  /'
        echo "Waiting on someone:"
        bash -c "$STATUS_BOARD_CMD waitingon" | sed 's/^/  /'
    fi
else
    echo "skipped: gh is not available or not logged in (the git and configured sections still apply)"
fi

for entry in "${STATUS_SECTIONS[@]}"; do
    section "${entry%%|*}"
    bash -c "${entry#*|}" 2>&1 || echo "(command failed)"
done
