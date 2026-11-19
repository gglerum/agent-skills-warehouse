"""Merge every requested SARIF report; missing or invalid input fails before output."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_io import entry, read_json, write_json


def merge_sarif(output_file, *input_files):
    runs = []
    if not input_files:
        raise ValueError("no inputs")
    for name in input_files:
        report = read_json(name, dict)
        if report.get("version") != "2.1.0" or not isinstance(report.get("runs"), list):
            raise ValueError("invalid SARIF envelope")
        for run in report["runs"]:
            if not isinstance(run, dict) or not isinstance(run.get("tool"), dict) or not isinstance(run.get("results", []), list):
                raise ValueError("invalid SARIF run")
        runs.extend(report["runs"])
    write_json(output_file, {"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "runs": runs})


def cli():
    if len(sys.argv) < 3:
        print("usage: merge_sarif.py OUTPUT INPUT [INPUT ...]", file=sys.stderr)
        return 2
    merge_sarif(*sys.argv[1:])


if __name__ == "__main__":
    sys.exit(entry(cli))
