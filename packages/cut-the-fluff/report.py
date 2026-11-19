"""Read-only candidate signals and explicitly cited architectural review. Stdlib only."""
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit

VERSION = '1.0'
ACTIONS = {'keep', 'trim', 'deduplicate', 'narrow_scope', 'conditional',
           'improve_trigger', 'defer', 'disable', 'archive'}


def short(value, limit=60):
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + '...'


def names(values, limit=5):
    values = sorted(str(v) for v in values)
    return ', '.join(values[:limit]) + (' and %d more' % (len(values) - limit) if len(values) > limit else '')


def validate(value, schema, defs, where='$'):
    """The small schema vocabulary used by this package; errors name the JSON path that failed."""
    if '$ref' in schema:
        return validate(value, defs[schema['$ref'].rsplit('/', 1)[1]], defs, where)
    if 'const' in schema and value != schema['const']:
        raise ValueError('schema constant at %s: expected %s, got %s' % (where, short(schema['const']), short(value)))
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('schema enum at %s: %s is not one of %s' % (where, short(value), names(schema['enum'], 12)))
    if 'type' in schema:
        actual = {str: 'string', int: 'integer', float: 'number', list: 'array',
                  dict: 'object', bool: 'boolean', type(None): 'null'}.get(type(value))
        allowed = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if actual not in allowed and not (actual == 'integer' and 'number' in allowed):
            raise ValueError('schema type at %s: expected %s, got %s' % (where, '/'.join(allowed), actual))
    if isinstance(value, dict):
        props = schema.get('properties', {})
        missing = set(schema.get('required', [])) - value.keys()
        if missing:
            raise ValueError('schema required at %s: missing key %s' % (where, names(missing)))
        extra = value.keys() - props.keys()
        if schema.get('additionalProperties') is False and extra:
            raise ValueError('schema properties at %s: unexpected key %s' % (where, names(extra)))
        for key, child in value.items():
            if key in props:
                validate(child, props[key], defs, where + '.' + key)
    if isinstance(value, list):
        for index, child in enumerate(value):
            validate(child, schema.get('items', {}), defs, '%s[%d]' % (where, index))
    if type(value) in (int, float):
        import math
        if not math.isfinite(value) or value < schema.get('minimum', float('-inf')) or value > schema.get('maximum', float('inf')):
            raise ValueError('schema number at %s: %s is out of range' % (where, short(value)))


def add_arguments(p):
    p.add_argument('--project', required=True)
    p.add_argument('--inventory', required=True, help='Inventory JSON from the same selected project')
    p.add_argument('--analysis', help='Optional analyze JSON from the same selected project/runtime')
    p.add_argument('--context', action='append', default=[], help='Explicit project-relative context files to scan')
    p.add_argument('--architecture', action='append', default=[], help='Explicit project-relative manifests/docs/tests/plans')
    p.add_argument('--diagnostic', action='append', default=[], help='Existing project-relative native diagnostic exports; never executed')
    p.add_argument('--review', help='Local cited review JSON; patches require --include-patches')
    p.add_argument('--include-patches', action='store_true', help='Emit reviewed source text in proposed diffs; private output')
    p.add_argument('--format', choices=('json', 'agent', 'human', 'markdown'), default='json',
                   help='json: full record, needed for approval and apply; agent: compact JSON for agents; '
                        'human: plain-language report; markdown: tables (default: %(default)s)')
    p.add_argument('--max-file-bytes', type=int, default=1048576,
                   help='Bytes per --context/--architecture/--diagnostic document (default: %(default)s = 1 MiB)')
    p.add_argument('--max-input-bytes', type=int, default=268435456,
                   help='Bytes per --inventory/--analysis/--review JSON file (default: %(default)s = 256 MiB)')
    p.add_argument('--max-total-bytes', type=int, default=536870912,
                   help='Bytes across all files read (default: %(default)s = 512 MiB)')
    p.add_argument('--max-files', type=int, default=200, help='Files read in total (default: %(default)s)')
    p.add_argument('--max-listed', type=int, default=25,
                   help='Rows per long listing in the output, e.g. file activity (default: %(default)s)')
    p.add_argument('--large-context-bytes', type=int, default=10240,
                   help='Candidate-only source byte threshold, not a runtime budget (default: %(default)s)')

GAP_DETAILS = {
    'project_identity_requires_reviewed_pairing': 'The tool cannot prove that --inventory and --analysis describe the same project; confirm the pairing before citing usage.',
    'no_usage_evidence': 'No --analysis was passed; usage signals are absent, not zero.',
    'native_diagnostics_not_supplied': 'No --diagnostic export was passed; runtime-reported context sizes are unknown.',
    'outside_project': 'The document resolves outside --project and was not read.',
    'pointer_outside_project': 'A Markdown link points outside --project; it was not checked.',
    'inventory_snapshot_mismatch': 'The file changed after --inventory was made; rerun inventory before citing it.',
}


def joiner(items):
    """Map an analysis component id to inventory ids by origin path, skill name or MCP server name."""
    by_origin, by_name = {}, {}
    for item in items.values():
        for label in [item['origin'], *item['aliases']]:
            by_origin.setdefault(label, []).append(item['id'])
        name = item['metadata'].get('name')
        if isinstance(name, str):
            by_name.setdefault((item['kind'], name), []).append(item['id'])
    def join(component):
        kind, _, rest = component.partition(':')
        if kind == 'file':
            matched = by_origin.get(rest, [])
        elif kind == 'skill':
            matched = by_name.get(('skill', rest), []) + by_name.get(('command', rest), [])
        elif kind == 'tool' and rest.startswith('mcp__'):
            matched = by_name.get(('mcp', rest.split('__')[1]), [])
        else:
            matched = []
        if matched:
            return sorted(set(matched)), 'inventory'
        # Built-in tools have no file; other names may be deleted, plugin-provided or host-bundled.
        return [], 'builtin_or_host_tool' if kind == 'tool' and not rest.startswith('mcp__') else 'not_in_inventory'
    return join


