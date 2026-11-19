# Fixture evidence

Validate expected-versus-observed fixture records and preserve each evidence run separately.

Python 3.10+ standard library; an independent test runner supplies observations.

```sh
python3 evidence.py records.json --out /chosen/results --run-id run-001
```

Each record contains id, property, oracle, preconditions, expected object, actual object and outcome. Outcomes are PASS, FAIL, BLOCKED_BY_SETUP, INCONCLUSIVE, BROKEN_TEST. Decisive PASS/FAIL requires `control_passed: true` and nonempty evidence. IDs are path-safe; duplicate IDs, no observations and an existing run directory fail before replacement. JSON assertions do not prove the control ran: the producer, oracle and evidence require independent review. No hostile publication corpus or draft product schema is included.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.
