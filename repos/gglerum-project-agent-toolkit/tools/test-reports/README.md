# Test reports

Summarize test failures and check per-file statement coverage.

Python 3.10+ standard library; Git only for locating the default JUnit report.

```sh
python3 failed_tests.py reports/junit.xml --no-rerun
python3 coverage_for_files.py reports/clover.xml src/Example.php --min=75
python3 coverage_for_files.py reports/clover.xml src/example.py --required-suffix=.py --min=75
```

Both commands are read-only. Failure summary exits 1 for failed tests, 2 for unavailable input. Its optional rerun hint uses PHPUnit; `--no-rerun` supports other JUnit producers without a misleading command. Coverage exits 1 below the configured threshold or for absent required-suffix source; 2 for invalid input. Zero-statement records are distinct from absent files. Default required suffix is `.php`; configure others explicitly. Container report paths can be mapped with `--report-prefix=/workspace --source-root=.`. This measures complete-file statements, not changed-line coverage. The default minimum is a CLI convenience, not consumer policy.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
