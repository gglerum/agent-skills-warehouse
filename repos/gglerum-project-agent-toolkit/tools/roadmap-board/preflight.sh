#!/usr/bin/env bash
# Preflight for one roadmap issue, in one call: the issue with comments, the state of every "Blocked by" issue,
# the finding or feedback text named by the board's source field, the decisions that apply, and the design artifacts.
# Read-only. Needs `gh` and `jq`; configuration: roadmap.conf (see roadmap.conf.example).
#
#   preflight.sh <issue number>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${ROADMAP_CONF:-$SCRIPT_DIR/roadmap.conf}"
# shellcheck disable=SC1090
[[ -f "$CONF" ]] && source "$CONF"
: "${BOARD_REPO:?set BOARD_REPO in roadmap.conf or the environment}"
: "${BOARD_OWNER:?set BOARD_OWNER in roadmap.conf or the environment}"
: "${BOARD_PROJECT:?set BOARD_PROJECT in roadmap.conf or the environment}"
PREFLIGHT_GATE_ISSUES="${PREFLIGHT_GATE_ISSUES:-}"
PREFLIGHT_SOURCE_FIELD="${PREFLIGHT_SOURCE_FIELD:-source}"

[[ "${1:-}" =~ ^[0-9]+$ ]] || { sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
n=$1

gh issue view "$n" -R "$BOARD_REPO" --comments

body=$(gh issue view "$n" -R "$BOARD_REPO" --json body --jq .body)

echo
echo "=== Blockers ==="
# Blockers are the GitHub "Blocked by" relation.
blockers=$(gh api "repos/$BOARD_REPO/issues/$n/dependencies/blocked_by" --jq '.[].number' | grep -E '^[0-9]+$' | sort -un || true)
if [[ -z "$blockers" ]]; then
    echo "none"
else
    for b in $blockers; do
        gh issue view "$b" -R "$BOARD_REPO" --json number,state,title --jq '"#\(.number) \(.state)\t\(.title)"'
    done
fi

# A story that names a gate issue (a design or decision issue) without being blocked by it is the mistake behind building before the design was approved.
for d in $PREFLIGHT_GATE_ISSUES; do
    [[ "$d" != "$n" ]] || continue
    if printf '%s\n' "$body" | grep -qE "#$d([^0-9]|$)" && ! printf '%s\n' "$blockers" | grep -qx "$d"; then
        echo "WARNING: this issue names gate issue #$d but is not blocked by it; add the relation or check that the design is approved."
    fi
done

echo
echo "=== Source ==="
# The source ids are a field of the board card (finding ids and feedback ids).
source_ids=$(gh project item-list "$BOARD_PROJECT" --owner "$BOARD_OWNER" --limit 300 --format json 2>/dev/null \
    | jq -r --argjson n "$n" --arg field "$PREFLIGHT_SOURCE_FIELD" '.items[] | select(.content.number == $n) | .[$field] // ""' 2>/dev/null || true)
echo "${source_ids:-none}"
for id in $source_ids; do
    if [[ -n "${PREFLIGHT_FINDINGS_CMD:-}" ]]; then
        case "$id" in
            FB-[0-9]*)
                echo; echo "--- feedback item $id ---"
                $PREFLIGHT_FINDINGS_CMD fb show "$id" || true ;;
            [A-Z][0-9]*)
                echo; echo "--- finding $id ---"
                $PREFLIGHT_FINDINGS_CMD show "$id" || true ;;
        esac
    fi
done

if [[ -n "${PREFLIGHT_DECISIONS_CMD:-}" ]]; then
    echo
    echo "=== Decisions (the record files are the single source; blockers included) ==="
    related=$(printf '%s\n' "$source_ids" | tr -s ' ,' '\n' | grep -E '^([A-Z][0-9]+[a-z]?|FB-[0-9]{3})$' || true)
    # shellcheck disable=SC2086
    $PREFLIGHT_DECISIONS_CMD for "$n" $blockers $related
fi

if [[ -n "${PREFLIGHT_DESIGN_CMD:-}" ]]; then
    echo
    echo "=== Design artifacts (design register; frames inside a file are file#fN) ==="
    # shellcheck disable=SC2086
    $PREFLIGHT_DESIGN_CMD for "$n" $blockers
fi
