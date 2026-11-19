#!/usr/bin/env python3
"""Compare screens with a design export (PDF): render, measure, diff.

Usage: python3 compare.py [--config FILE] <command> ...

  pages                         contact sheet of all pages of the design PDF, numbered
  render <page> [--dpi N]       render one PDF page to PNG
  spec <page>                   positions, sizes, colours and fonts of text and filled boxes measured in a PDF page
  shot <target> [--name N]      screenshot a page at the configured viewport
  measure <target> [--name N]   text and box positions measured in the browser
  compare <page> <target>       design page vs a page: side-by-side image plus a table of differences in px
  all [--only KIND] [--check] [--save-baseline] [--strict]   every screen in the screens file
  serve [start|stop|restart]    local static server on the serve root (needed by everything that opens a page)

<target> is a path under the serve root ('/prototypes/x.html'), a full http(s) URL, `auth:/route` (the application at
`app_url`, sent with the cookies of the session file) or `anon:/route` (the application without a session).

Python 3.10+ standard library, a Chrome/Chromium binary (CHROME_BIN or google-chrome/chromium on PATH) and poppler
(pdftoppm, pdftotext, pdftocairo, pdffonts) either on PATH or behind `poppler_prefix` (a command prefix, for example a
container run). Output goes to the configured output directory (not for version control). The server listens on
127.0.0.1 only and serves the whole serve root: do not point it at a directory with secrets.
"""
import argparse
import difflib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULTS = {
    "design_pdf": "design/design-export.pdf",
    "screens_file": "design/screens.json",
    "baseline_file": "design/baseline.json",
    "out_dir": "reports/design",
    "serve_root": ".",
    "serve_port": 8001,
    "viewport": [393, 852],
    "position_tolerance": 6.0,
    "size_tolerance": 8.0,
    "app_url": None,  # base URL of a running application for auth: and anon: targets
    "session_file": None,  # JSON {cookie name: value} written by the project's own login step; default <out_dir>/session.json
    "poppler_prefix": [],
    "path_rewrites": [],  # [[regex, replacement], ...] applied to request paths of the static server
    "settle_ms": 1800,
    "command": "python3 compare.py",
}

CFG = {}
ROOT = Path.cwd()
OUT = PDF = SCREENS = BASELINE = SESSION = Path()
W, H = 393, 852
WIN_W, WIN_H = 500, 960  # headless Chrome will not make a window narrower than 500 px; the iframe is the real viewport
POS_TOL, SIZE_TOL = 6.0, 8.0
BASE = ""
APP = ""


def die(msg):
    print(f"design-compare: {msg}", file=sys.stderr)
    sys.exit(2)


def configure(config_path):
    global CFG, ROOT, OUT, PDF, SCREENS, BASELINE, SESSION, W, H, WIN_W, WIN_H, POS_TOL, SIZE_TOL, BASE, APP
    CFG = dict(DEFAULTS)
    ROOT = Path.cwd()
    if config_path:
        path = Path(config_path).resolve()
        CFG.update(json.loads(path.read_text(encoding="utf-8")))
        ROOT = path.parent
    OUT = ROOT / CFG["out_dir"]
    PDF, SCREENS, BASELINE = ROOT / CFG["design_pdf"], ROOT / CFG["screens_file"], ROOT / CFG["baseline_file"]
    SESSION = ROOT / (CFG["session_file"] or f"{CFG['out_dir']}/session.json")
    W, H = (int(v) for v in CFG["viewport"])
    WIN_W, WIN_H = max(500, W), max(960, H + 108)
    POS_TOL, SIZE_TOL = float(CFG["position_tolerance"]), float(CFG["size_tolerance"])
    BASE = f"http://127.0.0.1:{int(CFG['serve_port'])}"
    APP = (CFG["app_url"] or "").rstrip("/")


# ---------------------------------------------------------------- helpers
def rel(p):
    return str(Path(p).resolve().relative_to(ROOT.resolve()))


def poppler(*args):
    """Run a poppler command (from the serve root, with relative paths), optionally behind a command prefix."""
    cmd = [*CFG["poppler_prefix"], *args]
    if not shutil.which(cmd[0]):
        die(f"{cmd[0]} not found (install poppler, or set poppler_prefix)")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        die(f"command failed: {' '.join(args)}\n{r.stderr[-600:]}")
    return r.stdout


