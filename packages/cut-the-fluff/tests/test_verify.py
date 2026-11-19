"""Distribution and observation contracts; no live agent sessions."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
from verify import run, compare


def trials(kind='synthetic'):
    pairs = []
    for category in ('normal', 'routed_reference', 'rare_essential'):
        observation = {'conditions': dict(model='fixture', runtime='fixture', version='1',
            surface='cli', tools='Read', isolation='temporary project', task_sha256='a'*64,
            configuration_sha256='b'*64), 'metrics': dict(quality=1, discovery_success=True,
            orientation_reads=1, repeated_reads=0, context_source_bytes=100, input_tokens=None),
            'evidence_refs':['fixture:event:1']}
        changed = copy.deepcopy(observation)
        changed['conditions']['configuration_sha256'] = 'c'*64
        changed['metrics']['context_source_bytes'] = 50
        pairs.append(dict(task_id=category, category=category, baseline=observation, changed=changed))
    return dict(schema_version='1.0', kind=kind, pairs=pairs, review_notes=['Synthetic only'])


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.package = self.root/'copied'
        shutil.copytree(PACKAGE, self.package, ignore=shutil.ignore_patterns('__pycache__'))
        self.args = SimpleNamespace(package=str(self.package), trials=None, inventory=None)

    def test_whole_package_no_execution_or_mutation(self):
        def snapshot():
            return {p.relative_to(self.package).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.package.rglob('*') if p.is_file()}
        before = snapshot()
        with patch('subprocess.run', side_effect=AssertionError('execution')), patch('subprocess.Popen', side_effect=AssertionError('execution')):
            result = run(self.args)
        self.assertEqual(result['structural']['errors'], [])
        self.assertEqual(result['behavior']['status'], 'not_run')
        self.assertEqual(before, snapshot())

    def test_missing_notice_link_escape_and_syntax_fail(self):
        (self.package/'notices/agent-writing/LICENSE-Matt-Pocock').unlink()
        (self.package/'bad.py').write_text('def broken(')
        (self.package/'bad.json').write_text('{')
        (self.package/'bad.md').write_text('[escape](../outside.md)\n[missing](no.md)')
        errors = run(self.args)['structural']['errors']
        self.assertTrue(any(x.startswith('missing:') for x in errors))
        self.assertIn('python_syntax:bad.py', errors)
        self.assertIn('json_syntax:bad.json', errors)
        self.assertEqual(sum(x.startswith('link:bad.md') for x in errors), 2)

    def test_bad_metadata_machine_paths_and_tampered_notice(self):
        (self.package/'SKILL.md').write_text('No metadata')
        (self.package/'dependency.md').write_text('Load /' + 'home/somebody/warehouse/script.py')
        (self.package/'notices/agent-writing/ORIGIN.md').write_text('Changed')
        errors=run(self.args)['structural']['errors']
        self.assertIn('skill_metadata', errors)
        self.assertIn('machine_path:dependency.md', errors)
        (self.package/'dependency.md').write_text('Load /' + 'Users/somebody/warehouse/script.py')
        self.assertIn('machine_path:dependency.md', run(self.args)['structural']['errors'])
        self.assertIn('notice_hash:notices/agent-writing/ORIGIN.md', errors)

    def test_symlinks_special_files_and_bounds_refused(self):
        path=self.package/'external.md'
        path.symlink_to(self.root/'outside')
        with self.assertRaises(ValueError): run(self.args)
        path.unlink()
        import os
        os.mkfifo(path)
        with self.assertRaises(ValueError): run(self.args)
        path.unlink()
        path.write_bytes(b'x'*(2*1024*1024+1))
        with self.assertRaises(ValueError): run(self.args)

    def test_comparison_keeps_evidence_classes_separate(self):
        self.assertEqual(compare(trials())['status'], 'demonstration_only')
        self.assertEqual(compare(trials('reviewer_walkthrough'))['status'], 'demonstration_only')
        result=compare(trials('live_agent'))
        self.assertEqual(result['status'], 'observed_preservation')
        self.assertFalse(result['independently_verified'])
        self.assertIsNone(result['pairs'][0]['changed']['input_tokens'])

    def test_quality_discovery_effort_and_conditions_block_acceptance(self):
        for field, value in [('quality',0.5),('discovery_success',False),('orientation_reads',3),('repeated_reads',2),('context_source_bytes',200),('input_tokens',11)]:
            v=trials('live_agent')
            v['pairs'][0]['baseline']['metrics']['input_tokens']=10
            v['pairs'][0]['changed']['metrics'][field]=value
            self.assertEqual(compare(v)['status'], 'regression_or_incomparable' if field in ('quality','discovery_success') else 'review_required',field)
        for field in ('model','runtime','version','surface','tools','isolation','task_sha256'):
            v=trials('live_agent')
            v['pairs'][0]['changed']['conditions'][field]='d'*64
            self.assertFalse(compare(v)['comparable'],field)

    def test_imperfect_baseline_is_not_a_regression(self):
        v=trials('live_agent')
        for side in ('baseline','changed'):
            v['pairs'][0][side]['metrics']['quality']=0.5
        result=compare(v)
        self.assertFalse(result['pairs'][0]['regression'])
        self.assertTrue(result['pairs'][0]['baseline_incomplete'])
        self.assertEqual(result['status'],'baseline_incomplete')
        v['pairs'][0]['baseline']['metrics']['discovery_success']=False
        v['pairs'][0]['changed']['metrics']['discovery_success']=False
        self.assertEqual(compare(v)['status'],'baseline_incomplete')
        # A change that does worse than an imperfect baseline is still a regression.
        v['pairs'][0]['changed']['metrics']['quality']=0.4
        self.assertTrue(compare(v)['pairs'][0]['regression'])
        self.assertEqual(compare(v)['status'],'regression_or_incomparable')

    def test_malformed_duplicate_unknown_and_incomplete_trials(self):
        for mutation in (lambda x:x.update(schema_version='2.0'),lambda x:x.update(kind='test'),
                         lambda x:x['pairs'].append(x['pairs'][0]),lambda x:x.update(pairs=[]),
                         lambda x:x['pairs'][0]['changed'].update(evidence_refs=[]),
                         lambda x:x['pairs'][0]['baseline']['metrics'].update(quality=float('nan'))):
            v=trials(); mutation(v)
            with self.assertRaises(ValueError): compare(v)
        v=trials('live_agent'); v['pairs'].pop()
        self.assertEqual(compare(v)['missing_categories'], ['rare_essential'])
        self.assertEqual(compare(v)['status'],'regression_or_incomparable')

    def test_relocated_isolated_cli_and_invalid_input(self):
        result=subprocess.run([sys.executable,'-I','-B',str(self.package/'inventory.py'),'verify'],
            cwd=self.root,capture_output=True,text=True)
        # Existing CLI deliberately imports sibling stdlib modules; isolated mode
        # is supported by the package bootstrap.
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['structural']['status'],'passed')
        bad=self.root/'invalid.json';bad.write_text('{}')
        result=subprocess.run([sys.executable,'-I','-B',str(self.package/'inventory.py'),'verify','--trials',str(bad)],cwd=self.root,capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertEqual(result.stdout,'')

    def test_behavior_fixtures_preserve_conditional_routes_in_both_profiles(self):
        import inventory
        base=PACKAGE/'tests/fixtures/behavior'
        for runtime, version in [('codex','docs-2026-11-11'),('claude','2.1.285')]:
            for variant in ('baseline','changed'):
                project=base/variant
                args=inventory.parser().parse_args(['inventory','--project',str(project),
                    '--runtime',runtime,'--runtime-version',version])
                result=inventory.Inventory(args).run()
                if variant=='changed':
                    refs={i['origin']:i for i in result['items']}
                    for leaf in ('ledger','recovery'):
                        item=refs['project:docs/'+leaf+'.md']
                        self.assertEqual(item['loading'],'conditional')
                        self.assertEqual(item['states']['loaded'],'unknown')
                for leaf in ('ledger','recovery'):
                    self.assertEqual((base/'baseline/docs'/f'{leaf}.md').read_bytes(),
                                     (base/'changed/docs'/f'{leaf}.md').read_bytes())
                self.assertEqual([i for i in result['items'] if i['kind'] in ('hook','mcp')],[])

    def test_explicit_inventory_preserves_effective_runtime_gap(self):
        result=subprocess.run([sys.executable,'-I','-B',str(self.package/'inventory.py'),'inventory',
            '--project',str(self.root),'--runtime','codex','--runtime-version','docs-2026-11-11'],
            capture_output=True,text=True,check=True)
        inv=self.root/'inventory.json';inv.write_text(result.stdout)
        self.args.inventory=str(inv)
        result=run(self.args)
        self.assertEqual(result['runtime']['effective_configuration'],'unknown')


if __name__ == '__main__': unittest.main()
