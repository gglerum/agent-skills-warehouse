#!/usr/bin/env bash
#
# Set up (or remove) a second work session in its own git worktree, so two Claude
# sessions can work on two branches/PRs at the same time without touching each
# other's files or dependencies.
#
# Usage:
#   <this script> <topic> [--window]   create <WORKTREES_DIR>/<topic> on <SESSION_PREFIX>/<date>-<topic>
#   <this script> --resume <topic>     retry setup in an existing, journaled worktree
#   <this script> --remove <topic>     remove the worktree (keeps the branch)
#   <this script> --list               list the session worktrees
#
# <topic>: lowercase letters, digits and dashes, e.g. "retry-logic".
# Settings: .agent-toolkit/workflow.conf. Project-specific setup (dependencies, env, test DB): .agent-toolkit/session-setup.sh.
# The worktree lives inside the repository (git-ignored) because only the repository folder is mounted
# into the devcontainer; a sibling folder would be lost on rebuild.

set -Eeuo pipefail

# Path the user ran, shown in hints (the script lives in utils/shared/scripts when vendored as a subtree).
SELF="$0"
MAIN_ROOT="$(cd "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" && pwd)"
BASE_BRANCH=main
SESSION_PREFIX=session
WORKTREES_DIR_NAME=.worktrees
# shellcheck disable=SC1091
[ -f "$MAIN_ROOT/.agent-toolkit/workflow.conf" ] && . "$MAIN_ROOT/.agent-toolkit/workflow.conf"
WORKTREES_DIR="$MAIN_ROOT/${WORKTREES_DIR:-$WORKTREES_DIR_NAME}"
RECOVERY_DIR="$(git rev-parse --path-format=absolute --git-common-dir)/session-recovery"

fail() { echo "❌ $*" >&2; exit 1; }
step() { echo "▶ $*"; }

validate_topic() {
    [[ "${1:-}" =~ ^[a-z0-9][a-z0-9-]{0,39}[a-z0-9]$ ]] || fail "Topic must be 2-41 chars of a-z, 0-9 and '-', e.g. retry-logic."
}

# Journals and locks live outside the worktree so failed cleanup retains evidence.
lock_session() {
    mkdir -p "$RECOVERY_DIR"
    mkdir "$RECOVERY_DIR/$1.lock" 2>/dev/null || fail "Session locked: $RECOVERY_DIR/$1.lock. Check for an active process before removing a stale lock."
    RECOVERY_HINT="$RECOVERY_DIR/$1"
    trap 'echo "Session stopped; inspect $RECOVERY_HINT and git worktree list before resume or cleanup." >&2' ERR
    trap "rmdir -- $(printf '%q' "$RECOVERY_DIR/$1.lock")" EXIT
}

phase() {
    printf '%s\n' "$1" > "$RECOVERY_DIR/$topic/phase.tmp"
    mv "$RECOVERY_DIR/$topic/phase.tmp" "$RECOVERY_DIR/$topic/phase"
}

verify_session() {
    [ "$(cat "$RECOVERY_DIR/$topic/path")" = "$dir" ] || fail "Recovery path mismatch. Inspect $RECOVERY_DIR/$topic."
    [ "$(git -C "$dir" rev-parse --show-toplevel)" = "$dir" ] || fail "Worktree identity mismatch."
    [ "$(git -C "$dir" rev-parse --path-format=absolute --git-common-dir)" = "$(git -C "$MAIN_ROOT" rev-parse --path-format=absolute --git-common-dir)" ] || fail "Repository identity mismatch."
    [ "$(git -C "$dir" branch --show-current)" = "$(cat "$RECOVERY_DIR/$topic/branch")" ] || fail "Branch changed; inspect recovery journal before cleanup."
}


list_sessions() {
    git -C "$MAIN_ROOT" worktree list | grep "/$(basename "$WORKTREES_DIR")/" || echo "No session worktrees."
}