def chrome():
    for n in (os.environ.get("CHROME_BIN"), "google-chrome", "chromium", "chromium-browser"):
        p = n and shutil.which(n)
        if p:
            return p
    die("no Chrome/Chromium found (set CHROME_BIN)")


def chrome_run(*args, timeout=60):
    return subprocess.run([chrome(), "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--password-store=basic", *args],
                          capture_output=True, text=True, timeout=timeout)


def url_of(target):
    """A path under the serve root, a full http(s) URL, or auth:/anon: routes of the application."""
    if target.startswith("http"):
        return target
    for prefix in ("auth", "anon"):
        if target.startswith(prefix + ":"):
            return f"{BASE}/{prefix}/" + target[len(prefix) + 1:].lstrip("/")
    return BASE + "/" + target.lstrip("/")


def parse_rgb(s):
    m = re.search(r"rgba?\(([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)(?:[, /]+([\d.]+))?", s or "")
    if not m:
        return None
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    return (round(float(m.group(1))), round(float(m.group(2))), round(float(m.group(3))), a)


def close(c1, c2, tol=6):
    return c1 is not None and c2 is not None and all(abs(a - b) <= tol for a, b in zip(c1[:3], c2[:3]))


def hexc(c):
    return "#%02x%02x%02x" % tuple(c[:3]) if c else "?"


# ---------------------------------------------------------------- static server
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def app_cookie():
    try:
        return "; ".join(f"{k}={v}" for k, v in json.loads(SESSION.read_text()).items())
    except (OSError, ValueError):
        return ""


class Handler(SimpleHTTPRequestHandler):
    """Serves the serve root and proxies the application, so a real page can be measured in the iframe (same origin).

    /auth/<path>  the application, with the cookies of the session file (a logged-in user)
    /anon/<path>  the application without a session
    Paths that are neither a file here nor under those prefixes are passed to the application too, in the mode of the page
    that asked (Referer): pages call APIs and load root-relative files."""

    def __init__(self, *a, **k):
        super().__init__(*a, directory=str((ROOT / CFG["serve_root"]).resolve()), **k)

    def translate_path(self, path):
        p = path.split("?")[0]
        for pattern, replacement in CFG["path_rewrites"]:
            p = re.sub(pattern, replacement, p)
        return super().translate_path(p)

    def do_GET(self):
        m = re.match(r"^/(auth|anon)(/.*)?$", self.path)
        if m and APP:
            return self.proxy(m.group(1), m.group(2) or "/")
        if APP and not os.path.exists(self.translate_path(self.path)):
            ref = re.match(rf"^{re.escape(BASE)}/(auth|anon)/", self.headers.get("Referer", ""))
            if ref:
                return self.proxy(ref.group(1), self.path)
        return super().do_GET()

    def proxy(self, mode, path):
        req = urllib.request.Request(APP + path, headers={"Accept": self.headers.get("Accept", "*/*"), "User-Agent": "design-compare"})
        if mode == "auth" and app_cookie():
            req.add_header("Cookie", app_cookie())
        try:
            r = urllib.request.build_opener(NoRedirect).open(req, timeout=20)
        except urllib.error.HTTPError as e:  # 3xx (not followed) and 4xx/5xx are passed through
            r = e
        except (urllib.error.URLError, OSError):
            body = f"design-compare: the application is not reachable at {APP}. Start it first.".encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = r.read()
        ctype = r.headers.get("Content-Type", "")

        def rewrite(text):
            return text.replace(APP, f"{BASE}/{mode}")
        if re.search(r"html|css|javascript|json|xml", ctype):
            body = rewrite(body.decode("utf-8", "replace")).encode()
        self.send_response(r.code)
        for k, v in r.headers.items():
            if k.lower() in ("content-type", "cache-control", "etag", "last-modified"):
                self.send_header(k, v)
            elif k.lower() == "location":
                self.send_header(k, rewrite(v))
        # Dropped on purpose: Content-Security-Policy, X-Frame-Options (the page is shown in our iframe) and Set-Cookie.
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def server_up():
    try:
        urllib.request.urlopen(BASE + "/", timeout=1)
        return True
    except urllib.error.HTTPError:
        return True  # it answered
    except Exception:
        return False


