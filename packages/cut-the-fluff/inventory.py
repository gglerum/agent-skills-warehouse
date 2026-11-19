#!/usr/bin/env python3
"""Bounded, local context inventory. No runtime commands or network access."""
import argparse
import datetime as dt
import hashlib
import json
from itertools import islice
import os
from pathlib import Path
import re
import stat
import sys
import tomllib

# Resolve only this copied package when Python isolated mode omits the script directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from urllib.parse import unquote, urlsplit

VERSION = "1.0"
PROFILE = "docs-2026-11-11"
CLAUDE_BASELINE = "2.1.285"


def version_status(runtime, version):
    """'baseline', 'newer' (rules assumed unchanged; warned) or 'unverified'."""
    if runtime == "codex":
        # Codex profiles are documentation snapshots; binary versions are not comparable.
        baseline, match = PROFILE, re.fullmatch(r"docs-(\d{4}-\d{2}-\d{2})", version)
        key = (lambda v: v) if match else None
    else:
        baseline, match = CLAUDE_BASELINE, re.fullmatch(r"\d+(?:\.\d+)*", version)
        key = lambda v: tuple(int(x) for x in v.split("."))
    if version == baseline:
        return "baseline"
    return "newer" if match and key(version) > key(baseline) else "unverified"
DOCS = {
    "codex-instructions": "https://learn.chatgpt.com/docs/agent-configuration/agents-md",
    "codex-skills": "https://learn.chatgpt.com/docs/build-skills",
    "codex-config": "https://learn.chatgpt.com/docs/config-file/config-basic",
    "claude-instructions": "https://code.claude.com/docs/en/memory",
    "claude-skills": "https://code.claude.com/docs/en/skills",
    "claude-config": "https://code.claude.com/docs/en/settings",
    "claude-plugins": "https://code.claude.com/docs/en/plugins-reference",
}
STATES = ("configured", "advertised", "loaded", "invoked", "successful", "unknown")


def within(path, root):
    return path == root or root in path.parents


def ancestry(root, leaf):
    # Explicit construction avoids duplicate root entries.
    rel = leaf.relative_to(root)
    return [root.joinpath(*rel.parts[:i]) for i in range(len(rel.parts) + 1)]


def visible_text(text):
    """Ignore fenced code and inline code for reference extraction."""
    lines, fence = [], None
    for line in text.splitlines():
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if m:
            if fence is None:
                fence = m[1][0]
            elif fence == m[1][0]:
                fence = None
            continue
        if fence is None:
            lines.append(re.sub(r"(`+).*?\1", "", line))
    return "\n".join(lines)


def frontmatter(text):
    """Conservative YAML subset; complex YAML is an explicit coverage gap."""
    if not text.startswith("---\n"):
        return {}, True
    head, sep, _ = text[4:].partition("\n---")
    if not sep:
        return {}, False
    result, key, lines = {}, None, head.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.fullmatch(r"([\w-]+):\s*(.*)", line)
        if m:
            key, value = m.groups()
            if key == "description" and re.fullmatch(r"[|>][+-]?", value):
                # Block scalar for description only: indented lines up to the next key.
                block = []
                while i < len(lines) and (not lines[i].strip() or lines[i][:1] in " \t"):
                    block.append(lines[i].strip())
                    i += 1
                if not any(block):
                    return {}, False
                text = "\n".join(block).strip("\n")
                result[key] = text if value[0] == "|" else " ".join(text.split())
                continue
            if value[:1] in ("|", ">") or any(c in value for c in ("&", "*", "{")):
                return {}, False
            if not value:
                result[key] = []
            elif value.startswith("["):
                try:
                    result[key] = json.loads(value)
                except ValueError:
                    return {}, False
            else:
                result[key] = value.strip("\"'")
        elif key and (m := re.fullmatch(r"\s+-\s+(.+)", line)):
            if not isinstance(result[key], list):
                return {}, False
            result[key].append(m[1].strip("\"'"))
        else:
            return {}, False
    return result, True


