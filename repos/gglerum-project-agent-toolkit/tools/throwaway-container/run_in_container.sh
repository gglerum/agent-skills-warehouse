#!/usr/bin/env bash
# Run a command in a throwaway container as the host user, with the host's git identity and the repository mounted at /workspace.
# Use it for anything that commits or runs checks when the host toolchain differs from the one the project's hooks need.
#
#   CONTAINER_IMAGE=my-dev-image run_in_container.sh <command> [args...]
#   CONTAINER_IMAGE=my-dev-image run_in_container.sh git commit -m "message"
#
# Environment:
#   CONTAINER_IMAGE        required: the image to run (built by the project; this script never builds or pulls)
#   CONTAINER_RUNTIME      container CLI, default docker
#   CONTAINER_SHARED_DIRS  space-separated directories (default "vendor node_modules") that a git worktree mounts from the main checkout
#   CONTAINER_EXTRA_ARGS   extra arguments for `run`, split on spaces (ports, networks, environment)
#   CONTAINER_DRY_RUN=1    print the command instead of running it
#
# In a git worktree the shared git directory and the main checkout's shared directories are mounted too, so git, package
# managers and linters work without copies or symlinks. Nothing from the host environment is passed except git identity.
set -euo pipefail

[[ $# -gt 0 ]] || { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
: "${CONTAINER_IMAGE:?set CONTAINER_IMAGE to the image this project builds}"
runtime="${CONTAINER_RUNTIME:-docker}"
shared="${CONTAINER_SHARED_DIRS:-vendor node_modules}"

name=$(git config user.name || true)
email=$(git config user.email || true)

extra=()
if [[ -f .git ]]; then
    common=$(git rev-parse --path-format=absolute --git-common-dir)
    main=$(dirname "$common")
    extra+=(-v "$common":"$common")
    for d in $shared; do
        [[ -d "$main/$d" ]] && extra+=(-v "$main/$d":/workspace/"$d")
    done
fi
# shellcheck disable=SC2206
[[ -n "${CONTAINER_EXTRA_ARGS:-}" ]] && extra+=(${CONTAINER_EXTRA_ARGS})

cmd=("$runtime" run --rm -u "$(id -u):$(id -g)" -v "$PWD":/workspace -w /workspace "${extra[@]}"
     -e GIT_AUTHOR_NAME="$name" -e GIT_AUTHOR_EMAIL="$email" -e GIT_COMMITTER_NAME="$name" -e GIT_COMMITTER_EMAIL="$email"
     "$CONTAINER_IMAGE" bash -c 'git config --global --add safe.directory /workspace; exec "$@"' _ "$@")

if [[ "${CONTAINER_DRY_RUN:-0}" == 1 ]]; then
    printf '%q ' "${cmd[@]}"; echo
    exit 0
fi
exec "${cmd[@]}"