def cmd_serve(a):
    pid = OUT / "server.pid"
    if a.action == "restart":  # after the tool itself changed: a running server keeps the old code
        cmd_serve(argparse.Namespace(action="stop"))
        time.sleep(0.5)
        a.action = "start"
    if a.action == "stop":
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), 15)
            except ProcessLookupError:
                pass
            pid.unlink()
            print("stopped")
        return
    if a.action == "run":  # internal: foreground server
        ThreadingHTTPServer(("127.0.0.1", int(CFG["serve_port"])), Handler).serve_forever()
    if server_up():
        print(f"already running: {BASE}/")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(Path(__file__).resolve())]
    if ARGS_CONFIG:
        cmd += ["--config", ARGS_CONFIG]
    p = subprocess.Popen([*cmd, "serve", "run"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid.write_text(str(p.pid))
    for _ in range(20):
        if server_up():
            print(f"running: {BASE}/")
            return
        time.sleep(0.2)
    die("server did not start")


def ensure_server():
    if not server_up():
        cmd_serve(argparse.Namespace(action="start"))


# ---------------------------------------------------------------- design side
def design_png(page, dpi=144):
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"design-p{page}"
    poppler("pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", "-singlefile", rel(PDF), rel(out))
    return OUT / f"design-p{page}.png"


def cmd_render(a):
    print(rel(design_png(a.page, a.dpi)))


def cmd_pages(a):
    d = OUT / "pages"
    d.mkdir(parents=True, exist_ok=True)
    poppler("pdftoppm", "-r", "30", "-png", rel(PDF), rel(d / "p"))
    files = sorted(d.glob("p-*.png"))
    number = re.compile(r"-(\d+)")
    cells = "".join(f'<figure style="margin:0;color:#fff;font:11px sans-serif"><img src="/{rel(f)}" width=150>'
                    f'{int(number.search(f.name).group(1))}</figure>' for f in files)
    sheet = OUT / "pages.html"
    sheet.write_text('<body style="margin:0;display:grid;grid-template-columns:repeat(9,150px);gap:4px;background:#888">' + cells)
    ensure_server()
    png = OUT / "pages.png"
    chrome_run("--window-size=1400,1000", f"--screenshot={png}", f"{BASE}/{rel(sheet)}")
    print(rel(png), f"({len(files)} pages, number under each)")


def group_lines(words):
    lines = []
    for w in sorted(words, key=lambda w: (round(w[1]), w[0])):
        if lines and abs(lines[-1]["y"] - w[1]) < 2 and w[0] - lines[-1]["x1"] < 14:
            L = lines[-1]
            L["text"] += " " + w[4]
            L["x1"] = w[2]
            L["w"] = w[2] - L["x"]
        else:
            lines.append({"text": w[4], "x": w[0], "y": w[1], "w": w[2] - w[0], "h": w[3] - w[1], "x1": w[2]})
    return lines


def svg_rects(svg_text):
    body = svg_text.split("</defs>")[-1]
    rects = []
    for m in re.finditer(r"<path ([^>]*?)/?>", body):
        attrs = m.group(1)
        d = re.search(r'\bd="([^"]*)"', attrs)
        st = re.search(r'style="([^"]*)"', attrs)
        if not d or not st:
            continue
        nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", d.group(1))]
        if len(nums) < 4 or len(nums) > 40:
            continue
        xs, ys = nums[0::2], nums[1::2]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        fm = re.search(r"fill:rgb\(([\d.]+)%,([\d.]+)%,([\d.]+)%\)", st.group(1))
        if not fm or "fill:none" in st.group(1):
            continue
        fill = tuple(round(float(v) * 2.55) for v in fm.groups())
        if x1 - x0 < 12 or y1 - y0 < 12:
            continue
        if x1 - x0 > W - 1 and y1 - y0 > H - 1:
            continue  # the page background
        rects.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "fill": fill})
    return rects


