"""Read-only Docker container and Linux memory snapshot; no daemon mounts or writes."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def memory(text):
    fields = {line.split(':', 1)[0]: int(line.split(':', 1)[1].split()[0]) for line in text.splitlines()}
    total = fields.get('SwapTotal', 0)
    return {'available_mb': fields['MemAvailable'] / 1024,
            'swap_used_pct': (100 * (total - fields.get('SwapFree', 0)) / total) if total else 0}


def evaluate(containers, mem, minimum, max_swap):
    if not containers:
        return {'healthy': False, 'complete': False, 'reason': 'no containers'}
    observed = []
    for c in containers:
        policy = c['HostConfig']['RestartPolicy']['Name']
        state = c['State']
        expected = policy in ('always', 'unless-stopped', 'on-failure')
        running = state.get('Running') is True
        health = state.get('Health', {}).get('Status')
        observed.append({'name': c['Name'], 'expected_running': expected,
                         'healthy': (not expected) or (running and health in (None, 'healthy'))})
    good_memory = mem is not None and (not minimum or mem['available_mb'] >= minimum) and (not max_swap or mem['swap_used_pct'] <= max_swap)
    return {'complete': mem is not None, 'healthy': good_memory and all(c['healthy'] for c in observed),
            'containers': observed, 'memory': mem}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', required=True)
    ap.add_argument('--min-available-mb', type=int, default=1500)
    ap.add_argument('--max-swap-pct', type=float, default=75)
    a = ap.parse_args()
    def docker(*args):
        return subprocess.check_output(['docker', *args], text=True, timeout=30, stderr=subprocess.DEVNULL)
    try:
        if a.min_available_mb < 0 or not 0 <= a.max_swap_pct <= 100:
            raise ValueError('invalid thresholds')
        ids = docker('ps', '-aq', '--filter', 'label=com.docker.compose.project=' + a.project).split()
        containers = json.loads(docker('inspect', *ids)) if ids else []
        mem = memory(Path('/proc/meminfo').read_text())
        result = evaluate(containers, mem, a.min_available_mb, a.max_swap_pct)
        print(json.dumps(result))
        return 0 if result['healthy'] else 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Container state unavailable', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