class Report:
    def __init__(self, args):
        self.a = args
        self.root = Path(args.project).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError('--project %s is not a directory' % args.project)
        for option in ('max_file_bytes', 'max_input_bytes', 'max_total_bytes', 'max_files', 'max_listed', 'large_context_bytes'):
            if getattr(args, option) < 1:
                raise ValueError('--%s must be at least 1' % option.replace('_', '-'))
        self.total = self.files = 0
        self.refs, self.gaps, self.signals, self.docs = [], [], [], {}
        self.defs = json.loads((Path(__file__).with_name('schema.json')).read_text())['$defs']

    def read(self, path, option, input_file=False):
        """Bounded read; refusals name the option, the file and the limit to raise."""
        limit, limit_option = ((self.a.max_input_bytes, '--max-input-bytes') if input_file
                               else (self.a.max_file_bytes, '--max-file-bytes'))
        self.files += 1
        if self.files > self.a.max_files:
            raise ValueError('file limit: %s %s would be file %d; raise --max-files (%d)' % (option, path, self.files, self.a.max_files))
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('nonregular file: %s %s is not a regular file' % (option, path))
            data = stream.read(min(limit, self.a.max_total_bytes - self.total) + 1)
        if len(data) > limit:
            raise ValueError('byte limit: %s %s is %d bytes, over %s (%d)' % (option, path, info.st_size, limit_option, limit))
        if self.total + len(data) > self.a.max_total_bytes:
            raise ValueError('byte limit: %s %s would bring the total past --max-total-bytes (%d)' % (option, path, self.a.max_total_bytes))
        self.total += len(data)
        return data

    def bundle(self, path, kind, prefix):
        option = '--' + kind
        try:
            value = json.loads(self.read(path, option, input_file=True))
        except json.JSONDecodeError as exc:
            raise ValueError('%s %s is not JSON (line %d)' % (option, path, exc.lineno)) from None
        try:
            validate(value, self.defs[kind], self.defs)
        except ValueError as exc:
            raise ValueError('%s %s: %s; pass the unedited output of the %s command' % (
                option, path, exc, 'analyze' if kind == 'analysis' else kind)) from None
        # Namespace IDs to prevent inventory/analysis evidence and coverage collisions.
        value = copy.deepcopy(value)
        ids = [e['id'] for e in value['evidence']]
        gaps = [g['id'] for g in value['coverage']]
        if len(set(ids + gaps)) != len(ids + gaps):
            raise ValueError('duplicate input identity in %s %s' % (option, path))
        mapping = {key: prefix + key for key in ids + gaps}
        def remap(obj):
            if isinstance(obj, dict):
                for key, child in obj.items():
                    if key == 'evidence_refs':
                        if not set(child) <= set(ids):
                            raise ValueError('dangling evidence in %s %s: %s' % (option, path, names(set(child) - set(ids))))
                        obj[key] = [mapping[r] for r in child]
                    elif key == 'id' and child in mapping:
                        obj[key] = mapping[child]
                    else:
                        remap(child)
            elif isinstance(obj, list):
                for child in obj:
                    remap(child)
        remap(value)
        self.refs.extend(value['evidence'])
        self.gaps.extend(value['coverage'])
        return value

    def gap(self, code, locator, detail=None):
        self.gaps.append(dict(schema_version=VERSION, id='report-gap:' + str(len(self.gaps)+1),
            code=code, locator=locator, status='unknown', detail=detail or GAP_DETAILS.get(code, code.replace('_', ' ')),
            evidence_refs=[]))

    def document(self, name, role):
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('--%s %s: expected a path relative to --project, without ..' % (role, name))
        path = (self.root / relative).resolve()
        label = 'project:' + relative.as_posix()
        if self.root not in path.parents:
            self.gap('outside_project', label)
            return
        if label in self.docs:
            self.docs[label]['roles'].add(role)
            return
        try:
            data = self.read(path, '--' + role)
            text = data.decode('utf-8')
        except (OSError, UnicodeError, ValueError) as exc:
            reason = exc.args[0] if isinstance(exc, ValueError) and exc.args else type(exc).__name__
            self.gap('unreadable_or_limited_document', label, 'Not read (%s); it is not cited or scanned.' % reason)
            return
        ref = 'document:' + str(len(self.docs)+1)
        self.refs.append(dict(schema_version=VERSION, id=ref, kind='file', locator=label,
                              sha256=hashlib.sha256(data).hexdigest()))
        self.docs[label] = dict(text=text, ref=ref, roles={role}, sha256=hashlib.sha256(data).hexdigest(),
                                path=relative.as_posix())

    def signal(self, code, components, refs, detail):
        self.signals.append(dict(id='signal:' + str(len(self.signals)+1), code=code,
                                 component_ids=components, evidence_refs=sorted(set(refs)), detail=detail))

    def run(self):
        inv = self.bundle(self.a.inventory, 'inventory', 'inventory:')
        analysis = self.bundle(self.a.analysis, 'analysis', 'analysis:') if self.a.analysis else None
        if analysis and not analysis['adapter_profile'].startswith(inv['runtime']['name'] + '-'):
            raise ValueError('runtime mismatch: --inventory is %s but --analysis comes from %s; rerun analyze with --runtime %s'
                             % (inv['runtime']['name'], analysis['adapter_profile'], inv['runtime']['name']))
        self.gap('project_identity_requires_reviewed_pairing', 'report')
        if not analysis:
            self.gap('no_usage_evidence', 'report')
        for role, paths in [('context', self.a.context), ('architecture', self.a.architecture), ('diagnostic', self.a.diagnostic)]:
            for name in paths:
                self.document(name, role)
        if not self.a.diagnostic:
            self.gap('native_diagnostics_not_supplied', 'report')
        items = {i['id']: i for i in inv['items']}
        if len(items) != len(inv['items']):
            raise ValueError('duplicate component id in --inventory %s' % self.a.inventory)
        dangling = {d for i in items.values() for d in i['dependencies'] if d not in items}
        if dangling:
            raise ValueError('dangling dependency in --inventory %s: %s' % (self.a.inventory, names(dangling)))
        origins = {label: [i for i in items.values() if label in [i['origin'], *i['aliases']]] for label in self.docs}
        hashes, triggers = {}, {}
        for label, doc in self.docs.items():
            if 'context' not in doc['roles']:
                continue
            matched = origins[label]
            components = [i['id'] for i in matched]
            refs = [doc['ref']]
            if len(doc['text'].encode()) > self.a.large_context_bytes:
                self.signal('large_context_body', components, refs,
                            str(len(doc['text'].encode())) + ' source bytes exceed selected review threshold ' + str(self.a.large_context_bytes) + '; scope and runtime cost require review.')
            for item in matched:
                expected = [r['sha256'] for r in inv['evidence'] if r['id'] in item['evidence_refs'] and r['kind'] == 'file']
                if doc['sha256'] not in expected:
                    self.gap('inventory_snapshot_mismatch', label)
            if doc['sha256'] in hashes:
                prev_label, prev = hashes[doc['sha256']]
                self.signal('duplicate_content', components + [i['id'] for i in origins[prev_label]],
                            refs + [prev['ref']], 'Exact bytes match; distinct scope or precedence may justify both.')
            hashes[doc['sha256']] = label, doc
            # Only local Markdown pointers are checked; never follow/read the targets.
            from inventory import frontmatter, visible_text  # same parsing rules as inventory
            clean = visible_text(doc['text'])
            for pointer in re.findall(r'\]\(([^)]+)\)', clean)[:200]:
                parsed = urlsplit(pointer)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                dest = (self.root / label[8:]).parent / unquote(parsed.path)
                resolved = dest.resolve()
                if self.root not in resolved.parents and resolved != self.root:
                    self.gap('pointer_outside_project', label)
                elif not resolved.exists():
                    self.signal('stale_pointer', components, refs, 'Missing local target: ' + str(dest.relative_to(self.root)))
            if any(i['kind'] == 'skill' for i in matched):
                # Frontmatter only; unparseable frontmatter is already an inventory gap.
                meta, parsed = frontmatter(doc['text'])
                trigger = meta.get('description', '') if parsed else ''
                trigger = trigger.strip() if isinstance(trigger, str) else ''
                if parsed and (not trigger or len(trigger.split()) < 5 or re.search(r'\b(any task|all tasks|everything|always use)\b', trigger, re.I)):
                    self.signal('weak_trigger', components, refs, 'Description may not distinguish relevant tasks; review frontmatter manually.')
                if trigger and trigger in triggers:
                    self.signal('overlapping_discovery', components + triggers[trigger][0], refs + [triggers[trigger][1]],
                                'Identical discovery descriptions; semantic tool overlap needs architectural review.')
                triggers[trigger] = components, doc['ref']
        configured = {}
        for item in items.values():
            name = item['metadata'].get('name')
            if item['kind'] not in ('mcp', 'skill', 'command', 'plugin') or not name:
                continue
            key = item['kind'], name
            if key in configured:
                previous = configured[key]
                self.signal('overlapping_configuration', [previous['id'], item['id']],
                            previous['evidence_refs'] + item['evidence_refs'],
                            'Same capability name in multiple configuration layers; precedence may explain it. Semantic equivalence is unproven.')
            configured[key] = item
        for edge in inv['relations']:
            if edge['source'] not in items or edge['target'] is not None and edge['target'] not in items:
                raise ValueError('dangling relation in --inventory %s: %s -> %s' % (self.a.inventory, edge['source'], edge['target']))
            if edge['relation'] == 'import':
                self.signal('eager_import', [edge['source']] + ([edge['target']] if edge['target'] else []),
                            items[edge['source']]['evidence_refs'], 'Import may load with parent; splitting alone provides no savings. Loading: ' + edge['loading'])
        usage, files = [], []
        if analysis:
            join = joiner(items)
            for metric in analysis['metrics']:
                comp = metric['component_id']
                # Per-metric coverage: file reads count only sessions with fully resolved reads.
                low = (metric['covered_sessions'] >= analysis['options']['min_sessions'] and
                       metric['activity_session_fraction'] is not None and
                       metric['activity_session_fraction'] <= analysis['options']['low_use_threshold'])
                matched, status = join(comp)
                if comp.startswith('file:') and not matched:
                    # Files outside the inventory are activity context, not audit candidates.
                    files.append(dict(component_id=comp, sessions_with_activity=metric['sessions_with_activity'],
                                      read_attempts=metric['read_attempts'], reads=metric['reads'],
                                      repeated_reads=metric['repeated_reads'], searches=metric['searches'],
                                      failures=metric['failures'], low_activity=low))
                    continue
                usage.append(dict(component_id=comp, inventory_ids=matched, join=status,
                                  invocations=metric['invocations'], successes=metric['successes'],
                                  failures=metric['failures'], reads=metric['reads'], searches=metric['searches'],
                                  sessions_with_activity=metric['sessions_with_activity'],
                                  covered_sessions=metric['covered_sessions'], selected_sessions=metric['selected_sessions']))
                components = [comp] + matched
                if metric['repeated_reads']:
                    self.signal('repeated_content_reads', components, metric['evidence_refs'],
                                str(metric['repeated_reads']) + ' repeated successful reads; full-file extent is unknown.')
                if metric['failures']:
                    self.signal('broken_access_candidate', components, metric['evidence_refs'],
                                str(metric['failures']) + ' failed outcomes; distinguish failed access from low demand.')
                # Tool reads are not how startup files or skill bodies reach the model: startup files load
                # every session, and skill use is measured by the skill:NAME metric.
                indirect = comp.startswith('file:') and all(
                    items[i]['loading'] == 'startup_expected' or items[i]['kind'] == 'skill' for i in matched)
                if low and matched and not indirect:
                    self.signal('low_observed_activity', components, metric['evidence_refs'],
                                'Active in %d of %d covered sessions; missing history, discovery and rare needs require review.'
                                % (metric['sessions_with_activity'], metric['covered_sessions']))
        files.sort(key=lambda f: (-f['failures'], -f['repeated_reads'], -f['sessions_with_activity'], f['component_id']))
        file_activity = dict(components=len(files), low_activity=sum(f['low_activity'] for f in files),
                             with_failures=sum(f['failures'] > 0 for f in files),
                             with_repeated_reads=sum(f['repeated_reads'] > 0 for f in files),
                             listed=files[:self.a.max_listed],
                             order='failures, then repeated reads, then sessions with activity (descending)')
        window = analysis['window'] if analysis else dict(since=inv['options']['since'], until=inv['options']['until'])
        totals = analysis['totals'] if analysis else {}
        sessions = dict(selected=totals.get('selected_sessions', 0), covered=totals.get('covered_sessions', 0),
                        file_read_covered=totals.get('file_read_covered_sessions', 0),
                        min_sessions=analysis['options']['min_sessions'] if analysis else None,
                        low_use_threshold=analysis['options']['low_use_threshold'] if analysis else None)
        coverage = dict(covered_sessions=analysis['totals']['covered_sessions'] if analysis else 0,
                        eligible_sessions=analysis['totals']['eligible_sessions'] if analysis else None,
                        gap_refs=[g['id'] for g in self.gaps])
        review = {'schema_version': VERSION, 'decisions': []}
        if self.a.review:
            try:
                review = json.loads(self.read(self.a.review, '--review', input_file=True))
            except json.JSONDecodeError as exc:
                raise ValueError('--review %s is not JSON (line %d)' % (self.a.review, exc.lineno)) from None
            try:
                validate(review, self.defs['architectural_review'], self.defs)
            except ValueError as exc:
                raise ValueError('--review %s: %s (decisions[N] is decision N+1)' % (self.a.review, exc)) from None
        refs = {r['id'] for r in self.refs}
        known_components = set(items) | ({m['component_id'] for m in analysis['metrics'] + analysis['observations']} if analysis else set())
        architecture_refs = {d['ref'] for d in self.docs.values() if 'architecture' in d['roles']}
        findings, mappings, changes = [], [], []
        for number, decision in enumerate(review['decisions'], 1):
            name = '--review decision %d (decisions[%d], components %s)' % (number, number - 1, names(decision['component_ids'], 3) or 'none')
            empty = [key for key in ('need', 'rationale', 'discovery_impact') if not decision[key].strip()]
            if empty or not decision['evidence_refs']:
                raise ValueError('empty architectural judgment: %s has empty %s' % (name, names(empty + ([] if decision['evidence_refs'] else ['evidence_refs']))))
            unknown = set(decision['component_ids']) - known_components
            if unknown:
                raise ValueError('unknown decision reference: %s names component ids not in --inventory or --analysis: %s' % (name, names(unknown)))
            unknown = set(decision['evidence_refs']) - refs
            if unknown:
                raise ValueError('unknown decision reference: %s cites evidence ids not in this report: %s (document ids are listed under documents)' % (name, names(unknown)))
            if not set(decision['evidence_refs']) & architecture_refs:
                raise ValueError('architectural citation required: %s cites no --architecture document; add one of: %s'
                                 % (name, names(architecture_refs) or 'none (pass --architecture FILE first)'))
            protected = decision['protected']
            if protected and decision['action'] != 'keep':
                raise ValueError('protected capability requires keep: %s has protected=true and action %s' % (name, decision['action']))
            savings = dict(amount=None, unit='source_bytes', basis='unknown',
                           method='No supported per-file runtime savings measurement.', overlap_group=None)
            proposed = None
            patch = decision.get('patch')
            if patch:
                if not self.a.include_patches or decision['action'] == 'keep':
                    raise ValueError('patch output requires explicit opt-in and change action: %s %s'
                                     % (name, 'has a patch; pass --include-patches' if not self.a.include_patches
                                        else 'has action keep, which cannot carry a patch'))
                label = 'project:' + patch['path']
                doc = self.docs.get(label)
                if not doc:
                    raise ValueError('patch needs cited context: %s patches %s, which is not a document; pass --context %s'
                                     % (name, patch['path'], patch['path']))
                if 'context' not in doc['roles']:
                    raise ValueError('patch needs cited context: %s patches %s (%s), which was passed only as --%s; pass it as --context too'
                                     % (name, patch['path'], doc['ref'], ', --'.join(sorted(doc['roles']))))
                if doc['ref'] not in decision['evidence_refs']:
                    raise ValueError('patch needs cited context: %s patches %s; add %s to its evidence_refs'
                                     % (name, patch['path'], doc['ref']))
                if any(g['code'] == 'inventory_snapshot_mismatch' and g['locator'] == label for g in self.gaps):
                    raise ValueError('stale inventory: %s patches %s, which changed after --inventory was made; rerun inventory'
                                     % (name, patch['path']))
                old, new = patch['old'], patch['new']
                if not old or old == new or doc['text'].count(old) != 1:
                    raise ValueError('ambiguous patch: %s: patch.old must be non-empty, differ from patch.new and occur exactly once in %s (found %d)'
                                     % (name, patch['path'], doc['text'].count(old) if old else 0))
                changed = doc['text'].replace(old, new, 1)
                from changes import proposal
                changes.append(proposal('finding:' + str(number), patch['path'], doc['text'], old, new))
                chunks = difflib.unified_diff(doc['text'].splitlines(True), changed.splitlines(True),
                                   fromfile='a/' + patch['path'], tofile='b/' + patch['path'])
                proposed = ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n' for line in chunks)
                savings = dict(amount=max(0, len(doc['text'].encode()) - len(changed.encode())), unit='source_bytes',
                    basis='estimated', method='UTF-8 source byte delta of this independent proposal; not tokens, loads, cache or billing.',
                    overlap_group='file:' + patch['path'])
            finding = dict(schema_version=VERSION, id='finding:' + str(number),
                component_ids=decision['component_ids'], action=decision['action'], evidence_refs=decision['evidence_refs'],
                confidence=decision['confidence'], rationale=decision['rationale'], window=window, coverage=coverage,
                savings=savings, discovery_impact=decision['discovery_impact'], proposed_patch=proposed)
            validate(finding, self.defs['finding'], self.defs)
            findings.append(finding)
            mappings.append(dict(finding_id=finding['id'], need=decision['need'], protected=protected,
                                 evidence_refs=decision['evidence_refs']))
        # Count unique file identities, never multiple roles/scopes as separate bytes.
        buckets = {}
        for i in items.values():
            buckets.setdefault(i['loading'], {})[i['origin']] = i['bytes']
        telemetry = [o for o in analysis['observations'] if o.get('access') == 'telemetry'] if analysis else []
        documents = [dict(id=d['ref'], path=d['path'], roles=sorted(d['roles'])) for d in self.docs.values()]
        return dict(schema_version=VERSION, kind='report', runtime=inv['runtime'], window=window, coverage=self.gaps,
            evidence=self.refs, documents=documents, sessions=sessions,
            components=[dict(id=i['id'], kind=i['kind'], origin=i['origin'], loading=i['loading']) for i in items.values()], usage=usage, file_activity=file_activity,
            signals=self.signals, mappings=mappings, findings=findings, changes=changes,
            accounting=dict(source_bytes_by_loading={k: sum(v.values()) for k, v in buckets.items()},
                method='Measured source bytes by documented loading class; roles deduplicated within each class. Classes are not additive runtime costs.',
                conditional_load_tokens=None, tool_result_tokens=None, repeated_input_tokens=None,
                caching='Aggregate telemetry only; no file attribution or cache-adjusted savings.',
                billing='Unknown; no price assumptions or charges derived.',
                telemetry_observations=telemetry, total_savings=None,
                savings_policy='Independent alternatives sharing an overlap_group must not be added; no aggregate savings computed.'),
            review_status='cited architectural review' if findings else 'candidate signals only; architectural review required')


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def refs_text(refs, limit=3):
    return ', '.join(refs[:limit]) + (' +%d more' % (len(refs) - limit) if len(refs) > limit else '')


