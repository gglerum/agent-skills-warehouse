"""Regression checks against disposable Git sources; never mutate upstream repos."""

from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location("warehouse", Path(__file__).resolve().parents[1] / "scripts/warehouse.py")
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)


class WarehouseChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.write("source/skills/one/SKILL.md", "---\nname: one\ndescription: Test a boundary.\n---\n# One\n")
        self.write("source/skills/one/references/example.md", "A supporting example.\n")
        self.write("source/LICENSE", "Fixture license\n")
        self.write("README.md", "# Warehouse\n")
        self.write("AGENTS.md", "# Procedure\n")
        self.write("validation/SMOKE.md", "# Scenarios\n")
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Fixture"], check=True)
        self.cfg = {
            "schema": 1, "reviewed_on": "2026-11-11",
            "sources": [{"id": "fixture", "name": "Fixture", "path": "source", "url": "https://example.invalid/source"}],
            "profiles": {"reference": {"text": "Copy supporting files.", "related": ["source/LICENSE"]}},
            "assets": [{"id": "one", "name": "One", "source": "fixture", "path": "source/skills/one/SKILL.md", "kind": "skill", "group": "Test and verify", "description": "Test a boundary.", "profile": "reference", "copy": ["source/skills/one"], "related": [], "alternatives": []}],
            "exclusions": [], "variants": [], "maturity_judgments": {}, "review": {},
            "routes": [{"task": "Test behavior", "assets": ["one"], "choice": "Use the focused workflow."}],
        }
        self.cfg["review"], _, _ = w.capture(self.root, self.cfg)
        self.save()

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def save(self):
        self.write("warehouse.json", json.dumps(self.cfg))
        self.write("CATALOG.md", w.render(self.cfg))

    def run_command(self, command="check", **kwargs):
        output = io.StringIO()
        with redirect_stdout(output):
            code = w.run(self.root, SimpleNamespace(command=command, **kwargs))
        return code, output.getvalue()

    def errors(self, cfg=None):
        cfg = cfg or self.cfg
        _, candidates, signals = w.capture(self.root, cfg)
        return w.validate(self.root, cfg, candidates, signals)

    def test_warehouse_owned_package_review_drift_and_discovery(self):
        self.write("packages/local/SKILL.md", "---\nname: local\ndescription: Local package\n---\n")
        self.write("packages/local/helper.py", "print('fixture')\n")
        self.cfg["sources"].append(dict(id="local", name="Local", path="packages/local",
            url="packages/local/SKILL.md", kind="warehouse-owned"))
        self.cfg["assets"].append(dict(id="local",name="Local",source="local",
            path="packages/local/SKILL.md",kind="skill",group="Test and verify",
            description="Local package",profile="reference",copy=["packages/local"],
            related=[],alternatives=[]))
        self.write("warehouse.json", json.dumps(self.cfg))
        self.assertEqual(self.run_command("record-review",date="2026-11-11")[0],0)
        self.assertEqual(self.run_command()[0],0)
        self.write("packages/local/helper.py", "print('changed')\n")
        self.assertIn("Asset bundle needs review: local",self.run_command()[1])
        self.write("packages/local/extra/SKILL.md", "# Extra\n")
        _, candidates, _ = w.capture(self.root, self.cfg)
        self.assertIn("packages/local/extra/SKILL.md", candidates)

    def test_warehouse_owned_symlink_and_unknown_kind_refused(self):
        self.write("packages/local/SKILL.md", "# Local\n")
        source=dict(id="local", name="Local",path="packages/local",url="packages/local/SKILL.md",kind="warehouse-owned")
        (self.root/"packages/local/escape").symlink_to(self.root/"source")
        with self.assertRaises(ValueError): w.source_files(self.root, source)
        self.cfg["sources"][0]["kind"]="unknown"
        self.assertTrue(any("Invalid source kind" in e for e in self.errors()))

    def test_clean_review_and_read_only_scan(self):
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(self.run_command()[0], 0)
        self.assertEqual(self.run_command("scan")[0], 0)
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_edit_to_bundled_reference_is_detected(self):
        self.write("source/skills/one/references/example.md", "Changed instructions\n")
        code, output = self.run_command()
        self.assertEqual(code, 1)
        self.assertIn("Asset bundle needs review: one", output)
        self.assertIn("Source revision or content needs review", output)

    def test_license_dependency_drift_is_detected(self):
        self.write("source/LICENSE", "Changed license\n")
        self.assertIn("Asset bundle needs review: one", self.run_command()[1])

    def test_executable_mode_drift_is_detected(self):
        path = self.root / "source/skills/one/references/example.md"
        path.chmod(0o755)
        self.assertIn("Asset bundle needs review: one", self.run_command()[1])

    def test_new_untracked_skill_requires_catalog_review(self):
        self.write("source/skills/two/SKILL.md", "# New skill\n")
        self.assertIn("Uncataloged entry point: source/skills/two/SKILL.md", self.errors())

    def test_deleted_entry_is_reported(self):
        (self.root / "source/skills/one/SKILL.md").unlink()
        self.assertTrue(any("Missing asset target" in e for e in self.errors()))

    def test_beta_marker_requires_contextual_judgment(self):
        self.write("source/skills/one/SKILL.md", "# One\nThis skill is experimental.\n")
        self.assertTrue(any("Maturity signal needs contextual judgment" in e for e in self.errors()))
        before = (self.root / "warehouse.json").read_bytes()
        self.assertEqual(self.run_command("record-review", date="2026-11-11")[0], 1)
        self.assertEqual(before, (self.root / "warehouse.json").read_bytes())

    def test_exclusion_cannot_be_exposed_inside_eligible_bundle(self):
        self.cfg["exclusions"] = [{"path": "source/skills/one/references", "reason": "Experimental"}]
        self.assertTrue(any("Eligible bundle overlaps exclusion" in e for e in self.errors()))

    def test_contextual_data_archival_warning_can_be_acknowledged(self):
        self.write("source/skills/one/SKILL.md", "# One\nArchived records can be restored.\n")
        _, _, signals = w.capture(self.root, self.cfg)
        self.cfg["maturity_judgments"] = {n: {"sha256": v["sha256"], "reason": "Data operation, not asset maturity"} for n, v in signals.items()}
        self.save()
        self.assertEqual(self.run_command("record-review", date="2026-11-11")[0], 0)
        self.assertEqual(self.run_command()[0], 0)

    def test_explicit_review_updates_only_warehouse_outputs(self):
        self.write("source/skills/one/references/example.md", "Reviewed update\n")
        before = w.source_files(self.root, self.cfg["sources"][0])
        self.assertEqual(self.run_command("record-review", date="2026-11-11")[0], 0)
        self.assertEqual(self.run_command()[0], 0)
        self.assertEqual(before, w.source_files(self.root, self.cfg["sources"][0]))

    def test_catalog_tampering_is_reported(self):
        self.write("CATALOG.md", "# Stale catalog\n")
        self.assertIn("CATALOG.md differs", self.run_command()[1])

    def test_missing_alternative_and_anchor_are_reported(self):
        self.cfg["assets"][0]["alternatives"] = ["missing"]
        self.assertIn("Unknown alternative: one: missing", self.errors())
        self.assertIn("Missing catalog anchor: #missing", w.catalog_links(self.root, "[missing](#missing)"))

    def test_generated_variant_maps_to_canonical_source(self):
        self.write("source/harness/skills/one/SKILL.md", "# Generated\n")
        self.write("source/adapter.md", "# Adapter\n")
        self.cfg["variants"] = [{"path": "source/harness", "canonical": "source/skills/one", "adapter": "source/adapter.md", "notes": "Generated"}]
        self.assertEqual(self.errors(), [])

    def test_paths_cannot_escape_warehouse(self):
        with self.assertRaises(ValueError):
            w.local(self.root, "../outside")
        with self.assertRaises(ValueError):
            w.local(self.root, "/tmp/outside")

    def test_new_manifest_and_mcp_require_coverage(self):
        self.write("source/new/.cursor-plugin/plugin.json", '{"name":"new"}\n')
        self.write("source/new/mcp.json", '{"mcpServers":{}}\n')
        errors = self.errors()
        self.assertIn("Uncataloged entry point: source/new/.cursor-plugin/plugin.json", errors)
        self.assertIn("Uncataloged entry point: source/new/mcp.json", errors)

    def test_search_cannot_return_excluded_skill(self):
        self.write("source/in-progress/two/SKILL.md", "# Experimental fixture\n")
        self.cfg["exclusions"] = [{"path": "source/in-progress", "reason": "Experimental"}]
        self.save()
        code, output = self.run_command("search", query="two")
        self.assertEqual(code, 0)
        self.assertIn("0 matches", output)


if __name__ == "__main__":
    unittest.main()
