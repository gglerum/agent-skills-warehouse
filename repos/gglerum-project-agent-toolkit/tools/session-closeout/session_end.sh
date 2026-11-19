#!/usr/bin/env bash
# What to check before a session stops, in one call: "is it recorded, generated, committed and pushed?".
# Read-only; exit 1 when something is not in order. Configuration: closeout.conf (see closeout.conf.example).
#
#   session_end.sh            checks, then the state of the branch
#   session_end.sh --offline  skip the checks that need the network (CLOSEOUT_ONLINE_CHECKS, the pull request state)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${CLOSEOUT_CONF:-$SCRIPT_DIR/closeout.conf}"
CLOSEOUT_CHECKS=()
CLOSEOUT_ONLINE_CHECKS=()
CLOSEOUT_DOC_PATHS=()
CLOSEOUT_BASE="origin/main"
# shellcheck disable=SC1090
[[ -f "$CONF" ]] && source "$CONF"

case "${1:-}" in
    ""|--offline) ;;
    *) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
offline=0; [[ "${1:-}" == "--offline" ]] && offline=1
git rev-parse --show-toplevel >/dev/null 2>&1 || { echo "FAIL  not inside a git work tree" >&2; exit 2; }
cd "$(git rev-parse --show-toplevel)"
failed=0

# run <label> <command string>: the command runs through bash -c so a configured check may hold arguments.
run() {
    local label=$1 out
    shift
    if out=$(bash -c "$*" 2>&1); then
        printf 'ok    %s\n' "$label"
    else
        printf 'FAIL  %s\n%s\n' "$label" "$(printf '%s\n' "$out" | head -8 | sed 's/^/        /')"
        failed=1
    fi
}

if [[ ${#CLOSEOUT_CHECKS[@]} -gt 0 ]]; then
    echo "== Records and generated files =="
    for entry in "${CLOSEOUT_CHECKS[@]}"; do run "${entry%%|*}" "${entry#*|}"; done
fi
if [[ $offline -eq 0 && ${#CLOSEOUT_ONLINE_CHECKS[@]} -gt 0 ]]; then
    for entry in "${CLOSEOUT_ONLINE_CHECKS[@]}"; do run "${entry%%|*}" "${entry#*|}"; done
fi

echo; echo "== Branch =="
branch=$(git branch --show-current)
echo "branch: ${branch:-"(detached)"}"
dirty=$(git status --porcelain)
if [[ -n "$dirty" ]]; then
    echo "FAIL  uncommitted or untracked files:"
    printf '%s\n' "$dirty" | head -15 | sed 's/^/        /'
    failed=1
else
    echo "ok    working tree clean"
fi
if upstream=$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null); then
    [[ "$upstream" == */"$branch" ]] || { echo "FAIL  upstream is $upstream, not <remote>/$branch: git push -u <remote> $branch"; failed=1; }
    ahead=$(git rev-list --count "$upstream..HEAD"); behind=$(git rev-list --count "HEAD..$upstream")
    if [[ "$ahead" -gt 0 ]]; then echo "FAIL  $ahead commit(s) not pushed to $upstream"; failed=1; else echo "ok    pushed ($upstream)"; fi
    [[ "$behind" -eq 0 ]] || echo "note  $behind commit(s) on $upstream that are not here"
else
    echo "FAIL  no upstream: git push -u <remote> $branch"; failed=1
fi

if [[ ${#CLOSEOUT_DOC_PATHS[@]} -gt 0 ]]; then
    echo; echo "== Docs this branch touched (against $CLOSEOUT_BASE) =="
    changed=$(git diff --name-only "$CLOSEOUT_BASE"...HEAD 2>/dev/null || true)
    for pair in "${CLOSEOUT_DOC_PATHS[@]}"; do
        path=${pair%%|*}; what=${pair#*|}
        if grep -q "^$path" <<<"$changed"; then echo "yes   $what"; else echo "no    $what"; fi
    done
    echo "(\"no\" is fine when nothing applies; a screen change without a design register change, or a step without a log entry, is not)"
fi

if [[ $offline -eq 0 ]] && command -v gh >/dev/null && pr=$(gh pr view --json number,url,state,mergeable -q '"#\(.number) \(.state) mergeable=\(.mergeable) \(.url)"' 2>/dev/null); then
    echo; echo "== Pull request =="; echo "$pr"
fi
exit $failed