def markdown(report, limit=25):
    """Readable summary: findings first, then grouped signals and gaps. The JSON output keeps every record."""
    rt, win, ses = report['runtime'], report['window'], report['sessions']
    known = {c['id']: c for c in report['components']}
    def label(cid):
        c = known.get(cid)
        return '%s (%s %s)' % (cid, c['kind'], c['origin']) if c else cid
    lines = ['# cut-the-fluff read-only report', '',
             report['review_status'] + '. No files changed. Source bytes are not runtime tokens or billing.', '',
             '- Runtime: %s %s (%s)' % (rt['name'], rt['version'], rt['surface']),
             '- Window: %s to %s' % (win['since'] or 'start', win['until'] or 'end'),
             '- Sessions: %d selected, %d covered, %d with every file read resolved' % (ses['selected'], ses['covered'], ses['file_read_covered']),
             '- Every finding shares this window and these session counts. Long lists show at most %d rows; the JSON output has all.' % limit]
    lines += ['', '## Findings (%d)' % len(report['findings']), '']
    if not report['findings']:
        lines.append('None yet. Write a cited review and pass --review to turn signals into findings.')
    for f, mapping in zip(report['findings'], report['mappings']):
        savings = f['savings']
        amount = 'unknown' if savings['amount'] is None else '%d %s (%s)' % (savings['amount'], savings['unit'], savings['basis'])
        lines += ['### %s: %s %s' % (f['id'], f['action'], ', '.join(map(label, f['component_ids']))), '',
                  '- Need: ' + mapping['need'] + (' (protected capability)' if mapping['protected'] else ''),
                  '- Rationale: ' + f['rationale'],
                  '- Discovery: ' + f['discovery_impact'],
                  '- Confidence: %s. Evidence: %s' % (f['confidence'], ', '.join(f['evidence_refs'])),
                  '- Savings: ' + amount, '']
        if f['proposed_patch']:
            lines += ['```diff', f['proposed_patch'].rstrip(), '```', '']
    groups = {}
    for signal in report['signals']:
        groups.setdefault(signal['code'], []).append(signal)
    lines += ['', '## Candidate signals (%d)' % len(report['signals']), '']
    if not groups:
        lines.append('None.')
    for code, signals in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines += ['### %s (%d)' % (code, len(signals)), '']
        for signal in signals[:limit]:
            lines.append('- %s: %s [%s]' % (', '.join(signal['component_ids']), signal['detail'], refs_text(signal['evidence_refs'])))
        if len(signals) > limit:
            lines.append('- ... %d more in the JSON output' % (len(signals) - limit))
        lines.append('')
    usage = sorted(report['usage'], key=lambda u: (u['component_id'].startswith('file:'), u['join'] != 'inventory', u['component_id']))
    lines += ['', '## Usage by component (%d)' % len(usage), '']
    if usage:
        lines += ['`join` says how the usage name matched the inventory: `inventory`, `builtin_or_host_tool`, or `not_in_inventory` (deleted, plugin or bundled).', '',
                  '| Component | Inventory ids | Join | Active sessions | Covered sessions | Invocations | Reads | Failures |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- |']
        lines += ['| %s | %s | %s | %d | %d | %d | %d | %d |' % (cell(u['component_id']), ', '.join(u['inventory_ids']) or '-', u['join'],
                  u['sessions_with_activity'], u['covered_sessions'], u['invocations'], u['reads'], u['failures']) for u in usage[:limit]]
        if len(usage) > limit:
            lines.append('\n%d more rows in the JSON output.' % (len(usage) - limit))
    else:
        lines.append('No usage evidence.')
    fa = report['file_activity']
    lines += ['', '## File activity outside the inventory (%d files)' % fa['components'], '']
    if fa['components']:
        lines += ['Context only: these files are not inventoried, so they get no signals. %d low activity, %d with failures, %d with repeated reads. Top %d by %s:'
                  % (fa['low_activity'], fa['with_failures'], fa['with_repeated_reads'], min(limit, len(fa['listed'])), fa['order']), '',
                  '| File | Active sessions | Read attempts | Searches | Failures | Repeated reads |', '| --- | --- | --- | --- | --- | --- |']
        lines += ['| %s | %d | %d | %d | %d | %d |' % (cell(f['component_id']), f['sessions_with_activity'], f['read_attempts'],
                  f['searches'], f['failures'], f['repeated_reads']) for f in fa['listed'][:limit]]
    else:
        lines.append('None.')
    lines += ['', '## Documents (%d)' % len(report['documents']), '']
    if report['documents']:
        lines += ['| Id | Path | Roles |', '| --- | --- | --- |']
        lines += ['| %s | %s | %s |' % (d['id'], cell(d['path']), ', '.join(d['roles'])) for d in report['documents']]
    else:
        lines.append('None passed. Use --context and --architecture.')
    gaps = {}
    for g in report['coverage']:
        gaps.setdefault(g['code'], []).append(g)
    lines += ['', '## Coverage gaps (%d, %d kinds)' % (len(report['coverage']), len(gaps)), '',
              '| Gap | Count | Status | What it means | Examples |', '| --- | --- | --- | --- | --- |']
    # Actionable gaps first; informational notes cannot hide tool use.
    for code, group in sorted(gaps.items(), key=lambda kv: (kv[1][0]['detail'].startswith('Informational'), -len(kv[1]), kv[0])):
        details = sorted({g['detail'] for g in group})
        detail = details[0] if len(details) == 1 else details[0] + ' (+%d variants)' % (len(details) - 1)
        examples = sorted({g['locator'] for g in group})
        lines.append('| %s | %d | %s | %s | %s |' % (code, len(group), '/'.join(sorted({g['status'] for g in group})),
                     cell(detail), cell(refs_text(examples))))
    acc = report['accounting']
    lines += ['', '## Accounting', '', acc['method'], '']
    lines += ['- %s: %d source bytes' % (k, v) for k, v in sorted(acc['source_bytes_by_loading'].items())]
    lines += ['', 'Runtime tokens, cache effects and billing are unknown. ' + acc['savings_policy']]
    cited = {r for f in report['findings'] for r in f['evidence_refs']} | {d['id'] for d in report['documents']}
    index = [r for r in report['evidence'] if r['id'] in cited]
    lines += ['', '## Evidence index (%d cited of %d)' % (len(index), len(report['evidence'])), '']
    lines += ['- %s: %s SHA-256=%s' % (r['id'], r['locator'], r['sha256']) for r in index]
    return '\n'.join(lines) + '\n'