def design_spec(page):
    """Words (as lines), filled rectangles and fonts of one PDF page, in points (= CSS px when the page is as wide as the viewport)."""
    OUT.mkdir(parents=True, exist_ok=True)
    words_f = OUT / f"design-p{page}-words.html"
    svg_f = OUT / f"design-p{page}.svg"
    poppler("pdftotext", "-bbox", "-f", str(page), "-l", str(page), rel(PDF), rel(words_f))
    poppler("pdftocairo", "-svg", "-f", str(page), "-l", str(page), rel(PDF), rel(svg_f))
    fonts = poppler("pdffonts", "-f", str(page), "-l", str(page), rel(PDF)).splitlines()[2:]
    words = [(float(m[0]), float(m[1]), float(m[2]), float(m[3]), html.unescape(m[4])) for m in
             re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
                        words_f.read_text(encoding="utf-8"))]
    lines = group_lines(words)
    spec = {"page": page, "lines": [{k: v for k, v in l.items() if k != "x1"} for l in lines],
            "rects": svg_rects(svg_f.read_text(encoding="utf-8")), "fonts": [" ".join(f.split()[:1]) for f in fonts]}
    (OUT / f"design-p{page}-spec.json").write_text(json.dumps(spec, indent=1))
    return spec


def cmd_spec(a):
    s = design_spec(a.page)
    print(f"page {a.page}: fonts {', '.join(s['fonts'])}")
    for l in s["lines"]:
        print(f"  text  x={l['x']:.0f} y={l['y']:.0f} w={l['w']:.0f} h={l['h']:.0f}  {l['text']}")
    for r in s["rects"]:
        print(f"  box   x={r['x']:.0f} y={r['y']:.0f} w={r['w']:.0f} h={r['h']:.0f}  {hexc(r['fill'])}")
    print(rel(OUT / f"design-p{a.page}-spec.json"))


# ---------------------------------------------------------------- browser side
MEASURE_JS = r"""
(function(){
var f=document.getElementById('f');
function go(){
 var d=f.contentDocument,w=f.contentWindow,out={url:w.location.pathname,w:w.innerWidth,h:w.innerHeight,docH:d.documentElement.scrollHeight,els:[],texts:[]};
 d.querySelectorAll('*').forEach(function(e){
  var tag=e.tagName.toLowerCase(); if(['script','style','head','html','meta','link','title'].indexOf(tag)>=0)return;
  var cs=w.getComputedStyle(e),r=e.getBoundingClientRect();
  if(r.width<=0||r.height<=0||cs.visibility==='hidden'||cs.display==='none')return;
  out.els.push({tag:tag,cls:typeof e.className==='string'?e.className:'',id:e.id,type:e.type||'',x:r.left,y:r.top,w:r.width,h:r.height,
   bg:cs.backgroundColor,bw:cs.borderTopWidth,bc:cs.borderTopColor,pos:cs.position});
 });
 d.querySelectorAll('input[placeholder],textarea[placeholder]').forEach(function(e){
  var cs=w.getComputedStyle(e),r=e.getBoundingClientRect(); if(r.width<=0||cs.display==='none'||cs.visibility==='hidden')return;
  var fs=parseFloat(cs.fontSize),lh=parseFloat(cs.lineHeight)||fs*1.2,x=r.left+parseFloat(cs.borderLeftWidth)+parseFloat(cs.paddingLeft);
  out.texts.push({t:e.getAttribute('placeholder'),tag:'placeholder',fs:cs.fontSize,fw:cs.fontWeight,ff:cs.fontFamily.split(',')[0].replace(/["']/g,''),color:cs.color,
   lines:[{x:x,y:r.top+(r.height-lh)/2,w:0,h:lh}]});
 });
 var tw=d.createTreeWalker(d.body,NodeFilter.SHOW_TEXT),n;
 while((n=tw.nextNode())){
  var t=n.nodeValue.replace(/\s+/g,' ').trim(); if(!t)continue;
  var p=n.parentElement,cs=w.getComputedStyle(p); if(cs.display==='none'||cs.visibility==='hidden')continue;
  var rg=d.createRange();rg.selectNodeContents(n);var rs=rg.getClientRects(),lines=[];
  for(var i=0;i<rs.length;i++){if(rs[i].width>0)lines.push({x:rs[i].left,y:rs[i].top,w:rs[i].width,h:rs[i].height});}
  if(lines.length)out.texts.push({t:t,tag:p.tagName.toLowerCase(),fs:cs.fontSize,fw:cs.fontWeight,ff:cs.fontFamily.split(',')[0].replace(/["']/g,''),color:cs.color,lines:lines});
 }
 document.getElementById('out').textContent=JSON.stringify(out);
}
f.addEventListener('load',function(){setTimeout(go,__SETTLE__)});
})();
"""


