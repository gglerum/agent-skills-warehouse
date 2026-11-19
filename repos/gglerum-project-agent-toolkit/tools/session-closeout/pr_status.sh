#!/usr/bin/env bash
# One-call status of a pull request: merge state, checks, and the log tail of every failed check. Read-only.
# Needs `gh` (logged in). The repository comes from PR_REPO (owner/repository) or from the current checkout.
#
#   pr_status.sh <pr-number>
set -euo pipefail

pr="${1:-}"
[[ "$pr" =~ ^[0-9]+$ ]] || { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
repo="${PR_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"

# GitHub computes "mergeable" lazily: the first answer is often UNKNOWN, so ask again.
for _ in 1 2 3; do
    [[ "$(gh pr view "$pr" -R "$repo" --json mergeable --jq .mergeable)" != UNKNOWN ]] && break
    sleep 2
done
gh pr view "$pr" -R "$repo" --json number,title,state,isDraft,headRefName,baseRefName,mergeable,mergeStateStatus,reviewDecision \
    --jq '"#\(.number) \(.title)\n\(.headRefName) -> \(.baseRefName), state \(.state)\(if .isDraft then " (draft)" else "" end)\nmergeable: \(.mergeable), merge state: \(.mergeStateStatus), review: \(.reviewDecision // "none")"'
echo "--- checks"
gh pr checks "$pr" -R "$repo" || true
if [[ "$(gh pr view "$pr" -R "$repo" --json mergeable --jq .mergeable)" == CONFLICTING ]]; then
    echo "--- merge conflict: git switch <branch> && git merge <base>, resolve, run the tests, push"
fi

failed=$(gh pr checks "$pr" -R "$repo" --json name,state,link --jq '.[] | select(.state=="FAILURE") | [.name, .link] | @tsv' 2>/dev/null || true)
[[ -n "$failed" ]] || exit 0
while IFS=$'\t' read -r name link; do
    run=$(grep -oE 'runs/[0-9]+' <<<"$link" | head -1 | cut -d/ -f2 || true)
    echo "--- failed: $name"
    if [[ -n "$run" ]]; then gh run view "$run" -R "$repo" --log-failed 2>/dev/null | tail -40; else echo "$link"; fi
done <<<"$failed"
