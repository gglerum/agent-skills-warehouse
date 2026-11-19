# Component origin

The owner authorized copying useful material from the selected projects. This records permission to copy and adapt; applicable third-party licences and notices remain in force. No blanket publication, service-access or source-project permission is imported.

## Sources

- source-project-k, revision `d4202160a3132986ea40627dde1afc3b53221df4`, path `utils/sonar-local.sh`, SHA-256 `033d57e584998c9ce6f9bd4ff067ffe09593f60728558417074b4b0174a80da4`.

## Adaptations

- Replace project key, name, sources, tests, exclusions, port and image tags with environment variables; derive container and network names from the project key.
- Generate the admin password with a private umask, keep the loopback-only binding and document that images are downloaded and containers started.

Keep this origin record and included licence files with the copied component. Exact source-file hashes distinguish working-copy material from a revision-only claim.