def harness(target):
    """One page that frames the target in an exact viewport-sized iframe. Headless Chrome will not make a window narrower
    than 500 px or give it the full height, so a plain screenshot would be laid out at the wrong size. The iframe is the
    viewport; measurements and screenshots both use it."""
    ensure_server()
    OUT.mkdir(parents=True, exist_ok=True)
    h = OUT / "_harness.html"
    script = MEASURE_JS.replace("__SETTLE__", str(int(CFG["settle_ms"])))
    h.write_text(f'<!doctype html><style>body.shot pre{{display:none}}</style><body style="margin:0;background:#fff">'
                 f'<iframe id="f" src="{url_of(target)}" style="width:{W}px;height:{H}px;border:0;display:block"></iframe>'
                 f'<pre id="out"></pre><script>if(location.hash==="#shot")document.body.classList.add("shot");{script}</script>')
    return h


def measure(target):
    h = harness(target)
    r = chrome_run(f"--window-size={WIN_W},{WIN_H}", "--virtual-time-budget=6000", "--dump-dom", f"{BASE}/{rel(h)}")
    m = re.search(r'<pre id="out">(.*?)</pre>', r.stdout, re.S)
    if not m or not m.group(1).strip():
        die(f"could not measure {target} (cross-origin or failed load; only pages served from {BASE} can be measured)")
    return json.loads(html.unescape(m.group(1)))


def shot(target, path, scale=1):
    """Screenshot of the harness: the page is in the top-left viewport corner of the image."""
    h = harness(target)
    chrome_run(f"--window-size={WIN_W},{WIN_H}", f"--force-device-scale-factor={scale}", "--virtual-time-budget=6000",
               f"--screenshot={path}", f"{BASE}/{rel(h)}#shot")
    return path


def _shot_named(target, name):
    d = OUT / (name or Path(target).stem)
    d.mkdir(parents=True, exist_ok=True)
    return shot(target, d / "page.png")


def cmd_shot(a):
    print(rel(_shot_named(a.target, a.name)))


def cmd_measure(a):
    m = measure(a.target)
    d = OUT / (a.name or Path(a.target).stem)
    d.mkdir(parents=True, exist_ok=True)
    (d / "measure.json").write_text(json.dumps(m, indent=1))
    print(f"viewport {m['w']}x{m['h']}, document height {m['docH']:.0f}")
    for t in m["texts"]:
        L = t["lines"][0]
        print(f"  text  x={L['x']:.0f} y={L['y']:.0f} w={L['w']:.0f} h={L['h']:.0f} {t['ff']} {t['fs']}/{t['fw']}  {t['t'][:60]}")
    print(rel(d / "measure.json"))


# ---------------------------------------------------------------- compare
def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", s.lower())).strip()


def iou(a, b):
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1, y1 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union else 0


