"""Local project gates: status/check are read-only; record requires explicit --write."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import tempfile
import os

CLASSES = {'AUTO', 'REVIEW', 'HUMAN'}
STATUSES = {'queued', 'active', 'recommended_pass', 'passed', 'blocked', 'parked'}


def local(root, name):
    p = (root / name).resolve()
    p.relative_to(root.resolve())
    return p


def validate(state, root):
    if not isinstance(state, dict) or not isinstance(state.get('gates'), list):
        raise ValueError('state needs a gates list')
    gates = {}
    for gate in state['gates']:
        if not isinstance(gate, dict) or not isinstance(gate.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', gate['id']) or gate['id'] in gates:
            raise ValueError('invalid or duplicate gate identity')
        if gate.get('class') not in CLASSES or gate.get('status') not in STATUSES:
            raise ValueError('invalid gate class/status')
        if not isinstance(gate.get('depends_on', []), list) or any(not isinstance(x, str) for x in gate.get('depends_on', [])):
            raise ValueError('invalid prerequisites')
        gates[gate['id']] = gate
    for gate in gates.values():
        deps = gate.get('depends_on', [])
        if any(d not in gates or d == gate['id'] for d in deps):
            raise ValueError('missing/self prerequisite')
        if gate['status'] == 'passed':
            evidence = gate.get('evidence')
            if not isinstance(evidence, list) or not evidence or any(not isinstance(x, str) or not local(root, x).is_file() for x in evidence):
                raise ValueError('passed gate needs existing local evidence files')
            if any(gates[d]['status'] != 'passed' for d in deps):
                raise ValueError('passed gate has unpassed prerequisite')
            if gate['class'] in ('REVIEW', 'HUMAN'):
                approval = gate.get('approval')
                if not isinstance(approval, dict) or not isinstance(approval.get('by'), str) or approval['by'].strip().lower() in ('', 'ai', 'agent', 'claude', 'automation'):
                    raise ValueError('human/review gate needs an explicit human approval record')
                if approval.get('gate') != gate['id'] or not approval.get('record'):
                    raise ValueError('approval must name this gate and its source record')
    def visit(gid, stack, done):
        if gid in stack:
            raise ValueError('cyclic prerequisites')
        if gid in done:
            return
        for dep in gates[gid].get('depends_on', []):
            visit(dep, stack | {gid}, done)
        done.add(gid)
    done = set()
    for gid in gates:
        visit(gid, set(), done)
    return gates


def atomic(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.state-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, indent=2)
            out.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', required=True)
    ap.add_argument('--state', default='PROJECT_STATE.json')
    sub = ap.add_subparsers(dest='action', required=True)
    sub.add_parser('check')
    sub.add_parser('status')
    record = sub.add_parser('record')
    record.add_argument('gate')
    record.add_argument('--evidence', action='append', required=True)
    record.add_argument('--approved-by')
    record.add_argument('--approval-record')
    record.add_argument('--write', action='store_true')
    a = ap.parse_args(argv)
    try:
        root = Path(a.root).resolve()
        path = local(root, a.state)
        before = path.read_text()
        state = json.loads(before)
        gates = validate(state, root)
        if a.action == 'record':
            gate = gates[a.gate]
            gate.update(status='passed', evidence=a.evidence)
            if a.approved_by or a.approval_record:
                gate['approval'] = {'by': a.approved_by, 'record': a.approval_record,
                                    'gate': a.gate, 'recorded_at': datetime.now(timezone.utc).isoformat()}
            validate(state, root)
            if a.write:
                if path.read_text() != before:
                    raise ValueError('state changed during validation; retry')
                atomic(path, state)
            print(json.dumps({'written': a.write, 'gate': gate}))
        elif a.action == 'status':
            frontier = [g['id'] for g in gates.values() if g['status'] in ('queued', 'active') and all(gates[d]['status'] == 'passed' for d in g.get('depends_on', []))]
            print(json.dumps({'phase': state.get('current_phase'), 'frontier': frontier,
                              'human_work': [g['id'] for g in gates.values() if g['class'] == 'HUMAN' and g['status'] == 'active']}))
        else:
            print('State valid. Approval records are assertions, not independently authenticated identities.')
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print('State unavailable or invalid; no transition written', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
