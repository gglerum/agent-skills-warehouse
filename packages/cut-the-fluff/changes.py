"""Explicit approval, project-local exact replacements and recoverable journals.

No patch interpreter, shell commands, implicit approval or global write roots.
The journal is private recovery data, not an authentication boundary.
"""
from contextlib import ExitStack
import base64
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

VERSION = '1.0'
PRIVATE_STATE = ('recovery directory must be private (mode 0700) and owned by current user;'
                 ' on WSL put --state on the Linux filesystem, not /mnt/<drive>')
LIMIT = 16 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode())


def proposal(finding_id, path, before, old, new):
    after = before.replace(old, new, 1)
    value = dict(finding_id=finding_id, scope='project', path=path,
                 before_sha256=sha(before.encode()), after_sha256=sha(after.encode()), old=old, new=new)
    return dict(value, change_sha256=fingerprint(value))


def add_arguments(sub):
    for command in ('apply', 'rollback'):
        p = sub.add_parser(command, help='Approved project edits' if command == 'apply' else 'Recover an existing journal without overwriting later edits')
        p.add_argument('--project', required=True)
        p.add_argument('--state', required=True, help='Private recovery directory outside the project; new for first apply')
        if command == 'apply':
            p.add_argument('--report', required=True)
            p.add_argument('--approval', required=True, help='Explicit user-reviewed approval JSON; never generated automatically')


