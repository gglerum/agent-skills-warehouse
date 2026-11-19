# Design compare

Compare a built screen with a page of a design export (PDF): render, measure in a real browser, and report differences in pixels with a side-by-side and a difference image.

Python 3.10+ standard library, a Chrome/Chromium binary (`CHROME_BIN` or on `PATH`) and poppler (`pdftoppm`, `pdftotext`, `pdftocairo`, `pdffonts`) on `PATH` or behind a command prefix (`poppler_prefix`, for example a container run). Copy the entire folder.

```sh
python3 compare.py --config compare.config.example.json pages                  # numbered contact sheet of the PDF
python3 compare.py --config compare.config.example.json spec 5                 # text and box geometry of PDF page 5
python3 compare.py --config compare.config.example.json compare 5 /prototypes/signup.html
python3 compare.py --config compare.config.example.json compare 5 auth:/signup --name signup
python3 compare.py --config compare.config.example.json all --only app --check
python3 compare.py --config compare.config.example.json all --save-baseline
```

## How it works

- A PDF page is rendered at one pixel per point and its words (as lines with boxes), filled rectangles and fonts are extracted.
- The target page is framed in an iframe of exactly the configured viewport (default 393 x 852; headless Chrome will not give a window that size), screenshotted, and measured: text positions, element boxes, background colours.
- `compare` matches design text lines to page text and design boxes to page elements, and prints OK, DIFF or MISSING rows with the position and size deltas, colour and wording differences. Tolerances default to 6 px for position and 8 px for size: "close is enough, not pixel exact". Smaller differences are not reported.
- Output under `out_dir`: `<name>/compare.png` (design | page | difference, black means the same), `report.md`, `page.png`, `measure.json`, and `summary.md` for `all`. Read the image before the table.
- `all` reads the screens file (see `screens.example.json`): each screen has a design page or `null` (screenshot only). A baseline file stores accepted differ/missing counts per screen; `--check` fails when a screen is worse than its baseline or the browser ended on a different route (a redirect to a login page is a setup problem, not a comparison).

## Targets and the application

A target is a path under `serve_root` (static wireframes or prototypes), a URL, `anon:/route` or `auth:/route`. The two prefixes go through a local proxy to `app_url`; `auth:` sends the cookies from the session file (`{"cookie": "value"}`, written by the project's own login step; this tool never logs in or starts the application). The proxy drops CSP, frame and cookie headers so the page can be shown in the iframe. `path_rewrites` maps request paths for old prototypes whose relative asset links only resolve elsewhere.

## Limits and safety

The server binds to `127.0.0.1` and serves the whole `serve_root`: do not point it at a directory with secrets, and stop it with `serve stop`. Matching is by normalised text and position; icons without a box, text matched to the wrong node and image colours are tool artefacts a reviewer must discount. Nothing is verified on a real device. The Chrome and poppler commands run locally; without them every command that opens a page exits 2 ("not found") and must be reported as blocked by setup, not as a pass. Pure matching logic is covered by tests; the browser and PDF paths need a real environment.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
