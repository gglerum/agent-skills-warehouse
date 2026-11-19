# Component origin

The owner authorized copying useful material from the selected projects. This records permission to copy and adapt; applicable third-party licences and notices remain in force. No blanket publication, service-access or source-project permission is imported.

## Sources

- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `tests/test_ci_status.py`, SHA-256 `88672b6b7beb26e33e7614fbe0435a9ab02de9889ed2c31c46caeeb5ad1c5cea`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `tests/test_report_helpers.py`, SHA-256 `26018d14d113202cbfda0d8ded72829d7e917de3a18b7487118b0b2b00742ccf`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `tests/test_new_session.py`, SHA-256 `f4d2c5bd78cc73cc535c8ccd8aa8be560820da33ad8881793e7b0404e4af027a`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `tests/test_test_db_fingerprint.py`, SHA-256 `b4fb0f35c8e0b3d2b53dfd1862a93c141a67af5c5e1c93fe263af0c5fc2aa0c7`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `tests/test_destructive_guard.py`, SHA-256 `8d9112257d63bfefe0f9188588fd74b56b5280b73c6ba6d4553517f5594908d7`.
- source-project-f, revision `f1286de441446ae9d87b3151d593181ebfd6cc06`, path `utils/workflow/tests/test_session_database.py`, SHA-256 `f2a9226e941caeda1278b3769d172081b24ee948608a623fa7181c25bfa7e900`.
- source-project-f, revision `f1286de441446ae9d87b3151d593181ebfd6cc06`, path `.claude/tests/test_pr_review.py`, SHA-256 `313c08654550aa0c7b37ad0d6edb344f769367298b126ec91e1cb1216ca71a30`.
- source-project-f, revision `f1286de441446ae9d87b3151d593181ebfd6cc06`, path `.claude/tests/test_asana.py`, SHA-256 `777fcc8cfbda799aea6ab50da4a16f2a6ad4ca7224d0daa459690a01fc5397a5`.
- source-project-f, revision `f1286de441446ae9d87b3151d593181ebfd6cc06`, path `.claude/tests/test_guard.py`, SHA-256 `6433cfa4b4d5c3de1a2c088bd4ab05b64de3fc1b240bd33b90d32b27945b7c1b`.
- source-project-g, revision `c56e0ff537c3384e617b9be91683c437299f610f`, path `tests/scripts/test_patch.py`, SHA-256 `3bcc23a6dd6f2b5d6453f63e7de7d326a7cb1ee6c3703bd5e2b82bf418f0b42e`.

## Adaptations

- Retain observable regression scenarios with relocated paths, synthetic identities and explicit fixture configuration.
- Retain pure approval/evaluation/API cases; replace project-specific applicability/transport tests with configurable-adapter cases.
- Retain pagination/deadline/atomic-output tests; configure fixture ownership and mock the no-redirect transport.
- Retain privacy guard regression scenarios with relocated fixture path.
- Retain exact-patch failure and mode invariants in unittest cases; no pytest dependency.
- New regression tests (record tools, design compare, floor and session guards, roadmap board, closeout, container and pull request conventions) were written for the eleventh source's tools; no source test files were copied.

Keep this origin record and included licence files with the copied component. Exact source-file hashes distinguish working-copy material from a revision-only claim.