def regular(path):
    """Bounded no-follow read; reject links, hardlinks and special files."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT:
            raise ValueError('unsupported file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError('file limit')
        return data, info
    finally:
        os.close(fd)


def load(path):
    data, _ = regular(path)
    return json.loads(data), sha(data)


def target(root, name):
    p = Path(name)
    if not name or p.is_absolute() or '..' in p.parts or p.as_posix() != name or name == '.':
        raise ValueError('expected canonical relative path')
    if any(part in {'.git', '.cut-the-fluff'} for part in p.parts):
        raise ValueError('reserved path')
    current = root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('symlink target or ancestor')
    if root not in current.resolve(strict=True).parents:
        raise ValueError('outside project')
    return current


def metadata(info):
    return dict(mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid)


def xattrs(path):
    # Filesystems without xattr support (some WSL drvfs/9p, FAT) cannot hold any.
    try:
        return os.listxattr(path, follow_symlinks=False)
    except OSError as error:
        if error.errno in (errno.ENOTSUP, errno.EOPNOTSUPP):
            return []
        raise


def snapshot(root, entry):
    data, info = regular(target(root, entry['path']))
    if xattrs(target(root, entry['path'])):
        raise ValueError('extended attributes require a separately reviewed editor')
    if info.st_uid != os.geteuid() or info.st_mode & 0o7000:
        raise ValueError('unsupported ownership or special permissions')
    if metadata(info) != entry['metadata']:
        raise ValueError('permissions or ownership changed')
    return data, info


def replace(root, entry, expected, desired):
    path = target(root, entry['path'])
    data, initial = snapshot(root, entry)
    if sha(data) != expected:
        raise ValueError('concurrent content change')
    fd, temporary = tempfile.mkstemp(prefix='.cut-the-fluff-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(desired)
            if metadata(os.fstat(stream.fileno()))['gid'] != entry['metadata']['gid']:
                os.fchown(stream.fileno(), -1, entry['metadata']['gid'])
            os.fchmod(stream.fileno(), entry['metadata']['mode'])
            stream.flush()
            os.fsync(stream.fileno())
        if xattrs(temporary):
            raise ValueError('inherited extended attributes require manual review')
        # Recheck both bytes and identity immediately before the atomic replacement.
        current, latest = snapshot(root, entry)
        if sha(current) != expected or (latest.st_dev, latest.st_ino, latest.st_mtime_ns, latest.st_ctime_ns) != (initial.st_dev, initial.st_ino, initial.st_mtime_ns, initial.st_ctime_ns):
            raise ValueError('concurrent edit')
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(state, journal):
    fd, temporary = tempfile.mkstemp(prefix='.journal-', dir=state)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(journal, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, state / 'manifest.json')
        sync_directory(state)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_journal(j, root):
    from report import validate
    defs = json.loads(Path(__file__).with_name('schema.json').read_text())['$defs']
    validate(j, defs['change_manifest'], defs)
    if j.get('schema_version') != VERSION or j.get('kind') != 'change_manifest' or j.get('project') != str(root):
        raise ValueError('journal identity')
    if j.get('status') not in ('prepared', 'applied', 'rolled_back') or not j.get('entries'):
        raise ValueError('journal status')
    paths = set()
    for e in j['entries']:
        if e['path'] in paths:
            raise ValueError('duplicate journal path')
        paths.add(e['path'])
        for side in ('before', 'after'):
            data = base64.b64decode(e[side + '_base64'], validate=True)
            if sha(data) != e[side + '_sha256']:
                raise ValueError('corrupt backup')
        if e['before_sha256'] == e['after_sha256']:
            raise ValueError('empty change')


def run(a):
    with ExitStack() as resources:
        return transaction(a, resources)


def lock(state, resources):
    import fcntl
    fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    resources.callback(os.close, fd)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def transaction(a, resources):
    if os.name != 'posix' or not hasattr(os, 'listxattr'):
        raise ValueError('mutation requires POSIX with extended-attribute inspection')
    root = Path(a.project).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('project directory required')
    raw_state = Path(a.state).absolute()
    # Refuse symlink ancestors, including for an existing recovery directory.
    if any(p.is_symlink() for p in (raw_state, *raw_state.parents)):
        raise ValueError('symlink recovery path')
    state = raw_state.resolve()
    if state == root or root in state.parents or state in root.parents:
        raise ValueError('recovery directory must be separate from project')
    selected = None
    if a.command == 'apply':
        report, report_hash = load(a.report)
        approval, _ = load(a.approval)
        from report import validate
        defs = json.loads(Path(__file__).with_name('schema.json').read_text())['$defs']
        validate(report, defs['report'], defs)
        validate(approval, defs['approval'], defs)
        if approval['project'] != str(root) or approval['report_sha256'] != report_hash:
            raise ValueError('approval project/report mismatch')
        choices = report.get('changes', [])
        findings = {f['id']: f for f in report['findings']}
        if len(findings) != len(report['findings']):
            raise ValueError('duplicate finding identity')
        selected, seen = [], set()
        for choice in approval['selections']:
            matches = [c for c in choices if c['finding_id'] == choice['finding_id'] and c['change_sha256'] == choice['change_sha256']]
            if len(matches) != 1:
                raise ValueError('selection does not identify one exact change')
            c = matches[0]
            unsigned = {k: v for k, v in c.items() if k != 'change_sha256'}
            f = findings.get(c['finding_id'])
            if fingerprint(unsigned) != c['change_sha256'] or c['scope'] != 'project' or not f or f['action'] == 'keep' or not f['proposed_patch']:
                raise ValueError('unreviewed or invalid proposal')
            if c['path'] in seen:
                raise ValueError('same-file alternatives require a fresh combined report')
            seen.add(c['path'])
            selected.append(c)
        if not selected:
            raise ValueError('approval must select changes')
        binding = dict(report_sha256=report_hash, approval_sha256=fingerprint(approval), selections=approval['selections'])
    if state.exists():
        info = state.stat()
        if not state.is_dir() or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError(PRIVATE_STATE)
        lock(state, resources)
        journal, _ = load(state / 'manifest.json')
        validate_journal(journal, root)
        if selected is not None:
            if journal['binding'] != binding or journal['status'] != 'applied':
                raise ValueError('existing or incomplete transaction; use rollback')
            for e in journal['entries']:
                data, _ = snapshot(root, e)
                if sha(data) != e['after_sha256']:
                    raise ValueError('applied content changed; refusing replay')
            return dict(status='already_applied', changed_files=0)
    else:
        if selected is None:
            raise ValueError('no recovery journal')
        entries = []
        for c in selected:
            data, info = regular(target(root, c['path']))
            text = data.decode('utf-8')
            if sha(data) != c['before_sha256'] or not c['old'] or c['old'] == c['new'] or text.count(c['old']) != 1:
                raise ValueError('stale or ambiguous replacement')
            after = text.replace(c['old'], c['new'], 1).encode()
            if sha(after) != c['after_sha256']:
                raise ValueError('replacement hash mismatch')
            entry = dict(path=c['path'], finding_id=c['finding_id'], change_sha256=c['change_sha256'],
                         metadata=metadata(info), before_sha256=sha(data), after_sha256=sha(after),
                         before_base64=base64.b64encode(data).decode(), after_base64=base64.b64encode(after).decode())
            snapshot(root, entry)
            entries.append(entry)
        journal = dict(schema_version=VERSION, kind='change_manifest', project=str(root), status='prepared', binding=binding, entries=entries,
                       recovery='Run inventory.py rollback --project PROJECT --state THIS_DIRECTORY. Keep backups private. Resolve conflicts manually; never overwrite later edits.')
        # Bound journal size so recovery always accepts what apply writes.
        if len((json.dumps(journal, indent=2) + '\n').encode()) > LIMIT:
            raise ValueError('journal limit')
        state.mkdir(mode=0o700)
        # Some filesystems (WSL /mnt/<drive>) ignore the mode; refuse before any project write.
        if stat.S_IMODE(state.stat().st_mode) != 0o700:
            state.rmdir()
            raise ValueError(PRIVATE_STATE)
        lock(state, resources)
        save(state, journal)  # Durable backups precede every project write.
        sync_directory(state.parent)
    if a.command == 'rollback':
        pending = []
        for e in journal['entries']:
            data, _ = snapshot(root, e)
            current = sha(data)
            if current == e['before_sha256']:
                continue
            if journal['status'] == 'rolled_back' or current != e['after_sha256']:
                raise ValueError('rollback conflict; later content preserved')
            pending.append(e)
        for e in reversed(pending):
            replace(root, e, e['after_sha256'], base64.b64decode(e['before_base64'], validate=True))
        journal['status'] = 'rolled_back'
        save(state, journal)
        return dict(status='rolled_back', changed_files=len(pending))
    for e in journal['entries']:
        replace(root, e, e['before_sha256'], base64.b64decode(e['after_base64'], validate=True))
    journal['status'] = 'applied'
    save(state, journal)
    return dict(status='applied', changed_files=len(journal['entries']))
