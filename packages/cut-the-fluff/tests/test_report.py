"""Report semantics, architectural review and read-only process boundaries."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_inventory import mod, SCHEMA, validate
from report import Report, compact, human, markdown
from evidence import Analysis

PACKAGE = Path(__file__).resolve().parents[1]


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.put('CLAUDE.md', 'Read [missing](missing.md).\n@guide.md\n')
        self.put('guide.md', 'Keep recovery instructions.\n')
        self.put('duplicate.md', 'Keep recovery instructions.\n')
        self.put('architecture.md', 'Recovery and security are required. A future release needs signing.\n')
        for skill in ('one', 'two'):
            self.put('.claude/skills/' + skill + '/SKILL.md', '---\nname: ' + skill + '\ndescription: all tasks\n---\nbody\n')
        args = mod.parser().parse_args(['inventory', '--project', str(self.project), '--runtime', 'claude', '--runtime-version', '2.1.285'])
        self.inv = mod.Inventory(args).run()
        self.inventory = self.base / 'inventory.json'
        self.inventory.write_text(json.dumps(self.inv))
        self.context = ['CLAUDE.md', 'guide.md', 'duplicate.md', '.claude/skills/one/SKILL.md', '.claude/skills/two/SKILL.md']

    def put(self, name, text):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def args(self, *extra):
        argv = ['report', '--project', str(self.project), '--inventory', str(self.inventory)]
        for name in self.context:
            argv += ['--context', name]
        argv += ['--architecture', 'architecture.md', *extra]
        return mod.parser().parse_args(argv)

    def run_report(self, *extra):
        with patch('subprocess.run', side_effect=AssertionError('execution')), patch('subprocess.Popen', side_effect=AssertionError('execution')), patch('os.system', side_effect=AssertionError('execution')):
            result = Report(self.args(*extra)).run()
        validate(result, SCHEMA['$defs']['report'])
        refs = {r['id'] for r in result['evidence']}
        for obj in result['signals'] + result['findings'] + result['mappings']:
            self.assertTrue(set(obj['evidence_refs']) <= refs)
        return result

    def decision(self, **changes):
        item = next(i for i in self.inv['items'] if i['origin'] == 'project:CLAUDE.md')
        value = dict(component_ids=[item['id']], action='trim', evidence_refs=['document:1', 'document:6'],
                     confidence='medium', rationale='Architecture preserves recovery; replace only a broken duplicate route.',
                     discovery_impact='Recovery remains discoverable through guide.md.', need='Recovery', protected=False)
        value.update(changes)
        path = self.base / 'review.json'
        path.write_text(json.dumps(dict(schema_version='1.0', decisions=[value])))
        return str(path)

    def test_large_context_threshold_is_only_a_candidate(self):
        result = self.run_report('--large-context-bytes', '10')
        self.assertIn('large_context_body', {s['code'] for s in result['signals']})
        self.assertEqual([], result['findings'])
        self.assertIsNone(result['accounting']['total_savings'])
        with self.assertRaises(ValueError):
            self.run_report('--large-context-bytes', '0')

    def test_candidates_are_not_findings_or_proven_unused(self):
        result = self.run_report()
        codes = {s['code'] for s in result['signals']}
        self.assertTrue({'stale_pointer', 'duplicate_content', 'eager_import', 'weak_trigger', 'overlapping_discovery'} <= codes)
        self.assertEqual([], result['findings'])
        self.assertIn('no_usage_evidence', {g['code'] for g in result['coverage']})
        self.assertIsNone(result['accounting']['total_savings'])
        self.assertNotIn('unused', json.dumps(result))
        self.assertIn('Evidence index', markdown(result))

    def test_weak_trigger_reads_frontmatter_description_only(self):
        # Folded description is strong; a body line that looks like YAML is ignored.
        self.put('.claude/skills/one/SKILL.md', '---\nname: one\ndescription: >\n  Use when auditing agent\n  context files for waste.\n---\ndescription: x\n')
        self.put('.claude/skills/two/SKILL.md', '---\nname: two\ndescription: Use when reviewing release notes for accuracy.\n---\ndescription: all tasks\n')
        args = mod.parser().parse_args(['inventory', '--project', str(self.project), '--runtime', 'claude', '--runtime-version', '2.1.285'])
        self.inventory.write_text(json.dumps(mod.Inventory(args).run()))
        result = self.run_report()
        self.assertNotIn('weak_trigger', {s['code'] for s in result['signals']})

    def test_cited_protected_capability_and_unknown_savings(self):
        result = self.run_report('--review', self.decision(action='keep', protected=True))
        f = result['findings'][0]
        self.assertTrue(result['mappings'][0]['protected'])
        self.assertEqual(0, f['coverage']['covered_sessions'])
        self.assertIsNone(f['coverage']['eligible_sessions'])
        self.assertEqual('unknown', f['savings']['basis'])
        with self.assertRaises(ValueError):
            self.run_report('--review', self.decision(protected=True))

    def test_concrete_patch_and_no_overlapping_total(self):
        proposed = {'path': 'CLAUDE.md', 'old': 'Read [missing](missing.md).\n', 'new': ''}
        review = self.decision(patch=proposed)
        with self.assertRaises(ValueError):
            self.run_report('--review', review)
        before = (self.project / 'CLAUDE.md').read_bytes()
        result = self.run_report('--review', review, '--include-patches')
        f = result['findings'][0]
        self.assertIn('-Read [missing]', f['proposed_patch'])
        self.assertEqual(len(proposed['old'].encode()), f['savings']['amount'])
        self.assertEqual('file:CLAUDE.md', f['savings']['overlap_group'])
        self.assertEqual(before, (self.project / 'CLAUDE.md').read_bytes())
        data = json.loads(Path(review).read_text())
        data['decisions'] *= 2
        Path(review).write_text(json.dumps(data))
        result = self.run_report('--review', review, '--include-patches')
        self.assertEqual(2, len(result['findings']))
        self.assertIsNone(result['accounting']['total_savings'])

    def test_rejects_unknown_citations_components_and_missing_architecture(self):
        for changes in ({'evidence_refs': ['not-real']}, {'component_ids': ['not-real']}, {'evidence_refs': ['document:1']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.run_report('--review', self.decision(**changes))

    def test_snapshot_drift_blocks_patch(self):
        self.put('CLAUDE.md', 'changed\nRead [missing](missing.md).\n')
        result = self.run_report()
        self.assertIn('inventory_snapshot_mismatch', {g['code'] for g in result['coverage']})
        with self.assertRaises(ValueError):
            self.run_report('--review', self.decision(patch={'path': 'CLAUDE.md', 'old': 'changed\n', 'new': ''}), '--include-patches')

    def test_patch_must_be_unambiguous_and_cited_context(self):
        for p in ({'path': 'CLAUDE.md', 'old': '', 'new': 'x'}, {'path': 'CLAUDE.md', 'old': 'absent', 'new': ''}, {'path': '../escape', 'old': 'a', 'new': 'b'}, {'path': 'architecture.md', 'old': 'Recovery', 'new': ''}):
            with self.subTest(p=p), self.assertRaises(ValueError):
                self.run_report('--review', self.decision(patch=p), '--include-patches')

    def test_all_actions_supported_without_invented_savings(self):
        for action in ('keep', 'trim', 'deduplicate', 'narrow_scope', 'conditional', 'improve_trigger', 'defer', 'disable', 'archive'):
            f = self.run_report('--review', self.decision(action=action))['findings'][0]
            self.assertEqual(action, f['action'])
            self.assertIsNone(f['savings']['amount'])

    def test_bounds_symlinks_fifo_and_privacy(self):
        sentinel = 'SECRET_DO_NOT_EMIT_9241'
        self.put('private.md', sentinel)
        result = self.run_report('--architecture', 'private.md')
        self.assertNotIn(sentinel, json.dumps(result))
        outside = self.base / 'outside.md'
        outside.write_text(sentinel)
        (self.project / 'external.md').symlink_to(outside)
        os.mkfifo(self.project / 'fifo')
        result = self.run_report('--architecture', 'external.md', '--context', 'fifo', '--max-file-bytes', '100000')
        self.assertTrue({'outside_project', 'unreadable_or_limited_document'} <= {g['code'] for g in result['coverage']})
        with self.assertRaises(ValueError):
            self.run_report('--context', '../outside.md')
        with self.assertRaises(ValueError):
            self.run_report('--max-total-bytes', '1')

    def test_schema_version_and_dangling_bundle_refs(self):
        for mutate in (lambda d: d.update(schema_version='99'), lambda d: d['items'][0]['evidence_refs'].append('absent')):
            value = copy.deepcopy(self.inv)
            mutate(value)
            self.inventory.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                self.run_report()

    def test_existing_diagnostics_are_reported_citations(self):
        self.put('doctor.txt', 'Reported claim: scope is broad; $(touch NO)')
        result = self.run_report('--diagnostic', 'doctor.txt', '--review', self.decision(evidence_refs=['document:1', 'document:6', 'document:7'], rationale='Reported native diagnostic scope warning corroborated by architecture.'))
        self.assertNotIn('native_diagnostics_not_supplied', {g['code'] for g in result['coverage']})
        self.assertIn('document:7', result['findings'][0]['evidence_refs'])
        self.assertFalse((self.project / 'NO').exists())

    def test_analysis_failures_reads_and_cache_stay_distinct(self):
        args = mod.parser().parse_args(['analyze', '--project', str(self.project), '--runtime', 'claude'])
        a = Analysis(args).run()
        # Normalized fixture metadata exercises report consumption, not adapter behavior.
        def metric(component, **values):
            m = dict(component_id=component, invocations=0, successes=2, failures=1,
                unknown_results=0, reads=2, repeated_reads=1, read_attempts=3, repeated_read_attempts=2,
                inferred_reads=0, searches=0, sessions=['session:one'], last_observed_use=None, evidence_refs=[], basis=['direct'],
                covered_sessions=10, selected_sessions=10, sessions_with_activity=1, activity_session_fraction=0.1)
            m.update(values)
            return m
        a['metrics'] = [metric('file:project:CLAUDE.md'),
                        metric('skill:one', failures=0, reads=0, repeated_reads=0, invocations=1),
                        metric('file:project:notes/outside.md'), metric('tool:Read', failures=0, repeated_reads=0)]
        a['totals'].update(covered_sessions=10, selected_sessions=10)
        a['options']['low_use_threshold'] = 0.2
        path = self.base / 'analysis.json'
        path.write_text(json.dumps(a))
        result = self.run_report('--analysis', str(path))
        by_code = {}
        for s in result['signals']:
            by_code.setdefault(s['code'], []).append(s['component_ids'])
        self.assertEqual([['file:project:CLAUDE.md', 'i1']], by_code['broken_access_candidate'])
        self.assertEqual([['file:project:CLAUDE.md', 'i1']], by_code['repeated_content_reads'])
        # Startup files load every session, so few tool reads say nothing; the skill metric is joined.
        self.assertEqual([['skill:one', 'i3']], by_code['low_observed_activity'])
        self.assertIsNone(result['accounting']['repeated_input_tokens'])
        # Uninventoried files are listed as activity context, never as signals.
        self.assertEqual(1, result['file_activity']['components'])
        self.assertEqual('file:project:notes/outside.md', result['file_activity']['listed'][0]['component_id'])
        joins = {u['component_id']: (u['inventory_ids'], u['join']) for u in result['usage']}
        self.assertEqual({'file:project:CLAUDE.md': (['i1'], 'inventory'), 'skill:one': (['i3'], 'inventory'),
                          'tool:Read': ([], 'builtin_or_host_tool')}, joins)
        # Unresolved shell reads lower a metric's coverage below the threshold.
        a['metrics'][1]['covered_sessions'] = 9
        path.write_text(json.dumps(a))
        result = self.run_report('--analysis', str(path))
        self.assertNotIn('low_observed_activity', {s['code'] for s in result['signals']})
        a['adapter_profile'] = 'codex-rollout-jsonl-1'
        path.write_text(json.dumps(a))
        with self.assertRaises(ValueError):
            self.run_report('--analysis', str(path))

    def test_markdown_is_short_and_ordered(self):
        result = self.run_report('--review', self.decision(action='keep', protected=True))
        text = markdown(result, limit=2)
        order = [text.index(h) for h in ('## Findings (1)', '## Candidate signals', '## Usage by component',
                                         '## File activity', '## Documents', '## Coverage gaps', '## Evidence index')]
        self.assertEqual(sorted(order), order)
        # Finding headers name the component; the window and denominators are printed once.
        self.assertIn('### finding:1: keep i1 (instruction project:CLAUDE.md)', text)
        self.assertEqual(1, text.count('- Sessions:'))
        self.assertNotIn('gap_refs', text)
        self.assertIn('| document:6 | architecture.md | architecture |', text)
        self.assertEqual([dict(id='document:1', path='CLAUDE.md', roles=['context'])], result['documents'][:1])
        # Gaps are one row per code; signals of one code are capped at the listing limit.
        self.assertEqual(1, text.count('| no_usage_evidence |'))
        result['signals'] = [dict(id='signal:%d' % n, code='stale_pointer', component_ids=['i1'], evidence_refs=[], detail='x')
                             for n in range(5)]
        self.assertIn('... 3 more in the JSON output', markdown(result, limit=2))

    def test_agent_report_keeps_counts_caps_lists_and_cites_only(self):
        patched = self.decision(patch={'path': 'CLAUDE.md', 'old': 'Read [missing](missing.md).\n', 'new': ''})
        result = self.run_report('--review', patched, '--include-patches')
        result['signals'] = [dict(id='signal:%d' % n, code='stale_pointer', component_ids=['i1'],
                                  evidence_refs=['document:1', 'document:6', 'inventory:e1', 'document:2'], detail='x')
                             for n in range(5)]
        result['evidence'].append(dict(schema_version='1.0', id='analysis:uncited', kind='session', locator='x', sha256='0' * 64))
        agent = compact(result, limit=2)
        self.assertEqual('agent_report', agent['kind'])
        self.assertEqual(5, agent['signals']['stale_pointer']['count'])
        self.assertEqual(2, len(agent['signals']['stale_pointer']['listed']))
        self.assertEqual((4, 3), (agent['signals']['stale_pointer']['listed'][0]['evidence_ref_count'],
                                  len(agent['signals']['stale_pointer']['listed'][0]['evidence_refs'])))
        ids = {r['id'] for r in agent['evidence']}
        self.assertNotIn('analysis:uncited', ids)
        self.assertTrue(set(agent['findings'][0]['evidence_refs']) <= ids)
        self.assertEqual(len(result['evidence']), agent['evidence_total'])
        self.assertEqual(result['changes'][0]['change_sha256'], agent['findings'][0]['change_sha256'])
        self.assertEqual(sum(g['count'] for g in agent['coverage']), len(result['coverage']))
        self.assertIsNone(agent['accounting']['total_savings'])
        # The summary can never stand in for the full report that approvals bind to.
        import report as report_module
        with self.assertRaises(ValueError):
            report_module.validate(agent, SCHEMA['$defs']['report'], SCHEMA['$defs'])

    def test_human_report_is_prose_without_codes(self):
        empty = human(self.run_report())
        self.assertIn('No recommendations yet', empty)
        self.assertIn('Nothing has been changed', empty)
        patched = self.decision(patch={'path': 'CLAUDE.md', 'old': 'Read [missing](missing.md).\n', 'new': ''})
        text = human(self.run_report('--review', patched, '--include-patches'))
        self.assertIn('### 1. Shorten `CLAUDE.md`', text)
        self.assertIn('**How sure we are:** medium', text)
        self.assertIn('```diff', text)
        self.assertIn('not tokens or cost', text)
        self.assertNotIn('0 things', text)
        self.assertIn('listed in the full report', text)
        for jargon in ('finding:', 'inventory:', 'document:', 'i1', '| --- |', 'gap_refs', 'no_usage_evidence', '_'):
            self.assertNotIn(jargon, text.split('```diff')[0], jargon)
        kept = human(self.run_report('--review', self.decision(action='keep', protected=True)))
        self.assertIn('**1 thing kept on purpose**, because the project needs it.', kept)
        self.assertIn('(must stay)', kept)
        self.assertIn('nothing to approve', kept)

    def test_refusals_name_the_input_and_the_fix(self):
        def refused(*extra):
            with self.assertRaises(ValueError) as caught:
                self.run_report(*extra)
            return str(caught.exception)
        message = refused('--max-input-bytes', '10')
        self.assertIn('--inventory ' + str(self.inventory), message)
        self.assertIn('over --max-input-bytes (10)', message)
        self.assertRegex(message, r'is \d+ bytes')
        path = self.base / 'review.json'
        path.write_text(json.dumps(dict(schema_version='1.0', decisions=[dict(component_ids=['i1'])])))
        message = refused('--review', str(path))
        self.assertIn('--review ' + str(path), message)
        self.assertIn('$.decisions[0]', message)
        self.assertIn('missing key action', message)
        message = refused('--review', self.decision(evidence_refs=['document:1']))
        self.assertIn('decision 1 (decisions[0], components i1)', message)
        self.assertIn('add one of: document:6', message)
        message = refused('--review', self.decision(patch={'path': 'architecture.md', 'old': 'Recovery', 'new': 'R'}),
                          '--include-patches')
        self.assertIn('passed only as --architecture; pass it as --context too', message)
        message = refused('--review', self.decision(patch={'path': 'guide.md', 'old': 'Keep', 'new': 'K'}),
                          '--include-patches')
        self.assertIn('add document:2 to its evidence_refs', message)
        message = refused('--review', self.decision(patch={'path': 'CLAUDE.md', 'old': 'x', 'new': 'y'}))
        self.assertIn('pass --include-patches', message)

    def test_missing_text_and_overlapping_tool_configuration(self):
        with self.assertRaises(ValueError):
            self.run_report('--review', self.decision(rationale=' '))
        values = copy.deepcopy(self.inv)
        prototype = copy.deepcopy(values['items'][0])
        for number in range(2):
            item = copy.deepcopy(prototype)
            item.update(id='server:' + str(number), kind='mcp', origin='project:config:' + str(number),
                        bytes=0, metadata={'name': 'same-tool', 'enabled': 'unknown'})
            values['items'].append(item)
        self.inventory.write_text(json.dumps(values))
        result = self.run_report()
        self.assertIn('overlapping_configuration', {s['code'] for s in result['signals']})

    def test_patch_without_final_newline_is_a_reviewable_unified_diff(self):
        self.put('CLAUDE.md', 'old text')
        args = mod.parser().parse_args(['inventory', '--project', str(self.project), '--runtime', 'claude', '--runtime-version', '2.1.285'])
        self.inv = mod.Inventory(args).run()
        self.inventory.write_text(json.dumps(self.inv))
        review = self.decision(patch={'path': 'CLAUDE.md', 'old': 'old text', 'new': 'new text'})
        result = self.run_report('--review', review, '--include-patches')
        diff = result['findings'][0]['proposed_patch']
        self.assertIn('-old text\n\\ No newline at end of file\n+new text\n', diff)
        self.assertEqual('old text', (self.project / 'CLAUDE.md').read_text())

    def test_relocated_cli_read_only_and_no_mutation_commands(self):
        dest = self.base / 'copied'
        shutil.copytree(PACKAGE, dest)
        def snapshot():
            return {str(p.relative_to(self.base)): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.base.rglob('*') if p.is_file()}
        argv = ['--project', str(self.project), '--inventory', str(self.inventory), '--context', 'CLAUDE.md', '--architecture', 'architecture.md']
        before = snapshot()
        command = [sys.executable, '-B', '-I', str(dest / 'inventory.py')]
        result = subprocess.run(command + ['report', *argv], cwd='/', capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        validate(json.loads(result.stdout), SCHEMA['$defs']['report'])
        for fmt, check in (('agent', lambda out: json.loads(out)['kind'] == 'agent_report'),
                           ('human', lambda out: out.startswith('# What cut-the-fluff found'))):
            out = subprocess.run(command + ['report', *argv, '--format', fmt], cwd='/', capture_output=True, text=True, timeout=10)
            self.assertEqual(0, out.returncode, out.stderr)
            self.assertTrue(check(out.stdout), fmt)
        self.assertEqual(before, snapshot())
        for name in ('apply',):
            result = subprocess.run(command + [name], capture_output=True, text=True, timeout=10)
            self.assertEqual(2, result.returncode)
        result = subprocess.run(command + ['report', *argv, '--max-total-bytes', '1'], capture_output=True, text=True, timeout=10)
        self.assertEqual(2, result.returncode)
        self.assertEqual('', result.stdout)
        # Refusals name the failed check so an agent can correct its review input.
        uncited = self.base / 'uncited.json'
        uncited.write_text(json.dumps(dict(schema_version='1.0', decisions=[dict(
            component_ids=['i1'], action='trim', evidence_refs=['document:1'], confidence='low',
            rationale='r', discovery_impact='d', need='n', protected=False)])))
        result = subprocess.run(command + ['report', *argv, '--review', str(uncited)], capture_output=True, text=True, timeout=10)
        self.assertEqual(2, result.returncode)
        self.assertIn('architectural citation required', result.stderr)


if __name__ == '__main__':
    unittest.main()
