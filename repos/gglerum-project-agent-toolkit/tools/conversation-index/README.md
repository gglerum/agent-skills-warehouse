# Conversation index

Split selected Markdown conversations byte-exactly and validate source-backed segment/decision plans.

Python 3.10+ standard library. Supported export headings are `## You (YYYY-MM-DD HH:MM UTC)` and `## ChatGPT (...)`.

```sh
python3 index.py build selected-export.md chunks --max-lines=2400
python3 index.py check selected-export.md chunks
python3 index.py segments-check selected-export.md segments.json
```

Explicitly scope access to the input conversation. Build writes verbatim chunks and index metadata only into a new/empty directory; it will not overwrite existing annotations. Check verifies original hash, chunk coverage/order and exact reassembly. Segment plans are lists of start/end line records, optionally decisions with line/quote. Coverage must be exact and quotations must occur near the cited line in their segment. This verifies text evidence, not whether an answer was genuinely accepted. No actual conversation, model invocation or automatic preference extraction is included.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
