"""Read-only source integrity: syntax, local links, provenance and relocated entrypoints."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def check():
    errors = []
    files = [p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.relative_to(ROOT).parts and '__pycache__' not in p.parts]
    for p in files:
        if p.is_symlink():
            errors.append('source assets must not be symlinks: ' + str(p.relative_to(ROOT)))
        if p.suffix == '.py':
            try:
                ast.parse(p.read_text(), filename=str(p.relative_to(ROOT)))
            except SyntaxError as e:
                errors.append(str(e))
        if p.suffix == '.sh':
            r = subprocess.run(['bash', '-n', str(p)], capture_output=True, text=True)
            if r.returncode:
                errors.append(r.stderr)
        if p.suffix == '.php' and shutil.which('php'):
            r = subprocess.run(['php', '-l', str(p)], capture_output=True, text=True)
            if r.returncode:
                errors.append(r.stderr)
        if p.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', p.read_text()):
                u = urlsplit(target.strip('<>'))
                if u.scheme or u.netloc or not u.path:
                    continue
                q = (p.parent / unquote(u.path)).resolve()
                if not q.is_relative_to(ROOT) or not q.exists():
                    errors.append(f'{p.relative_to(ROOT)}: unresolved local target {target}')
        if p.suffix in ('.py', '.sh', '.php', '.md') and p.name != 'check.py':
            if re.search(r'/home/[A-Za-z0-9_.-]+/|/mnt/[a-z]/Users/', p.read_text(errors='replace')):
                errors.append('machine-specific path: ' + str(p.relative_to(ROOT)))
    for agent in sorted((ROOT / 'agents').glob('*.md')):
        if not agent.name.endswith('.ORIGIN.md') and not (ROOT / 'agents' / (agent.stem + '.ORIGIN.md')).is_file():
            errors.append(f'agents/{agent.name}: missing ORIGIN record')
    for family in ('tools', 'skills'):
        for folder in sorted((ROOT / family).iterdir()):
            if not folder.is_dir():
                continue
            for required in ('ORIGIN.md', 'README.md' if family == 'tools' else 'SKILL.md'):
                if not (folder / required).is_file():
                    errors.append(f'{folder.relative_to(ROOT)}: missing {required}')
    ledger = json.loads((ROOT / 'inventory.json').read_text())
    if len(ledger['sources']) != 11 or len(ledger['groups']) != 49:
        errors.append('initial source/group inventory is incomplete')
    for group in ledger['groups']:
        for path in group.get('represented_by', []):
            if not (ROOT / path).exists():
                errors.append('inventory points to missing component: ' + path)
    origins = json.loads((ROOT / 'provenance/components.json').read_text())
    for component, record in origins.items():
        if not record.get('origins') or not record.get('adaptations'):
            errors.append('component has incomplete provenance: ' + component)
        for name, expected in record['destination_hashes'].items():
            p = ROOT / name
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
                errors.append('reviewed component changed: ' + name)
    probes = {
        'test-reports': ['failed_tests.py', 'coverage_for_files.py'],
        'exact-patch': ['patch.py'], 'code-navigation': ['code_map.py'],
        'session-analysis': ['session_cost.py', 'review_due.py'],
        'report-converters': ['composer_audit_to_sarif.py', 'security_to_sarif.py', 'convert_reports.py', 'merge_sarif.py', 'eslint_json_to_sarif.py'],
        'service-readers': ['ci_status.py', 'asana.py', 'sonar_status.py', 'dojo_findings.py', 'pr_review.py'],
        'git-checks': ['status.py', 'select_changes.py', 'checks.py'],
        'laravel-tests': ['session_database.py'], 'project-state': ['state.py'],
        'project-checks': ['check.py'], 'conversation-index': ['index.py'],
        'reference-library': ['query.py', 'hig_download.py', 'nng_download.py'],
        'container-status': ['status.py'], 'deployment-receipt': ['receipt.py'],
        'issue-session': ['issue_brief.py'], 'ux-workspace': ['check.py', 'sync.py', 'feedback.py'],
        'fixture-evidence': ['evidence.py'], 'lexical-search': ['search.py'],
        'origin-drift': ['check.py'], 'decision-records': ['decisions.py'], 'finding-records': ['findings.py'],
        'design-register': ['register.py'], 'design-compare': ['compare.py'], 'floor-guard': ['floor_guard.py'],
        'session-guards': ['workflow_guard.py', 'context_guard.py'],
    }
    # A relocated copy contains no source-project access and does not use a warehouse path.
    with tempfile.TemporaryDirectory(prefix='toolkit-relocation-') as temporary:
        scratch = Path(temporary)
        subprocess.run(['git', 'init', '-q', str(scratch)], check=True, capture_output=True)
        for family, scripts in probes.items():
            target = scratch / family
            shutil.copytree(ROOT / 'tools' / family, target)
            for script in scripts:
                r = subprocess.run([sys.executable, '-B', '-I', str(target / script), '--help'], cwd=scratch, capture_output=True, text=True, timeout=20)
                if r.returncode:
                    errors.append(f'relocated {family}/{script}: {r.stderr[:300]}')
        target = scratch / 'worktrees'
        shutil.copytree(ROOT / 'tools/worktrees', target)
        r = subprocess.run(['bash', str(target / 'new_session.sh'), '--help'], cwd=scratch, capture_output=True, text=True)
        if r.returncode:
            errors.append('relocated worktree entrypoint failed')
        target = scratch / 'hooks'
        shutil.copytree(ROOT / 'tools/hooks', target)
        import os
        hook_env = dict(os.environ, CLAUDE_CONFIG_DIR=str(scratch / 'hook-config'))
        for script, payload, expected in [
            ('destructive_guard.py', {'tool_name': 'Bash', 'tool_input': {'command': 'git reset --hard'}}, 2),
            ('dotenv_guard.py', {'tool_name': 'Read', 'tool_input': {'file_path': '.env'}}, 2),
            ('session_review_pointer.py', {'cwd': str(scratch)}, 0),
        ]:
            r = subprocess.run([sys.executable, '-B', '-I', str(target / script)], input=json.dumps(payload),
                               env=hook_env, cwd=scratch, capture_output=True, text=True, timeout=10)
            if r.returncode != expected:
                errors.append('relocated hook probe failed: ' + script)
        if shutil.which('php'):
            target = scratch / 'php-quality-config'
            shutil.copytree(ROOT / 'tools/php-quality-config', target)
            r = subprocess.run(['php', str(target / 'generate.php'), str(scratch)], capture_output=True, text=True)
            if r.returncode:
                errors.append('relocated PHP generator failed')
    return errors


if __name__ == '__main__':
    try:
        errors = check()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as e:
        errors = ['Integrity check unavailable: ' + type(e).__name__]
    print('\n'.join(errors) if errors else 'OK: syntax, local targets, provenance, inventory and relocated entrypoints')
    sys.exit(1 if errors else 0)