def compact(report, limit=25):
    """Agent summary: exact counts, capped lists, cited evidence only. Not an apply input."""
    def head(items, n=limit):
        return list(items)[:n]
    mappings = {m['finding_id']: m for m in report['mappings']}
    changes = {c['finding_id']: c.get('change_sha256') for c in report['changes']}
    findings = [dict(id=f['id'], action=f['action'], component_ids=f['component_ids'],
                     need=mappings[f['id']]['need'], protected=mappings[f['id']]['protected'],
                     confidence=f['confidence'], rationale=f['rationale'], discovery_impact=f['discovery_impact'],
                     evidence_refs=f['evidence_refs'], savings=f['savings'], proposed_patch=f['proposed_patch'],
                     change_sha256=changes.get(f['id'])) for f in report['findings']]
    signals = {}
    for s in report['signals']:
        group = signals.setdefault(s['code'], dict(count=0, listed=[]))
        group['count'] += 1
        if len(group['listed']) < limit:
            group['listed'].append(dict(id=s['id'], component_ids=s['component_ids'], detail=s['detail'],
                                        evidence_ref_count=len(s['evidence_refs']), evidence_refs=s['evidence_refs'][:3]))
    gaps = {}
    for g in report['coverage']:
        gaps.setdefault(g['code'], []).append(g)
    coverage = [dict(code=code, count=len(group), status=sorted({g['status'] for g in group}),
                     informational=group[0]['detail'].startswith('Informational'),
                     detail=sorted({g['detail'] for g in group})[0], examples=sorted({g['locator'] for g in group})[:3])
                for code, group in sorted(gaps.items(), key=lambda kv: (kv[1][0]['detail'].startswith('Informational'), -len(kv[1]), kv[0]))]
    usage = sorted(report['usage'], key=lambda u: (u['component_id'].startswith('file:'), u['join'] != 'inventory', u['component_id']))
    cited = {d['id'] for d in report['documents']}
    for f in findings:
        cited.update(f['evidence_refs'])
    for group in signals.values():
        for s in group['listed']:
            cited.update(s['evidence_refs'])
    acc = report['accounting']
    return dict(schema_version=report['schema_version'], kind='agent_report', runtime=report['runtime'],
        window=report['window'], sessions=report['sessions'], review_status=report['review_status'], listing_limit=limit,
        note='Summary for agents: counts are exact, lists stop at listing_limit, and evidence holds only cited references. '
             'Approvals and apply need the full report (--format json).',
        findings=findings, signals=signals, coverage=coverage, documents=report['documents'], components=report['components'],
        usage=dict(count=len(usage), listed=head(usage)), file_activity=report['file_activity'],
        evidence=[r for r in report['evidence'] if r['id'] in cited], evidence_total=len(report['evidence']),
        accounting=dict(source_bytes_by_loading=acc['source_bytes_by_loading'], method=acc['method'],
                        savings_policy=acc['savings_policy'], total_savings=None))


