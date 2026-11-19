"""Local discovery and relocation scenarios using the actual reviewed inventory."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "warehouse.json").read_text())
ASSETS = {a["id"]: a for a in CFG["assets"]}


class ConsumptionScenarios(unittest.TestCase):
    def test_new_project_route_includes_specification_and_breakdown(self):
        route = next(r for r in CFG["routes"] if r["task"] == "Write a specification and break down work")
        for aid in ["addy-spec-driven-development", "addy-planning-and-task-breakdown", "matt-to-spec", "matt-to-tickets"]:
            self.assertIn(aid, route["assets"])
            self.assertTrue((ROOT / ASSETS[aid]["path"]).is_file())

    def test_debugging_route_exposes_distinct_workflow_choices(self):
        route = next(r for r in CFG["routes"] if r["task"] == "Diagnose bugs or performance")
        for aid in ["addy-debugging-and-error-recovery", "matt-diagnosing-bugs"]:
            self.assertIn(aid, route["assets"])
        addy = ASSETS["addy-debugging-and-error-recovery"]
        self.assertIn("matt-diagnosing-bugs", addy["alternatives"])

    def test_review_route_includes_different_scopes_and_personas(self):
        route = next(r for r in CFG["routes"] if r["task"] == "Review code, security, or readiness")
        for aid in ["addy-code-review-and-quality", "matt-code-review", "cursor-bundle-thermos"]:
            self.assertIn(aid, route["assets"])
        self.assertTrue((ROOT / ASSETS["addy-agent-security-auditor"]["path"]).exists())

    def test_service_configuration_is_discoverable_without_connecting(self):
        entry = ASSETS["cursor-bundle-google-sheets"]
        self.assertEqual(entry["profile"], "integration")
        mcp = json.loads((ROOT / entry["path"] / "mcp.json").read_text())
        self.assertIn("google-sheets", mcp["mcpServers"])
        self.assertIn("authentication", entry["notes"])
        self.assertIn("Client/backend-managed auth", CFG["profiles"]["integration"]["text"])

    def test_shared_reference_survives_relocation(self):
        entry = ASSETS["addy-test-driven-development"]
        source = ROOT / entry["path"]
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / ".claude/skills/test-driven-development"
            shutil.copytree(source.parent, target)
            # Deliberately make the asset self-contained instead of retaining repo layout.
            text = (target / "SKILL.md").read_text()
            references = set(re.findall(r"\.\./\.\./references/([\w-]+\.md)", text))
            self.assertIn("testing-patterns.md", references)
            (target / "references").mkdir(exist_ok=True)
            for name in references:
                shutil.copy2(ROOT / "repos/addyosmani-agent-skills/references" / name, target / "references" / name)
            (target / "SKILL.md").write_text(text.replace("../../references/", "references/"))
            shutil.copy2(ROOT / "repos/addyosmani-agent-skills/LICENSE", target / "LICENSE")
            for name in references:
                self.assertTrue((target / "references" / name).is_file())
            self.assertNotIn("../../references/", (target / "SKILL.md").read_text())
            self.assertIn("Addy Osmani", (target / "LICENSE").read_text())
            self.assertNotIn(str(ROOT), (target / "SKILL.md").read_text())
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_claude_verification_generator_keeps_adapter_and_examples(self):
        variant = next(v for v in CFG["variants"] if v["canonical"] == "repos/cursor-plugins/pstack")
        source = ROOT / variant["path"]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            for name in ["create-verification-skill", "maintain-verification-skill"]:
                shutil.copytree(source / "skills" / name, target / "skills" / name)
            adapter = target / "docs/harness/claude-code.md"
            adapter.parent.mkdir(parents=True)
            shutil.copy2(source / "docs/harness/claude-code.md", adapter)
            shutil.copy2(source / "LICENSE", target / "LICENSE")
            skill = target / "skills/create-verification-skill/SKILL.md"
            for ref in re.findall(r"\]\(([^)]+)\)", skill.read_text()):
                if "://" not in ref and not ref.startswith("#"):
                    self.assertTrue((skill.parent / ref.split("#")[0]).exists(), ref)
            self.assertTrue((skill.parent / "references/feature-map-example/README.md").is_file())
            # This is the generator and support material, not a generated app harness.
            self.assertTrue(adapter.is_file())

    def test_disqualified_buckets_are_not_searchable_assets(self):
        banned = ["repos/mattpocock-skills/skills/misc", "repos/mattpocock-skills/skills/in-progress", "repos/mattpocock-skills/skills/deprecated", "repos/cursor-plugins/third_party/salesforce-headless-360"]
        for a in CFG["assets"]:
            for path in a["copy"]:
                self.assertFalse(any(path == prefix or path.startswith(prefix + "/") for prefix in banned), path)

    def test_toolkit_converter_survives_catalog_copy_and_preserves_output_on_bad_input(self):
        entry = ASSETS['project-toolkit-tool-report-converters']
        with tempfile.TemporaryDirectory() as folder:
            consumer = Path(folder)
            target = consumer / 'helpers'
            shutil.copytree(ROOT / entry['copy'][0], target)
            (consumer / 'scan.json').write_text('{broken')
            output = consumer / 'scan.sarif'
            output.write_text('prior evidence')
            run = subprocess.run([sys.executable, '-B', '-I', str(target / 'composer_audit_to_sarif.py'),
                                  'scan.json', 'scan.sarif'], cwd=consumer, capture_output=True, text=True)
            self.assertEqual(2, run.returncode)
            self.assertEqual('prior evidence', output.read_text())
            self.assertTrue((target / 'ORIGIN.md').is_file())

    def test_toolkit_skill_copy_bundles_include_their_linked_helpers_and_notices(self):
        prefix = 'repos/gglerum-project-agent-toolkit/'
        for entry in CFG['assets']:
            if entry['source'] != 'project-toolkit' or entry['kind'] != 'skill':
                continue
            with self.subTest(asset=entry['id']), tempfile.TemporaryDirectory() as folder:
                consumer = Path(folder)
                for name in entry['copy']:
                    source = ROOT / name
                    target = consumer / name.removeprefix(prefix)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_dir():
                        shutil.copytree(source, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(source, target)
                skill = consumer / entry['path'].removeprefix(prefix)
                self.assertTrue((skill.parent / 'ORIGIN.md').is_file())
                for ref in re.findall(r'\]\(([^)]+)\)', skill.read_text()):
                    if '://' not in ref and not ref.startswith('#'):
                        self.assertTrue((skill.parent / ref.split('#')[0]).exists(), ref)


if __name__ == "__main__":
    unittest.main()
