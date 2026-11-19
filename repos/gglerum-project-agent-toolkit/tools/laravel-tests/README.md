# Laravel tests

Laravel related-test selection, schema fingerprints, warm-up and owned worktree database adapters.

Linux/Unix shell, PHP/Laravel/PHPUnit; fcntl for database receipts; MySQL/MariaDB for the database adapter. No general-purpose database portability is claimed.

```sh
printf "%s\n" app/Services/Example.php | bash related_tests.sh
bash warm-test-databases.sh 4 tests/Feature/SmallDatabaseTest.php
python3 session_database.py setup /path/to/worktree feature-topic
python3 session_database.py teardown /path/to/worktree feature-topic
```

Related tests use Laravel naming/namespace references and exclude browser tests. It is a selection heuristic; keep a full-suite path. Integrate `TestDatabaseFingerprint.php` deliberately with the consumer's test bootstrap; see its public compute/matches/record methods and tests. A fingerprint is a schema/input cache key, not proof the suite passed. Warm-up is advisory unless `WARM_STRICT=1`; its worker count/tokens must match the test runner.

Database setup/teardown mutates only explicitly owned hashed worktree databases and exact numeric worker suffixes; ownership uncertainty blocks cleanup. Receipts live in the common Git directory. Do not operate on the main checkout or adopt an existing resource. `setup.sh` is an optional Laravel adapter that copies an absent `.env`, runs Composer/npm/build and requires a test bootstrap reading `.testing-database`; it never regenerates keys. `teardown.sh` calls the journalled adapter. These scripts are not run by import and are not generic setup hooks. Wire them through reviewed project-local `.agent-toolkit` adapters only under the consumer's permissions.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
