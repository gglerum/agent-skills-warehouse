#!/usr/bin/env bash
#
# Warm the parallel test databases before Infection, so its mutant processes do not each run
# `migrate:fresh --seed` and get killed by the mutant timeout (20 s).
#
# Usage:  <this script> <threads> <phpunit-test-path-or-filter>
#
# <threads>: the same number you give Infection (--threads); tokens 1..N map to the databases <name>_test_<token>.
# <test>: one small RefreshDatabase test of the repo. Its run migrates the database once and
#         TestDatabaseFingerprint records the fingerprint at shutdown (see TestDatabaseFingerprint.php).
# Advisory: a failing warm-up does not fail the stage unless WARM_STRICT=1.
# PHPUNIT_BIN overrides vendor/bin/phpunit.

set -uo pipefail

if [[ $# -ne 2 || ! $1 =~ ^[1-9][0-9]*$ ]]; then
    echo "Usage: $0 <threads> <phpunit-test-path-or-filter>" >&2
    exit 2
fi

threads=$1
test=$2
phpunit=${PHPUNIT_BIN:-vendor/bin/phpunit}
failed=0

for ((token = 1; token <= threads; token++)); do
    start=$SECONDS
    if TEST_TOKEN=$token LARAVEL_PARALLEL_TESTING=1 "$phpunit" "$test"; then
        echo "warm-up token $token: $((SECONDS - start)) s"
    else
        echo "warm-up token $token failed after $((SECONDS - start)) s" >&2
        failed=1
    fi
done

if [[ $failed -ne 0 && ${WARM_STRICT:-0} == 1 ]]; then
    exit 1
fi
exit 0
