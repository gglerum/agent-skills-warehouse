#!/usr/bin/env bash
# Add a numbered step to a process log (before the "## Next steps" heading) from a text file, and print the number.
# The file holds the body of the step: bullets, then a lesson line. Use the editor for changes to existing steps.
#
#   log_step.sh "Title of the step" <body-file>
# LOG_FILE (default docs/process-log.md) names the log; it must contain a "## Next steps" heading.
set -euo pipefail

log="${LOG_FILE:-docs/process-log.md}"
[[ $# -eq 2 && -f "$2" && -f "$log" ]] || { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
grep -q '^## Next steps$' "$log" || { echo "no '## Next steps' heading in $log" >&2; exit 1; }

last=$(grep -oE '^## Step [0-9]+' "$log" | tail -1 | grep -oE '[0-9]+' || true)
next=$(( ${last:-0} + 1 ))
tmp=$(mktemp)
awk -v n="$next" -v title="$1" -v body="$2" '
    /^## Next steps$/ && !done {
        printf "## Step %d: %s\n\n", n, title
        while ((getline line < body) > 0) print line
        print ""
        done = 1
    }
    { print }' "$log" > "$tmp"
cat "$tmp" > "$log"
rm -f "$tmp"
echo "added Step $next to $log"
