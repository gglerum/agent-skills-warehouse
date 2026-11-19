# Component origin

The owner authorized copying useful material from the selected projects. This records permission to copy and adapt; applicable third-party licences and notices remain in force. No blanket publication, service-access or source-project permission is imported.

## Sources

- source-project-f, revision `f1286de441446ae9d87b3151d593181ebfd6cc06`, path `.claude/session-database.py`, SHA-256 `c1ebd38cf82f04e9dedaad5ce1bff47a9bd487ebba4b686dd007a56ee97281ec`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `scripts/hooks/related_tests.sh`, SHA-256 `9bd2566fcae6b1c8e2a5dfed13293680ad01c8e4fb2a43292465986a20e1aff4`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `scripts/laravel/TestDatabaseFingerprint.php`, SHA-256 `241305354602d546618ff2c702438d68a2c3dfdb6c2e4d349cf4c3a0e7acbdf5`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `scripts/laravel/warm-test-databases.sh`, SHA-256 `ca98d985eccd064fded814685fad9f68a966d14f3aaaa858aa10809e4a97d14b`.
- source-project-f, revision `f1286de441446ae9d87b3151d593181ebfd6cc06`, path `.claude/session-setup.sh`, SHA-256 `5700e6dd290c1cd83b675ea766291d060127e3b1ca58eeb2bf6a6bdb200fbaba`.
- source-project-f, revision `f1286de441446ae9d87b3151d593181ebfd6cc06`, path `.claude/session-teardown.sh`, SHA-256 `624c11b27cd91fc6434a8aae62acd3e1bcf0f19e4d594bf87bb2d81c7b9033d7`.
- source-project-i, revision `8b8553730fcc49d7caf59c8ab656f34432b80db5`, path `.claude/session-setup.sh`, SHA-256 `21caf2a39d69c12c3b7e62bc2ace9c8c2a9d996ab31ecdade23ed317aadb244a`.
- source-project-i, revision `8b8553730fcc49d7caf59c8ab656f34432b80db5`, path `.claude/session-teardown.sh`, SHA-256 `9386e7bffd88a9d7a351c339a3272b12ce43d46e27db40b02a6992e17b63807e`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `tests/test_toolchain_config.py`, SHA-256 `534e632d63d1618265a22b850c8101341f8b154434fc8390560c8cbe1c200067`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `tests/test_related_tests.py`, SHA-256 `151746c312f98b3640b1928861aa6ee44291c3bd0d4a30d8b53f5665b80a132f`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `tests/test_warm_test_databases.py`, SHA-256 `ff98e96efdeaec71acff6776d65115d6590c88ca9dc8c5ab72ec58219ca0b029`.

## Adaptations

- Retain explicit ownership receipts and exact worker matching; document Linux/PHP/Laravel/MySQL adapter prerequisites.
- Keep Laravel-specific behavior as an optional isolated component; no install or database operation during import.
- Optional Laravel adapter; no key regeneration; preserve existing env; require isolated test bootstrap and dependency success.
- Optional Laravel adapter; exact journalled resource cleanup only.
- Compare source-project-i adapter with canonical optional Laravel adapter; keep per-project hooks rather than copying package IDs/database assumptions.
- Compare teardown and retain exact resource ownership; avoid broad worker-prefix removal.
- Inspect supporting implementation/dependencies; retain general mechanism or lesson and deliberately omit product-specific execution/configuration.

Keep this origin record and included licence files with the copied component. Exact source-file hashes distinguish working-copy material from a revision-only claim.