# Plain-language wording for people. Codes, IDs and tables stay in the other formats.
ACTIONS = {'trim': 'Shorten', 'deduplicate': 'Remove the repeated text in', 'narrow_scope': 'Load only where needed:',
           'conditional': 'Load only when needed:', 'improve_trigger': 'Make it clearer when to use', 'defer': 'Load later:',
           'disable': 'Turn off', 'archive': 'Archive', 'keep': 'Keep'}
SIGNAL_WORDS = {
    'large_context_body': 'These files are large, so they take up a lot of the agent\'s reading space whenever they load',
    'duplicate_content': 'These files are exact copies of each other',
    'stale_pointer': 'These files link to something that no longer exists',
    'eager_import': 'These files automatically pull in other files whenever they load',
    'weak_trigger': 'These skills have a description too vague for the agent to know when to use them',
    'overlapping_discovery': 'These skills have the same description, so the agent cannot tell them apart',
    'overlapping_configuration': 'The same setting is defined in more than one place',
    'repeated_content_reads': 'The agent read these files again and again within a single session',
    'broken_access_candidate': 'These sometimes failed when the agent used them. A failure can mean a wrong path or setting, so check that before removing anything',
    'low_observed_activity': 'These were rarely used in the sessions we could see. Rarely used is not the same as unneeded: they may be for rare jobs, or people may start them by typing their name, which this tool cannot see',
}

