"""Static shell-text analysis for file-access inference. Never executes, expands or opens anything.

`file_accesses(command, cwd, home, expand)` returns (accesses, reason). `accesses` are
(path, kind) pairs: kind 'read' for content readers (cat, head, sed, ...) and
'search' for searchers (grep, rg, ...), whose output shows only matching lines.
Paths resolve against the tracked working directory; `~` and `$HOME` resolve only
against an explicit `home`. `for NAME in WORDS` binds NAME for the loop body. Globs
resolve only through a caller-supplied `expand` matcher. `reason` is set when an operand, the working directory,
or the command itself depends on runtime values ($VAR, $(...), globs, eval, xargs,
...). Command substitutions are parsed as commands too, because they run.
"""
import posixpath
import re

READERS = {'cat', 'tac', 'nl', 'less', 'more', 'bat', 'batcat', 'head', 'tail', 'sed'}
SEARCHERS = {'grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack'}
# Commands whose first operand is a script or pattern, unless an option supplies it.
PATTERN_FIRST = SEARCHERS | {'sed'}
PATTERN_OPTIONS = {'-e', '-f', '--expression', '--file', '--regexp'}
# Options that consume the following word, per command.
OPTION_ARGS = {'head': {'-n', '-c', '--lines', '--bytes'},
               'tail': {'-n', '-c', '--lines', '--bytes', '--pid', '-s', '--sleep-interval'},
               'sed': {'-e', '-f', '-l', '--expression', '--file', '--line-length'},
               'nl': {'-b', '-d', '-f', '-h', '-i', '-l', '-n', '-s', '-v', '-w'},
               'bat': {'-l', '--language', '-r', '--line-range', '-H', '--highlight-line',
                       '--style', '--theme', '--paging', '--color', '-m', '--map-syntax'},
               'less': {'-b', '-h', '-j', '-k', '-o', '-O', '-p', '-P', '-t', '-T', '-x', '-y', '-z'},
               'grep': {'-e', '-f', '-m', '-A', '-B', '-C', '-d', '-D', '--regexp', '--file',
                        '--max-count', '--after-context', '--before-context', '--context',
                        '--include', '--exclude', '--exclude-dir', '--label', '--color', '--colour'},
               'rg': {'-e', '-f', '-g', '-t', '-T', '-m', '-A', '-B', '-C', '-M', '-j', '-d', '-E', '-r',
                      '--regexp', '--file', '--glob', '--iglob', '--type', '--type-not', '--type-add',
                      '--max-count', '--after-context', '--before-context', '--context',
                      '--max-columns', '--threads', '--max-depth', '--encoding', '--replace',
                      '--sort', '--sortr', '--color', '--colors', '--max-filesize', '--pre',
                      '--pre-glob', '--engine', '--context-separator', '--path-separator'},
               'ag': {'-A', '-B', '-C', '-G', '-g', '-m', '--depth', '--ignore', '--file-search-regex'},
               'ack': {'-A', '-B', '-C', '-m', '--type', '--ignore-dir', '--ignore-file'}}
OPTION_ARGS['batcat'] = OPTION_ARGS['bat']
OPTION_ARGS['egrep'] = OPTION_ARGS['fgrep'] = OPTION_ARGS['grep']
# Searcher modes that list paths or files instead of showing content.
LISTING = {'--files', '--type-list'}
HOME = re.compile(r'\$(HOME(?!\w)|\{HOME\})')
SIMPLE_PARAMETER = re.compile(r'\$(?:([A-Za-z_]\w*)|\{([A-Za-z_]\w*)\})')
MAX_EXPANSIONS = 64
WRAPPERS = {'command', 'builtin', 'exec', 'nohup', 'time', 'sudo', 'env', 'nice', 'stdbuf', 'timeout'}
KEYWORDS = {'if', 'then', 'else', 'elif', 'fi', 'do', 'done', 'while', 'until', '!', '{', '}'}
DYNAMIC_COMMANDS = {'eval', 'source', '.', 'case', 'select', 'function', 'coproc', 'alias'}
SHELLS = {'sh', 'bash', 'dash', 'zsh'}
REDIRECT = re.compile(r'\d*(<<<|<<-|<<|&>>|&>|>>|>&|<&|>\||<>|>|<)')
MAX_DEPTH = 4


