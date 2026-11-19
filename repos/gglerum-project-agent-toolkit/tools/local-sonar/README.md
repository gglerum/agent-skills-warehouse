# Local SonarQube scan

Scan a project with a disposable local SonarQube server and print the open issues and security hotspots, without a hosted service.

Bash, Docker, curl and Python 3. Copy the entire folder. Running it downloads images, starts containers and uploads the project's source to a server on this machine, so run it only when the consuming project authorizes that.

```sh
SONAR_SOURCES=src,lib SONAR_TESTS=tests SONAR_EXCLUSIONS='**/*.min.js' bash sonar_local.sh
bash sonar_local.sh stop      # remove server, network and the generated password
```

The server binds to `127.0.0.1` only and is connected to nothing else. On the first start the well-known default admin password is replaced by a random one stored in `SONAR_REPORTS` (default `reports/`; keep that directory out of version control). The scan runs in a scanner container with the working directory mounted, waits for the server's background processing, and writes `sonarqube-issues.json` and `sonarqube-hotspots.json` next to the password file. Project key, sources, tests, exclusions, port and image tags are environment variables (see the script header).

This is a local approximation for fast feedback (the same analyzer family as IDE integrations); it is not a quality-gate decision and not a substitute for the project's CI. The image tags are defaults to pin deliberately; check them before relying on the result.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