GAP_WORDS = {
    'unresolved_shell_access': 'the agent ran shell commands whose file names were only known while they ran, so we could not tell which files they read',
    'unresolved_file_access': 'the agent opened a file by a path we could not work out',
    'unresolved_shell_workdir': 'a shell command ran in a folder we could not work out',
    'incomplete_transcript': 'the session never finished, or was still running (often the session that ran this audit)',
    'compaction': 'the conversation was shortened to save space, so its early part is missing',
    'unknown_tool_outcome': 'a tool\'s result did not say whether it worked',
    'missing_tool_result': 'a tool was started but its result was never recorded',
    'unsupported_native_tool': 'the agent recorded a built-in tool in a form this audit cannot read',
    'unknown_native_item': 'the agent recorded an entry this audit does not recognize',
    'session_limit': 'there were more sessions than the audit was set to read',
    'byte_limit': 'the past sessions were bigger than the audit was set to read',
    'no_evidence': 'no past sessions were found',
}


def human(report, limit=25):
    """Prose report for people: what was found, why, how sure, and what happens next."""
    import re
    known = {c['id']: c for c in report['components']}
    def name(cid):
        c = known.get(cid)
        if c:
            where, _, path = c['origin'].partition(':')
            path = path if where == 'project' else ('~/' + path if where == 'home' else path)
            return '`%s`' % path
        kind, _, rest = cid.partition(':')
        if kind == 'skill':
            return 'the `%s` skill' % rest
        if kind == 'tool':
            return 'the `%s` tool' % rest
        if kind == 'file':
            return '`%s`' % rest.partition(':')[2]
        return '`%s`' % cid
    def names_of(ids):
        # A signal often names the usage key and its inventory id; show each thing once.
        shown = [name(i) for i in ids if i in known] or [name(i) for i in ids]
        return ', '.join(dict.fromkeys(shown))
    def count(n, word):
        return '%d %s%s' % (n, word, '' if n == 1 else 's')
    rt, ses = report['runtime'], report['sessions']
    runtime = {'claude': 'Claude Code', 'codex': 'Codex'}.get(rt['name'], rt['name'])
    findings = list(zip(report['findings'], report['mappings']))
    changes = [(f, m) for f, m in findings if f['action'] != 'keep']
    kept = [(f, m) for f, m in findings if f['action'] == 'keep']
    covered = {c for f, _ in findings for c in f['component_ids']}
    others = [s for s in report['signals'] if not set(s['component_ids']) & covered]
    measured = [f['savings']['amount'] for f, _ in changes if f['savings']['amount'] is not None]
    lines = ['# What cut-the-fluff found', '',
             'This report looks at the instructions, skills and settings that %s %s loads for this project, '
             'and at how they were used in past sessions. **Nothing has been changed.**' % (runtime, rt['version']), '',
             '## The short version', '']
    if findings:
        line = '- **%s suggested.**' % count(len(changes), 'change')
        if measured:
            line += (' The ones with a ready-made edit would remove about %s bytes of text in total. That counts '
                     'characters in files; it is not a measure of tokens, speed or cost, and some edits may overlap.' % format(sum(measured), ','))
        lines.append(line)
        if kept:
            lines.append('- **%s kept on purpose**, because the project needs %s.' % (count(len(kept), 'thing'), 'it' if len(kept) == 1 else 'them'))
    else:
        lines.append('- **No recommendations yet.** The agent has not written its review. Below is only what looked worth checking.')
    if others:
        lines.append('- **%s worth a look** that no recommendation covers yet.' % count(len(others), 'other item'))
    if ses['selected']:
        lines.append('- **How much we could see:** %d of %d past sessions in full.' % (ses['covered'], ses['selected']))
    else:
        lines.append('- **No past sessions were checked**, so this report cannot say what actually gets used.')
    if changes:
        lines += ['', '## Suggested changes', '']
        for n, (f, m) in enumerate(changes, 1):
            savings = f['savings']['amount']
            lines += ['### %d. %s %s' % (n, ACTIONS.get(f['action'], f['action']), names_of(f['component_ids'])), '',
                      f['rationale'], '',
                      '- **What it is for:** ' + m['need'],
                      '- **Effect on the agent:** ' + f['discovery_impact'],
                      '- **How sure we are:** ' + f['confidence'],
                      '- **Size:** ' + ('about %s bytes less text (an estimate of file size, not tokens or cost).' % format(savings, ',')
                                        if savings is not None else 'not measured; there is no ready-made edit for this one yet.'), '']
            if f['proposed_patch']:
                lines += ['The exact edit:', '', '```diff', f['proposed_patch'].rstrip(), '```', '']
    if kept:
        lines += ['', '## Kept on purpose', '']
        for f, m in kept:
            lines.append('- %s: %s%s. %s' % (names_of(f['component_ids']), m['need'],
                         ' (must stay)' if m['protected'] else '', f['rationale']))
    if others:
        lines += ['', '## Worth a look', '']
        groups = {}
        for s in others:
            groups.setdefault(s['code'], []).append(s)
        for code, group in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            items = []
            for s in group[:limit]:
                detail = s['detail']
                hit = re.match(r'Active in (\d+) of (\d+)', detail) or re.match(r'(\d+) failed', detail)
                if code == 'low_observed_activity' and hit:
                    extra = ' (used in %s of %s sessions)' % hit.groups()
                elif code == 'broken_access_candidate' and hit:
                    extra = ' (failed %s)' % ('once' if hit.group(1) == '1' else hit.group(1) + ' times')
                elif code == 'stale_pointer':
                    extra = ' (%s)' % detail.replace('Missing local target: ', 'missing: ')
                else:
                    extra = ''
                items.append(names_of(s['component_ids']) + extra)
            more = ' and %d more' % (len(group) - limit) if len(group) > limit else ''
            lines += ['%s: %s%s.' % (SIGNAL_WORDS.get(code, code.replace('_', ' ').capitalize()), ', '.join(items), more), '']
    lines += ['', '## How much we could see', '']
    if ses['selected']:
        lines.append('We looked at %d past sessions. In %d of them we could follow every tool the agent used, and in %d we could '
                     'also tell exactly which files it read.' % (ses['selected'], ses['covered'], ses['file_read_covered']))
    else:
        lines.append('No past sessions were included.')
    gaps, other = {}, set()
    for g in report['coverage']:
        if g['code'] in GAP_WORDS:
            reason = GAP_WORDS[g['code']]
            gaps.setdefault(reason[0].upper() + reason[1:], []).append(g)
        elif not g['detail'].startswith('Informational'):
            other.add(g['code'])
    if gaps:
        top = sorted(gaps.items(), key=lambda kv: -len(kv[1]))[:3]
        lines += ['', 'The most common reasons something could not be seen:', '']
        lines += ['- %s (%s).' % (reason, count(len(group), 'time')) for reason, group in top]
    if other or len(gaps) > 3:
        lines += ['', '%s of limits, mostly about what this audit can and cannot read, are listed in the full report.'
                  % count(len(other) + max(0, len(gaps) - 3), 'other kind').capitalize()]
    lines += ['', 'That is why this report never calls anything unused, only "not seen".']
    lines += ['', '## What happens next', '']
    if changes:
        lines.append('Nothing changes until you say so. Tell your agent which suggested changes you approve, by number. '
                     'It will show you the exact edit, keep a backup and can undo it. Before calling a change an improvement, '
                     'it should test the agent on real tasks before and after.')
    elif findings:
        lines.append('Every recommendation is to keep things as they are, so there is nothing to approve.')
    else:
        lines.append('Your agent should now read the project\'s documents and write a review that turns these items '
                     'into recommendations, each with a reason and a source.')
    return '\n'.join(lines) + '\n'
