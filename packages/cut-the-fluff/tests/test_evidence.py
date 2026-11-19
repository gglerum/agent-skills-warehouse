"""Synthetic scoped transcript tests; no real evidence or agent execution."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
import inventory
from evidence import Analysis
from test_inventory import validate, SCHEMA

TIME = '2026-11-10T12:00:00Z'


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.other = self.root / 'other'
        self.other.mkdir()

    def put(self, name, rows):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        return path

    def claude(self, sid='session-full-identifier', cwd=None, tool='Read', call='call-full-id',
               args=None, error=False):
        common = dict(sessionId=sid, cwd=str(cwd or self.project), timestamp=TIME)
        return [dict(common, type='assistant', uuid=sid+'-event-call', message=dict(content=[
                    dict(type='tool_use', id=call, name=tool, input=args or dict(file_path='AGENTS.md'))])),
                dict(common, type='user', uuid=sid+'-event-result', message=dict(content=[
                    dict(type='tool_result', tool_use_id=call, is_error=error, content='SECRET-RESULT')])),
                dict(common, type='assistant', uuid=sid+'-event-end', message=dict(
                    content='SECRET-TRANSCRIPT', stop_reason='end_turn'))]

    def codex(self, sid='codex-full-id', cwd=None):
        def row(kind, payload):
            return dict(type=kind, payload=payload, timestamp=TIME)
        return [row('session_meta', dict(id=sid, cwd=str(cwd or self.project))),
                row('response_item', dict(type='function_call', name='exec_command', call_id='call-full-id',
                                         arguments=json.dumps(dict(cmd='cat AGENTS.md')))),
                row('response_item', dict(type='function_call_output', call_id='call-full-id',
                                         output=dict(exit_code=0))),
                row('event_msg', dict(type='task_complete'))]

    def run_analysis(self, *extra, runtime='claude'):
        args = inventory.parser().parse_args(['analyze', '--project', str(self.project),
                                              '--runtime', runtime, *map(str, extra)])
        with patch('os.system', side_effect=AssertionError('execution')), patch(
                'subprocess.Popen', side_effect=AssertionError('execution')):
            result = Analysis(args).run()
        validate(result, SCHEMA['$defs']['analysis'])
        refs = {e['id'] for e in result['evidence']}
        self.assertEqual(len(refs), len(result['evidence']))
        for obs in result['observations']:
            self.assertTrue(set(obs['evidence_refs']) <= refs)
        self.assertEqual([], result['findings'])
        rendered = json.dumps(result)
        for secret in ('SECRET-RESULT', 'SECRET-TRANSCRIPT', 'api_key=SECRET', str(self.project)):
            self.assertNotIn(secret, rendered)
        return result

    @staticmethod
    def gaps(result):
        return {g['code'] for g in result['coverage']}

    @staticmethod
    def metric(result, component):
        return next(m for m in result['metrics'] if m['component_id'] == component)

    def test_claude_traceable_reads_and_success(self):
        path = self.put('claude.jsonl', self.claude())
        result = self.run_analysis('--evidence', path)
        self.assertEqual(1, result['totals']['covered_sessions'])
        m = self.metric(result, 'file:project:AGENTS.md')
        self.assertEqual((1, 1, 0), (m['reads'], m['successes'], m['failures']))
        self.assertEqual('2026-11-10T12:00:00+00:00', m['last_observed_use'])
        self.assertTrue(any(o['state'] == 'loaded' for o in result['observations']))
        self.assertIn('session-full-identifier-event-call', {o['event_id'] for o in result['observations']})
        self.assertIn('retention_unknown', self.gaps(result))

    def test_codex_shell_reads_remain_inference(self):
        path = self.put('codex.jsonl', self.codex())
        result = self.run_analysis('--evidence', path, runtime='codex')
        m = self.metric(result, 'file:project:AGENTS.md')
        self.assertEqual(['inference'], m['basis'])
        self.assertIsNone(m['last_observed_use'])
        self.assertFalse(any(o['state'] == 'loaded' for o in result['observations']))
        self.assertEqual(1, self.metric(result, 'tool:exec_command')['successes'])

    def test_codex_real_metadata_and_usage_mirrors(self):
        rows = self.codex()
        def row(kind, payload):
            return dict(type=kind, payload=payload, timestamp=TIME)
        usage = dict(input_tokens=120, cached_input_tokens=20, output_tokens=10)
        rows[1:1] = [
            row('world_state', dict(full=True, state=dict(agents_md='SECRET-TRANSCRIPT'))),
            row('event_msg', dict(type='thread_settings_applied', thread_settings=dict(model='synthetic'))),
            row('token_usage_record', dict(usage=usage, turn_token_usage=usage, thread_token_usage=usage)),
            row('event_msg', dict(type='token_count', info=dict(last_token_usage=usage)))]
        result = self.run_analysis('--evidence', self.put('codex-real-shapes.jsonl', rows), runtime='codex')
        self.assertEqual(1, result['totals']['covered_sessions'])
        telemetry = [o for o in result['observations'] if o['access'] == 'telemetry']
        self.assertEqual([usage], [o['measurements'] for o in telemetry])
        self.assertIn('ignored_usage_summary', self.gaps(result))
        self.assertIn('ignored_bookkeeping_record', self.gaps(result))

    def test_codex_usage_mirrors_require_same_file_session_and_multiplicity(self):
        usage = dict(input_tokens=120, output_tokens=10)
        mirror = dict(type='token_usage_record', payload=dict(usage=usage), timestamp=TIME)
        canonical = dict(type='event_msg', payload=dict(type='token_count', info=dict(last_token_usage=usage)), timestamp=TIME)
        cases = [
            [self.codex() + [mirror]],
            [self.codex() + [mirror, mirror, canonical]],
            [self.codex() + [mirror], self.codex()[:1] + [canonical]],
            [self.codex() + [mirror] + self.codex('other-session') + [canonical]],
        ]
        for index, groups in enumerate(cases):
            with self.subTest(case=index):
                extra = []
                for n, rows in enumerate(groups):
                    extra += ['--evidence', self.put(f'usage-{index}-{n}.jsonl', rows)]
                result = self.run_analysis(*extra, runtime='codex')
                self.assertIn('unmatched_usage_summary', self.gaps(result))
                self.assertIn('unmatched_usage_summary', result['sessions'][0]['gaps'])

    def test_codex_real_text_blocks_and_native_file_changes_stay_partial(self):
        rows = self.codex()
        rows[1]['payload'].update(type='custom_tool_call', name='apply_patch', input='SECRET-TRANSCRIPT')
        rows[1]['payload'].pop('arguments')
        rows[2]['payload'].update(type='custom_tool_call_output', output=[dict(type='input_text', text='SECRET-RESULT')])
        rows.insert(3, dict(type='event_msg', timestamp=TIME, payload=dict(type='item_completed',
                         item=dict(type='FileChange', id='native-item', status='completed', changes=[], stdout='SECRET-RESULT'))))
        result = self.run_analysis('--evidence', self.put('codex-text-blocks.jsonl', rows), runtime='codex')
        metric = self.metric(result, 'tool:apply_patch')
        self.assertEqual((1, 0, 1), (metric['invocations'], metric['successes'], metric['unknown_results']))
        self.assertTrue({'unknown_tool_outcome', 'unsupported_native_tool'} <= self.gaps(result))
        self.assertEqual(0, result['totals']['covered_sessions'])

    def test_codex_unknown_metadata_shapes_are_not_ignored(self):
        rows = self.codex()
        rows += [dict(type='world_state', payload=dict(state={}, tool_calls=[]), timestamp=TIME),
                 dict(type='token_usage_record', payload=dict(usage={}), timestamp=TIME),
                 dict(type='event_msg', payload=dict(type='thread_settings_applied'), timestamp=TIME)]
        result = self.run_analysis('--evidence', self.put('codex-unknown-metadata.jsonl', rows), runtime='codex')
        self.assertTrue({'unsupported_record', 'missing_usage_fields', 'unsupported_event_msg'} <= self.gaps(result))
        self.assertEqual(0, result['totals']['covered_sessions'])

    def test_codex_null_usage_and_text_items_keep_coverage(self):
        rows = self.codex()
        def event(payload):
            return dict(type='event_msg', payload=payload, timestamp=TIME)
        rows[1:1] = [event(dict(type='token_count', info=None, rate_limits=dict(primary=None))),
                     event(dict(type='item_completed', item=dict(type='Reasoning', id='r'))),
                     event(dict(type='item_completed', item=dict(type='Plan', id='p')))]
        result = self.run_analysis('--evidence', self.put('codex-null-usage.jsonl', rows), runtime='codex')
        self.assertEqual(1, result['totals']['covered_sessions'])
        self.assertIn('usage_not_yet_reported', self.gaps(result))
        self.assertFalse(any(o['access'] == 'telemetry' for o in result['observations']))
        self.assertNotIn('missing_usage_fields', self.gaps(result))

    def test_codex_tool_and_unknown_items_stay_partial(self):
        for item, code in (('CommandExecution', 'unsupported_native_tool'), ('Mystery', 'unknown_native_item'),
                           ('ContextCompaction', 'compaction')):
            with self.subTest(item=item):
                rows = self.codex()
                rows.insert(1, dict(type='event_msg', timestamp=TIME,
                                    payload=dict(type='item_completed', item=dict(type=item, id='x'))))
                result = self.run_analysis('--evidence', self.put(f'codex-item-{item}.jsonl', rows), runtime='codex')
                self.assertIn(code, self.gaps(result))
                self.assertEqual(0, result['totals']['covered_sessions'])
        rows = self.codex()
        rows.insert(1, dict(type='event_msg', timestamp=TIME, payload=dict(type='token_count')))
        result = self.run_analysis('--evidence', self.put('codex-no-info.jsonl', rows), runtime='codex')
        self.assertIn('missing_usage_fields', self.gaps(result))

    def test_deduplicate_archives_resume_and_duplicate_path(self):
        rows = self.claude()
        active = self.put('active.jsonl', rows)
        archived = self.put('archive.jsonl', rows)
        result = self.run_analysis('--evidence', active, '--evidence', archived, '--evidence', active)
        self.assertEqual(3, result['totals']['duplicate_events'])
        self.assertEqual(1, self.metric(result, 'tool:Read')['invocations'])
        self.assertEqual(1, result['totals']['selected_sessions'])

    def test_duplicate_call_with_changed_content_is_conflict(self):
        rows = self.claude()
        rows += self.claude(args=dict(file_path='different'))
        result = self.run_analysis('--evidence', self.put('conflict.jsonl', rows))
        self.assertIn('event_identity_conflict', self.gaps(result))
        self.assertEqual(0, result['totals']['covered_sessions'])

    def test_cross_project_and_similar_prefix_excluded(self):
        prefix = self.root / 'project-other'
        prefix.mkdir()
        rows = self.claude() + self.claude('outside', self.other, tool='SECRET-TOOL')
        rows += self.claude('prefix', prefix, tool='SECRET-TOOL')
        result = self.run_analysis('--evidence', self.put('shared.jsonl', rows))
        self.assertEqual(['session-full-identifier'], [s['id'] for s in result['sessions']])
        self.assertNotIn('SECRET-TOOL', json.dumps(result))

    def test_worktree_and_subagent_linkage(self):
        rows = self.claude('parent')
        rows += self.claude('worktree', self.other)
        child = self.claude('parent')
        for row in child:
            row['agentId'] = 'agent-full-identifier'
            row.pop('cwd')
        rows += child
        result = self.run_analysis('--evidence', self.put('tree.jsonl', rows), '--worktree', self.other)
        self.assertEqual(3, len(result['sessions']))
        s = next(s for s in result['sessions'] if s['parent_id'])
        self.assertEqual('parent', s['parent_id'])
        self.assertEqual('parent/agent:agent-full-identifier', s['id'])
        self.assertIn('inherited_project_identity', s['gaps'])
        self.assertIn('file:worktree:1:AGENTS.md', [m['component_id'] for m in result['metrics']])

    def test_explicit_codex_subagent_parent_and_orphan(self):
        child = self.codex('child')
        child[0]['payload'].pop('cwd')
        a = self.put('child.jsonl', child)
        b = self.put('parent.jsonl', self.codex('parent'))
        result = self.run_analysis('--evidence', a, '--evidence', b, '--subagent', 'child=parent', runtime='codex')
        self.assertEqual(2, len(result['sessions']))
        self.assertEqual('parent', next(s for s in result['sessions'] if s['id'] == 'child')['parent_id'])
        result = self.run_analysis('--evidence', a, runtime='codex')
        self.assertEqual([], result['metrics'])

    def test_compaction_unsupported_and_missing_results_are_partial(self):
        rows = self.codex()[:2]
        rows += [dict(type='compacted', payload={}, timestamp=TIME),
                 dict(type='alien', payload={}, timestamp=TIME),
                 dict(type='event_msg', payload=dict(type='token_count'), timestamp=TIME)]
        result = self.run_analysis('--evidence', self.put('partial.jsonl', rows), runtime='codex')
        self.assertTrue({'compaction', 'unsupported_record', 'missing_tool_result',
                         'missing_usage_fields', 'incomplete_transcript'} <= self.gaps(result))
        self.assertEqual(0, result['totals']['covered_sessions'])
        self.assertIsNone(result['totals']['eligible_sessions'])
        self.assertEqual(1, self.metric(result, 'tool:exec_command')['unknown_results'])

    def test_bookkeeping_records_do_not_hide_coverage(self):
        rows = self.claude()
        common = dict(sessionId='session-full-identifier', cwd=str(self.project), timestamp=TIME)
        rows[1:1] = [dict(common, type='ai-title', uuid='t1'), dict(common, type='system', subtype='turn_duration', uuid='t2'),
                     dict(common, type='attachment', uuid='t3', message=dict(content=[dict(type='tool_addition')]))]
        result = self.run_analysis('--evidence', self.put('bookkeeping.jsonl', rows))
        self.assertEqual(1, result['totals']['covered_sessions'])
        self.assertIn('ignored_bookkeeping_record', self.gaps(result))
        rows.insert(1, dict(common, type='future-kind', uuid='t4', message=dict(content=[dict(type='tool_use', id='x', name='Read')])))
        result = self.run_analysis('--evidence', self.put('hidden-tool.jsonl', rows))
        self.assertEqual(0, result['totals']['covered_sessions'])
        self.assertIn('unsupported_record', self.gaps(result))

    def test_malformed_encoding_truncation_and_limits(self):
        p = self.put('broken.jsonl', self.claude())
        with p.open('ab') as stream:
            stream.write(b'\xff\n{}\n{"broken":')
        result = self.run_analysis('--evidence', p)
        self.assertTrue({'unsupported_encoding', 'unsupported_record',
                         'oversized_or_incomplete_record'} <= self.gaps(result))
        self.assertEqual(0, result['totals']['covered_sessions'])
        result = self.run_analysis('--evidence', p, '--max-total-bytes', 80, '--max-line-bytes', 20)
        self.assertEqual([], result['metrics'])
        self.assertLessEqual(result['totals']['bytes_read'], 80)
        self.assertIn('byte_limit', self.gaps(result))

    def test_failures_do_not_become_loads(self):
        result = self.run_analysis('--evidence', self.put('failure.jsonl', self.claude(error=True)))
        self.assertEqual(1, self.metric(result, 'tool:Read')['failures'])
        self.assertFalse(any(o['state'] == 'loaded' for o in result['observations']))

    def test_repeated_reads_aliases_skill_and_task_denominator(self):
        rows = self.claude('chosen')
        again = self.claude('chosen', call='call-2', args=dict(file_path='alias.md'))
        for row in again:
            row['uuid'] += '-2'
        rows += again + self.claude('unselected')
        rows += self.claude('chosen', tool='Skill', call='skill-call', args=dict(skill='testing'))
        result = self.run_analysis('--evidence', self.put('reads.jsonl', rows),
                                   '--alias', 'file:project:alias.md=file:project:AGENTS.md',
                                   '--relevant-session', 'chosen')
        self.assertEqual(1, result['totals']['selected_sessions'])
        self.assertEqual(1, self.metric(result, 'file:project:AGENTS.md')['repeated_reads'])
        self.assertEqual(1, self.metric(result, 'skill:testing')['invocations'])

    def test_window_unknown_time_and_results_outside_window(self):
        rows = self.claude()
        rows[1]['timestamp'] = '2026-11-11T12:00:00Z'
        rows[2].pop('timestamp')
        result = self.run_analysis('--evidence', self.put('window.jsonl', rows), '--until', '2026-11-10')
        self.assertIn('missing_timestamp', self.gaps(result))
        self.assertEqual(0, self.metric(result, 'tool:Read')['successes'])
        self.assertEqual(1, self.metric(result, 'tool:Read')['unknown_results'])

    def test_handoff_and_telemetry_cannot_manufacture_usage(self):
        common = dict(format='ctf-evidence-1', project=str(self.project), session_id='reported', timestamp=TIME,
                      component='skill:testing', content='api_key=SECRET')
        handoff = self.put('handoff.jsonl', [dict(common, kind='handoff')])
        telemetry = self.put('telemetry.jsonl', [dict(common, kind='telemetry')])
        result = self.run_analysis('--handoff', handoff, '--telemetry', telemetry)
        self.assertEqual([], result['metrics'])
        self.assertEqual({'reported', 'direct'}, {o['basis'] for o in result['observations']})
        self.assertTrue(all(o['state'] == 'unknown' for o in result['observations']))
        self.assertEqual(0, result['totals']['covered_sessions'])

    def test_discovery_scopes_symlinks_and_missing_stores(self):
        p = self.put('config/projects/key/session.jsonl', self.claude())
        outside = self.put('private.jsonl', self.claude('secret'))
        (p.parent / 'link.jsonl').symlink_to(outside)
        result = self.run_analysis('--discover', '--config-home', self.root / 'config')
        self.assertEqual(1, len(result['sessions']))
        self.assertIn('symlink_evidence', self.gaps(result))
        result = self.run_analysis('--store', self.root / 'missing')
        self.assertIn('missing_or_symlink_store', self.gaps(result))
        self.assertIn('no_evidence', self.gaps(result))

    def test_streaming_large_file_and_event_limit(self):
        rows = self.codex()
        rows[1:1] = [dict(type='response_item', timestamp=TIME,
                          payload=dict(type='message', content='x'*3000))] * 1000
        p = self.put('large.jsonl', rows)
        result = self.run_analysis('--evidence', p, runtime='codex')
        self.assertGreater(result['totals']['bytes_read'], 3000000)
        self.assertEqual(1, self.metric(result, 'tool:exec_command')['invocations'])
        self.assertLess(len(json.dumps(result)), 12000)
        result = self.run_analysis('--evidence', p, '--max-events', 1, runtime='codex')
        self.assertIn('event_limit', self.gaps(result))

    def test_nonregular_missing_and_no_evidence(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        result = self.run_analysis('--evidence', fifo, '--evidence', self.root / 'missing')
        self.assertTrue({'nonregular_evidence', 'inaccessible_evidence'} <= self.gaps(result))
        self.assertEqual([], result['metrics'])
        self.assertIn('no_evidence', self.gaps(self.run_analysis()))

    def test_bad_arguments_and_cycles(self):
        for extra in [('--discover',), ('--max-files', '0'), ('--low-use-threshold', '2'),
                      ('--alias', 'a=b', '--alias', 'b=a'), ('--since', '2026-11-11', '--until', '2026-11-10')]:
            args = inventory.parser().parse_args(['analyze', '--project', str(self.project), '--runtime', 'claude', *extra])
            with self.assertRaises(ValueError):
                Analysis(args)

    def test_invalid_call_ids_version_and_parent_cycles(self):
        rows = self.codex()
        rows[1]['payload']['call_id'] = ['malformed']
        rows.append(dict(type='future', schema_version='9000', payload={}, timestamp=TIME))
        result = self.run_analysis('--evidence', self.put('invalid-id.jsonl', rows), runtime='codex')
        self.assertTrue({'missing_call_identity', 'unsupported_format_version', 'orphan_tool_result'} <= self.gaps(result))
        self.assertEqual([], result['metrics'])
        rows = self.claude('a') + self.claude('b')
        result = self.run_analysis('--evidence', self.put('cycle.jsonl', rows),
                                   '--subagent', 'a=b', '--subagent', 'b=a')
        self.assertIn('parent_cycle', self.gaps(result))
        self.assertEqual(0, result['totals']['covered_sessions'])

    def test_telemetry_measurements_and_reported_load(self):
        common = dict(format='ctf-evidence-1', project=str(self.project), session_id='reported', timestamp=TIME,
                      component='runtime:usage')
        handoff = self.put('claim.jsonl', [dict(common, kind='handoff', state='loaded')])
        telemetry = self.put('measure.jsonl', [dict(common, kind='telemetry', measurements=dict(
            input_tokens=200, output_tokens=10, api_key='SECRET', duration_ms=-1))])
        result = self.run_analysis('--handoff', handoff, '--telemetry', telemetry)
        claim = next(o for o in result['observations'] if o['access'] == 'handoff')
        self.assertEqual(('loaded', 'reported'), (claim['state'], claim['basis']))
        measured = next(o for o in result['observations'] if o['access'] == 'telemetry')
        self.assertEqual(dict(input_tokens=200, output_tokens=10), measured['measurements'])
        self.assertEqual([], result['metrics'])

    def test_failed_read_not_confirmed_and_opaque_codex_result(self):
        result = self.run_analysis('--evidence', self.put('failed-read.jsonl', self.claude(error=True)))
        m = self.metric(result, 'file:project:AGENTS.md')
        self.assertEqual((1, 0, 0), (m['read_attempts'], m['reads'], m['repeated_reads']))
        rows = self.codex()
        rows[2]['payload']['output'] = 'opaque runtime output'
        result = self.run_analysis('--evidence', self.put('opaque.jsonl', rows), runtime='codex')
        self.assertEqual(1, self.metric(result, 'tool:exec_command')['unknown_results'])
        self.assertEqual(0, self.metric(result, 'tool:exec_command')['successes'])

    def test_static_shell_commands_resolve_without_execution(self):
        command = ("cd docs && sed -n '1,20p' guide.md | head -5 2>/dev/null; (cd .. && cat AGENTS.md)\n"
                   "git commit -m \"$(cat <<'EOF'\nnote (don't) $HOME\nEOF\n)\" && touch NEVER_RUN")
        rows = self.claude(tool='Bash', args=dict(command=command))
        result = self.run_analysis('--evidence', self.put('shell.jsonl', rows))
        self.assertNotIn('unresolved_shell_access', self.gaps(result))
        self.assertEqual((1, 1), (result['totals']['covered_sessions'], result['totals']['file_read_covered_sessions']))
        self.assertEqual(1, self.metric(result, 'file:project:docs/guide.md')['inferred_reads'])
        self.assertEqual(1, self.metric(result, 'file:project:AGENTS.md')['inferred_reads'])
        self.assertFalse((self.project / 'NEVER_RUN').exists())

    def test_dynamic_shell_qualifies_only_file_reads(self):
        rows = self.claude(call='call-read')[:2]
        rows += self.claude(tool='Bash', call='call-shell', args=dict(command='cat "$F" ~/x; touch NEVER_RUN'))
        result = self.run_analysis('--evidence', self.put('shell.jsonl', rows))
        self.assertIn('unresolved_shell_access', self.gaps(result))
        session = result['sessions'][0]
        self.assertEqual(('covered', True), (session['status'], session['file_reads_partial']))
        self.assertEqual((1, 0), (result['totals']['covered_sessions'], result['totals']['file_read_covered_sessions']))
        self.assertEqual(1, self.metric(result, 'tool:Bash')['covered_sessions'])
        self.assertEqual(0, self.metric(result, 'file:project:AGENTS.md')['covered_sessions'])
        self.assertFalse((self.project / 'NEVER_RUN').exists())

    def test_shell_parser_cases(self):
        import shell
        cases = {'cat a; touch x': ['/p/a'], 'cd /q && cat a b | head -5': ['/q/a', '/q/b'],
                 '(cd sub && cat x) && cat y': ['/p/sub/x', '/p/y'], 'sed -i s/a/b/ f': [],
                 'head -n 40 f || tail -20 g': ['/p/f', '/p/g'], 'cat < in': ['/p/in'],
                 'cat <<EOF > out\n$x\nEOF\ncat z': ['/p/z'], 'echo $(cat k)': ['/p/k'],
                 'bash -lc "cat q"': ['/p/q'], '[ -f a ] && cat a': ['/p/a'], 'ls | wc -l': [],
                 'nl -ba f | sed -n 1,5p': ['/p/f'], 'cat a # cat b': ['/p/a'], 'head --lines=3 f': ['/p/f'],
                 'cd $D && ls': [], 'cat -n -- -w': ['/p/-w'], 'sed -e p -n f': ['/p/f'],
                 'for f in a b; do cat "$f"; done': ['/p/a', '/p/b'],
                 'for d in x y; do for f in 1 2; do head "$d/$f.md"; done; done':
                     ['/p/x/1.md', '/p/x/2.md', '/p/y/1.md', '/p/y/2.md'],
                 'for f in a; do\n  cd /q\n  cat ${f}\ndone': ['/q/a']}
        for command, paths in cases.items():
            self.assertEqual(([(p, 'read') for p in paths], None), shell.file_accesses(command, '/p'), command)
        searches = {'rg -n foo src | head': ['/p/src'], 'rg foo': [], 'grep -e a -e b f': ['/p/f'],
                    'grep -rn --include=*.md x docs R.md': ['/p/docs', '/p/R.md'], 'grep -A 3 x f': ['/p/f'],
                    'rg -g "*.py" -t py def lib': ['/p/lib'], 'rg --files src': []}
        for command, paths in searches.items():
            self.assertEqual(([(p, 'search') for p in paths], None), shell.file_accesses(command, '/p'), command)
        for command in ('cat $F', 'cat *.md', 'cat {a,b}', 'eval "cat a"', 'find . | xargs cat',
                        'ls | xargs grep x', 'cd "$D" && cat a', 'for f in *.md; do cat "$f"; done',
                        'for f in a; do :; done; cat "$f"', 'while read f; do cat "$f"; done < l',
                        'for f in a; do while read g; do cat "$f"; done; cat "$g"; done', 'cat "$f"*',
                        'cat "open', 'find . -exec grep x {} +', 'cat ~bob/x', 'cat $HOMEDIR/x'):
            self.assertIsNotNone(shell.file_accesses(command, '/p', '/h')[1], command)
        self.assertEqual(([], 'unknown_cwd'), shell.file_accesses('cat a', None))
        self.assertEqual(([], 'unknown_home'), shell.file_accesses('cat ~/x', '/p'))
        home = {'cat ~/x "$HOME/y" ${HOME}/z': ['/h/x', '/h/y', '/h/z'], 'cd ~/q && cat a': ['/h/q/a'],
                'cd && cat a': ['/h/a']}
        for command, paths in home.items():
            self.assertEqual(([(p, 'read') for p in paths], None), shell.file_accesses(command, '/p', '/h'), command)

    def test_searches_and_home_resolution(self):
        home = self.root / 'home'
        self.project = home / 'project'
        self.project.mkdir(parents=True)
        rows = self.claude(tool='Bash', call='call-1', args=dict(
            command='rg -n TODO docs; cat ~/project/AGENTS.md'))[:2]
        rows += self.claude(call='call-2', args=dict(file_path='~/project/AGENTS.md'))
        evidence = self.put('home.jsonl', rows)
        result = self.run_analysis('--evidence', evidence)
        self.assertIn('unresolved_shell_access', self.gaps(result))
        self.assertIn('unresolved_file_access', self.gaps(result))
        m = self.metric(result, 'file:project:docs')
        self.assertEqual((1, 0, 0), (m['searches'], m['read_attempts'], m['inferred_reads']))
        result = self.run_analysis('--evidence', evidence, '--home', home)
        self.assertNotIn('unresolved_shell_access', self.gaps(result))
        self.assertFalse(result['sessions'][0]['file_reads_partial'])
        m = self.metric(result, 'file:project:AGENTS.md')
        self.assertEqual((2, 1, 1), (m['read_attempts'], m['inferred_reads'], m['reads']))
        with self.assertRaises(ValueError):
            self.run_analysis('--evidence', evidence, '--home', 'relative')

    def test_globs_match_current_tree_only_when_asked(self):
        for name in ('docs/a.md', 'docs/b.md', 'docs/c.txt'):
            (self.project / name).parent.mkdir(exist_ok=True)
            (self.project / name).write_text('x')
        outside = self.other / 'secret.md'
        outside.write_text('x')
        command = 'cat docs/*.md; for f in docs/*.txt; do head "$f"; done'
        rows = self.claude(tool='Bash', args=dict(command=command))
        evidence = self.put('glob.jsonl', rows)
        result = self.run_analysis('--evidence', evidence)
        self.assertIn('unresolved_shell_access', self.gaps(result))
        self.assertNotIn('file:project:docs/a.md', {m['component_id'] for m in result['metrics']})
        result = self.run_analysis('--evidence', evidence, '--expand-globs')
        self.assertNotIn('unresolved_shell_access', self.gaps(result))
        self.assertIn('glob_matched_current_tree', self.gaps(result))
        self.assertEqual(('covered', False), (result['sessions'][0]['status'], result['sessions'][0]['file_reads_partial']))
        for name in ('docs/a.md', 'docs/b.md', 'docs/c.txt'):
            self.assertEqual(['inference'], self.metric(result, 'file:project:' + name)['basis'])
        # No match today, an ambiguous quoted wildcard, or a parent-rooted pattern stay unresolved.
        for command in ('cat docs/*.rst', 'cat "d*"/*.md', 'cat ' + str(self.root) + '/*/AGENTS.md'):
            rows = self.claude(tool='Bash', args=dict(command=command))
            result = self.run_analysis('--evidence', self.put('glob2.jsonl', rows), '--expand-globs')
            self.assertIn('unresolved_shell_access', self.gaps(result), command)
        # A pattern rooted outside the project cannot match project files; it is never listed.
        rows = self.claude(tool='Bash', args=dict(command='cat ' + str(self.other) + '/*.md'))
        with patch('glob.iglob', side_effect=AssertionError('listed')):
            result = self.run_analysis('--evidence', self.put('glob3.jsonl', rows))
        self.assertEqual({'external_glob_not_listed', 'retention_unknown'}, self.gaps(result))
        self.assertFalse(result['sessions'][0]['file_reads_partial'])

    def test_shell_uses_each_record_cwd_and_codex_argv(self):
        rows = self.claude(tool='Bash', call='call-1', args=dict(command='cat x'))[:2]
        rows += self.claude(cwd=self.project / 'sub', tool='Bash', call='call-2', args=dict(command='cat x'))
        result = self.run_analysis('--evidence', self.put('cwd.jsonl', rows))
        self.assertEqual(1, self.metric(result, 'file:project:x')['inferred_reads'])
        self.assertEqual(1, self.metric(result, 'file:project:sub/x')['inferred_reads'])
        rows = self.codex()
        rows[1]['payload']['arguments'] = json.dumps(dict(cmd=['bash', '-lc', 'cat AGENTS.md']))
        result = self.run_analysis('--evidence', self.put('argv.jsonl', rows), runtime='codex')
        self.assertEqual(1, self.metric(result, 'file:project:AGENTS.md')['inferred_reads'])
        self.assertNotIn('unresolved_shell_access', self.gaps(result))

    def test_request_copies_are_checked_against_the_conversation(self):
        def blob(*ids):
            return dict(type='api-request-blob', sessionId='session-full-identifier', hash='h', message=dict(
                role='user', content=[dict(type='text', text='SECRET-TRANSCRIPT')] +
                [dict(type='tool_result', tool_use_id=i, content='SECRET-RESULT') for i in ids]))
        rows = [blob('call-full-id')] + self.claude()
        path = self.put('copy.jsonl', rows)
        result = self.run_analysis('--evidence', path, '--evidence', self.put('archive.jsonl', rows))
        self.assertIn('ignored_request_copy', self.gaps(result))
        self.assertNotIn('unmatched_request_copy', self.gaps(result))
        self.assertEqual(1, result['totals']['covered_sessions'])
        result = self.run_analysis('--evidence', self.put('extra.jsonl', self.claude() + [blob('call-elsewhere')]))
        self.assertIn('unmatched_request_copy', result['sessions'][0]['gaps'])
        self.assertEqual(0, result['totals']['covered_sessions'])

    def test_caps_warn_on_stderr_and_gaps_name_sessions(self):
        first = self.put('first.jsonl', self.claude(sid='session-one'))
        second = self.put('second.jsonl', self.claude(sid='session-two')[:2])  # no completion marker
        command = [sys.executable, '-I', '-B', str(PACKAGE / 'inventory.py'), 'analyze', '--project', str(self.project),
                   '--runtime', 'claude', '--evidence', str(first), '--evidence', str(second)]
        proc = subprocess.run(command + ['--session-limit', '1'], capture_output=True, text=True, timeout=10)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn('WARNING: session_limit hit 1 time(s); output is partial. Raise --session-limit.', proc.stderr)
        proc = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual('', proc.stderr)
        gap = next(g for g in json.loads(proc.stdout)['coverage'] if g['code'] == 'incomplete_transcript')
        self.assertEqual('session:session-two', gap['locator'])
        self.assertIn('completion marker', gap['detail'])
        # --help prints each limit's default.
        proc = subprocess.run([sys.executable, '-I', '-B', str(PACKAGE / 'inventory.py'), 'analyze', '--help'],
                              capture_output=True, text=True, timeout=10, env=dict(os.environ, COLUMNS='200'))
        for line in ('--session-limit SESSION_LIMIT', '--max-total-bytes MAX_TOTAL_BYTES', '--max-files MAX_FILES'):
            self.assertRegex(proc.stdout, re.escape(line) + r'\s+[^\n]*\(default: \d+')

    def test_relocation_readonly_and_cli(self):
        copy = self.root / 'copied'
        shutil.copytree(PACKAGE, copy)
        evidence = self.put('session.jsonl', self.claude())
        def snapshot():
            return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.root.rglob('*') if p.is_file()}
        before = snapshot()
        proc = subprocess.run([sys.executable, '-I', '-B', str(copy / 'inventory.py'), 'analyze',
                               '--project', str(self.project), '--runtime', 'claude', '--evidence', str(evidence)],
                              cwd=self.other, capture_output=True, text=True, timeout=10)
        self.assertEqual(0, proc.returncode, proc.stderr)
        validate(json.loads(proc.stdout), SCHEMA['$defs']['analysis'])
        self.assertEqual(before, snapshot())
        for command in ('report', 'apply'):
            proc = subprocess.run([sys.executable, '-B', str(copy / 'inventory.py'), command],
                                  capture_output=True, timeout=10)
            self.assertEqual(2, proc.returncode)
