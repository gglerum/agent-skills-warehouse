# Reference library

Search an authorized local Markdown reference library; separately download selected public design references.

Python 3.10+ standard library. Query needs a local reference folder; download commands need network permission and current source access/usage terms.

```sh
python3 query.py --root /path/to/selected-library "focus recovery" --limit=5 --chars=400
python3 hig_download.py --out /chosen/private/hig
python3 nng_download.py --list /chosen/article-list.txt --out /chosen/private/nng --dry-run
```

Query is read-only, returns bounded excerpts and follows no symlink outside the selected root. Downloaders are separate opt-in network/writing commands; NN/g `--dry-run` still reads robots.txt. NN/g list lines are public article URL optionally followed by `| keywords`; no article list or downloaded text/images is shipped. Respect rights and robots/crawl delay, stop on access/rate-limit refusal and report partial fetches. Do not publish downloaded reference content without applicable rights.

No downloader was run during validation. The source's combination of Apple HIG and NN/g is a project choice, not a requirement that every consumer follow both. Choose references suited to the actual platform and use real user evidence to decide interactions.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
