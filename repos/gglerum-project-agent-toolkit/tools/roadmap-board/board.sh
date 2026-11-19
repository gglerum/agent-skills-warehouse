#!/usr/bin/env bash
# Roadmap board helper for a GitHub Project (v2) whose cards are issues of one repository.
# Needs `gh` (logged in, with the `project` scope) and `jq`. Configuration: see roadmap.conf.example.
#
#   board.sh next                      open Ready/Backlog issues whose blockers (GitHub "Blocked by" relation) are all closed, that are no epic (has sub-issues) and not waiting on someone
#   board.sh status <issue> <Status>   move a card (any status name of the project's Status field)
#   board.sh handoff <issue> <file>    write <file> as the session handoff to <handoff dir>/<date>-issue-<n>.md (committed with the PR; not a tracker comment)
#   board.sh waitingon                 list open issues that wait on someone (wait label, assignee, the "Waiting on" line)
#   board.sh waitingon <issue> "<what>" [--who <login>]   mark an issue as waiting: label + assignee (default BOARD_DEFAULT_WAIT_ASSIGNEE) + one dated line on top
#   board.sh waitingon <issue> --done  clear it again (label, assignee and line removed)
#   board.sh session-prompt <issue>... [free text]   print the start prompt for a fresh session on these issues (from issue and board data only)
#
# Everything except `handoff` and `session-prompt` (read-only) writes to the tracker: run those only when the project authorizes it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="${ROADMAP_CONF:-$SCRIPT_DIR/roadmap.conf}"
# shellcheck disable=SC1090
[[ -f "$CONF" ]] && source "$CONF"
: "${BOARD_REPO:?set BOARD_REPO (owner/repository) in roadmap.conf or the environment}"
: "${BOARD_OWNER:?set BOARD_OWNER (the login that owns the project) in roadmap.conf or the environment}"
: "${BOARD_PROJECT:?set BOARD_PROJECT (the project number) in roadmap.conf or the environment}"
BOARD_REPO_OWNER="${BOARD_REPO%%/*}"
BOARD_REPO_NAME="${BOARD_REPO##*/}"
BOARD_READY_STATUSES="${BOARD_READY_STATUSES:-Ready Backlog}"
BOARD_WAIT_LABEL="${BOARD_WAIT_LABEL:-waiting-on}"
BOARD_DEFAULT_WAIT_ASSIGNEE="${BOARD_DEFAULT_WAIT_ASSIGNEE:-$BOARD_OWNER}"
BOARD_EPIC_PREFIX="${BOARD_EPIC_PREFIX:-EPIC}"
BOARD_HANDOFF_DIR="${BOARD_HANDOFF_DIR:-docs/handoffs}"
BOARD_SESSION_SKILL="${BOARD_SESSION_SKILL:-roadmap-session}"
BOARD_PREFLIGHT_CMD="${BOARD_PREFLIGHT_CMD:-tools/preflight.sh}"
BOARD_CODE_REGEX="${BOARD_CODE_REGEX:-^\\[(?<code>[A-Z]+-[0-9]+)\\] ?(?<t>.*)\$}"
WAIT_PREFIX="Waiting on"

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

