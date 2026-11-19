"""Synthetic inventories and process boundaries; no installed agent or private data."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
spec = importlib.util.spec_from_file_location('ctf_inventory', PACKAGE / 'inventory.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SCHEMA = json.loads((PACKAGE / 'schema.json').read_text())


def validate(value, schema):
    """Validate the small JSON Schema vocabulary used by this contract, no packages."""
    if '$ref' in schema:
        return validate(value, SCHEMA['$defs'][schema['$ref'].rsplit('/', 1)[1]])
    if 'const' in schema:
        assert value == schema['const'], (value, schema)
    if 'enum' in schema:
        assert value in schema['enum'], (value, schema)
    if 'type' in schema:
        types = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        actual = {str: 'string', int: 'integer', float: 'number', list: 'array', dict: 'object',
                  bool: 'boolean', type(None): 'null'}[type(value)]
        assert actual in types or actual == 'integer' and 'number' in types, (value, schema)
    if isinstance(value, dict):
        for key in schema.get('required', []):
            assert key in value, key
        if schema.get('additionalProperties') is False:
            assert set(value) <= set(schema['properties']), value
        for key, child in value.items():
            if key in schema.get('properties', {}):
                validate(child, schema['properties'][key])
    if isinstance(value, list):
        for item in value:
            validate(item, schema.get('items', {}))
    if type(value) in (int, float):
        assert value >= schema.get('minimum', float('-inf'))
        assert value <= schema.get('maximum', float('inf'))


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'parent/project'
        self.home = self.root / 'home'
        self.project.mkdir(parents=True)
        self.home.mkdir()

    def put(self, name, text, base=None):
        path = (base or self.project) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def skill(self, name, base=None, runtime='claude', text=''):
        return self.put(('.agents' if runtime == 'codex' else '.claude') + '/skills/' + name + '/SKILL.md',
                        '---\nname: ' + name + '\ndescription: Synthetic fixture\n---\n' + text, base)

    def run_inventory(self, runtime='claude', *extra):
        args = mod.parser().parse_args(['inventory', '--project', str(self.project), '--home', str(self.home),
                     '--runtime', runtime, '--runtime-version', mod.PROFILE if runtime == 'codex' else '2.1.285', *extra])
        with patch('subprocess.run', side_effect=AssertionError('command executed')), patch('subprocess.Popen', side_effect=AssertionError('command executed')), patch('os.system', side_effect=AssertionError('command executed')):
            result = mod.Inventory(args).run()
        validate(result, SCHEMA)
        ids = {i['id'] for i in result['items']}
        evidence = {e['id'] for e in result['evidence']}
        for i in result['items']:
            self.assertTrue(set(i['dependencies']) <= ids)
            self.assertTrue(set(i['evidence_refs']) <= evidence)
            self.assertEqual('unknown', i['states']['loaded'])
            self.assertEqual('unknown', i['states']['advertised'])
            self.assertEqual('unknown', i['states']['invoked'])
            self.assertEqual('unknown', i['states']['successful'])
        for r in result['relations']:
            self.assertIn(r['source'], ids)
            self.assertTrue(r['target'] is None or r['target'] in ids)
        self.assertEqual([], result['observations'])
        self.assertEqual([], result['findings'])
        return result

    def items(self, result, kind=None):
        return {i['origin']: i for i in result['items'] if kind is None or i['kind'] == kind}

    def gaps(self, result):
        return {g['code'] for g in result['coverage']}

    def test_codex_fixture_accounts_for_exact_expected_sources_and_precedence(self):
        self.put('.codex/AGENTS.md', 'Global', self.home)
        self.put('AGENTS.md', 'Parent outside repo', self.project.parent)
        self.put('AGENTS.md', 'Root [reference](docs/guide.md)')
        self.put('docs/guide.md', 'Conditional guide')
        self.put('src/AGENTS.override.md', 'Override')
        self.put('src/AGENTS.md', 'Suppressed')
        self.put('src/deep/AGENTS.override.md', '')
        self.put('src/deep/TEAM.md', 'Fallback')
        self.put('.codex/config.toml', 'project_doc_fallback_filenames = ["TEAM.md"]\n[mcp_servers.local]\ncommand = "touch NEVER_RUN"\n[hooks.SessionStart]\ncommand = "touch NEVER_RUN"\n')
        self.skill('root', runtime='codex')
        self.skill('user', self.home, runtime='codex')
        self.put('.codex/rules/allow.rules', 'prefix_rule(pattern=["echo"], decision="allow")')
        self.put('.codex/hooks.json', '{"hooks":{"Stop":[{"command":"touch NEVER_RUN"}]}}')
        result = self.run_inventory('codex', '--cwd', str(self.project / 'src/deep'))
        instructions = self.items(result, 'instruction')
        self.assertEqual({'config:AGENTS.md', 'project:AGENTS.md', 'project:src/AGENTS.override.md',
                          'project:src/AGENTS.md', 'project:src/deep/AGENTS.override.md', 'project:src/deep/TEAM.md'}, set(instructions))
        self.assertEqual('not_selected', instructions['project:src/AGENTS.md']['loading'])
        self.assertEqual('not_selected', instructions['project:src/deep/AGENTS.override.md']['loading'])
        self.assertEqual('startup_expected', instructions['project:src/deep/TEAM.md']['loading'])
        self.assertLess(instructions['config:AGENTS.md']['precedence'], instructions['project:AGENTS.md']['precedence'])
        self.assertLess(instructions['project:AGENTS.md']['precedence'], instructions['project:src/deep/TEAM.md']['precedence'])
        self.assertEqual('conditional', self.items(result)['project:docs/guide.md']['loading'])
        self.assertEqual(2, len(self.items(result, 'skill')))
        self.assertEqual(1, len(self.items(result, 'mcp')))
        self.assertEqual(2, len(self.items(result, 'hook')))
        self.assertNotIn('NEVER_RUN', json.dumps(result))
        self.assertIn('trust', self.gaps(result))

    def test_claude_fixture_global_parent_nested_rules_plugins_memory_and_configs(self):
        self.put('.claude/CLAUDE.md', 'Global', self.home)
        self.put('.claude/rules/personal.md', 'Personal rule', self.home)
        self.put('CLAUDE.md', 'Parent', self.project.parent)
        self.put('CLAUDE.md', '@docs/always.md\n[conditional](docs/later.md)')
        self.put('docs/always.md', 'Eager import')
        self.put('docs/later.md', 'Conditional reference')
        self.put('CLAUDE.local.md', 'Local')
        self.put('AGENTS.md', 'Not chosen')
        self.put('nested/CLAUDE.md', 'Nested')
        self.put('.claude/rules/common.md', 'Common')
        self.put('.claude/rules/api.md', '---\npaths:\n  - "src/**/*.py"\n---\nAPI')
        self.skill('project')
        self.skill('user', self.home)
        self.skill('nested', self.project / 'nested')
        self.put('.claude/commands/check.md', 'A legacy command')
        self.put('.claude/settings.json', '{"enabledPlugins":{"example@local":true},"hooks":{"Stop":[{"command":"touch NEVER_RUN"}]}}')
        self.put('.claude/settings.local.json', '{"enabledPlugins":{"example@local":false}}')
        self.put('.mcp.json', '{"mcpServers":{"fixture":{"command":"touch NEVER_RUN","env":{"API_KEY":"SECRET"}}}}')
        plugin = self.project / 'plugin'
        self.put('.claude-plugin/plugin.json', '{"name":"example","skills":["./extra-skills"],"hooks":"./extra-hooks.json"}', plugin)
        self.put('extra-skills/custom/SKILL.md', '---\nname: custom\ndescription: Fixture\n---\nCustom', plugin)
        self.put('extra-hooks.json', '{"hooks":{"Stop":[]}}', plugin)
        self.put('skills/standard/SKILL.md', '---\nname: standard\ndescription: Fixture\n---\nStandard', plugin)
        self.put('memory/MEMORY.md', '[Topic](topic.md)')
        self.put('memory/topic.md', 'Remember fixture')
        result = self.run_inventory('claude', '--boundary', str(self.project.parent), '--directory', 'nested',
                                    '--plugin', str(plugin), '--memory', str(self.project / 'memory/MEMORY.md'))
        files = self.items(result)
        expected = {'config:CLAUDE.md', 'config:rules/personal.md', 'boundary:CLAUDE.md',
                    'project:CLAUDE.md', 'project:CLAUDE.local.md', 'project:AGENTS.md',
                    'project:docs/always.md', 'project:docs/later.md', 'project:nested/CLAUDE.md',
                    'project:.claude/rules/common.md', 'project:.claude/rules/api.md',
                    'project:.claude/skills/project/SKILL.md', 'config:skills/user/SKILL.md',
                    'project:nested/.claude/skills/nested/SKILL.md', 'project:.claude/commands/check.md',
                    'project:.claude/settings.json', 'project:.claude/settings.local.json', 'project:.mcp.json',
                    'project:plugin/.claude-plugin/plugin.json', 'project:plugin/extra-skills/custom/SKILL.md',
                    'project:plugin/extra-hooks.json', 'project:plugin/skills/standard/SKILL.md',
                    'project:memory/MEMORY.md', 'project:memory/topic.md'}
        self.assertEqual(expected, {k for k, i in files.items() if '#' not in k})
        self.assertEqual('startup_expected', files['project:docs/always.md']['loading'])
        self.assertEqual('conditional', files['project:docs/later.md']['loading'])
        self.assertEqual('conditional', files['project:nested/CLAUDE.md']['loading'])
        self.assertEqual('conditional', files['project:.claude/rules/api.md']['loading'])
        self.assertEqual('not_selected', files['project:AGENTS.md']['loading'])
        self.assertEqual(2, len(self.items(result, 'plugin')))
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('NEVER_RUN', json.dumps(result))
        self.assertIn('ancestors_omitted', self.gaps(result))
        self.assertIn('host_context', self.gaps(result))

    def test_claude_agents_default_and_explicit_modes(self):
        self.put('AGENTS.md', 'Default')
        result = self.run_inventory()
        self.assertEqual('startup_expected', self.items(result)['project:AGENTS.md']['loading'])
        self.put('CLAUDE.md', 'Other')
        for mode, expected in [('claude-md', 'not_selected'), ('claude-md-and-agents-md', 'startup_expected'),
                               ('managed-only', 'not_selected')]:
            self.put('.claude/settings.json', json.dumps({'pluginConfigs': {'cc-plugin-agents-md@builtin':
                     {'options': {'instructionFiles': mode}}}}), self.home)
            result = self.run_inventory()
            self.assertEqual(expected, self.items(result)['project:AGENTS.md']['loading'])

    def test_symlink_aliases_cycles_outside_boundary_and_inaccessible_files(self):
        self.put('CLAUDE.md', '@docs/a.md\n@docs/alias.md\n@outside.md\n@private.md\n@broken.md')
        a = self.put('docs/a.md', '@b.md')
        self.put('docs/b.md', '@a.md')
        (a.parent / 'alias.md').symlink_to('a.md')
        self.put('secret.md', 'DO_NOT_READ', self.root)
        (self.project / 'outside.md').symlink_to(self.root / 'secret.md')
        private = self.put('private.md', 'PRIVATE')
        private.chmod(0)
        self.addCleanup(private.chmod, 0o600)
        (self.project / 'broken.md').symlink_to('missing.md')
        self.skill('alias')
        (self.project / '.claude/skills/also-alias').symlink_to('alias', target_is_directory=True)
        self.put('.claude/rules/one.md', 'Rule')
        (self.project / '.claude/rules/cycle').symlink_to('.', target_is_directory=True)
        result = self.run_inventory()
        self.assertTrue({'boundary', 'inaccessible', 'missing', 'import_cycle', 'directory_cycle_or_alias'} <= self.gaps(result))
        self.assertEqual(1, len(self.items(result, 'skill')))
        self.assertEqual(2, len(self.items(result)['project:docs/a.md']['aliases']))
        self.assertNotIn('DO_NOT_READ', json.dumps(result))

    def test_import_code_skips_spaces_relative_paths_and_depth_limit(self):
        self.put('CLAUDE.md', 'Inline `@missing-inline.md`\n```text\n@missing-fence.md\n```\n@Design\\ Docs/one.md\n@"quoted.md"')
        self.put('Design Docs/one.md', '@two.md')
        self.put('Design Docs/two.md', '@three.md')
        self.put('Design Docs/three.md', '@four.md')
        self.put('Design Docs/four.md', '@five.md')
        self.put('Design Docs/five.md', 'Past the runtime import limit')
        result = self.run_inventory()
        self.assertIn('project:Design Docs/one.md', self.items(result))
        self.assertNotIn('missing', self.gaps(result))
        self.assertIn('import_depth', self.gaps(result))
        self.assertNotIn('project:Design Docs/five.md', self.items(result))

    def test_bad_formats_and_version_surface_gaps(self):
        self.put('CLAUDE.md', 'Instructions')
        self.put('.claude/settings.json', '{bad')
        self.put('.mcp.json', '[]')
        self.put('.claude/rules/complex.md', '---\npaths: &anchor\n---\nUnsupported')
        self.skill('complex', text='!`touch NEVER_RUN`')
        result = self.run_inventory('claude', '--runtime-version', '0.0.1', '--surface', 'cloud')
        self.assertTrue({'configuration_format', 'frontmatter', 'dynamic_context', 'unverified_version', 'unsupported_surface'} <= self.gaps(result))
        self.assertEqual('unknown', self.items(result)['project:.claude/rules/complex.md']['loading'])

    def test_relative_explicit_paths_use_cwd_and_flag_project_relative_mistake(self):
        self.put('CLAUDE.md', 'Instructions')
        self.put('notes/rules.md', 'Project-relative rules')
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.root)
        for option in ('--instruction', '--memory', '--extra-config'):
            with self.assertRaisesRegex(ValueError, option + ' notes/rules.md not found in the current directory'):
                self.run_inventory('claude', option, 'notes/rules.md')
        # From the project folder the same relative path is the intended file.
        os.chdir(self.project)
        self.assertIn('project:notes/rules.md', self.items(self.run_inventory('claude', '--instruction', 'notes/rules.md')))
        # Absolute paths are never second-guessed.
        self.items(self.run_inventory('claude', '--instruction', str(self.project / 'notes/rules.md')))

    def test_block_scalar_description_is_supported_only_for_description(self):
        self.put('CLAUDE.md', 'Instructions')
        self.put('.claude/skills/folded/SKILL.md', '---\nname: folded\ndescription: >\n  Use when auditing\n  agent context.\n---\nBody')
        self.put('.claude/skills/other/SKILL.md', '---\nname: other\ndescription: Synthetic\nnotes: |\n  complex\n---\nBody')
        items = self.items(self.run_inventory())
        folded = items['project:.claude/skills/folded/SKILL.md']
        self.assertNotEqual('unknown', folded['loading'])
        self.assertEqual('Use when auditing agent context.', mod.frontmatter(
            '---\ndescription: >\n  Use when auditing\n  agent context.\n---\n')[0]['description'])
        self.assertEqual('unknown', items['project:.claude/skills/other/SKILL.md']['loading'])

    def test_newer_version_keeps_loading_with_warning(self):
        self.put('CLAUDE.md', 'Instructions')
        newer = self.run_inventory('claude', '--runtime-version', '2.1.322')
        item = self.items(newer)['project:CLAUDE.md']
        self.assertEqual(('startup_expected', 'low'), (item['loading'], item['confidence']))
        self.assertIn('newer_version', self.gaps(newer))
        self.assertNotIn('unverified_version', self.gaps(newer))
        older = self.run_inventory('claude', '--runtime-version', '2.1.9')
        self.assertEqual('unknown', self.items(older)['project:CLAUDE.md']['loading'])
        self.assertIn('unverified_version', self.gaps(older))
        self.put('AGENTS.md', 'Instructions')
        self.assertIn('newer_version', self.gaps(self.run_inventory('codex', '--runtime-version', 'docs-2027-01-01')))
        binary = self.run_inventory('codex', '--runtime-version', '0.50.0')
        self.assertEqual('unknown', self.items(binary)['project:AGENTS.md']['loading'])

    def test_limits_and_nonregular_files(self):
        self.put('AGENTS.md', 'x' * 100)
        result = self.run_inventory('codex', '--max-file-bytes', '20')
        self.assertIn('file_limit', self.gaps(result))
        self.put('AGENTS.md', 'Small')
        os.mkfifo(self.project / 'AGENTS.override.md')
        result = self.run_inventory('codex')
        self.assertIn('nonregular', self.gaps(result))
        self.skill('one', runtime='codex')
        result = self.run_inventory('codex', '--max-items', '1')
        self.assertTrue({'item_limit', 'directory_limit'} & self.gaps(result))
        result = self.run_inventory('codex', '--max-total-bytes', '1')
        self.assertIn('total_limit', self.gaps(result))

    def test_codex_budget_and_unsafe_fallback_names(self):
        self.put('AGENTS.md', 'x' * 100)
        self.put('.codex/config.toml', 'project_doc_max_bytes = 20\nproject_doc_fallback_filenames = ["../escape.md"]')
        result = self.run_inventory('codex')
        self.assertTrue({'instruction_budget', 'configuration_shape'} <= self.gaps(result))
        self.assertEqual('unknown', self.items(result)['project:AGENTS.md']['loading'])

    def test_no_implicit_home_or_cross_project_mcp_access(self):
        self.put('CLAUDE.md', 'Fixture')
        self.put('.claude.json', json.dumps({'mcpServers': {'user': {}}, 'projects': {
            str(self.project): {'mcpServers': {'selected': {}}}, '/other/project': {'mcpServers': {'PRIVATE_OTHER': {}}}}}), self.home)
        result = self.run_inventory()
        self.assertEqual(2, len(self.items(result, 'mcp')))
        self.assertNotIn('PRIVATE_OTHER', json.dumps(result))
        args = mod.parser().parse_args(['inventory', '--project', str(self.project), '--runtime', 'claude', '--runtime-version', '2.1.285'])
        result = mod.Inventory(args).run()
        self.assertIn('home_omitted', self.gaps(result))
        self.assertEqual(0, len(self.items(result, 'mcp')))

    def test_read_only_cli_relocation_no_command_execution_and_no_extra_commands(self):
        self.put('CLAUDE.md', 'Instructions !`touch NEVER_RUN`')
        self.put('.claude/settings.json', '{"hooks":{"Stop":[{"command":"touch NEVER_RUN"}]}}')
        relocated = self.root / 'relocated'
        shutil.copytree(PACKAGE, relocated)
        before = {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob('*') if p.is_file()}
        env = {**os.environ, 'HOME': str(self.home)}
        command = [sys.executable, '-B', '-I', str(relocated / 'inventory.py'), 'inventory', '--project', str(self.project), '--runtime', 'claude', '--runtime-version', '2.1.285']
        run = subprocess.run(command, cwd=self.root, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(0, run.returncode, run.stderr)
        validate(json.loads(run.stdout), SCHEMA)
        after = {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        for name in ('apply', 'verify'):
            run = subprocess.run(command[:5] + [name], capture_output=True, timeout=10)
            self.assertEqual(2, run.returncode)

    def test_suppressed_import_trees_and_nested_agents_are_not_eager(self):
        self.put('CLAUDE.md', 'Main guidance')
        self.put('AGENTS.md', '@docs/one.md')
        self.put('docs/one.md', '@two.md')
        self.put('docs/two.md', 'Suppressed import')
        self.put('nested/CLAUDE.md', 'Nested guidance')
        self.put('nested/AGENTS.md', 'Nested fallback')
        result = self.run_inventory('claude', '--directory', 'nested')
        for name in ('project:AGENTS.md', 'project:docs/one.md', 'project:docs/two.md', 'project:nested/AGENTS.md'):
            self.assertEqual('not_selected', self.items(result)[name]['loading'])

    def test_unreadable_override_keeps_fallback_loading_unknown(self):
        self.put('AGENTS.md', 'Base guidance')
        override = self.put('AGENTS.override.md', 'Override guidance')
        override.chmod(0)
        self.addCleanup(override.chmod, 0o600)
        result = self.run_inventory('codex')
        self.assertEqual('unknown', self.items(result)['project:AGENTS.md']['loading'])
        self.assertIn('inaccessible', self.gaps(result))

    def test_referenced_helpers_sidecar_and_bad_encoding_are_accounted_for(self):
        self.put('AGENTS.md', '[helper](helpers/run.py)')
        self.put('helpers/run.py', 'raise RuntimeError("MUST_NOT_EXECUTE")')
        self.skill('fixture', runtime='codex')
        self.put('.agents/skills/fixture/agents/openai.yaml', 'policy: unsupported')
        self.put('.agents/skills/fixture/another.md', 'Not a referenced file')
        bad = self.put('.codex/rules/bad.rules', 'temporary')
        bad.write_bytes(b'\xff\xfe')
        result = self.run_inventory('codex')
        self.assertIn('project:helpers/run.py', self.items(result))
        self.assertIn('project:.agents/skills/fixture/agents/openai.yaml', self.items(result))
        self.assertNotIn('project:.agents/skills/fixture/another.md', self.items(result))
        self.assertTrue({'reference_not_parsed', 'skill_sidecar', 'unsupported_encoding'} <= self.gaps(result))
        self.assertNotIn('MUST_NOT_EXECUTE', json.dumps(result))

    def test_directory_and_reference_budgets_bound_discovery(self):
        self.put('CLAUDE.md', ' '.join('@missing-%s.md' % n for n in range(100)))
        for n in range(20):
            (self.project / '.claude/rules' / str(n)).mkdir(parents=True)
        result = self.run_inventory('claude', '--max-items', '5')
        self.assertTrue({'reference_limit', 'directory_limit'} <= self.gaps(result))
        self.assertLess(len(result['coverage']), 20)

    def test_explicit_managed_instruction_requires_a_read_root(self):
        instruction = self.put('managed/CLAUDE.md', 'Managed guidance', self.root)
        result = self.run_inventory('claude', '--instruction', str(instruction))
        self.assertIn('boundary', self.gaps(result))
        self.assertEqual(0, len(self.items(result, 'instruction')))
        result = self.run_inventory('claude', '--instruction', str(instruction), '--allow-root', str(instruction.parent))
        item = next(iter(self.items(result, 'instruction').values()))
        self.assertEqual('explicit:unknown', item['scope'])
        self.assertEqual('unknown', item['loading'])

    def test_duplicate_link_and_import_routes_preserve_eager_loading(self):
        self.put('CLAUDE.md', '[later](docs/one.md) @docs/one.md')
        self.put('docs/one.md', '@two.md')
        self.put('docs/two.md', 'Eager dependency')
        result = self.run_inventory()
        refs = self.items(result, 'reference')
        self.assertEqual(2, len(refs))
        for item in refs.values():
            self.assertEqual('startup_expected', item['loading'])
        one = refs['project:docs/one.md']['id']
        self.assertEqual({'link', 'import'}, {r['relation'] for r in result['relations'] if r['target'] == one})

    def test_cli_rejects_bad_inputs_without_partial_output(self):
        for extra in (['--min-sessions', '0'], ['--low-use-threshold', '2'],
                      ['--since', '2026-02-01', '--until', '2026-01-01'],
                      ['--cwd', str(self.home)], ['--directory', '../']):
            command = [sys.executable, '-B', str(PACKAGE / 'inventory.py'), 'inventory', '--project', str(self.project),
                       '--runtime', 'claude', '--runtime-version', '2.1.285', *extra]
            run = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(2, run.returncode)
            self.assertEqual('', run.stdout)

    def test_contract_rejects_missing_version_and_invalid_loading_state(self):
        result = self.run_inventory()
        altered = copy.deepcopy(result)
        altered.pop('schema_version')
        with self.assertRaises(AssertionError):
            validate(altered, SCHEMA)
        self.put('CLAUDE.md', 'Fixture')
        result = self.run_inventory()
        result['items'][0]['loading'] = 'definitely_loaded'
        with self.assertRaises(AssertionError):
            validate(result, SCHEMA)


if __name__ == '__main__':
    unittest.main()
