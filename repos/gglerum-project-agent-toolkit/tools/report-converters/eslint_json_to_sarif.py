#!/usr/bin/env python3
"""Convert an ESLint JSON report (--format json) to SARIF 2.1.0.

Usage: eslint_json_to_sarif.py <eslint.json> <eslint.sarif>

Missing or malformed input exits 2 without replacing the output.
"""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_io import read_json, write_json, entry

LEVELS = {1: "warning", 2: "error"}


def convert(source: str) -> dict:
    files = read_json(source, list)

    results = []
    for entry in files:
        uri = os.path.relpath(entry["filePath"], os.getcwd())
        for message in entry.get("messages", []):
            line = max(message.get("line", 1), 1)
            column = max(message.get("column", 1), 1)
            results.append({
                "ruleId": message.get("ruleId") or "eslint-parse-error",
                "level": LEVELS.get(message.get("severity"), "warning"),
                "message": {"text": message.get("message", "")},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": uri},
                        "region": {"startLine": line, "startColumn": column},
                    },
                }],
            })

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "ESLint", "informationUri": "https://eslint.org"}},
            "results": results,
        }],
    }


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    write_json(sys.argv[2], convert(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(entry(main))
