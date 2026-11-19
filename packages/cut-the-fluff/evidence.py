"""Bounded evidence ingestion and descriptive usage metrics, without recommendations."""
import datetime as dt
import glob
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import stat
from collections import Counter, defaultdict

from adapters import FILE_READ, INFORMATIONAL, Claude, Codex, Supplement, Unsupported
import shell

VERSION = '1.0'
GLOB_LIMIT = 200  # More matches than this leave the command unresolved.


def stamp(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('timestamp')
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone required')
    return parsed.astimezone(dt.timezone.utc).isoformat()


def inside(path, root):
    return path == root or root in path.parents


def token(value):
    # Metadata only: never emit commands, arguments, output, or excerpts.
    return value if isinstance(value, str) and re.fullmatch(r'[\w.:/@+-]{1,200}', value) else None


# Gap codes that mean a cap stopped reading, and the option that raises the cap.
LIMIT_OPTIONS = {'session_limit': '--session-limit', 'byte_limit': '--max-total-bytes', 'event_limit': '--max-events',
                 'file_limit': '--max-files', 'discovery_limit': '--max-files',
                 'oversized_or_incomplete_record': '--max-line-bytes'}

GAP_DETAILS = {
    'session_limit': 'More sessions than --session-limit; later sessions were not analyzed. Raise --session-limit or narrow --since/--until.',
    'byte_limit': 'Transcript bytes reached --max-total-bytes; the rest of this file and later files were not read. Raise --max-total-bytes.',
    'event_limit': 'Tool events reached --max-events; later events were not read. Raise --max-events.',
    'file_limit': 'More transcript files than --max-files; later files were not read. Raise --max-files.',
    'discovery_limit': 'Store discovery stopped at the --max-files bound; some transcripts were not found. Raise --max-files.',
    'oversized_or_incomplete_record': 'A record exceeded --max-line-bytes or had no final newline (a session still being written); it was skipped.',
    'incomplete_transcript': 'This session has no completion marker; it may still be running (for example, the audit session itself) or was cut off.',
    'ignored_bookkeeping_record': 'Informational: typed records without tool content were skipped; they cannot hide tool use.',
    'ignored_request_copy': 'Informational: API request copies were skipped because every tool id also appears in the conversation.',
    'ignored_usage_summary': 'Informational: Codex usage summaries are not counted twice; matching token_count records are checked within the same file and session.',
    'unmatched_usage_summary': 'A Codex usage summary has no matching token_count record in the same file and session; telemetry may be missing.',
    'unsupported_native_tool': 'A native tool item has no supported call/result mapping; its invocations and outcomes cannot be attributed safely.',
    'unknown_native_item': 'A Codex item_completed record has an unknown item type; it may be a tool, so its use cannot be ruled out.',
    'usage_not_yet_reported': 'Informational: Codex token_count records with info: null carry rate limits only; they hold no usage to count.',
    'unknown_tool_outcome': 'A matched result has no structured Boolean success or integer exit_code; text and text blocks do not establish an outcome.',
    'glob_matched_current_tree': 'Informational: a wildcard was matched against the project as it is today (--expand-globs), not as it was.',
    'external_glob_not_listed': 'Informational: a wildcard outside the project was not listed; nothing was attributed to it.',
    'unresolved_shell_access': 'A shell command reads files named only at runtime (variables, command output, globs); file-read counts for this session are partial.',
    'unresolved_file_access': 'A read tool named a path that could not be resolved; pass --home if it starts with ~. File-read counts for this session are partial.',
    'unresolved_shell_workdir': 'A shell call had a relative or invalid workdir; file-read counts for this session are partial.',
    'compaction': 'The transcript was compacted; events before the compaction may be missing.',
    'missing_tool_result': 'A tool call has no recorded result; its outcome is unknown.',
    'retention_unknown': 'How long the runtime keeps transcripts is unknown; older sessions may have been deleted.',
    'unmatched_or_excluded_session': 'Some sessions ran outside --project and its --worktree roots; they were excluded.',
    'no_evidence': 'No transcript files were found; pass --store DIR or --evidence FILE.',
    'missing_parent': 'A subagent session names a parent session that was not read.',
}


def limit_hints(result):
    """One stderr line per cap that stopped reading, naming the option to raise."""
    hits = {}
    for g in result['coverage']:
        if g['code'] in LIMIT_OPTIONS:
            hits[g['code']] = hits.get(g['code'], 0) + 1
    return ['WARNING: %s hit %d time(s); output is partial. Raise %s%s.' % (
                code, count, LIMIT_OPTIONS[code],
                ', unless the file is still being written (no final newline)' if code == 'oversized_or_incomplete_record' else '')
            for code, count in sorted(hits.items())]


def add_arguments(p):
    p.add_argument('--project', required=True)
    p.add_argument('--runtime', choices=('codex', 'claude'), required=True)
    p.add_argument('--evidence', action='append', default=[], help='Explicit transcript JSONL file')
    p.add_argument('--handoff', action='append', default=[], help='Explicit ctf-evidence-1 handoff JSONL')
    p.add_argument('--telemetry', action='append', default=[], help='Explicit ctf-evidence-1 telemetry JSONL')
    p.add_argument('--store', action='append', default=[], help='Authorized evidence directory, bounded discovery')
    p.add_argument('--config-home', help='Explicit agent config root for --discover; no implicit home')
    p.add_argument('--discover', action='store_true')
    p.add_argument('--home', help='Absolute home directory the recorded agent used; resolves ~ and $HOME')
    p.add_argument('--expand-globs', action='store_true',
                   help='Match shell wildcards against the project tree as it is now (not as it was)')
    p.add_argument('--worktree', action='append', default=[])
    p.add_argument('--subagent', action='append', default=[], metavar='CHILD=PARENT')
    p.add_argument('--alias', action='append', default=[], metavar='OLD=NEW', help='Explicit component identity mapping')
    p.add_argument('--relevant-session', action='append', default=[], help='Explicit task-relevant session IDs')
    p.add_argument('--since', type=dt.date.fromisoformat)
    p.add_argument('--until', type=dt.date.fromisoformat)
    p.add_argument('--session-limit', type=int, default=100,
                   help='Sessions kept; later ones are dropped with a session_limit gap (default: %(default)s)')
    p.add_argument('--min-sessions', type=int, default=10,
                   help='Covered sessions needed before report emits low_observed_activity (default: %(default)s)')
    p.add_argument('--low-use-threshold', type=float, default=0.05,
                   help='Fraction of covered sessions at or below which activity counts as low (default: %(default)s)')
    p.add_argument('--max-line-bytes', type=int, default=1048576,
                   help='Bytes per transcript record (default: %(default)s = 1 MiB)')
    p.add_argument('--max-total-bytes', type=int, default=134217728,
                   help='Transcript bytes read in total (default: %(default)s = 128 MiB)')
    p.add_argument('--max-events', type=int, default=100000, help='Tool events kept in total (default: %(default)s)')
    p.add_argument('--max-files', type=int, default=1000,
                   help='Transcript files read; store discovery also stops after 4x this many entries (default: %(default)s)')


class Analysis:
    def __init__(self, args):
        self.a = args
        self.roots = [Path(p).resolve(strict=True) for p in [args.project, *args.worktree]]
        if not all(p.is_dir() for p in self.roots):
            raise ValueError('project/worktree must be directories')
        if args.discover and not args.config_home:
            raise ValueError('--discover requires explicit --config-home')
        if args.home is not None and not Path(args.home).is_absolute():
            raise ValueError('--home must be absolute')
        # Kept as text: the recorded machine's home need not exist here.
        self.home = os.path.normpath(args.home) if args.home else None
        if args.since and args.until and args.since > args.until:
            raise ValueError('invalid window')
        if any(getattr(args, n) < 1 for n in ('session_limit', 'min_sessions', 'max_line_bytes',
                                             'max_total_bytes', 'max_events', 'max_files')):
            raise ValueError('limits must be positive')
        if not 0 <= args.low_use_threshold <= 1:
            raise ValueError('invalid threshold')
        self.parents = self.mapping(args.subagent)
        self.aliases = self.mapping(args.alias)
        for key in self.aliases:
            seen, value = set(), key
            while value in self.aliases:
                if value in seen:
                    raise ValueError('alias cycle')
                seen.add(value)
                value = self.aliases[value]
        self.sessions, self.events, self.refs, self.gaps = {}, [], [], []
        self.gap_keys, self.seen = set(), {}
        self.total = self.records = self.duplicates = 0
        self.files = []
        self.adapter = Codex() if args.runtime == 'codex' else Claude()

    @staticmethod
    def mapping(values):
        result = {}
        for value in values:
            old, sep, new = value.partition('=')
            if not sep or not old or not new or old in result:
                raise ValueError('invalid identity mapping')
            result[old] = new
        return result

    def gap(self, code, locator='analysis', sid=None):
        if sid and locator == 'analysis':
            locator = 'session:' + sid  # name the session the gap applies to
        key = code, locator, sid
        if key in self.gap_keys:
            return
        self.gap_keys.add(key)
        self.gaps.append(dict(schema_version=VERSION, id='gap:' + str(len(self.gaps) + 1), code=code,
                              locator=locator, status='partial', detail=GAP_DETAILS.get(code, code.replace('_', ' ')),
                              evidence_refs=[locator] if locator.startswith('evidence:') else []))
        if sid in self.sessions and code in FILE_READ:
            self.sessions[sid]['file_reads_partial'] = True
        elif sid in self.sessions and code not in INFORMATIONAL:
            self.sessions[sid]['gaps'].add(code)

    def scope(self, value):
        if not isinstance(value, str) or not Path(value).is_absolute():
            return None
        path = Path(value).resolve()
        for i, root in enumerate(self.roots):
            if inside(path, root):
                return 'project' if i == 0 else 'worktree:' + str(i)
        return 'excluded'

    def session(self, sid):
        if sid not in self.sessions:
            if len(self.sessions) >= self.a.session_limit:
                self.gap('session_limit')
                return None
            self.sessions[sid] = dict(id=sid, native_id=sid, parent_id=self.parents.get(sid), scope=None,
                                      cwd=None, gaps=set(), evidence_refs=set(), ended=False, events=0,
                                      file_reads_partial=False,
                                      first=None, last=None, transcript=False)
        return self.sessions[sid]

    def paths(self):
        candidates = [(Path(p), self.adapter, None) for p in self.a.evidence]
        candidates += [(Path(p), Supplement(), kind) for kind, values in
                       [('handoff', self.a.handoff), ('telemetry', self.a.telemetry)] for p in values]
        stores = [Path(p) for p in self.a.store]
        if self.a.discover:
            base = Path(self.a.config_home)
            stores += [base / name for name in
                       (('sessions', 'archived_sessions') if self.a.runtime == 'codex' else ('projects',))]
        for index, store in enumerate(stores):
            label = 'store:' + str(index + 1)
            try:
                if store.is_symlink() or not store.is_dir():
                    self.gap('missing_or_symlink_store', label)
                    continue
                root = store.resolve(strict=True)
                # Bound directory entries as well as transcript count; never follow links.
                pending, visited = [root], 0
                while pending and visited < self.a.max_files * 4:
                    folder = pending.pop()
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            visited += 1
                            if visited > self.a.max_files * 4:
                                self.gap('discovery_limit', label)
                                break
                            if entry.is_symlink():
                                self.gap('symlink_evidence', label)
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(Path(entry.path))
                            elif entry.name.endswith('.jsonl'):
                                candidates.append((Path(entry.path), self.adapter, None))
                                if len(candidates) >= self.a.max_files:
                                    self.gap('discovery_limit', label)
                                    pending.clear()
                                    break
                if pending:
                    self.gap('discovery_limit', label)
            except OSError:
                self.gap('inaccessible_store', label)
        seen = set()
        for path, adapter, expected in candidates:
            key = path.resolve(), adapter.name
            if key in seen:
                continue
            seen.add(key)
            if len(self.files) >= self.a.max_files:
                self.gap('file_limit')
                break
            self.files.append((path, adapter, expected))
        if not self.files:
            self.gap('no_evidence')

    def read(self, path, adapter, expected, number):
        file_id = 'source:' + str(number)
        sid = None
        touched = set()
        file_gaps = set()
        file_calls, mirror_calls = set(), set()
        usage_records, usage_copies = Counter(), Counter()
        hasher = hashlib.sha256()
        try:
            # Nonblocking open protects FIFOs; fstat checks the opened object.
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    self.gap('nonregular_evidence', file_id)
                    return
                line_no = 0
                while True:
                    budget = self.a.max_total_bytes - self.total
                    if budget <= 0 or len(self.events) >= self.a.max_events:
                        code = 'byte_limit' if budget <= 0 else 'event_limit'
                        self.gap(code, file_id)
                        file_gaps.add(code)
                        break
                    raw = stream.readline(min(self.a.max_line_bytes + 1, budget))
                    if not raw:
                        break
                    self.total += len(raw)
                    hasher.update(raw)
                    line_no += 1
                    ref = 'evidence:' + str(number) + ':' + str(line_no)
                    if len(raw) > self.a.max_line_bytes or not raw.endswith(b'\n'):
                        code = 'oversized_or_incomplete_record'
                        self.gap(code, file_id)
                        file_gaps.add(code)
                        # Drain oversized lines without keeping them in memory.
                        while raw and not raw.endswith(b'\n') and self.total < self.a.max_total_bytes:
                            raw = stream.readline(min(self.a.max_line_bytes, self.a.max_total_bytes - self.total))
                            self.total += len(raw)
                            hasher.update(raw)
                        continue
                    try:
                        row = json.loads(raw.decode('utf-8'))
                        if not isinstance(row, dict):
                            raise Unsupported('record_shape')
                        if expected and row.get('kind') != expected:
                            raise Unsupported('export_kind_mismatch')
                        meta, events, gaps = adapter.decode(row)
                        raw_time = row.get('timestamp')
                        timestamp = stamp(raw_time)
                    except (ValueError, TypeError, AttributeError) as exc:
                        code = ('unsupported_encoding' if isinstance(exc, UnicodeDecodeError) else
                                str(exc) if isinstance(exc, Unsupported) else 'malformed_record_or_timestamp')
                        self.gap(code, file_id)
                        file_gaps.add(code)
                        continue
                    new_sid = meta.get('id')
                    if new_sid is not None and (not isinstance(new_sid, str) or not new_sid):
                        self.gap('invalid_session_id', file_id)
                        file_gaps.add('invalid_session_id')
                        continue
                    if new_sid:
                        sid = new_sid
                    if not sid:
                        self.gap('missing_session_identity', file_id)
                        file_gaps.add('missing_session_identity')
                        continue
                    session = self.session(sid)
                    if session is None:
                        continue
                    touched.add(sid)
                    if meta.get('mirror_usage'):
                        usage_copies[sid, meta['mirror_usage']] += 1
                    if meta.get('canonical_usage'):
                        usage_records[sid, meta['canonical_usage']] += 1
                    session['native_id'] = meta.get('native_id', session['native_id'])
                    parent = meta.get('parent')
                    if parent:
                        if not isinstance(parent, str) or (session['parent_id'] and session['parent_id'] != parent):
                            self.gap('parent_conflict', file_id, sid)
                        else:
                            session['parent_id'] = parent
                    cwd = meta.get('cwd')
                    if cwd is not None:
                        scope = self.scope(cwd)
                        if scope is None:
                            self.gap('invalid_project_identity', file_id, sid)
                        elif session['scope'] and session['scope'] != scope:
                            session['scope'] = 'excluded'
                            self.gap('project_identity_conflict', file_id, sid)
                        else:
                            session['scope'] = scope
                            session['cwd'] = str(Path(cwd).resolve())
                    if adapter.name != 'supplement':
                        session['transcript'] = True
                    mirror_calls.update(meta.get('mirror_calls', ()))
                    row_cwd = str(Path(cwd).resolve()) if isinstance(cwd, str) and Path(cwd).is_absolute() else None
                    for code in gaps:
                        self.gap(code, file_id, sid)
                    for block, event in enumerate(events):
                        if len(self.events) >= self.a.max_events:
                            self.gap('event_limit', file_id, sid)
                            file_gaps.add('event_limit')
                            break
                        if event['kind'] in ('call', 'result') and (
                                not isinstance(event.get('call'), str) or not event['call']):
                            self.gap('missing_call_identity', file_id, sid)
                            continue
                        file_calls.add(event.get('call'))
                        # Full native record IDs plus block offsets; content hash fallback.
                        rid = row.get('uuid', row.get('id'))
                        if rid is not None and not isinstance(rid, str):
                            self.gap('invalid_event_id', file_id, sid)
                            continue
                        event_id = rid if rid is not None else 'sha256:' + hashlib.sha256(raw).hexdigest()
                        digest = hashlib.sha256(json.dumps([event, timestamp], sort_keys=True).encode()).hexdigest()
                        key = adapter.name, sid, event_id, block
                        # Tool call/result identities survive active/archive and resumed exports.
                        if event.get('call') and event['kind'] in ('call', 'result'):
                            key = adapter.name, sid, event['kind'], event['call']
                        if key in self.seen:
                            if self.seen[key] == digest:
                                self.duplicates += 1
                            else:
                                self.gap('event_identity_conflict', file_id, sid)
                            continue
                        self.seen[key] = digest
                        self.records += 1
                        self.refs.append(dict(schema_version=VERSION, id=ref + ':' + str(block),
                                              kind='handoff' if expected == 'handoff' else
                                              'telemetry' if expected == 'telemetry' else 'session',
                                              locator=file_id + '#line=' + str(line_no),
                                              sha256=hashlib.sha256(raw).hexdigest()))
                        # The record's own cwd, when recorded, resolves relative paths at call time.
                        event.update(session_id=sid, event_id=event_id, timestamp=timestamp,
                                     evidence_ref=self.refs[-1]['id'], cwd=row_cwd)
                        self.events.append(event)
                        session['evidence_refs'].add(event['evidence_ref'])
                    if timestamp:
                        session['first'] = min(session['first'] or timestamp, timestamp)
                        session['last'] = max(session['last'] or timestamp, timestamp)
            self.refs.append(dict(schema_version=VERSION, id=file_id, kind='file',
                                  locator=file_id, sha256=hasher.hexdigest()))
        except OSError:
            self.gap('inaccessible_evidence', file_id)
            file_gaps.add('inaccessible_evidence')
        if mirror_calls - file_calls:
            # A request copy names calls this file never recorded: usage may be missing.
            self.gap('unmatched_request_copy', file_id)
            file_gaps.add('unmatched_request_copy')
        for member, _ in usage_copies - usage_records:
            self.gap('unmatched_usage_summary', file_id, member)
        for member in touched:
            self.sessions[member]['gaps'].update(file_gaps)
        # Orphan malformed files still affect audit-wide coverage, never imply non-use.

    def canonical(self, component):
        while component in self.aliases:
            component = self.aliases[component]
        return component

    def file_component(self, value, session):
        if not isinstance(value, str) or not value or '\x00' in value:
            return None
        if value == '~' or value.startswith('~/'):
            if not self.home:
                return None
            value = self.home + value[1:]
        path = Path(value)
        cwd = session.get('cwd')
        if not path.is_absolute():
            if not cwd:
                return None
            path = Path(cwd) / path
        path = path.resolve()
        for i, root in enumerate(self.roots):
            if inside(path, root):
                prefix = 'project:' if i == 0 else 'worktree:' + str(i) + ':'
                return self.canonical('file:' + prefix + path.relative_to(root).as_posix())
        # Retain identity without exposing external path contents.
        return 'file:external-sha256:' + hashlib.sha256(str(path).encode()).hexdigest()

    def accesses(self, event, session):
        tool, args = event.get('tool'), event.get('args', {})
        local = dict(session, cwd=event.get('cwd') or session.get('cwd'))
        if tool in ('Read', 'read_file', 'functions.read_file'):
            value = args.get('file_path', args.get('path'))
            component = self.file_component(value, local)
            if component:
                return [(component, 'direct_file', 'direct')]
            self.gap('unresolved_file_access', event['evidence_ref'], session['id'])
        if tool in ('Skill', 'skill'):
            name = token(args.get('skill', args.get('name')))
            if name:
                return [(self.canonical('skill:' + name), 'activation', 'direct')]
            self.gap('unresolved_skill_identity', event['evidence_ref'], session['id'])
        if tool in ('exec_command', 'functions.exec_command', 'Bash', 'shell_command'):
            command = args.get('cmd', args.get('command'))
            if (isinstance(command, list) and len(command) == 3 and all(isinstance(p, str) for p in command)
                    and command[0].rsplit('/', 1)[-1] in shell.SHELLS and command[1] in ('-c', '-lc')):
                command = command[2]  # argv form: [bash, -lc, SCRIPT]
            if not isinstance(command, str):
                self.gap('unresolved_shell_access', event['evidence_ref'], session['id'])
                return []
            workdir = args.get('workdir')
            if workdir is not None:
                if not isinstance(workdir, str) or not Path(workdir).is_absolute():
                    self.gap('unresolved_shell_workdir', event['evidence_ref'], session['id'])
                    return []
                local['cwd'] = workdir
            # Static parse only: the text is never run and named files are never opened.
            notes = set()
            found, reason = shell.file_accesses(command, local['cwd'], self.home, self.matcher(notes))
            if reason:
                self.gap('unresolved_shell_access', event['evidence_ref'], session['id'])
            for code in sorted(notes):
                self.gap(code, event['evidence_ref'], session['id'])
            return [(self.file_component(p, local), 'shell_' + kind, 'inference') for p, kind in found]
        return []

    def matcher(self, notes):
        """Glob matcher bounded to the project roots; today's tree, not the recorded one."""
        def expand(pattern):
            static = []
            for part in pattern.split('/'):
                if re.search(r'[*?[]', part):
                    break
                static.append(part)
            base = Path('/'.join(static) or '/').resolve()
            if not any(inside(base, root) or inside(root, base) for root in self.roots):
                # Rooted outside the project: no project file can match. Never listed.
                notes.add('external_glob_not_listed')
                return []
            if not self.a.expand_globs or not any(inside(base, root) for root in self.roots):
                return None
            matches = sorted(itertools.islice(glob.iglob(pattern), GLOB_LIMIT + 1))
            if not matches or len(matches) > GLOB_LIMIT:
                return None
            notes.add('glob_matched_current_tree')
            return matches
        return expand

    def in_window(self, timestamp):
        if timestamp is None:
            return not (self.a.since or self.a.until)
        day = dt.datetime.fromisoformat(timestamp).date()
        return not ((self.a.since and day < self.a.since) or (self.a.until and day > self.a.until))

    def run(self):
        self.paths()
        for n, (path, adapter, expected) in enumerate(self.files, 1):
            self.read(path, adapter, expected, n)
        for _ in range(len(self.sessions)):
            changed = False
            for s in self.sessions.values():
                parent = self.sessions.get(s['parent_id'])
                if s['scope'] is None and parent and parent['scope']:
                    s['scope'], s['cwd'] = parent['scope'], parent['cwd']
                    s['gaps'].add('inherited_project_identity')
                    changed = True
            if not changed:
                break
        for sid, s in self.sessions.items():
            chain, cursor = set(), sid
            while cursor in self.sessions:
                if cursor in chain:
                    self.gap('parent_cycle', sid=sid)
                    break
                chain.add(cursor)
                cursor = self.sessions[cursor]['parent_id']
        selected = {}
        for sid, s in self.sessions.items():
            if s['scope'] in (None, 'excluded'):
                self.gap('unmatched_or_excluded_session', sid='')
                continue
            if self.a.relevant_session and sid not in self.a.relevant_session:
                continue
            selected[sid] = s
            if s['parent_id'] and s['parent_id'] not in self.sessions:
                self.gap('missing_parent', sid=sid)
        observations, calls, results = [], {}, {}
        counts = defaultdict(lambda: dict(invocations=0, successes=0, failures=0, unknown_results=0,
                                          reads=0, repeated_reads=0, read_attempts=0, repeated_read_attempts=0,
                                          inferred_reads=0, searches=0, sessions=set(), last_observed_use=None,
                                          evidence_refs=[], basis=set()))
        reads = defaultdict(int)
        confirmed_reads = defaultdict(int)
        for event in self.events:
            sid = event['session_id']
            if sid not in selected:
                continue
            if event['timestamp'] is None:
                self.gap('missing_timestamp', event['evidence_ref'], sid)
            if not self.in_window(event['timestamp']):
                continue
            s = selected[sid]
            s['events'] += 1
            if event['kind'] == 'end':
                s['ended'] = True
                continue
            if event['kind'] == 'result':
                if not isinstance(event.get('call'), str) or not event['call']:
                    self.gap('missing_result_identity', event['evidence_ref'], sid)
                    continue
                key = sid, event.get('call')
                results[key] = event
                continue
            if event['kind'] in ('handoff', 'telemetry'):
                component = token(event.get('component'))
                if not component:
                    self.gap('unsupported_export_component', event['evidence_ref'], sid)
                    continue
                self.observe(observations, event, self.canonical(component), event.get('state', 'unknown'), event['basis'], event['kind'])
                if event['kind'] == 'telemetry' and not event.get('measurements'):
                    self.gap('missing_telemetry_measurements', event['evidence_ref'], sid)
                # Claims and aggregate telemetry never manufacture invocations or loads.
                continue
            name = token(event.get('tool'))
            if not name or not isinstance(event.get('call'), str) or not event['call']:
                self.gap('missing_call_identity', event['evidence_ref'], sid)
                continue
            component = self.canonical('tool:' + name)
            accesses = self.accesses(event, s)
            components = [(component, 'tool', 'direct'), *accesses]
            calls[sid, event['call']] = (event, components)
            for comp, access, basis in components:
                if not comp:
                    continue
                state = 'invoked' if access in ('tool', 'activation') else 'unknown'
                self.observe(observations, event, comp, state, basis, access)
                c = counts[comp]
                c['invocations'] += access in ('tool', 'activation')
                c['sessions'].add(sid)
                c['basis'].add(basis)
                c['evidence_refs'].append(event['evidence_ref'])
                if event['timestamp'] and basis == 'direct':
                    c['last_observed_use'] = max(c['last_observed_use'] or event['timestamp'], event['timestamp'])
                if access in ('direct_file', 'shell_read'):
                    c['read_attempts'] += 1
                    c['inferred_reads'] += access == 'shell_read'
                    c['repeated_read_attempts'] += reads[sid, comp] > 0
                    reads[sid, comp] += 1
                # A search shows matching lines only: counted apart from reads.
                c['searches'] += access == 'shell_search'
        for key, (event, components) in calls.items():
            result = results.pop(key, None)
            outcome = result.get('success') if result else None
            if result is None:
                self.gap('missing_tool_result', event['evidence_ref'], key[0])
            elif outcome is None:
                self.gap('unknown_tool_outcome', result['evidence_ref'], key[0])
            for comp, access, basis in components:
                if not comp:
                    continue
                c = counts[comp]
                if outcome is True:
                    c['successes'] += 1
                    self.observe(observations, result, comp, 'successful', basis, access)
                    if access == 'direct_file':
                        c['reads'] += 1
                        c['repeated_reads'] += confirmed_reads[key[0], comp] > 0
                        confirmed_reads[key[0], comp] += 1
                        # Successful direct read establishes content delivery; not proof of influence.
                        self.observe(observations, result, comp, 'loaded', 'direct', access)
                elif outcome is False:
                    c['failures'] += 1
                else:
                    c['unknown_results'] += 1
        for result in results.values():
            self.gap('orphan_tool_result', result['evidence_ref'], result['session_id'])
        sessions = []
        for sid, s in selected.items():
            if not s['events']:
                continue
            if not s['ended'] or not s['transcript']:
                self.gap('incomplete_transcript', sid=sid)
            sessions.append(dict(id=sid, native_id=s['native_id'], parent_id=s['parent_id'], scope=s['scope'],
                                 first=s['first'], last=s['last'], events=s['events'],
                                 status='partial' if s['gaps'] else 'covered', gaps=sorted(s['gaps']),
                                 file_reads_partial=s['file_reads_partial'],
                                 evidence_refs=sorted(s['evidence_refs'])))
        denominator = len(sessions)
        covered = sum(s['status'] == 'covered' for s in sessions)
        # File-read metrics need sessions whose shell and read targets were all resolved.
        read_covered = sum(s['status'] == 'covered' and not s['file_reads_partial'] for s in sessions)
        metrics = []
        for comp, c in sorted(counts.items()):
            c['sessions'] = sorted(c['sessions'])
            c['basis'] = sorted(c['basis'])
            metrics.append(dict(component_id=comp, **c,
                                covered_sessions=read_covered if comp.startswith('file:') else covered,
                                selected_sessions=denominator, sessions_with_activity=len(c['sessions']),
                                activity_session_fraction=len(c['sessions']) / denominator if denominator else None))
        self.gap('retention_unknown')
        if self.aliases:
            self.gap('explicit_identity_mapping')
        retained = {r for s in sessions for r in s['evidence_refs']}
        retained.update(r for g in self.gaps for r in g['evidence_refs'])
        scoped_refs = [r for r in self.refs if r['kind'] == 'file' or r['id'] in retained]
        return dict(schema_version=VERSION, kind='analysis', adapter_profile=self.adapter.profile,
                    export_profile=Supplement.profile, scope=dict(project='project:.', worktrees=len(self.roots)-1),
                    window=dict(since=str(self.a.since) if self.a.since else None,
                                until=str(self.a.until) if self.a.until else None),
                    options=dict(min_sessions=self.a.min_sessions, low_use_threshold=self.a.low_use_threshold,
                                 relevant_sessions=self.a.relevant_session),
                    sessions=sessions, observations=observations, metrics=metrics,
                    evidence=scoped_refs, coverage=self.gaps,
                    totals=dict(selected_sessions=denominator, covered_sessions=covered,
                                file_read_covered_sessions=read_covered,
                                eligible_sessions=None, duplicate_events=self.duplicates,
                                bytes_read=self.total), findings=[])

    @staticmethod
    def observe(output, event, component, state, basis, access):
        output.append(dict(schema_version=VERSION, id='observation:' + str(len(output)+1),
                           component_id=component, state=state, basis=basis,
                           session_id=event['session_id'], event_id=event['event_id'], call_id=event.get('call'),
                           timestamp=event['timestamp'], confidence='high' if basis == 'direct' else 'low',
                           evidence_refs=[event['evidence_ref']], access=access,
                           measurements=event.get('measurements', {})))
