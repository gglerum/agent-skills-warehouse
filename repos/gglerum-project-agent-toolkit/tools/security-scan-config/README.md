# Security scan configuration

Starting configuration for three scanners: gitleaks (secrets in history and files), Trivy (dependency vulnerabilities, secrets, misconfiguration) and OWASP ZAP (dynamic scan of a running application).

Files only; copy what fits. Nothing here installs or runs a scanner. Copy the entire folder.

| File | Purpose |
| --- | --- |
| `gitleaks.example.toml` | Default ruleset plus narrow allowlists for lock-file hashes, vendored directories, example environment files and made-up test passwords. |
| `trivy.example.yaml` | Scanners, skipped directories and a SARIF output path. `skip-dirs` must sit under `scan:`; at the top level Trivy ignores it silently. |
| `trivyignore.example` | Where accepted findings go: one rule id per line with a comment naming the reason and the record that holds the decision. |
| `zap.example.yaml` | An automation context that reads the target from `ZAP_TARGET`. An unauthenticated scan sees only public pages. |

Lessons built into the examples: allowlists are narrow and carry a description; accepted scanner findings point to a recorded decision; reports go to an ignored `reports/` directory; a scan that was not run is reported as not run, never as clean. Check the options against the installed tool versions, and run scanners only against systems the project owns and has authorized.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