def compare_data(spec, meas):
    rows = []  # (kind, status, what, detail)
    for l in spec["lines"]:
        ft = norm(l["text"])
        if not ft:
            continue
        best = None
        for t in meas["texts"]:
            dt = norm(t["t"])
            if dt == ft or dt.startswith(ft) or ft.startswith(dt) and len(dt) > 3 or \
                    difflib.SequenceMatcher(None, dt[:len(ft)], ft).ratio() >= 0.88 or \
                    len(dt) >= 8 and difflib.SequenceMatcher(None, dt, ft[:len(dt)]).ratio() >= 0.88:
                d = abs(t["lines"][0]["y"] + t["lines"][0]["h"] / 2 - l["y"] - l["h"] / 2)
                if best is None or d < best[0]:
                    best = (d, t)
        if best:
            t = best[1]
            L = t["lines"][0]
            # vertical centre, not top: the PDF's text box uses the font's full metrics and is taller than the browser's
            dx, dy, dw = L["x"] - l["x"], (L["y"] + L["h"] / 2) - (l["y"] + l["h"] / 2), L["w"] - l["w"]
            ok = abs(dx) <= POS_TOL and abs(dy) <= POS_TOL
            wording = "" if norm(t["t"])[:len(ft)] == ft else f" | wording: design '{l['text'][:40]}' vs page '{t['t'][:40]}'"
            rows.append(("text", "OK" if ok else "DIFF", l["text"][:46],
                         f"design x={l['x']:.0f} mid-y={l['y'] + l['h'] / 2:.0f} w={l['w']:.0f} | page x={L['x']:.0f} mid-y={L['y'] + L['h'] / 2:.0f} w={L['w']:.0f}"
                         f" | dx={dx:+.0f} dy={dy:+.0f} dw={dw:+.0f} | {t['ff']} {t['fs']}{wording}"))
        elif any(ft in norm(t["t"]) for t in meas["texts"]):
            rows.append(("text", "OK", l["text"][:46], "found inside a longer text (position not compared)"))
        else:
            rows.append(("text", "MISSING", l["text"][:46], f"not on the page (design x={l['x']:.0f} y={l['y']:.0f})"))
    for r in spec["rects"]:
        fill = tuple(r["fill"]) + (1.0,)
        cands = []
        for e in meas["els"]:
            if e["w"] < 10 or e["h"] < 10:
                continue
            bgm = close(parse_rgb(e["bg"]), fill) and (parse_rgb(e["bg"]) or (0, 0, 0, 0))[3] > 0.5
            shape = e["tag"] in ("input", "button", "img", "a", "svg", "label", "div", "form", "section")
            if bgm or (e["tag"] in ("img", "input", "button") and shape):
                cands.append((iou(r, e), bgm, e))
        cands.sort(key=lambda c: -c[0])
        label = f"box {hexc(r['fill'])} {r['w']:.0f}x{r['h']:.0f}"
        if (not cands or cands[0][0] < 0.25) and r["w"] <= 24 and r["h"] <= 24:
            cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
            near = [(((e["x"] + e["w"] / 2 - cx) ** 2 + (e["y"] + e["h"] / 2 - cy) ** 2) ** 0.5, e) for e in meas["els"]
                    if e["tag"] == "input" and e["type"] in ("checkbox", "radio") and e["w"] <= 30]
            near = [n for n in near if n[0] <= 60]
            if near:
                cands = [(0.25, False, min(near, key=lambda n: n[0])[1])]
        if not cands or cands[0][0] < 0.25:
            rows.append(("box", "MISSING", label, f"nothing on the page near x={r['x']:.0f} y={r['y']:.0f}"))
            continue
        i, bgm, e = cands[0]
        dx, dy, dw, dh = e["x"] - r["x"], e["y"] - r["y"], e["w"] - r["w"], e["h"] - r["h"]
        ok = abs(dx) <= POS_TOL and abs(dy) <= POS_TOL and abs(dw) <= SIZE_TOL and abs(dh) <= SIZE_TOL
        note = "" if bgm or e["tag"] == "img" else f" | colour: page {hexc(parse_rgb(e['bg']))} vs design {hexc(r['fill'])}"
        sel = f"{e['tag']}{('#' + e['id']) if e['id'] else ''}{('.' + e['cls'].split()[0]) if e['cls'] else ''}"
        rows.append(("box", "OK" if ok and not note else "DIFF", label,
                     f"design x={r['x']:.0f} y={r['y']:.0f} | page {sel} x={e['x']:.0f} y={e['y']:.0f} {e['w']:.0f}x{e['h']:.0f}"
                     f" | dx={dx:+.0f} dy={dy:+.0f} dw={dw:+.0f} dh={dh:+.0f}{note}"))
    return rows