class Unparsed(ValueError):
    pass


class Word:
    def __init__(self):
        self.text, self.opaque, self.glob, self.quoted, self.subs = '', False, False, False, []
        self.home = False  # Starts with ~ or $HOME; resolvable only with an explicit home.
        self.vars = []  # (offset in text, name) for plain $NAME / ${NAME} references.
        self.quoted_meta = False  # Quoted *, ? or [ make glob matching ambiguous.

    @property
    def dynamic(self):
        return self.opaque or bool(self.vars)


def tokenize(src, pos=0, stop=None, depth=0):
    """Return (tokens, end). Tokens are ('op', text) or ('word', Word)."""
    if depth > MAX_DEPTH:
        raise Unparsed('nesting')
    tokens, pending, word = [], [], None
    n = len(src)

    def flush():
        nonlocal word
        if word is not None:
            tokens.append(('word', word))
            word = None

    def cur():
        nonlocal word
        if word is None:
            word = Word()
        return word

    def substitution(i, closer):
        inner, end = tokenize(src, i, closer, depth + 1)
        w = cur()
        w.opaque = True
        w.subs.append(inner)
        return end

    while pos < n:
        c = src[pos]
        if stop == ')' and c == ')' and not _open_parens(tokens):
            flush()
            return tokens, pos + 1
        if stop == '`' and c == '`':
            flush()
            return tokens, pos + 1
        if c == '\\':
            if pos + 1 < n and src[pos + 1] == '\n':
                pos += 2
                continue
            if pos + 1 < n:
                cur().text += src[pos + 1]
                word.quoted = True
                word.quoted_meta |= src[pos + 1] in '*?['
            pos += 2
            continue
        if c == "'":
            end = src.find("'", pos + 1)
            if end < 0:
                raise Unparsed('quote')
            w = cur()
            w.text += src[pos + 1:end]
            w.quoted = True
            w.quoted_meta |= bool(re.search(r'[*?[]', src[pos + 1:end]))
            pos = end + 1
            continue
        if c == '"':
            pos += 1
            w = cur()
            w.quoted = True
            while True:
                if pos >= n:
                    raise Unparsed('quote')
                d = src[pos]
                if d == '"':
                    pos += 1
                    break
                if d == '\\' and pos + 1 < n:
                    if src[pos + 1] in '$`"\\\n':
                        w.text += src[pos + 1] if src[pos + 1] != '\n' else ''
                    else:
                        w.text += src[pos:pos + 2]
                    pos += 2
                elif src.startswith('$((', pos):
                    w.opaque = True
                    pos = _skip_balanced(src, pos + 1)
                elif src.startswith('$(', pos):
                    pos = substitution(pos + 2, ')')
                elif d == '`':
                    pos = substitution(pos + 1, '`')
                elif d == '$' and pos + 1 < n and re.match(r'[\w{@*#?$!-]', src[pos + 1]):
                    pos = _parameter(src, pos, w)
                else:
                    w.text += d
                    w.quoted_meta |= d in '*?['
                    pos += 1
            continue
        if c == '$':
            if src.startswith('$((', pos):
                cur().opaque = True
                pos = _skip_balanced(src, pos + 1)
            elif src.startswith('$(', pos):
                pos = substitution(pos + 2, ')')
            elif src.startswith("$'", pos) or src.startswith('$"', pos):
                cur().opaque = True  # Locale/ANSI-C strings: treat as runtime values.
                pos += 1
            elif pos + 1 < n and re.match(r'[\w{@*#?$!-]', src[pos + 1]):
                pos = _parameter(src, pos, cur())
            else:
                cur().text += c
                pos += 1
            continue
        if c == '`':
            pos = substitution(pos + 1, '`')
            continue
        if c in '<>' and src.startswith('(', pos + 1) and word is None:
            # Process substitution runs a command and yields a dynamic path.
            pos = substitution(pos + 2, ')')
            continue
        if c in ' \t':
            flush()
            pos += 1
            continue
        if c == '#' and word is None:
            while pos < n and src[pos] != '\n':
                pos += 1
            continue
        if c == '\n':
            flush()
            tokens.append(('op', '\n'))
            pos += 1
            for delim, strip in pending:
                pos = _skip_heredoc(src, pos, delim, strip)
            pending = []
            continue
        m = REDIRECT.match(src, pos)
        if m and (word is None or word.text.isdigit() and not word.quoted and not word.dynamic and m.start() == pos):
            if word is not None:  # fd prefix such as 2>
                word = None
            flush()
            op = re.sub(r'^\d+', '', m.group(0))
            tokens.append(('redir', op))
            pos = m.end()
            if op in ('<<', '<<-'):
                while pos < n and src[pos] in ' \t':
                    pos += 1
                start = pos
                while pos < n and src[pos] not in ' \t\n;&|<>()':
                    pos += 1
                delim = src[start:pos].replace("'", '').replace('"', '').replace('\\', '')
                if not delim:
                    raise Unparsed('heredoc')
                pending.append((delim, op == '<<-'))
                tokens.append(('word', _literal(delim)))
            continue
        two = src[pos:pos + 2]
        if two in ('&&', '||', '|&', ';;'):
            flush()
            tokens.append(('op', two))
            pos += 2
            continue
        if c in ';&|()':
            flush()
            tokens.append(('op', c))
            pos += 1
            continue
        w = cur()
        if c in '*?[':
            w.glob = True
        if c == '~' and w.text == '' and not w.quoted and not w.home and not w.dynamic:
            if pos + 1 >= n or src[pos + 1] in '/ \t\n;&|()<>':
                w.home = True  # ~ or ~/path; ~user stays dynamic.
                pos += 1
                continue
            w.opaque = True
        if c == '{' and re.match(r'\{[^{}\s]*(,|\.\.)[^{}\s]*\}', src[pos:]):
            w.glob = True  # Brace expansion yields several runtime paths.
        w.text += c
        pos += 1
    if stop:
        raise Unparsed('unterminated')
    if pending:
        raise Unparsed('heredoc')
    flush()
    return tokens, pos


