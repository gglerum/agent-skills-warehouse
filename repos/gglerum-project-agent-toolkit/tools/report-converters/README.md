# Report converters

Convert native scanner reports to SARIF or Sonar generic issues without hiding missing evidence.

Python 3.10+ standard library. Copy the entire folder, including report_io.py.

```sh
python3 composer_audit_to_sarif.py composer.json composer.sarif
python3 security_to_sarif.py gitleaks gitleaks.json gitleaks.sarif
python3 security_to_sarif.py trivy trivy.json trivy.sarif
python3 eslint_json_to_sarif.py eslint.json eslint.sarif
python3 convert_reports.py rector rector.json rector-sonar.json
python3 merge_sarif.py merged.sarif composer.sarif gitleaks.sarif
```

`convert_reports.py` supports rector, deptrac, pint (Checkstyle XML), infection, cspell, zap and composer-audit. Inputs must match the declared producer envelope. Valid empty reports remain empty; missing, malformed or incomplete input exits nonzero before replacing existing output. File replacement is atomic. Conversion success means a report was converted, not that a scan passed or ran. Retain the producer's exit status and revision in CI. Merging requires every named input; it never silently skips one. Locations/schema compatibility still require validation against the actual tool versions and consumer. No scanner is installed or executed.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
