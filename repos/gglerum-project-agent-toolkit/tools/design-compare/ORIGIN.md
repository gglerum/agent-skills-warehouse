# Component origin

The owner authorized copying useful material from the selected projects. This records permission to copy and adapt; applicable third-party licences and notices remain in force. No blanket publication, service-access or source-project permission is imported.

## Sources

- source-project-k, revision `d4202160a3132986ea40627dde1afc3b53221df4`, path `utils/design/design.py`, SHA-256 `3344e51364801f1d62c81a5afe79c67b771e316ed1e859def6a3833549711df7`.
- source-project-k, revision `d4202160a3132986ea40627dde1afc3b53221df4`, path `utils/design.sh`, SHA-256 `272aae9b5d32ec6a0c39c0d7b29615a8401f7e9df7b9296262c9c9655dfd9a04`.

## Adaptations

- Replace project paths, viewport, container image, test account, application start and login steps with a JSON configuration, a command prefix for poppler and a session cookie file written by the consumer.
- Rename the external design tool references to a neutral design export, rename targets to auth:/anon:, rename the screens-file key to design_page and make the baseline kinds free text.
- Keep PDF text/box extraction, in-iframe measurement, matching with tolerances, side-by-side and difference image, baseline check and redirect warnings; remove the application proxy rewrites tied to one framework.
- Add README, example configuration and screens file; cover the pure matching and baseline logic with tests. Browser and PDF paths need a real environment.

Keep this origin record and included licence files with the copied component. Exact source-file hashes distinguish working-copy material from a revision-only claim.