class Inventory:
    def __init__(self, args):
        self.a = args
        self.project = Path(args.project).resolve(strict=True)
        self.cwd = Path(args.cwd or self.project).resolve(strict=True)
        self.boundary = Path(args.boundary or self.project).resolve(strict=True)
        if not all(p.is_dir() for p in (self.project, self.cwd, self.boundary)):
            raise ValueError("project, cwd and boundary must be directories")
        if not within(self.cwd, self.project) or not within(self.project, self.boundary):
            raise ValueError("require boundary <= project <= cwd")
        self.home = Path(args.home).resolve(strict=True) if args.home else None
        self.config_home = (Path(args.config_home).resolve(strict=True) if args.config_home
                            else self.home / (".codex" if args.runtime == "codex" else ".claude")
                            if self.home else None)
        self.roots = [self.project]
        if self.home:
            self.roots.append(self.home)
        if self.config_home:
            self.roots.append(self.config_home)
        self.roots += [Path(p).resolve(strict=True) for p in args.allow_root]
        self.items, self.evidence, self.gaps, self.edges = [], [], [], []
        self.files, self.file_evidence = {}, {}
        self.bytes_read = 0
        self.order = 0
        self.walk_count = 0
        self.read_cache = {}
        self.claude_mode = "claude-md-or-agents-md"

    def explicit(self, value, option):
        """Relative paths resolve against the shell's working directory, like other CLIs.
        Refuse the likely mistake of naming a project-relative path from elsewhere."""
        path = Path(value).absolute()
        if not Path(value).is_absolute() and not os.path.lexists(path) and os.path.lexists(self.project / value):
            raise ValueError(f"{option} {value} not found in the current directory, but "
                             f"{self.project / value} exists; pass that path or an absolute one")
        return path
    def label(self, path):
        path = Path(os.path.abspath(path))
        for base, name in ((self.project, "project"), (self.config_home, "config"),
                           (self.home, "home"), (self.boundary, "boundary")):
            if base and within(path, base):
                return name + ":" + path.relative_to(base).as_posix()
        for i, base in enumerate(self.roots):
            if within(path, base):
                return f"allowed-{i}:" + path.relative_to(base).as_posix()
        # Do not expose external absolute paths, commands, credentials or file text.
        return "outside:" + hashlib.sha256(os.fsencode(path)).hexdigest()[:16]

    def ev(self, kind, locator, sha=None):
        key = (kind, locator, sha)
        if key not in self.file_evidence:
            eid = f"e{len(self.evidence) + 1}"
            self.file_evidence[key] = eid
            self.evidence.append(dict(schema_version=VERSION, id=eid, kind=kind,
                                      locator=locator, sha256=sha))
        return self.file_evidence[key]

    def gap(self, code, path=None, refs=()):
        record = dict(schema_version=VERSION, id=f"g{len(self.gaps) + 1}", code=code,
                      locator=self.label(path) if path else "runtime", evidence_refs=list(refs),
                      status="unknown", detail=GAP_DETAILS.get(code, code))
        if not any((g["code"], g["locator"]) == (code, record["locator"]) for g in self.gaps):
            self.gaps.append(record)

    def resolve(self, path, exact=False):
        try:
            target = path.resolve(strict=True)
            if not (exact and target == path and within(path, self.boundary)) and not any(
                    within(target, root) for root in self.roots):
                self.gap("boundary", path)
                return None
            return target
        except FileNotFoundError:
            self.gap("missing", path)
        except (OSError, RuntimeError):
            self.gap("inaccessible", path)
        return None

    def read(self, path, exact=False):
        target = self.resolve(path, exact)
        if target is None:
            return None
        if target in self.read_cache:
            return self.read_cache[target]
        if self.bytes_read >= self.a.max_total_bytes:
            self.gap("total_limit", path)
            return None
        try:
            mode = target.stat().st_mode
            if not stat.S_ISREG(mode):
                self.gap("nonregular", path)
                return None
            if not mode & 0o444:
                self.gap("inaccessible", path)
                return None
            with target.open("rb") as f:
                data = f.read(self.a.max_file_bytes + 1)
            self.bytes_read += len(data)
            if len(data) > self.a.max_file_bytes:
                self.gap("file_limit", path)
                return None
            if self.bytes_read > self.a.max_total_bytes:
                self.gap("total_limit", path)
                return None
            text = data.decode("utf-8")
            result = target, text, self.ev("file", self.label(target), hashlib.sha256(data).hexdigest())
            self.read_cache[target] = result
            return result
        except UnicodeError:
            self.gap("unsupported_encoding", path)
            return None
        except OSError:
            self.gap("inaccessible", path)
            return None

    def candidates(self, folder, suffix, recursive=False):
        """Traverse only named context trees; directory identity prevents symlink loops."""
        pending, seen = [folder], set()
        while pending:
            self.walk_count += 1
            if self.walk_count > self.a.max_items:
                self.gap("directory_limit", folder)
                return
            current = pending.pop()
            if not os.path.lexists(current):
                continue
            target = self.resolve(current)
            if target is None:
                continue
            if target in seen:
                self.gap("directory_cycle_or_alias", current)
                continue
            seen.add(target)
            try:
                children = sorted(islice(current.iterdir(), max(1, self.a.max_items - self.walk_count + 1)))
            except OSError:
                self.gap("inaccessible", current)
                continue
            for child in children:
                self.walk_count += 1
                if self.walk_count > self.a.max_items:
                    self.gap("directory_limit", folder)
                    return
                if len(self.items) >= self.a.max_items:
                    self.gap("item_limit", folder)
                    return
                resolved = self.resolve(child)
                if resolved is None:
                    continue
                if resolved.is_dir():
                    if recursive:
                        pending.append(child)
                    elif suffix == "SKILL.md":
                        skill = child / suffix
                        if os.path.lexists(skill):
                            yield skill
                elif suffix != "SKILL.md" and child.suffix in suffix:
                    yield child

    def add(self, path, kind, scope, loading, rule, *, exact=False, depth=0, import_depth=0, stack=()):
        if len(self.items) >= self.a.max_items:
            self.gap("item_limit", path)
            return None
        data = self.read(path, exact)
        if data is None:
            return None
        target, text, ref = data
        # Identity is content target + role + scope; aliases keep separate edges.
        key = (target, kind, scope)
        if key in self.files:
            item = self.files[key]
            if self.label(path) not in item["aliases"]:
                item["aliases"].append(self.label(path))
            return item
        self.order += 1
        item = dict(schema_version=VERSION, id=f"i{len(self.items) + 1}", kind=kind,
                    origin=self.label(target), aliases=[self.label(path)], owner=scope.split(":")[0],
                    scope=scope, precedence=self.order, loading=loading, loading_basis=rule,
                    evidence_refs=[ref, self.ev("documentation", DOCS[rule])],
                    claim_basis="runtime_documented" if loading in ("startup_expected", "metadata_expected") else "inference",
                    confidence="medium" if loading in ("startup_expected", "metadata_expected") else "low",
                    states={s: ("observed" if s == "configured" else "unknown") for s in STATES},
                    bytes=len(text.encode()), dependencies=[], metadata={})
        self.files[key] = item
        self.items.append(item)
        if kind == "instruction":
            item["metadata"]["precedence_semantics"] = "root-to-cwd append; later guidance is more specific"
        if kind == "configuration":
            item["metadata"]["precedence_semantics"] = "source order only; effective merges and runtime overrides unresolved"
        if kind in ("skill", "command", "rule"):
            meta, ok = frontmatter(text)
            if not ok:
                self.gap("frontmatter", path, [ref])
                item["loading"] = "unknown"
            # Avoid exporting descriptions or arbitrary YAML values.
            item["metadata"] = {k: meta[k] for k in ("paths", "disable-model-invocation", "user-invocable") if k in meta}
            if kind in ("skill", "command"):
                item["metadata"]["name"] = meta.get("name", path.parent.name if kind == "skill" else path.stem)
                if kind == "skill" and not all(isinstance(meta.get(k), str) and meta[k] for k in ("name", "description")):
                    self.gap("skill_metadata", path, [ref])
                    item["loading"] = "unknown"
                item["metadata"]["body_loading"] = "conditional"
                item["metadata"]["advertisement"] = "expected_metadata_only; runtime visibility unknown"
                if meta.get("disable-model-invocation") == "true":
                    item["metadata"]["advertisement"] = "user_only; runtime visibility unknown"
            if kind == "rule" and meta.get("paths"):
                item["loading"] = "conditional"
        if kind in ("instruction", "rule", "reference", "skill", "command", "memory") and (kind != "reference" or path.suffix in (".md", ".txt")):
            if "!`" in text:
                self.gap("dynamic_context", path, [ref])
            if depth > 20:
                self.gap("reference_depth", path, [ref])
                return item
            clean = visible_text(text)
            refs = [(unquote(m[1]), "link") for m in re.finditer(r"\]\(([^)]+)\)", clean)]
            if self.a.runtime == "claude" and kind in ("instruction", "rule", "reference"):
                refs += [(m[1].replace("\\ ", " "), "import") for m in re.finditer(
                    r"(?:^|\s)@((?:\\ |[^\s`\"'<>])+)", clean)]
            if len(refs) > self.a.max_items:
                self.gap("reference_limit", path, [ref])
            for value, relation in refs[:self.a.max_items]:
                if len(self.edges) >= self.a.max_items:
                    self.gap("reference_limit", path, [ref])
                    break
                parsed = urlsplit(value)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                if value.startswith("~/"):
                    if not self.home:
                        self.gap("home_omitted", path)
                        continue
                    dest = self.home / value[2:]
                else:
                    dest = path.parent / parsed.path
                # An instruction reference is data, never a new read permission.
                if relation == "import" and import_depth >= 4:
                    self.gap("import_depth", dest, [ref])
                    continue
                resolved = self.resolve(dest)
                if resolved is None:
                    continue
                if resolved in (*stack, target):
                    previous = next((i for (p, k, s), i in self.files.items() if p == resolved and s == scope), item)
                    self.edges.append(dict(source=item["id"], target=previous["id"], relation="cycle", locator=self.label(dest), loading="unknown"))
                    self.gap("import_cycle", dest, [ref])
                    continue
                child_loading = loading if relation == "import" else "conditional"
                if relation == "import" and scope.startswith("project") and not within(resolved, self.cwd):
                    child_loading = "unknown"
                    self.gap("external_import_approval", dest, [ref])
                # Links may name binary helpers; record metadata without parsing code.
                child = self.add(dest, "reference", scope, child_loading, rule,
                                 depth=depth + 1, import_depth=import_depth + 1 if relation == "import" else 0, stack=(*stack, target))
                self.edges.append(dict(source=item["id"], target=child["id"] if child else None,
                                       relation=relation, locator=self.label(dest), loading=child_loading))
                if child and child["id"] not in item["dependencies"]:
                    item["dependencies"].append(child["id"])
                if child is None or resolved.suffix not in (".md", ".txt"):
                    self.gap("reference_not_parsed", dest, [ref])
        return item

    def config(self, path, scope, rule, exact=False):
        if not os.path.lexists(path):
            return {}
        item = self.add(path, "configuration", scope, "unknown", rule, exact=exact)
        if not item:
            return {}
        raw = self.read(path, exact)
        if not raw:
            return {}
        try:
            data = tomllib.loads(raw[1]) if path.suffix == ".toml" else json.loads(raw[1])
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, RecursionError):
            self.gap("configuration_format", path, item["evidence_refs"])
            return {}
        for key, kind in (("mcp_servers", "mcp"), ("mcpServers", "mcp"),
                          ("enabledPlugins", "plugin"), ("plugins", "plugin"), ("hooks", "hook")):
            block = data.get(key, {})
            if not isinstance(block, dict):
                self.gap("configuration_shape", path, item["evidence_refs"])
                continue
            for name, value in sorted(block.items()):
                self.component(item, kind, name, scope, value)
        # Inventories per-project MCP entries only for the selected project.
        if "projects" in data:
            block = data["projects"]
            selected = block.get(str(self.project), {}) if isinstance(block, dict) else {}
            if not isinstance(block, dict) or not isinstance(selected, dict):
                self.gap("configuration_shape", path, item["evidence_refs"])
            else:
                servers = selected.get("mcpServers", {})
                if isinstance(servers, dict):
                    for name, value in servers.items():
                        self.component(item, "mcp", name, "project:.", value)
                else:
                    self.gap("configuration_shape", path, item["evidence_refs"])
        supported = {"mcp_servers", "mcpServers", "enabledPlugins", "plugins", "hooks", "projects",
                     "project_doc_fallback_filenames", "project_doc_max_bytes", "skills", "pluginConfigs",
                     "permissions", "env", "model", "autoMemoryEnabled", "autoMemoryDirectory",
                     "name", "version", "description", "commands", "agents", "lspServers"}
        if set(data) - supported:
            self.gap("configuration_keys", path, item["evidence_refs"])
        for key in ("skills", "pluginConfigs"):
            if key in data:
                self.gap("runtime_resolution", path, item["evidence_refs"])
        return data

    def component(self, parent, kind, name, scope, value):
        if len(self.items) >= self.a.max_items:
            self.gap("item_limit")
            return
        states = {s: ("observed" if s == "configured" else "unknown") for s in STATES}
        item = dict(schema_version=VERSION, id=f"i{len(self.items) + 1}", kind=kind,
                    origin=parent["origin"] + "#" + kind + ":" + name, aliases=[],
                    owner=scope.split(":")[0], scope=scope, precedence=parent["precedence"],
                    loading="unknown", loading_basis=parent["loading_basis"], evidence_refs=parent["evidence_refs"][:],
                    states=states, claim_basis="direct", confidence="high", bytes=0, dependencies=[parent["id"]],
                    metadata={"name": name, "enabled": value if isinstance(value, bool) else
                              value["enabled"] if isinstance(value, dict) and type(value.get("enabled")) is bool else "unknown"})
        self.items.append(item)

    def instructions(self, directory, scope, active, exact=False, fallbacks=()):
        rule = self.a.runtime + "-instructions"
        if self.a.runtime == "codex":
            chosen, uncertain = False, False
            for name in ("AGENTS.override.md", "AGENTS.md", *fallbacks):
                path = directory / name
                if not os.path.lexists(path):
                    continue
                item = self.add(path, "instruction", scope, "startup_expected" if active else "conditional", rule, exact=exact)
                if not item:
                    uncertain = True
                if item:
                    if chosen or not item["bytes"]:
                        item["loading"] = "not_selected"
                    else:
                        chosen = True
                        if uncertain:
                            item["loading"] = "unknown"
                            item["confidence"] = "low"
        else:
            names = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude/AGENTS.md")
            for name in names:
                path = directory / name
                if os.path.lexists(path):
                    item = self.add(path, "instruction", scope,
                                    "startup_expected" if active else "conditional", rule, exact=exact)
                    if item and "AGENTS.md" in name:
                        local_guidance = any(os.path.lexists(directory / n) for n in names[:3])
                        if self.claude_mode in ("claude-md", "managed-only") or (self.claude_mode == "claude-md-or-agents-md" and (self.claude_has_guidance or local_guidance)):
                            item["loading"] = "not_selected"
                    if item and self.claude_mode == "managed-only" and active:
                        item["loading"] = "not_selected"

    def context_tree(self, directory, scope, active):
        runtime = self.a.runtime
        if runtime == "codex":
            folder = directory / ".agents/skills"
        else:
            folder = directory / ".claude/skills"
        for path in self.candidates(folder, "SKILL.md"):
            self.add(path, "skill", scope, "metadata_expected" if active else "conditional", runtime + "-skills")
            sidecar = path.parent / "agents/openai.yaml"
            if os.path.lexists(sidecar):
                self.add(sidecar, "configuration", scope, "unknown", runtime + "-skills")
                self.gap("skill_sidecar", sidecar)
        if runtime == "claude":
            for path in self.candidates(directory / ".claude/commands", {".md"}, True):
                self.add(path, "command", scope, "metadata_expected" if active else "conditional", "claude-skills")
        for path in self.candidates(directory / (".codex/rules" if runtime == "codex" else ".claude/rules"),
                                    {".md", ".rules"}, True):
            item = self.add(path, "rule", scope,
                            "startup_expected" if runtime == "claude" and active else "unknown", runtime + "-instructions")
            if runtime == "codex" and item:
                self.gap("codex_rules", path, item["evidence_refs"])

    def run(self):
        a = self.a
        runtime = a.runtime
        if a.surface != "cli":
            self.gap("unsupported_surface")
        version = version_status(runtime, a.runtime_version)
        if version != "baseline":
            self.gap("newer_version" if version == "newer" else "unverified_version")
        self.gap("host_context")
        self.gap("runtime_resolution")
        self.gap("nested_scope")
        if self.boundary.parent != self.boundary and runtime == "claude":
            self.gap("ancestors_omitted")
        dirs = ancestry(self.boundary, self.cwd)
        self.claude_has_guidance = any(os.path.lexists(d / name) for d in dirs
                                      for name in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"))
        fallbacks, limit = [], 32768
        if self.config_home:
            if runtime == "codex":
                data = self.config(self.config_home / "config.toml", "user:all", "codex-config")
                self.instructions(self.config_home, "user:all", True)
                self.config(self.config_home / "hooks.json", "user:all", "codex-config")
                for path in self.candidates(self.config_home / "rules", {".rules"}, True):
                    self.add(path, "rule", "user:all", "unknown", "codex-instructions")
                    self.gap("codex_rules", path)
                fallbacks, limit = self.codex_options(data, fallbacks, limit)
                # Legacy locations are inventoried with unknown loading.
                for path in self.candidates(self.config_home / "skills", "SKILL.md"):
                    item = self.add(path, "skill", "user:all", "unknown", "codex-skills")
                    if item:
                        self.gap("legacy_skill_location", path, item["evidence_refs"])
            else:
                user_data = self.config(self.config_home / "settings.json", "user:all", "claude-config")
                configs = user_data.get("pluginConfigs", {})
                if isinstance(configs, dict):
                    for key in ("agents-md@builtin", "cc-plugin-agents-md@builtin"):
                        cfg = configs.get(key, {})
                        if isinstance(cfg, dict) and isinstance(cfg.get("options", {}), dict):
                            self.claude_mode = cfg.get("options", {}).get("instructionFiles", self.claude_mode)
                if self.claude_mode not in ("claude-md", "claude-md-or-agents-md", "claude-md-and-agents-md", "managed-only"):
                    self.gap("configuration_shape")
                    self.claude_mode = "unknown"
                user_guidance = self.config_home / "CLAUDE.md"
                if os.path.lexists(user_guidance):
                    self.add(user_guidance, "instruction", "user:all", "startup_expected", "claude-instructions")
                # User config directory itself contains rules/skills, not another .claude.
                for path in self.candidates(self.config_home / "skills", "SKILL.md"):
                    self.add(path, "skill", "user:all", "metadata_expected", "claude-skills")
                for path in self.candidates(self.config_home / "rules", {".md"}, True):
                    self.add(path, "rule", "user:all", "startup_expected", "claude-instructions")
                if self.home:
                    self.config(self.home / ".claude.json", "user:all", "claude-config")
        else:
            self.gap("home_omitted")
        if self.home and runtime == "codex":
            for path in self.candidates(self.home / ".agents/skills", "SKILL.md"):
                self.add(path, "skill", "user:all", "metadata_expected", "codex-skills")
        if runtime == "codex":
            for directory in ancestry(self.project, self.cwd):
                data = self.config(directory / ".codex/config.toml", "project:" + directory.relative_to(self.project).as_posix(), "codex-config")
                self.config(directory / ".codex/hooks.json", "project:" + directory.relative_to(self.project).as_posix(), "codex-config")
                if data:
                    self.gap("trust", directory)
                fallbacks, limit = self.codex_options(data, fallbacks, limit)
            dirs = ancestry(self.project, self.cwd)
        else:
            self.config(self.project / ".claude/settings.json", "project:.", "claude-config")
            self.config(self.project / ".claude/settings.local.json", "local:.", "claude-config")
            self.config(self.project / ".mcp.json", "project:.", "claude-config")
        for directory in dirs:
            scope = "project:" + directory.relative_to(self.project).as_posix() if within(directory, self.project) else "parent:" + self.label(directory)
            self.instructions(directory, scope, True, exact=True, fallbacks=fallbacks)
            if within(directory, self.project):
                self.context_tree(directory, scope, True)
        for value in sorted(set(a.directory)):
            directory = (self.project / value).resolve(strict=True)
            if not within(directory, self.project) or not directory.is_dir():
                raise ValueError("--directory must name a project directory")
            if directory in dirs:
                continue
            scope = "project:" + directory.relative_to(self.project).as_posix()
            self.instructions(directory, scope, False, fallbacks=fallbacks)
            self.context_tree(directory, scope, False)
        if runtime == "codex":
            total = sum(i["bytes"] for i in self.items if i["kind"] == "instruction" and i["loading"] == "startup_expected")
            if total > limit:
                self.gap("instruction_budget")
                for item in self.items:
                    if item["kind"] == "instruction" and item["loading"] == "startup_expected":
                        item["loading"] = "unknown"
        for value in a.instruction:
            self.add(self.explicit(value, "--instruction"), "instruction", "explicit:unknown", "unknown", runtime + "-instructions")
        for value in a.memory:
            path = self.explicit(value, "--memory")
            self.add(path, "memory", "project:.", "unknown", runtime + "-instructions")
            self.gap("memory_runtime", path)
        for value in a.plugin:
            self.plugin(self.explicit(value, "--plugin"))
        for value in a.extra_config:
            self.config(self.explicit(value, "--extra-config"), "explicit:unknown", runtime + "-config")
        if not a.memory:
            self.gap("memory_scope_omitted")
        if self.claude_mode in ("managed-only", "unknown") and runtime == "claude":
            for item in self.items:
                if item["owner"] == "user" and item["kind"] in ("instruction", "rule"):
                    item["loading"] = "not_selected" if self.claude_mode == "managed-only" else "unknown"
        # Resolve incoming load routes after suppression; a link and an eager
        # import can point at the same target. Keep external approval uncertainty.
        by_id = {item["id"]: item for item in self.items}
        incoming = {}
        for edge in self.edges:
            if edge["target"] and edge["relation"] != "cycle":
                incoming.setdefault(edge["target"], []).append(edge)
        rank = {"not_selected": 0, "conditional": 1, "metadata_expected": 1,
                "unknown": 2, "startup_expected": 3}
        for _ in range(22):  # bounded by the reference traversal depth
            changed = False
            for item in self.items:
                if item["kind"] != "reference" or item["id"] not in incoming:
                    continue
                routes = []
                for edge in incoming[item["id"]]:
                    parent = by_id[edge["source"]]["loading"]
                    if parent == "not_selected":
                        routes.append("not_selected")
                    elif edge["relation"] == "link":
                        routes.append("conditional")
                    elif edge["loading"] == "unknown":
                        routes.append("unknown")
                    else:
                        routes.append(parent)
                loading = max(routes, key=rank.get)
                if item["loading"] != loading:
                    item["loading"] = loading
                    changed = True
            if not changed:
                break
        names = {}
        for item in self.items:
            if item["kind"] == "skill":
                names.setdefault(str(item["metadata"].get("name")), []).append(item)
        for matches in names.values():
            if len(matches) > 1:
                self.gap("skill_name_collision", refs=[r for i in matches for r in i["evidence_refs"]])
        if a.surface != "cli" or version == "unverified":
            for item in self.items:
                item["loading"] = "unknown"
                item["confidence"] = "low"
        elif version == "newer":
            for item in self.items:
                if item["claim_basis"] == "runtime_documented":
                    item["confidence"] = "low"
        # Capture aliases even when target identity was already scanned.
        for edge in self.edges:
            if edge["target"]:
                item = by_id[edge["target"]]
                if edge["locator"] not in item["aliases"]:
                    item["aliases"].append(edge["locator"])
        return dict(schema_version=VERSION, kind="inventory", runtime=dict(name=runtime, version=a.runtime_version,
                    surface=a.surface, profile=PROFILE),
                    scope=dict(project="project:.", cwd=self.label(self.cwd), boundary=self.label(self.boundary),
                               directories=a.directory, global_access=self.home is not None or self.config_home is not None),
                    options=dict(since=a.since, until=a.until, session_limit=a.session_limit,
                                 min_sessions=a.min_sessions, low_use_threshold=a.low_use_threshold),
                    items=self.items, evidence=self.evidence, coverage=self.gaps, relations=self.edges,
                    observations=[], findings=[])

    def codex_options(self, data, fallbacks, limit):
        names = data.get("project_doc_fallback_filenames", fallbacks)
        value = data.get("project_doc_max_bytes", limit)
        if not isinstance(names, list) or not all(isinstance(n, str) and n and Path(n).name == n and n not in (".", "..") for n in names):
            self.gap("configuration_shape")
        else:
            fallbacks = names
        if type(value) is int and value > 0:
            limit = value
        else:
            self.gap("configuration_shape")
        return fallbacks, limit

    def plugin(self, folder):
        runtime = self.a.runtime
        if runtime != "claude":
            self.gap("plugin_format", folder)
            return
        manifest = folder / ".claude-plugin/plugin.json"
        data = self.config(manifest, "plugin:" + self.label(folder), "claude-plugins")
        scope = "plugin:" + self.label(folder)
        self.gap("plugin_activation", folder)
        for path in self.candidates(folder / "skills", "SKILL.md"):
            self.add(path, "skill", scope, "unknown", "claude-skills")
        for path in self.candidates(folder / "commands", {".md"}, True):
            self.add(path, "command", scope, "unknown", "claude-skills")
        for path in (folder / ".mcp.json", folder / "hooks/hooks.json"):
            self.config(path, scope, "claude-plugins")
        # Custom component paths are bounded and handled as explicit configs or skill roots.
        for key in ("skills", "commands", "hooks", "mcpServers"):
            values = data.get(key, [])
            if isinstance(values, str):
                values = [values]
            if isinstance(values, list):
                for value in values:
                    if not isinstance(value, str):
                        self.gap("configuration_shape", manifest)
                        continue
                    path = folder / value
                    if key in ("hooks", "mcpServers"):
                        self.config(path, scope, "claude-plugins")
                    else:
                        for child in self.candidates(path, "SKILL.md" if key == "skills" else {".md"}, key == "commands"):
                            self.add(child, "skill" if key == "skills" else "command", scope, "unknown", "claude-skills")
            elif isinstance(values, dict) and key == "commands":
                for name, command in values.items():
                    if isinstance(command, dict) and isinstance(command.get("source"), str):
                        self.add(folder / command["source"], "command", scope, "unknown", "claude-skills")
                    else:
                        self.gap("plugin_inline_command", manifest)
            elif not isinstance(values, dict):
                self.gap("configuration_shape", manifest)
        if any(key in data for key in ("agents", "lspServers", "outputStyles")):
            self.gap("plugin_components", manifest)


GAP_DETAILS = {
    "host_context": "Host prompts, managed policy, bundled/account skills, CLI overrides and runtime injections are not observable from these files.",
    "runtime_resolution": "Configuration is inventoried as data; active profiles, permissions, enablement, merges, overrides and actual loads require runtime evidence.",
    "nested_scope": "Only the launch chain and explicit --directory scopes are covered; other project directories were not searched.",
    "ancestors_omitted": "Ancestors above --boundary were not read; inherited guidance there remains unknown.",
    "home_omitted": "No explicit home/config scope supplied; global context remains unknown.",
    "boundary": "Target lies outside allowed read roots; it was not read.",
    "external_import_approval": "External import approval is unknown; permission to inventory does not prove runtime loading.",
    "unverified_version": "Runtime version is older than or not comparable with the documented baseline; loading values are unknown.",
    "newer_version": "Runtime version is newer than the documented baseline; loading values assume unchanged rules and need confirmation.",
    "unsupported_surface": "Only local CLI file layouts are modeled. This surface may inject or resolve context differently.",
    "trust": "Project configuration loading depends on workspace trust, which was not observed.",
    "frontmatter": "Frontmatter is outside the conservative supported YAML subset; loading remains unknown.",
    "missing": "A configured or referenced file does not exist; check the path or the reference that names it.",
    "inaccessible": "A file exists but could not be read (permissions or I/O error).",
    "memory_scope_omitted": "No --memory was passed; auto memory is unknown. For Claude Code pass --memory ~/.claude/projects/<encoded-project>/memory/MEMORY.md.",
    "memory_runtime": "Memory file inventoried; whether and how much of it the runtime loads is unknown.",
    "item_limit": "More items than --max-items; the rest were not inventoried. Raise --max-items.",
    "file_limit": "The file is larger than --max-file-bytes; it was not read. Raise --max-file-bytes.",
    "total_limit": "Bytes read reached --max-total-bytes; the rest were not read. Raise --max-total-bytes.",
    "configuration_keys": "Some configuration keys are outside this inventory adapter; their effects remain unknown.",
}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory", help="Read files and emit metadata JSON to stdout")
    inv.add_argument("--project", required=True)
    inv.add_argument("--cwd")
    inv.add_argument("--boundary", help="Ancestor discovery stops here; defaults to project")
    inv.add_argument("--runtime", choices=("codex", "claude"), required=True)
    inv.add_argument("--runtime-version", required=True)
    inv.add_argument("--surface", default="cli")
    inv.add_argument("--home", help="Explicit authorized synthetic or real user home; no implicit home access")
    inv.add_argument("--config-home")
    for option in ("directory", "allow-root", "plugin", "memory", "extra-config", "instruction"):
        inv.add_argument("--" + option, action="append", default=[])
    inv.add_argument("--since", type=dt.date.fromisoformat)
    inv.add_argument("--until", type=dt.date.fromisoformat)
    inv.add_argument("--session-limit", type=int, default=100)
    inv.add_argument("--min-sessions", type=int, default=10)
    inv.add_argument("--low-use-threshold", type=float, default=0.05)
    inv.add_argument("--max-file-bytes", type=int, default=1048576, help="Bytes per file (1 MiB)")
    inv.add_argument("--max-total-bytes", type=int, default=16777216, help="Bytes across all files (16 MiB)")
    inv.add_argument("--max-items", type=int, default=2000)
    from evidence import add_arguments
    add_arguments(sub.add_parser("analyze", help="Read explicit local evidence and emit usage JSON"))
    from report import add_arguments as report_arguments
    report_arguments(sub.add_parser("report", help="Read-only signals and cited architectural review"))
    from changes import add_arguments as change_arguments
    change_arguments(sub)
    from verify import add_arguments as verify_arguments
    verify_arguments(sub.add_parser("verify", help="Read-only package checks and supplied behavior comparisons"))
    # --help shows every non-empty default, including options without help text.
    for command in sub.choices.values():
        for action in command._actions:
            if action.default in (None, [], False, argparse.SUPPRESS) or "%(default)" in (action.help or ""):
                continue
            action.help = ((action.help + " ") if action.help else "") + "(default: %(default)s)"
    return p


def fail(summary, exc):
    """Name the refused check so the caller can correct its input; never echo file bodies."""
    reason = exc.args[0] if isinstance(exc, (ValueError, KeyError)) and exc.args and isinstance(exc.args[0], str) else ""
    detail = type(exc).__name__ + (": " + reason[:500] if reason else "")
    print("ERROR: " + summary + " (" + detail + ")", file=sys.stderr)


def main(argv=None):
    p = parser()
    a = p.parse_args(argv)
    if a.command == "verify":
        from verify import run
        try:
            result = run(a)
            print(json.dumps(result, indent=2))
            return 1 if result["structural"]["status"] == "failed" else 0
        except (OSError, ValueError, RuntimeError, RecursionError, KeyError, TypeError) as exc:
            fail("verification input could not be processed", exc)
            return 2
    if a.command in ("apply", "rollback"):
        from changes import run
        try:
            print(json.dumps(run(a), indent=2))
            return 0
        except (OSError, ValueError, RuntimeError, RecursionError, KeyError, TypeError) as exc:
            fail("change refused or interrupted; preserve --state and use rollback for recovery", exc)
            return 2
    if a.command == "report":
        from report import Report, compact, human, markdown, validate
        try:
            reporter = Report(a)
            result = reporter.run()
            validate(result, reporter.defs["report"], reporter.defs)
            if a.format == "json":
                print(json.dumps(result, indent=2))
            elif a.format == "agent":
                print(json.dumps(compact(result, a.max_listed), indent=1))
            else:
                print((human if a.format == "human" else markdown)(result, a.max_listed))
            return 0
        except (OSError, ValueError, RuntimeError, RecursionError, KeyError, TypeError) as exc:
            fail("report input could not be processed", exc)
            return 2
    if a.command == "analyze":
        from evidence import Analysis, limit_hints
        try:
            result = Analysis(a).run()
            print(json.dumps(result, indent=2))
            for hint in limit_hints(result):
                print(hint, file=sys.stderr)
            return 0
        except (OSError, ValueError, RuntimeError, RecursionError) as exc:
            fail("evidence input could not be processed", exc)
            return 2
    if a.since and a.until and a.since > a.until:
        p.error("--since must not follow --until")
    if any(getattr(a, n) < 1 for n in ("session_limit", "min_sessions", "max_file_bytes", "max_total_bytes", "max_items")) or not 0 <= a.low_use_threshold <= 1:
        p.error("limits must be positive; low-use threshold must be between 0 and 1")
    try:
        result = Inventory(a).run()
        print(json.dumps(result, indent=2, default=str))
        return 0
    except (OSError, ValueError, RuntimeError, RecursionError) as exc:
        fail("inventory input could not be processed", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
