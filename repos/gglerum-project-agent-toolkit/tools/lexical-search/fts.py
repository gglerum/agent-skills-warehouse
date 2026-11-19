"""Local identifier/word FTS5 index, incremental refresh and ranked path lookup.

Stored tables are the portable default. Optional contentless_delete tables require
SQLite 3.43+. The CLI always uses stored tables. Deletion is by indexed rowid;
path and rowid metadata indexes avoid full scans during refresh.
"""
import hashlib, os, re, sqlite3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tokens as L

DEF = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:def|class|func|function|type|interface|const|let|var|struct|enum|trait|impl|fn|public|private|protected|static|#{1,6})\b[^\n]*", re.M)
TESTP = re.compile(r"(^|/)(tests?|test-d|__tests__|testdata)/|_test\.go$|(^|/)test_[^/]*\.py$|\.test\.[jt]sx?$")
IDENT = re.compile(r"`([^`]+)`|\"([^\"]+)\"|'([^']+)'|\b([A-Za-z]+_[A-Za-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]*|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*|[A-Z]{2,}[a-z][A-Za-z0-9]*)\b|\b([A-Za-z_][A-Za-z0-9_]*)\(")


def is_test(p): return bool(TESTP.search(p))
def esc(t): return '"' + t.replace('"', ' ') + '"'


def idents(q):
    out = []
    for m in IDENT.finditer(q):
        t = next(g for g in m.groups() if g).strip()
        if t and t not in out and not (len(m.groups()) and m.group(4) is None and m.group(5) is None and " " not in t and t.lower() in L.STOP): out.append(t)
    return out


def words(q):
    ts = []
    for t in L.terms(q):
        for w in L.split_ident(t).split():
            w = re.sub(r"[^A-Za-z0-9]", "", w).lower()
            if len(w) >= 2 and w not in L.STOP and w not in ts: ts.append(w)
    return ts


def build(corpus, files, db, contentless=False, path_in_words=True, detail_s="full"):
    if os.path.exists(db): os.remove(db)
    c = sqlite3.connect(db)
    cl = ", content='', contentless_delete=1" if contentless else ""
    c.execute(f"create virtual table d using fts5(path UNINDEXED, pathtok, raw, split, defs, tokenize='unicode61 remove_diacritics 2 tokenchars _'{cl})")
    c.execute(f"create virtual table s using fts5(split, tokenize='porter unicode61 remove_diacritics 2'{cl}, detail={detail_s})")
    c.execute("create table m(path primary key, h text, rid integer, mt integer, sz integer)")
    c.execute("create unique index m_rid on m(rid)")
    c.execute("create table meta(piw integer)"); c.execute("insert into meta values(?)", (int(path_in_words),))
    for f in files: upsert(c, corpus, f, force=True)
    c.commit(); return c


def upsert(c, corpus, f, force=False, st=None):
    p = os.path.join(corpus, f); st = st or os.stat(p)
    row = None if force else c.execute("select h, rid, mt, sz from m where path=?", (f,)).fetchone()
    raw = open(p, errors="ignore").read(); h = hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()
    if row and row[0] == h:
        c.execute("update m set mt=?, sz=? where path=?", (st.st_mtime_ns, st.st_size, f)); return False
    if row: _delete_rid(c, row[1])
    defs = "\n".join(m.group(0) for m in DEF.finditer(raw))
    piw = bool(c.execute("select piw from meta").fetchone()[0])
    cur = c.execute("insert into d(path, pathtok, raw, split, defs) values(?,?,?,?,?)", (f, f.replace("/", " ") + " " + L.split_ident(f), raw, "", defs))
    c.execute("insert into s(rowid, split) values(?,?)", (cur.lastrowid, (L.split_ident(f.replace("/", " ").replace(".", " ")) + "\n" if piw else "") + L.split_ident(raw)))
    c.execute("insert or replace into m values(?,?,?,?,?)", (f, h, cur.lastrowid, st.st_mtime_ns, st.st_size)); return True


def _delete_rid(c, rid):
    c.execute("delete from d where rowid=?", (rid,)); c.execute("delete from s where rowid=?", (rid,))


def _drop_missing(c, live):
    n = 0
    for p, rid in c.execute("select path, rid from m").fetchall():
        if p not in live: _delete_rid(c, rid); c.execute("delete from m where path=?", (p,)); n += 1
    return n


def refresh_hash(c, corpus, files):
    n = _drop_missing(c, set(files))
    for f in files: n += upsert(c, corpus, f)
    c.commit(); return n


def refresh_stat(c, corpus, files, last_index_ns):
    """Re-read a file only if (mtime_ns, size) differ, or its mtime is not older than the previous refresh (git 'racy' rule)."""
    n = _drop_missing(c, set(files)); known = {p: (mt, sz) for p, mt, sz in c.execute("select path, mt, sz from m")}
    for f in files:
        st = os.stat(os.path.join(corpus, f)); k = known.get(f)
        if k is None or k[0] != st.st_mtime_ns or k[1] != st.st_size or st.st_mtime_ns >= last_index_ns: n += upsert(c, corpus, f, st=st)
    c.commit(); return n


def search(c, q, k=10, use_idents=True, use_defs=True, nontest=True, bare_words=False):
    """Tiers: definition-line identifier hits, then whole-identifier hits, then stemmed word hits (BM25 inside each tier); test paths demoted within a tier.
    Returns (top-k paths, number of distinct candidates)."""
    ranked, seen = [], set()
    def add(rowids):
        paths = [(rid, c.execute("select path from m where rid=?", (rid,)).fetchone()[0]) for rid in rowids if rid not in seen]
        if nontest: paths = [x for x in paths if not is_test(x[1])] + [x for x in paths if is_test(x[1])]
        for rid, p in paths: ranked.append(p); seen.add(rid)
    ids = idents(q) if use_idents else []
    if ids:
        m = " OR ".join(esc(t) for t in ids)
        if use_defs: add([r[0] for r in c.execute("select rowid from d where defs match ? order by bm25(d, 0,1,1,1,1) limit 200", (m,))])
        add([r[0] for r in c.execute("select rowid from d where raw match ? order by bm25(d, 0,1,1,1,1) limit 200", (m,))])
    ws = words(q)
    if ws: add([r[0] for r in c.execute("select rowid from s where s match ? order by bm25(s) limit 200", (" OR ".join((w if bare_words else esc(w)) for w in ws),))])
    return ranked[:k], len(ranked)