def _open_parens(tokens):
    depth = 0
    for kind, value in tokens:
        if kind == 'op' and value == '(':
            depth += 1
        elif kind == 'op' and value == ')':
            depth -= 1
    return depth > 0


def _literal(text):
    w = Word()
    w.text = text
    return w


def _parameter(src, pos, word):
    """Consume a parameter expansion. A leading $HOME marks the word home-relative."""
    m = HOME.match(src, pos)
    if m and word.text == '' and not (word.home or word.dynamic or word.subs):
        word.home = True
        return m.end()
    m = SIMPLE_PARAMETER.match(src, pos)
    if m:
        word.vars.append((len(word.text), m.group(1) or m.group(2)))
        return m.end()
    word.opaque = True
    return _skip_parameter(src, pos)


def _skip_parameter(src, pos):
    pos += 1
    if src[pos] == '{':
        end = src.find('}', pos)
        if end < 0:
            raise Unparsed('parameter')
        return end + 1
    if re.match(r'[@*#?$!0-9-]', src[pos]):
        return pos + 1
    m = re.compile(r'\w+').match(src, pos)
    return m.end()


def _skip_balanced(src, pos):
    depth = 0
    while pos < len(src):
        if src[pos] == '(':
            depth += 1
        elif src[pos] == ')':
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    raise Unparsed('arithmetic')


def _skip_heredoc(src, pos, delim, strip):
    while pos < len(src):
        end = src.find('\n', pos)
        line = src[pos:] if end < 0 else src[pos:end]
        pos = len(src) if end < 0 else end + 1
        if (line.lstrip('\t') if strip else line) == delim:
            return pos
    raise Unparsed('heredoc')


def commands(tokens):
    """Split tokens into simple commands: (words, redirects), or 'push'/'pop' for subshells."""
    result, words, redirs = [], [], []
    i = 0
    while i < len(tokens):
        kind, value = tokens[i]
        if kind == 'word':
            words.append(value)
        elif kind == 'redir':
            target = tokens[i + 1][1] if i + 1 < len(tokens) and tokens[i + 1][0] == 'word' else None
            if target is None:
                raise Unparsed('redirect')
            redirs.append((value, target))
            i += 1
        else:
            if words or redirs:
                result.append((words, redirs))
            words, redirs = [], []
            if value in ('(', ')'):
                result.append(('push' if value == '(' else 'pop', None))
            elif value == ';;':
                raise Unparsed('case')
        i += 1
    if words or redirs:
        result.append((words, redirs))
    return result