remove_session() {
    local topic="$1" dir="$WORKTREES_DIR/$1"
    validate_topic "$topic"
    lock_session "$topic"
    [ -d "$RECOVERY_DIR/$topic" ] || fail "No recovery journal; inspect legacy session manually. No resources removed."
    verify_session
    [ -d "$dir" ] || fail "No worktree at $dir."
    if [ -n "$(git -C "$dir" status --porcelain)" ]; then
        fail "$dir has uncommitted changes; commit or discard them first."
    fi
    local branch
    branch="$(git -C "$dir" branch --show-current)"

    if [ -f "$RECOVERY_DIR/$topic/setup-required" ] && [ ! -x "$MAIN_ROOT/.agent-toolkit/session-teardown.sh" ]; then
        fail "Teardown adapter missing; worktree and resource evidence kept. Restore adapter before removal."
    fi
    if [ -x "$MAIN_ROOT/.agent-toolkit/session-teardown.sh" ]; then
        step "Running .agent-toolkit/session-teardown.sh"
        phase teardown
        MAIN_ROOT="$MAIN_ROOT" "$MAIN_ROOT/.agent-toolkit/session-teardown.sh" "$dir" "$topic" || fail "Teardown failed. Worktree and journal kept: $RECOVERY_DIR/$topic. Retry: $SELF --remove $topic"
    fi

    phase removing
    step "Removing worktree $dir"
    git -C "$MAIN_ROOT" worktree remove "$dir"
    phase removed

    echo "✅ Removed. Branch $branch is kept; delete it with: git branch -d $branch (only when its PR is merged)."
}

create_session() {
    local topic="$1" open_window="$2"
    validate_topic "$topic"
    lock_session "$topic"
    local dir="$WORKTREES_DIR/$topic"
    local branch="$SESSION_PREFIX/$(date +%Y-%m-%d)-$topic"

    if [ "${3:-}" = resume ]; then
        [ -d "$RECOVERY_DIR/$topic" ] || fail "No recovery journal for $topic."
        branch="$(cat "$RECOVERY_DIR/$topic/branch")"
        verify_session
    else
        [ ! -e "$RECOVERY_DIR/$topic" ] || fail "Recovery journal exists. Use $SELF --resume $topic or inspect $RECOVERY_DIR/$topic."
        [ ! -e "$dir" ] || fail "$dir already exists."
        if git -C "$MAIN_ROOT" show-ref --verify --quiet "refs/heads/$branch"; then
            fail "Branch $branch already exists."
        fi
        mkdir "$RECOVERY_DIR/$topic"
        printf '%s\n' "$branch" > "$RECOVERY_DIR/$topic/branch"
        printf '%s\n' "$dir" > "$RECOVERY_DIR/$topic/path"
        phase creating
        step "Creating worktree $dir on $branch (from origin/$BASE_BRANCH)"
        git -C "$MAIN_ROOT" fetch -q origin || fail "Fetch failed; journal kept at $RECOVERY_DIR/$topic. No worktree created. Inspect journal and retry after resolving origin access."
        mkdir -p "$WORKTREES_DIR"
        git -C "$MAIN_ROOT" worktree add -q -b "$branch" "$dir" "origin/$BASE_BRANCH" || fail "Creation failed; inspect $RECOVERY_DIR/$topic and git worktree list. No automatic deletion."
    fi
    # Don't track the base branch, so a bare `git push` can never push to it.
    git -C "$dir" branch --unset-upstream 2>/dev/null || true

    # Keep the worktree folder out of commits even if .gitignore lacks it (info/exclude is shared by all worktrees).
    local exclude_file
    exclude_file="$(git rev-parse --path-format=absolute --git-common-dir)/info/exclude"
    grep -qxF "/$(basename "$WORKTREES_DIR")/" "$exclude_file" 2>/dev/null || echo "/$(basename "$WORKTREES_DIR")/" >> "$exclude_file"


    if [ -x "$MAIN_ROOT/.agent-toolkit/session-setup.sh" ]; then
        step "Running .agent-toolkit/session-setup.sh (dependencies, env, test database)"
        touch "$RECOVERY_DIR/$topic/setup-required"
        phase setup
        MAIN_ROOT="$MAIN_ROOT" "$MAIN_ROOT/.agent-toolkit/session-setup.sh" "$dir" "$topic" || fail "Setup failed. Worktree and journal kept. Resume: $SELF --resume $topic; cleanup: $SELF --remove $topic"
    fi

    if [ "$open_window" = "yes" ] && command -v code >/dev/null; then
        step "Opening a new VS Code window"
        code -n "$dir" || echo "  (could not open a window; use a terminal in this one)"
    fi

    phase ready
    cat <<MSG

✅ Session ready
   Folder:   $dir
   Branch:   $branch  (no PR yet; /finish opens one against $BASE_BRANCH)

Start Claude there, in a new terminal (Terminal → New Terminal, or split):

   cd $dir && claude

Then run /start, or describe the task. /start reuses this branch instead of creating one.
Remove the session when its PR is merged: $SELF --remove $topic
MSG
}

case "${1:-}" in
    --resume) create_session "${2:-}" no resume ;;
    --remove) remove_session "${2:-}" ;;
    --list) list_sessions ;;
    ""|-h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) create_session "$1" "$([ "${2:-}" = "--window" ] && echo yes || echo no)" ;;
esac
