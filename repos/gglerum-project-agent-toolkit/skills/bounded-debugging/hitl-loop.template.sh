#!/usr/bin/env bash
# Human-in-the-loop reproduction loop (adapted from mattpocock/skills).
# Copy outside the repo, edit the steps below, run it. The agent runs the script; the owner follows
# the prompts in their terminal.
#   step "<instruction>"        show instruction, wait for Enter
#   capture VAR "<question>"    show question, read the answer into VAR
# Captured values print as KEY=VALUE at the end for the agent to parse. `capture` echoes the value
# back where the agent reads it, so capture observations only; leave sign-in to the owner as a `step`.
set -euo pipefail

step() {
  printf '\n>>> %s\n' "$1"
  read -r -p "    [Enter when done] " _
}

capture() {
  local var="$1" question="$2" answer
  printf '\n>>> %s\n' "$question"
  read -r -p "    > " answer
  printf -v "$var" '%s' "$answer"
}

# --- edit below ---------------------------------------------------------
step "Open the reproduction target (for example the lab HTML file) in Edge."
capture ERRORED "Perform the action. Did the problem appear? (y/n)"
capture ERROR_MSG "Paste the message you saw (or 'none'):"
# --- edit above ---------------------------------------------------------

printf '\n--- Captured ---\n'
printf 'ERRORED=%s\n' "$ERRORED"
printf 'ERROR_MSG=%s\n' "$ERROR_MSG"