def file_accesses(command, cwd, home=None, expand=None):
    """Return ([(path, 'read'|'search')], reason); reason is None when every operand resolved.

    `expand(absolute_pattern)` is an optional caller-supplied glob matcher returning a
    list of paths ([] means resolved with nothing to attribute), or None when it
    declines. Without it, glob operands are unresolved.
    """
    found, state = [], dict(reason=None, home=home, expand=expand, loops=[])
    try:
        tokens, _ = tokenize(command)
        _walk(tokens, cwd, found, state, 0)
    except (Unparsed, IndexError, AttributeError):
        return [], 'unparsed'
    return found, state['reason']


def _binding(state, name):
    for frame in reversed(state['loops']):
        if name in frame:
            return frame[name]
    return None


def _values(word, cwd, state):
    """Expand one word to strings: loop variables, home, then globs. Return (values, reason)."""
    if word.opaque:
        return None, 'dynamic_operand'
    texts = [word.text]
    for offset, name in reversed(word.vars):  # Right to left keeps earlier offsets valid.
        values = _binding(state, name)
        if values is None:
            return None, 'dynamic_operand'
        texts = [t[:offset] + v + t[offset:] for v in values for t in texts]
        if len(texts) > MAX_EXPANSIONS:
            return None, 'dynamic_operand'
    if word.home:
        if not state['home']:
            return None, 'unknown_home'
        texts = [state['home'] + t for t in texts]
    if not word.glob:
        return texts, None
    if word.quoted_meta or not state['expand']:
        return None, 'dynamic_operand'
    matches = []
    for text in texts:
        if not posixpath.isabs(text) and not cwd:
            return None, 'unknown_cwd'
        found = state['expand'](posixpath.normpath(posixpath.join(cwd or '/', text)))
        if found is None:
            return None, 'dynamic_operand'
        matches += found
    return matches, None


def _resolve(word, cwd, state):
    """Return (absolute paths, None) or (None, reason)."""
    values, reason = _values(word, cwd, state)
    if values is None:
        return None, reason
    if not cwd and not all(posixpath.isabs(v) for v in values):
        return None, 'unknown_cwd'
    return [posixpath.normpath(posixpath.join(cwd or '/', v)) for v in values], None


def _walk(tokens, cwd, found, state, depth):
    if depth > MAX_DEPTH:
        raise Unparsed('nesting')
    stack = []
    for words, redirs in commands(tokens):
        if words == 'push':
            stack.append(cwd)
            continue
        if words == 'pop':
            cwd = stack.pop() if stack else cwd
            continue
        for word in words:
            for sub in word.subs:
                _walk(sub, cwd, found, state, depth + 1)
        for _, target in redirs:
            for sub in target.subs:
                _walk(sub, cwd, found, state, depth + 1)
        cwd = _simple(list(words), redirs, cwd, found, state, depth)


