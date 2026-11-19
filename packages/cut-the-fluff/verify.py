"""Read-only distribution checks and comparison of supplied behavior observations.

Never launches an agent, executes package helpers or discovers private evidence.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import unquote, urlsplit

VERSION = '1.0'
REQUIRED = {'SKILL.md', 'README.md', 'inventory.py', 'adapters.py', 'evidence.py', 'shell.py',
            'report.py', 'changes.py', 'verify.py', 'schema.json', 'PROVENANCE.md',
            'provenance.json', 'references/validation-contract.md',
            'references/runtime-contract.md', 'references/codex-report.md',
            'references/claude-report.md', 'references/change-contract.md',
            'references/evidence-contract.md', 'references/report-contract.md',
            'notices/agent-writing/LICENSE-Matt-Pocock', 'tests/README.md',
            'tests/test_inventory.py', 'tests/test_evidence.py', 'tests/test_report.py',
            'tests/test_changes.py', 'tests/test_verify.py', 'tests/fixtures/behavior/tasks.json'}
REQUIRED.update('tests/fixtures/behavior/' + variant + '/' + leaf
                for variant in ('baseline', 'changed')
                for leaf in ('AGENTS.md', 'docs/ledger.md', 'docs/recovery.md'))
CONDITIONS = ('model', 'runtime', 'version', 'surface', 'tools', 'isolation', 'task_sha256')
METRICS = ('quality', 'discovery_success', 'orientation_reads', 'repeated_reads',
           'context_source_bytes', 'input_tokens')


def add_arguments(p):
    p.add_argument('--package', default=str(Path(__file__).resolve().parent))
    p.add_argument('--trials', help='Explicit local paired observation JSON; no agent is launched')
    p.add_argument('--inventory', help='Explicit existing inventory JSON; loading stays an expectation')


def read(path, limit=2*1024*1024):
    # Do not block on FIFOs or follow a final symlink, including explicit inputs.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('regular file required')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('file limit')
    return data


def compare(value):
    from report import validate
    defs = json.loads(read(Path(__file__).with_name('schema.json')))['$defs']
    validate(value, defs['behavior_trials'], defs)
    if not value['pairs'] or len(value['pairs']) > 100:
        raise ValueError('nonempty bounded pairs required')
    seen, categories, pairs = set(), set(), []
    for pair in value['pairs']:
        if not pair['task_id'].strip() or pair['task_id'] in seen:
            raise ValueError('unique task identity required')
        seen.add(pair['task_id'])
        categories.add(pair['category'])
        before, after = pair['baseline'], pair['changed']
        for trial in (before, after):
            for key in CONDITIONS:
                if not trial['conditions'][key].strip():
                    raise ValueError('explicit conditions required')
            for key in ('task_sha256', 'configuration_sha256'):
                if not re.fullmatch('[0-9a-f]{64}', trial['conditions'][key]):
                    raise ValueError('sha256 required')
            if not trial['evidence_refs'] or any(not x.strip() for x in trial['evidence_refs']):
                raise ValueError('observation citations required')
        differences = [key for key in CONDITIONS if before['conditions'][key] != after['conditions'][key]]
        a, b = before['metrics'], after['metrics']
        # An imperfect baseline is not a regression caused by the change; it means
        # the comparison cannot certify preservation until the baseline is rerun.
        incomplete = a['quality'] < 1 or not a['discovery_success']
        regression = (b['quality'] < a['quality'] or (a['discovery_success'] and not b['discovery_success'])
                      or (not incomplete and b['quality'] < 1))
        # Effort/context increases must be investigated, never hidden by a lower byte estimate.
        increases = [key for key in METRICS[2:] if a[key] is not None and b[key] is not None and b[key] > a[key]]
        pairs.append(dict(task_id=pair['task_id'], category=pair['category'],
                          condition_differences=differences, regression=regression,
                          baseline_incomplete=incomplete,
                          metric_increases=increases, baseline=a, changed=b,
                          evidence_refs=before['evidence_refs'] + after['evidence_refs']))
    missing = sorted({'normal', 'routed_reference', 'rare_essential'} - categories)
    comparable = not any(p['condition_differences'] for p in pairs)
    regressions = any(p['regression'] for p in pairs)
    increases = any(p['metric_increases'] for p in pairs)
    actual = value['kind'] == 'live_agent'
    return dict(kind=value['kind'], missing_categories=missing, comparable=comparable,
                review_notes=value['review_notes'], pairs=pairs,
                status=('regression_or_incomparable' if regressions or not comparable or missing else
                        'baseline_incomplete' if any(p['baseline_incomplete'] for p in pairs) else
                        'review_required' if increases else
                        'observed_preservation' if actual else 'demonstration_only'),
                independently_verified=False)


def run(args):
    root = Path(args.package).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('package directory required')
    errors, files, total = [], {}, 0
    # A bounded complete bundle walk, never the audited project or home.
    def walk(directory):
        nonlocal total
        for path in sorted(directory.iterdir()):
            if path.name in {'.git', '__pycache__'}:
                continue
            if path.is_symlink():
                raise ValueError('symlink in distribution')
            if path.is_dir():
                if len(path.relative_to(root).parts) > 16:
                    raise ValueError('directory depth limit')
                walk(path)
            else:
                data = read(path)
                total += len(data)
                if len(files) >= 500 or total > 16*1024*1024:
                    raise ValueError('bundle limit')
                files[path.relative_to(root).as_posix()] = data
    walk(root)
    errors.extend('missing:' + name for name in sorted(REQUIRED - files.keys()))
    for name, data in files.items():
        if name.endswith('.py'):
            try:
                ast.parse(data, filename=name)
            except (SyntaxError, ValueError):
                errors.append('python_syntax:' + name)
        if name.endswith('.json'):
            try:
                json.loads(data)
            except (ValueError, UnicodeError):
                errors.append('json_syntax:' + name)
        if name.endswith(('.md', '.py', '.json')):
            text = data.decode('utf-8')
            if re.search(r'/(?:home|Users|mnt/[a-z]/Users)/[^\s"\']+', text):
                errors.append('machine_path:' + name)
        if name.endswith('.md'):
            # Supported Markdown links only; code examples are not dependencies.
            text = re.sub(r'```.*?```|`[^`\n]*`', '', data.decode('utf-8'), flags=re.S)
            for target in re.findall(r'\]\(([^)]+)\)', text):
                url = urlsplit(target.strip('<>'))
                if url.scheme or url.netloc or not url.path:
                    continue
                relative = (root / name).parent / unquote(url.path)
                resolved = relative.resolve()
                if not resolved.is_relative_to(root) or not resolved.exists():
                    errors.append('link:' + name + ':' + target)
    skill = files.get('SKILL.md', b'').decode('utf-8')
    if not re.match(r'---\nname: cut-the-fluff\ndescription: [^\n]+\n---\n', skill):
        errors.append('skill_metadata')
    if sys.version_info < (3, 11):
        errors.append('python_version')
    if 'provenance.json' in files:
        try:
            provenance = json.loads(files['provenance.json'])
            for source in provenance['sources']:
                folder = source['original_folder'].rsplit('/', 1)[-1]
                for original, expected in source['reviewed_files_sha256'].items():
                    dest = 'notices/' + folder + '/' + original.rsplit('/', 1)[-1]
                    if dest in files and hashlib.sha256(files[dest]).hexdigest() != expected:
                        errors.append('notice_hash:' + dest)
                for leaf in ('ORIGIN.json', 'ORIGIN.md'):
                    if 'notices/' + folder + '/' + leaf not in files:
                        errors.append('missing_origin:' + folder + '/' + leaf)
        except (KeyError, TypeError, ValueError):
            errors.append('provenance_contract')
    runtime = {'status': 'not_supplied', 'effective_configuration': 'unknown'}
    if args.inventory:
        from report import validate
        inv = json.loads(read(Path(args.inventory)))
        defs = json.loads(files['schema.json'])['$defs']
        validate(inv, defs['inventory'], defs)
        runtime = {'status': 'configured_files_only', 'effective_configuration': 'unknown',
                   'coverage_gaps': len(inv['coverage']),
                   'loading_expectations': sorted({i['loading'] for i in inv['items']})}
    behavior = compare(json.loads(read(Path(args.trials)))) if args.trials else {'status': 'not_run'}
    return {'schema_version': VERSION, 'kind': 'verification',
            'structural': {'status': 'failed' if errors else 'passed', 'errors': errors,
                           'files': len(files), 'source_bytes': total},
            'tools': {'python': '.'.join(map(str, sys.version_info[:3])),
                      'mutation_platform': 'supported' if os.name == 'posix' else 'unsupported'},
            'runtime': runtime, 'behavior': behavior,
            'limitations': ['Static checks do not execute documented commands, tests or host discovery.',
                            'Supplied observations are reviewer records, not authenticated runtime evidence.',
                            'Source bytes are not runtime tokens, cache use or billing.']}
