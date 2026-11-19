"""Statement coverage per file from a Clover report.

Usage:
    python3 coverage_for_files.py <clover.xml> <file> [<file> ...] [--min=80]

Prints covered/total statements and the percentage for each given file, and
exits 1 when any file is below the minimum. Zero-statement records and absent
non-PHP files are listed separately. Requested required-suffix files absent from the report
fail the coverage check. Missing or malformed reports exit 2. Relative report,
requested-file and Clover file paths are resolved against the working directory.
"""

import argparse
import math
import os
import sys
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report')
    parser.add_argument('files', nargs='+')
    parser.add_argument('--min', type=float, default=80.0)
    parser.add_argument('--required-suffix', action='append', default=None,
                        help='missing requested files with this suffix fail; default .php')
    parser.add_argument('--report-prefix', help='strip this exact report-path prefix before mapping')
    parser.add_argument('--source-root', default='.')
    options = parser.parse_args()
    minimum = options.min
    if not math.isfinite(minimum) or not 0 <= minimum <= 100:
        parser.error('--min must be finite and between 0 and 100')
    report, files = options.report, [os.path.abspath(f) for f in options.files]
    suffixes = tuple(options.required_suffix or ['.php'])
    def mapped(name):
        if options.report_prefix:
            prefix = options.report_prefix.rstrip('/') + '/'
            if not name.startswith(prefix):
                raise ValueError('report source path does not match --report-prefix')
            name = name[len(prefix):]
        return os.path.abspath(os.path.join(options.source_root, name))
    metrics = {}
    try:
        for node in ET.parse(report).getroot().iter('file'):
            m = node.find('metrics')
            if m is not None:
                covered = int(m.attrib['coveredstatements'])
                total = int(m.attrib['statements'])
                if not 0 <= covered <= total:
                    raise ValueError('invalid statement counts')
                key = mapped(node.attrib['name'])
                if key in metrics:
                    raise ValueError('duplicate report source record')
                metrics[key] = (covered, total)
    except (OSError, ET.ParseError, KeyError, ValueError) as error:
        print(f'Cannot read Clover report at {report}: {error}', file=sys.stderr)
        return 2

    below = False
    for path in files:
        rel = os.path.relpath(path)
        if path not in metrics and path.lower().endswith(suffixes):
            print(f'  LOW    {rel} (source not in report; coverage unknown)')
            below = True
            continue
        covered, total = metrics.get(path, (0, 0))
        if total == 0:
            note = 'not in report' if path not in metrics else 'no statements'
            print(f"  -      {rel} ({note})")
            continue
        pct = 100.0 * covered / total
        flag = 'OK ' if pct >= minimum else 'LOW'
        below = below or pct < minimum
        print(f"  {flag} {pct:5.1f}% {rel} ({covered}/{total})")

    return 1 if below else 0


if __name__ == '__main__':
    sys.exit(main())
