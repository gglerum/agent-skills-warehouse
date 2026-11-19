#!/usr/bin/env bash
# Scan the project with a throwaway local SonarQube server and print the open issues and security hotspots.
# Run on the host (it needs Docker), not inside a dev container.
#
#   sonar_local.sh          start the server if needed, scan, print the issues
#   sonar_local.sh stop     remove the server, its network and the stored password again
#
# The server listens only on 127.0.0.1 and is connected to nothing else. A random admin password is generated on the first
# start and kept in the reports directory (keep it out of version control). Environment:
#   SONAR_PROJECT     project key (default: name of the current directory, lowercased)
#   SONAR_SOURCES     comma-separated source directories (default ".")
#   SONAR_TESTS       test directories (default none)
#   SONAR_EXCLUSIONS  comma-separated glob patterns to exclude
#   SONAR_PORT        local port (default 9000)
#   SONAR_REPORTS     output directory (default reports)
#   SONAR_IMAGE       server image (default sonarqube:community), SCANNER_IMAGE scanner image (default sonarsource/sonar-scanner-cli:11.4)
# The images are pulled by docker on first use; this downloads software and starts containers, so run it only when that is authorized.
set -euo pipefail

command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
PROJECT="${SONAR_PROJECT:-$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_.-\n' '-')}"
SOURCES="${SONAR_SOURCES:-.}"
TESTS="${SONAR_TESTS:-}"
EXCLUSIONS="${SONAR_EXCLUSIONS:-}"
PORT="${SONAR_PORT:-9000}"
REPORTS="${SONAR_REPORTS:-reports}"
IMAGE="${SONAR_IMAGE:-sonarqube:community}"
SCANNER="${SCANNER_IMAGE:-sonarsource/sonar-scanner-cli:11.4}"
NAME="$PROJECT-sonarqube"
NETWORK="$PROJECT-sonar"
URL="http://127.0.0.1:$PORT"
PASSWORD_FILE="$REPORTS/.sonar-local-password"

if [ "${1:-}" = "stop" ]; then
    docker rm -f "$NAME" > /dev/null && docker network rm "$NETWORK" > /dev/null
    rm -f "$PASSWORD_FILE"
    echo "SonarQube removed."
    exit 0
fi

mkdir -p "$REPORTS"
if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    docker network create "$NETWORK" > /dev/null 2>&1 || true
    docker run -d --name "$NAME" --network "$NETWORK" -p "127.0.0.1:$PORT:9000" \
        -e SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true "$IMAGE" > /dev/null
    echo -n "Starting SonarQube"
    until curl -s "$URL/api/system/status" | grep -q '"status":"UP"'; do echo -n "."; sleep 5; done
    echo
    # First start: replace the well-known default password with a random one, create the project
    umask 077
    python3 -c 'import secrets; print(secrets.token_urlsafe(24))' > "$PASSWORD_FILE"
    DEFAULT_LOGIN=admin
    curl -s --user "$DEFAULT_LOGIN:$DEFAULT_LOGIN" -X POST "$URL/api/users/change_password" \
        --data-urlencode "login=admin" --data-urlencode "previousPassword=$DEFAULT_LOGIN" \
        --data-urlencode "password=$(cat "$PASSWORD_FILE")" > /dev/null
    curl -s --user "admin:$(cat "$PASSWORD_FILE")" -X POST "$URL/api/projects/create" --data-urlencode "project=$PROJECT" --data-urlencode "name=$PROJECT" > /dev/null
fi
LOGIN="admin:$(cat "$PASSWORD_FILE")"

TOKEN=$(curl -s --user "$LOGIN" -X POST "$URL/api/user_tokens/generate" \
    -d "name=scan-$(date +%s)&type=PROJECT_ANALYSIS_TOKEN&projectKey=$PROJECT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')

CACHE=$(mktemp -d)
args=("-Dsonar.projectKey=$PROJECT" "-Dsonar.userHome=/tmp/sonar-cache" "-Dsonar.scm.disabled=true" "-Dsonar.sources=$SOURCES")
[[ -z "$TESTS" ]] || args+=("-Dsonar.tests=$TESTS")
[[ -z "$EXCLUSIONS" ]] || args+=("-Dsonar.exclusions=$EXCLUSIONS")
docker run --rm --network "$NETWORK" -u "$(id -u):$(id -g)" \
    -e SONAR_HOST_URL="http://$NAME:9000" -e SONAR_TOKEN="$TOKEN" \
    -v "$PWD":/usr/src -v "$CACHE":/tmp/sonar-cache \
    "$SCANNER" "${args[@]}" | grep -E "EXECUTION|ERROR" || true
rm -rf "$CACHE"

# The server processes the report in the background
until curl -s --user "$LOGIN" "$URL/api/ce/component?component=$PROJECT" | grep -q '"queue":\[\]'; do sleep 3; done

curl -s --user "$LOGIN" "$URL/api/issues/search?componentKeys=$PROJECT&resolved=false&ps=500" > "$REPORTS/sonarqube-issues.json"
curl -s --user "$LOGIN" "$URL/api/hotspots/search?projectKey=$PROJECT&ps=500" > "$REPORTS/sonarqube-hotspots.json"
python3 - "$REPORTS" "$URL" "$PROJECT" "$PASSWORD_FILE" <<'PY'
import json, sys
reports, url, project, password_file = sys.argv[1:5]
issues = json.load(open(f'{reports}/sonarqube-issues.json'))['issues']
hotspots = json.load(open(f'{reports}/sonarqube-hotspots.json'))['hotspots']
for i in sorted(issues, key=lambda i: i['component']):
    print(f"{i['severity']:8} {i['component'].split(':', 1)[1]}:{i.get('line', '')}  {i['message']}")
for h in hotspots:
    print(f"HOTSPOT  {h['component'].split(':', 1)[1]}:{h.get('line', '')}  {h['message']}")
print(f"\n{len(issues)} issues, {len(hotspots)} security hotspots. Details: {reports}/sonarqube-*.json,")
print(f"or browse {url}/dashboard?id={project} (login admin, password in {password_file}).")
PY