def side_by_side(d, design_png_path, page_png):
    sheet = d / "compare.html"
    sheet.write_text(
        '<body style="margin:0;background:#888;font:12px sans-serif;color:#fff"><div style="display:flex;gap:8px;padding:8px">'
        f'<figure style="margin:0"><img src="/{rel(design_png_path)}" width="{W}">Design</figure>'
        f'<figure style="margin:0"><div style="width:{W}px;height:{H}px;overflow:hidden"><img src="/{rel(page_png)}" style="width:{WIN_W}px;display:block"></div>Page</figure>'
        f'<figure style="margin:0;background:#000;position:relative;width:{W}px;height:{H}px"><img src="/{rel(design_png_path)}" width="{W}" '
        f'style="position:absolute;left:0;top:0"><div style="position:absolute;left:0;top:0;width:{W}px;height:{H}px;overflow:hidden;mix-blend-mode:difference">'
        f'<img src="/{rel(page_png)}" style="width:{WIN_W}px;display:block"></div>'
        '<span style="position:absolute;left:0;bottom:-16px">Difference (black = same)</span></figure></div>')
    png = d / "compare.png"
    chrome_run(f"--window-size={W * 3 + 40},{H + 50}", "--virtual-time-budget=3000", f"--screenshot={png}", f"{BASE}/{rel(sheet)}")
    return png


def redirect_warning(target, meas):
    """The application may redirect a guest to a login page and a signed-in user away from it: the measured page is then not the one asked for."""
    want = urllib.parse.urlparse(url_of(target)).path
    got = meas.get("url", "")
    if want.rstrip("/") != got.rstrip("/"):
        hint = ("not signed in (refresh the session file), or the page needs a state the test account is not in" if target.startswith("auth:")
                else "check the route and the mode (auth: or anon:)")
        return f"asked for {want} but the browser ended on {got} ({hint})"
    return ""


def compare_one(name, page, target):
    ensure_server()
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    dpng = design_png(page, 72)  # 1 px per pt so the page screenshot (scale 1) overlays exactly
    ppng = shot(target, d / "page.png", scale=1)
    spec = design_spec(page)
    meas = measure(target)
    (d / "measure.json").write_text(json.dumps(meas, indent=1))
    warn = redirect_warning(target, meas)
    rows = compare_data(spec, meas)
    png = side_by_side(d, dpng, ppng)
    n = {s: sum(1 for r in rows if r[1] == s) for s in ("OK", "DIFF", "MISSING")}
    md = [f"# {name} vs design page {page}", "", f"Target: `{target}`. Tolerance: {POS_TOL:.0f} px position, {SIZE_TOL:.0f} px size.",
          f"Design fonts: {', '.join(spec['fonts'])}. Page height {meas['docH']:.0f} px (design {H}).", "",
          *([f"**WARNING: {warn}**", ""] if warn else []),
          f"**{n['OK']} ok, {n['DIFF']} differ, {n['MISSING']} missing.** Image: `{rel(png)}` (design | page | difference).", "",
          "| Status | Kind | Item | Detail |", "|---|---|---|---|"]
    md += [f"| {s} | {k} | {w} | {x} |" for k, s, w, x in sorted(rows, key=lambda r: (r[1] == "OK", r[0], r[2]))]
    (d / "report.md").write_text("\n".join(md) + "\n")
    n["warn"] = warn
    return n, d


def cmd_compare(a):
    name = a.name or Path(a.target).stem
    n, d = compare_one(name, a.page, a.target)
    print(f"{name}: {n['OK']} ok, {n['DIFF']} differ, {n['MISSING']} missing -> {rel(d / 'report.md')}, {rel(d / 'compare.png')}")
    if n["warn"]:
        print("  WARNING:", n["warn"])
    for line in (d / "report.md").read_text().splitlines():
        if line.startswith("| DIFF") or line.startswith("| MISSING"):
            print(" ", line)
    if a.strict and (n["DIFF"] or n["MISSING"]):
        sys.exit(1)


