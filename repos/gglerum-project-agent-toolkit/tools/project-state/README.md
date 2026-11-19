# Project state

Track local project phase gates with explicit evidence and human-review records.

Python 3.10+ standard library. Start from the example state and replace it with actual project gates.

```sh
python3 state.py --root . status
python3 state.py --root . check
python3 state.py --root . record checks --evidence reports/checks.txt
python3 state.py --root . record checks --evidence reports/checks.txt --write
```

Status/check are read-only. Record previews by default; `--write` explicitly changes the selected state file. Gates use id/class/status/depends_on/evidence. Classes are AUTO, REVIEW, HUMAN. Statuses are queued, active, recommended_pass, passed, blocked, parked. Passed prerequisites must themselves be passed; cycles, missing/escaping evidence and duplicate IDs fail.

REVIEW/HUMAN passes require `--approved-by` and `--approval-record`, tied to that gate. The record must reflect an actual approval authorized in the consuming task; a name string is not authentication. Local state is independent of remote boards; a separate adapter must preserve project authorization. No source product gates or board IDs are included.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
