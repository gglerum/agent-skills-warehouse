# Code navigation

Read one Markdown section or Python/C# symbol; generate configured code maps.

Python 3.10+ standard library. Copy both Python files.

```sh
python3 sect.py README.md --list
python3 sect.py README.md "Installation"
python3 sect.py src/example.py function_name
python3 code_map.py src tests --root . --output CODE_MAP.md
python3 code_map.py src tests --root . --output CODE_MAP.md --check
```

Section reads are read-only and ignore fenced Markdown headings. Exit 1 means no match; 2 means ambiguous. Symbol scanning is regex-based and supports ordinary Python/C# layouts, not every language construct. Code-map generation writes only the requested output; `--check` compares without writing. Existing descriptions keyed by file/symbol are retained. The source globs and output path are explicit; no source-project paths are required.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