cmd_next() {
    local -A state status
    local number st title blockers waiting ready=0

    while IFS=$'\t' read -r number st; do state[$number]=$st; done < <(
        gh issue list -R "$BOARD_REPO" --state all --limit 300 --json number,state --jq '.[] | [.number, .state] | @tsv')
    while IFS=$'\t' read -r number st; do status[$number]=$st; done < <(
        gh project item-list "$BOARD_PROJECT" --owner "$BOARD_OWNER" --limit 300 --format json \
            --jq '.items[] | select(.content.number != null) | [.content.number, (.status // "")] | @tsv')

    while IFS=$'\t' read -r number title waiting blockers; do
        [[ "${state[$number]:-}" == "OPEN" ]] || continue
        [[ "$waiting" == "0" ]] || continue
        [[ " $BOARD_READY_STATUSES " == *" ${status[$number]:-} "* && -n "${status[$number]:-}" ]] || continue
        local open_blockers="" b
        for b in ${blockers//,/ }; do
            [[ "${state[$b]:-OPEN}" == "CLOSED" ]] || open_blockers+=" #$b"
        done
        [[ -z "$open_blockers" ]] || continue
        printf '#%s\t%s\t%s\n' "$number" "${status[$number]}" "$title"
        ready=1
    done < <(gh api graphql --paginate -F owner="$BOARD_REPO_OWNER" -F name="$BOARD_REPO_NAME" -F wait="$BOARD_WAIT_LABEL" -F epic="$BOARD_EPIC_PREFIX" -f query='
        query($owner: String!, $name: String!, $endCursor: String) { repository(owner: $owner, name: $name) {
            issues(first: 100, states: OPEN, orderBy: {field: CREATED_AT, direction: ASC}, after: $endCursor) {
                pageInfo { hasNextPage endCursor }
                nodes { number title body labels(first: 20) { nodes { name } } blockedBy(first: 50) { nodes { number } } subIssues(first: 1) { totalCount } }
            } } }' --jq '
        .data.repository.issues.nodes[]
        | select(((.subIssues.totalCount > 0) or (.title | startswith("'"$BOARD_EPIC_PREFIX"'"))) | not)
        | [.number, .title, (if any(.labels.nodes[]; .name == "'"$BOARD_WAIT_LABEL"'") then "1" else "0" end),
           ([.blockedBy.nodes[].number] | unique | map(tostring) | join(","))]
        | @tsv')

    [[ $ready -eq 1 ]] || echo "Nothing is ready: every open issue is blocked, waiting on someone (see waitingon), waiting for a decision, or in progress."
}

cmd_status() {
    local issue=${1:-} name=${2:-}
    [[ "$issue" =~ ^[0-9]+$ && -n "$name" ]] || usage
    local project_id field_id option_id item_id
    project_id=$(gh project view "$BOARD_PROJECT" --owner "$BOARD_OWNER" --format json --jq .id)
    field_id=$(gh project field-list "$BOARD_PROJECT" --owner "$BOARD_OWNER" --format json --jq '.fields[] | select(.name=="Status") | .id')
    option_id=$(gh project field-list "$BOARD_PROJECT" --owner "$BOARD_OWNER" --format json \
        | jq -r --arg name "$name" '.fields[] | select(.name=="Status") | .options[] | select(.name==$name) | .id')
    [[ -n "$option_id" ]] || { echo "Unknown status: $name" >&2; exit 1; }
    item_id=$(gh project item-list "$BOARD_PROJECT" --owner "$BOARD_OWNER" --limit 300 --format json \
        | jq -r --argjson n "$issue" '.items[] | select(.content.number==$n) | .id')
    [[ -n "$item_id" ]] || { echo "Issue #$issue is not on the board" >&2; exit 1; }
    gh project item-edit --id "$item_id" --project-id "$project_id" --field-id "$field_id" --single-select-option-id "$option_id" >/dev/null
    echo "#$issue -> $name"
}

cmd_handoff() {
    local issue=${1:-} file=${2:-}
    [[ "$issue" =~ ^[0-9]+$ && -f "$file" ]] || usage
    local dir target branch
    dir="$BOARD_HANDOFF_DIR"
    mkdir -p "$dir"
    target="$dir/$(date +%F)-issue-$issue.md"
    branch=$(git branch --show-current 2>/dev/null || true)
    { printf '# Handoff issue #%s (%s, branch %s)\n\n' "$issue" "$(date +%F)" "${branch:-unknown}"; cat "$file"; } >"$target"
    echo "written $target; commit it with the branch"
}

# "What we wait for" is one line at the top of the body; WHO we wait on is the assignee; the label makes it filterable.
cmd_waitingon() {
    local issue=${1:-} what=${2:-} who="$BOARD_DEFAULT_WAIT_ASSIGNEE" body assignee
    [[ "${3:-}" == "--who" && -n "${4:-}" ]] && who=$4
    if [[ -z "$issue" ]]; then
        [[ -n "$(gh issue list -R "$BOARD_REPO" --state open --label "$BOARD_WAIT_LABEL" --json number --jq '.[].number')" ]] || { echo "Nothing is waiting on anyone."; return; }
        gh issue list -R "$BOARD_REPO" --state open --label "$BOARD_WAIT_LABEL" --limit 300 --json number,title,body,assignees | jq -r --arg prefix "$WAIT_PREFIX" '
            sort_by(.number)[]
            | "#\(.number)\t\(.title)\n    "
              + (([.assignees[].login] | map("@" + .) | join(" ")) as $who | (if $who == "" then "(no assignee)" else $who end) + "  ")
              + (.body | split("\n") | map(select(startswith("**" + $prefix))) | first // "(no wait line)")'
        return
    fi
    [[ "$issue" =~ ^[0-9]+$ && ( "$what" == "--done" || -n "$what" ) ]] || usage
    body=$(mktemp)
    gh issue view "$issue" -R "$BOARD_REPO" --json body --jq .body >"$body"
    # Drop the wait line; for "set", put the new line on top.
    local strip='gsub("(^|\n)\\*\\*" + $prefix + "[^\n]*\n*"; "\n") | sub("^\\s+"; "")'
    if [[ "$what" == "--done" ]]; then
        jq -Rsr --arg prefix "$WAIT_PREFIX" "$strip" <"$body" >"$body.new"
        gh issue edit "$issue" -R "$BOARD_REPO" --body-file "$body.new" --remove-label "$BOARD_WAIT_LABEL" >/dev/null
        for assignee in $(gh issue view "$issue" -R "$BOARD_REPO" --json assignees --jq '.assignees[].login'); do
            [[ "$assignee" == "$BOARD_OWNER" ]] || gh issue edit "$issue" -R "$BOARD_REPO" --remove-assignee "$assignee" >/dev/null
        done
        echo "#$issue is no longer waiting"
    else
        jq -Rsr --arg prefix "$WAIT_PREFIX" --arg line "**$WAIT_PREFIX $who ($(date +%F)):** $what" "$strip | \$line + \"\\n\\n\" + ." <"$body" >"$body.new"
        gh issue edit "$issue" -R "$BOARD_REPO" --body-file "$body.new" --add-label "$BOARD_WAIT_LABEL" --add-assignee "$who" >/dev/null
        echo "#$issue waits on $who: $what"
    fi
    rm -f "$body" "$body.new"
}

cmd_session_prompt() {
    [[ $# -gt 0 ]] || usage
    local n items="" line extra="" args=() board nums
    # Numbers are issues; any other word is free text for the session, added to the prompt.
    for n in "$@"; do
        if [[ "$n" =~ ^#?[0-9]+$ ]]; then args+=("$n"); else extra+="${extra:+ }$n"; fi
    done
    [[ ${#args[@]} -gt 0 ]] || usage
    set -- "${args[@]}"
    board=$(gh project item-list "$BOARD_PROJECT" --owner "$BOARD_OWNER" --limit 300 --format json)
    for n in "$@"; do
        n=${n#\#}
        line=$(jq -r --argjson n "$n" --arg re "$BOARD_CODE_REGEX" '
            .items[] | select(.content.number == $n)
            | (.content.title | capture($re) // {code: "", t: .content.title}) as $m
            | "#\($n) " + (if $m.code != "" then $m.code + " " else "" end) + $m.t
              + ([.kind, (if .size then "size " + .size else null end)] | map(select(. != null and . != "")) | if length > 0 then " (" + join(", ") + ")" else "" end)
              + (if (.source // "") != "" then ", source " + .source else "" end)' <<<"$board")
        [[ -n "$line" ]] || { echo "Issue #$n is not on the board" >&2; exit 1; }
        items+="- $line"$'\n'
    done
    nums=$(printf '#%s, ' "$@" | sed 's/, $//; s/##/#/g')
    printf 'Use the %s skill. Run `%s <n>` for each of %s and follow the skill from there.\n%sOne branch, one PR; reference the issues with `Refs`, never `Closes`.\n' "$BOARD_SESSION_SKILL" "$BOARD_PREFLIGHT_CMD" "$nums" "$items"
    [[ -z "$extra" ]] || printf 'Extra: %s\n' "$extra"
}

case "${1:-}" in
    session-prompt) shift; cmd_session_prompt "$@" ;;
    next) cmd_next ;;
    status) shift; cmd_status "$@" ;;
    handoff) shift; cmd_handoff "$@" ;;
    waitingon) shift; cmd_waitingon "$@" ;;
    *) usage ;;
esac