def _simple(words, redirs, cwd, found, state, depth):
    while words and not words[0].quoted and words[0].text in KEYWORDS:
        keyword = words.pop(0).text
        if keyword in ('while', 'until'):
            state['loops'].append({})  # Keeps frames paired with `done`.
        elif keyword == 'done' and state['loops']:
            state['loops'].pop()
    while words and re.fullmatch(r'[A-Za-z_]\w*=.*', words[0].text) and not words[0].quoted:
        words.pop(0)
    if words and words[0].text == 'for' and not words[0].quoted:
        # Loop header: bind the variable to its list so the body can be resolved.
        name = words[1].text if len(words) > 1 else ''
        values = None
        if len(words) > 2 and words[2].text == 'in':
            values = []
            for word in words[3:]:
                expanded, _ = _values(word, cwd, state)
                if expanded is None:
                    values = None
                    break
                values += expanded
        state['loops'].append({name: values})
        return cwd
    via_xargs = False
    while words:
        name = posixpath.basename(words[0].text)
        if name == 'xargs':
            via_xargs = True
            words = _drop_options(words[1:], {'-I', '-i', '-n', '-P', '-L', '-d', '-E', '-s', '-a'})
        elif name in WRAPPERS:
            rest = _drop_options(words[1:], {'-u', '-g', '-n', '-i', '-o', '-e', '-k', '-s', '-C', '-D'})
            while rest and re.fullmatch(r'[A-Za-z_]\w*=.*', rest[0].text):
                rest = rest[1:]
            if name == 'timeout' and rest:
                rest = rest[1:]
            words = rest
        else:
            break
    if not words:
        return cwd
    head = words[0]
    if head.text in ('[', '[[') and not head.quoted:
        return cwd
    if head.dynamic or head.glob or head.home:
        state['reason'] = 'dynamic_command'
        return cwd
    name = posixpath.basename(head.text)
    if name in DYNAMIC_COMMANDS:
        state['reason'] = 'dynamic_command'
        return cwd
    if name in ('cd', 'pushd'):
        args = [w for w in words[1:] if not w.text.startswith('-') or w.text == '-']
        if not args:
            return state['home']  # Bare cd goes home.
        if args[0].text == '-':
            return None
        paths, _ = _resolve(args[0], cwd, state)
        return paths[0] if paths and len(paths) == 1 else None
    if name == 'popd':
        return None
    if name in SHELLS:
        args = words[1:]
        for i, w in enumerate(args):
            if w.text.startswith('-') and 'c' in w.text and not w.text.startswith('--'):
                if i + 1 >= len(args) or args[i + 1].dynamic:
                    state['reason'] = 'dynamic_command'
                else:
                    tokens, _ = tokenize(args[i + 1].text, depth=depth + 1)
                    _walk(tokens, cwd, found, state, depth + 1)
                return cwd
        return cwd  # A script file is an unknown program, like any other.
    if name == 'find':
        for i, w in enumerate(words):
            if w.text in ('-exec', '-execdir', '-ok', '-okdir') and i + 1 < len(words):
                if posixpath.basename(words[i + 1].text) in READERS | SEARCHERS:
                    state['reason'] = 'find_exec'
        return cwd
    if name not in READERS | SEARCHERS:
        return cwd
    if via_xargs:
        state['reason'] = 'xargs_operand'
        return cwd
    operands = _operands(name, words[1:])
    if operands is None:
        return cwd  # sed -i edits files; listing modes show no content.
    for op, target in redirs:
        if op == '<':
            operands.append(target)
    kind = 'read' if name in READERS else 'search'
    for word in operands:
        if word.text == '-' and not word.dynamic:
            continue
        paths, reason = _resolve(word, cwd, state)
        if paths is None:
            state['reason'] = reason
        else:
            found.extend((path, kind) for path in paths)
    return cwd


def _drop_options(words, with_arg):
    i = 0
    while i < len(words) and words[i].text.startswith('-') and words[i].text != '-':
        if words[i].text == '--':
            return words[i + 1:]
        i += 2 if words[i].text in with_arg else 1
    return words[i:]


def _operands(name, args):
    takes = OPTION_ARGS.get(name, set())
    result, script, explicit_script, i = [], name in PATTERN_FIRST, False, 0
    while i < len(args):
        text = args[i].text
        if text == '--':
            result.extend(args[i + 1:])
            break
        if text.startswith('-') and text != '-' and not args[i].dynamic:
            if name == 'sed' and (text.startswith('-i') or text.startswith('--in-place')):
                return None
            if name in SEARCHERS and text.split('=', 1)[0] in LISTING:
                return None
            option = text.split('=', 1)[0]
            bundled = name in PATTERN_FIRST and re.match(r'-[a-zA-Z]*[ef]$', text)
            if name in PATTERN_FIRST and (option in PATTERN_OPTIONS or bundled or
                                          re.match(r'-[ef].', text)):
                explicit_script = True
            if ('=' not in text and option in takes) or bundled:
                i += 1
            i += 1
            continue
        if script and not explicit_script:
            script = False  # First operand is the sed script or search pattern.
        else:
            result.append(args[i])
        i += 1
    return result
