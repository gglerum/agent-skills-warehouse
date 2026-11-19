"""Strict report input and atomic output shared by converters. Python stdlib only."""
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET


def read_json(path, expected):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, expected):
        raise ValueError("unexpected report root type")
    return data


def write_json(path, data):
    target = Path(path)
    fd, temporary = tempfile.mkstemp(dir=target.resolve().parent, prefix=".report-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_report(path, kind):
    """Validate producer envelope before a converter may interpret absence as empty."""
    expected = list if kind in ('gitleaks', 'infection', 'eslint') else dict
    data = read_json(path, expected)
    if expected is list:
        if any(not isinstance(item, dict) for item in data):
            raise ValueError('invalid report item')
        if kind == 'gitleaks' and any(not all(k in item for k in ('RuleID', 'File', 'StartLine')) for item in data):
            raise ValueError('incomplete Gitleaks finding')
        return data
    keys = {'composer': ('advisories', (dict, list)), 'trivy': ('Results', list),
            'rector': ('file_diffs', list), 'deptrac': ('files', dict),
            'cspell': ('issues', list), 'zap': ('site', list)}
    key, types = keys[kind]
    if data.get('__audit_failed__') or key not in data or not isinstance(data[key], types):
        raise ValueError('incomplete producer report')
    if kind == 'composer' and isinstance(data[key], list) and data[key]:
        raise ValueError('invalid advisory list')
    return data


def entry(main):
    import sys
    if sys.argv[1:] in (['-h'], ['--help']):
        print(main.__doc__ or 'Report conversion; see this folder\'s README.md for producer-specific arguments and completeness contracts.')
        return 0
    try:
        result = main()
        return 0 if result is None else result
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ET.ParseError) as error:
        print("Report unavailable: " + type(error).__name__, file=sys.stderr)
        return 2
