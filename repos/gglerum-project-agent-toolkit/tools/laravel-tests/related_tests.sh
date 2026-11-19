#!/bin/sh
# Reads staged app PHP files (one path per line) on stdin and prints, per file, the tests that relate to it:
#   test <path>    a related test file
#   none <path>    no related test found for this app file (the pre-commit hook then runs the full suite)
# Run from the repository root.
#
# Related = the test named <Class>Test.php, plus tests that mention the class. A bare word match is too wide for
# generic names (`Admin` matches 47 of 165 test files in a large source project), so when more than RELATED_TESTS_MAX (default 15)
# files match, only tests that import or reference the class by a qualified name count: `\Class` (not followed by a
# further `\`, so the namespace `App\Models\Admin\User` does not count for `Admin`) or `Class::class`.
# The name-matched test file alone is enough, so `RabbitMQConsumeCommand` finds `RabbitMQConsumeCommandTest.php`
# (a word match never does: `-w` does not match inside `RabbitMQConsumeCommandTest`).
# Dusk tests (tests/Browser) need a browser and a running server, so they are never picked.

MAX=${RELATED_TESTS_MAX:-15}

while IFS= read -r APP_FILE; do
    [ -n "$APP_FILE" ] || continue
    CLASS_NAME=$(basename "$APP_FILE" .php)

    BY_NAME=$(find tests -name "${CLASS_NAME}Test.php" -not -path 'tests/Browser/*' 2>/dev/null)
    MENTIONS=$(grep -rlw --include='*Test.php' --exclude-dir=Browser "$CLASS_NAME" tests 2>/dev/null)

    if [ -n "$MENTIONS" ] && [ "$(printf '%s\n' "$MENTIONS" | wc -l)" -gt "$MAX" ]; then
        # A grouped import (`use App\Models\{Admin, User};`, also over several lines) names the class without a
        # `\Class` or `Class::class`, so word matches that contain one are kept: a false positive only runs one
        # test file too many, a false negative would skip a test.
        GROUPED=$(printf '%s\n' "$MENTIONS" | while IFS= read -r TEST_FILE; do
            grep -qE '^use [^;]*\{' "$TEST_FILE" && echo "$TEST_FILE"
        done)
        QUALIFIED=$(grep -rlE --include='*Test.php' --exclude-dir=Browser "(\\\\${CLASS_NAME}([^A-Za-z0-9_\\\\]|\$)|${CLASS_NAME}::class)" tests 2>/dev/null)
        MENTIONS=$(printf '%s\n%s\n' "$QUALIFIED" "$GROUPED")
    fi

    FOUND=$(printf '%s\n%s\n' "$BY_NAME" "$MENTIONS" | grep -v '^$' | sort -u)
    if [ -z "$FOUND" ]; then
        echo "none $APP_FILE"
    else
        printf '%s\n' "$FOUND" | sed 's/^/test /'
    fi
done

exit 0
