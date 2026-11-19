import re

STOP = set("a an the of in on to is are was were be by for from with and or not do does did what which where how when who whom find file files code that this these those it its as at into out up down over after before while than then there their them they you your i we our us after if any all each both some such no nor only own same so too very can will just should now function class method defined defines definition documentation document explaining explains explain about used usage usages calls call implemented implement produces produce text error contains contain library source".split())

def split_ident(s):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    return s.replace("_", " ")

def terms(query):
    toks = re.findall(r"[A-Za-z_#][A-Za-z0-9_\-#]*", query)
    out = []
    for t in toks:
        tl = t.lower()
        if tl in STOP or len(tl) < 3: continue
        if t not in out: out.append(t)
    return out
