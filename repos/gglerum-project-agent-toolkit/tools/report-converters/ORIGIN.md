# Component origin

The owner authorized copying useful material from the selected projects. This records permission to copy and adapt; applicable third-party licences and notices remain in force. No blanket publication, service-access or source-project permission is imported.

## Sources

- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `scripts/composer_audit_to_sarif.py`, SHA-256 `986e26e51e21f046a02996562a947be22a991bda600e97947a5ef62d3f16f8d0`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `scripts/security_to_sarif.py`, SHA-256 `022b7464ef4577a1a42f3dbe4ffafd43b4e788cf443cacde508e231307b555f3`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `scripts/merge_sarif.py`, SHA-256 `4a598ebf434bd68f40492b4d27c04f497f4d35c152133b1a750e01e698ebb8b5`.
- source-project-d, revision `09b0dd7c91311e7a1f97725f13c6116a3853913f`, path `scripts/convert_reports.py`, SHA-256 `6af3ccf814bfdf165e27a5e8c411bb107c895157b409022fe5b286a83d725feb`.
- source-project-f, revision `f1286de441446ae9d87b3151d593181ebfd6cc06`, path `utils/eslint_json_to_sarif.py`, SHA-256 `e757d6812c9bd896bb0753d16958bdc2c08fbed6d91175141816070cce0e4cdc`.

## Adaptations

- Reject missing/malformed input and schema errors before writing output; remove empty Composer stub.
- Require a valid ESLint report; never convert missing input to clean results.

Keep this origin record and included licence files with the copied component. Exact source-file hashes distinguish working-copy material from a revision-only claim.