def cmd_all(a):
    """screens file: [{"name", "design_page" (or null), "url", "kind", "note"}]"""
    try:
        screens = [s for s in json.loads(SCREENS.read_text()) if not a.only or s.get("kind", "wireframe") == a.only]
    except (OSError, ValueError) as e:
        die(f"cannot read the screens file {SCREENS}: {e}")
    summary = ["# Design check", "", "| Screen | Design page | OK | Differ | Missing | Report |", "|---|---|---|---|---|---|"]
    results, worse, warned = {}, [], []
    base = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    for s in screens:
        if s.get("design_page"):
            n, d = compare_one(s["name"], s["design_page"], s["url"])
            results[s["name"]] = {"differ": n["DIFF"], "missing": n["MISSING"]}
            summary.append(f"| {s['name']} | {s['design_page']} | {n['OK']} | {n['DIFF']} | {n['MISSING']} | `{rel(d / 'report.md')}` |")
            line = f"{s['name']:28} page {s['design_page']:>2}: {n['OK']} ok, {n['DIFF']} differ, {n['MISSING']} missing"
            if n["warn"]:
                warned.append(s["name"])
                line += f"  WARNING: {n['warn']}"
            b = base.get(s["name"])
            if b is not None and n["DIFF"] + n["MISSING"] > b["differ"] + b["missing"]:
                worse.append(s["name"])
                line += f"  WORSE than baseline ({b['differ']} differ, {b['missing']} missing)"
            print(line)
        else:
            p = _shot_named(s["url"], s["name"])
            summary.append(f"| {s['name']} | none ({s.get('note', 'no design page')}) | - | - | - | `{rel(p)}` |")
            print(f"{s['name']:28} no design page: screenshot only")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.md").write_text("\n".join(summary) + "\n")
    print(rel(OUT / "summary.md"))
    if a.save_baseline:
        base.update(results)
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(base, indent=2, sort_keys=True) + "\n")
        print(f"baseline saved: {rel(BASELINE)} ({len(results)} screens)")
    if a.check and (worse or warned):
        print(f"design check failed: {len(worse)} screen(s) worse than the baseline, {len(warned)} redirected", file=sys.stderr)
        sys.exit(1)
    if a.strict and any(r["differ"] or r["missing"] for r in results.values()):
        sys.exit(1)


ARGS_CONFIG = None


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="configuration file (JSON); paths are relative to it")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("serve", help="local static server on the serve root")
    p.add_argument("action", nargs="?", default="start", choices=["start", "stop", "restart", "run"])
    p.set_defaults(f=cmd_serve)
    p = sp.add_parser("pages", help="contact sheet of all pages of the design PDF, numbered")
    p.set_defaults(f=cmd_pages)
    p = sp.add_parser("render", help="render one design page to PNG")
    p.add_argument("page", type=int)
    p.add_argument("--dpi", type=int, default=144)
    p.set_defaults(f=cmd_render)
    p = sp.add_parser("spec", help="print positions, sizes, colours and fonts measured in a design page")
    p.add_argument("page", type=int)
    p.set_defaults(f=cmd_spec)
    p = sp.add_parser("shot", help="screenshot a page at the configured viewport")
    p.add_argument("target")
    p.add_argument("--name")
    p.set_defaults(f=cmd_shot)
    p = sp.add_parser("measure", help="print text and box positions measured in the browser")
    p.add_argument("target")
    p.add_argument("--name")
    p.set_defaults(f=cmd_measure)
    p = sp.add_parser("compare", help="design page vs a page: side-by-side image plus a table of differences in px")
    p.add_argument("page", type=int)
    p.add_argument("target", help="a path under the serve root, auth:/path, anon:/path or a URL served by `serve`")
    p.add_argument("--name")
    p.add_argument("--strict", action="store_true", help="exit 1 when anything differs")
    p.set_defaults(f=cmd_compare)
    p = sp.add_parser("all", help="compare every screen in the screens file")
    p.add_argument("--only", help="only screens of this kind")
    p.add_argument("--check", action="store_true", help="exit 1 when a screen is worse than the baseline file or was redirected")
    p.add_argument("--save-baseline", action="store_true", help="write the current counts to the baseline file")
    p.add_argument("--strict", action="store_true", help="exit 1 when anything differs at all")
    p.set_defaults(f=cmd_all)
    return ap


def main():
    global ARGS_CONFIG
    a = parser().parse_args()
    ARGS_CONFIG = a.config
    configure(a.config)
    a.f(a)


if __name__ == "__main__":
    main()
