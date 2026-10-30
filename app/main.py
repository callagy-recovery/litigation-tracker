"""Litigation Tracker launcher: single instance, local web server, idle shutdown. It is opened from Callagy Hub only, so
it makes no desktop shortcut (removed 2026-10-27; that step also cost about 2 s at every start).

Run as "Litigation Tracker.exe" (PyInstaller) or, from source, `.venv\\Scripts\\python app\\main.py`.
"""
import datetime as dt
import getpass
import html
import http.server
import json
import logging
import mimetypes
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data  # noqa: E402
import resources  # noqa: E402
import signups  # noqa: E402

FROZEN = getattr(sys, "frozen", False)
# LT_ROOT: set by the daily update, whose exe sits one folder down (Daily Update\), when it builds the website.
ROOT = (Path(os.environ["LT_ROOT"]) if os.environ.get("LT_ROOT") else
        Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent)
STATIC = ROOT / "app" / "static"
REPORTS, RESOURCES, ASSETS, LOGS = ROOT / "reports", ROOT / "resources", ROOT / "assets", ROOT / "logs"
CALLAGY = ROOT / "callagy"  # CSV export of app/tools/callagy_cases.sql (also accepted in reports\)
AUTO = ROOT / "auto"  # what the daily update found (Daily Update\Litigation Tracker Daily Update.exe)
APPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Litigation Tracker"
INSTANCE = APPDATA / "instance.json"
IDLE_SECONDS = 60 * 60
PING = b"litigation-tracker"
DEFAULT_THEME = {"brand": "#2447a8", "brandDark": "#1b2f6b", "accent": "#3b3b3b", "tint": "#eef2fc"}

log = logging.getLogger("lt")
# The newsletter Sign up button is the dashboard's only write. Each run gets a fresh code that only this dashboard's own
# page knows (it is in the page's data), so another website cannot sign someone up through the local server.
import secrets  # noqa: E402
SIGNUP_TOKEN = secrets.token_urlsafe(24)
# The published website's newsletter button opens this form (a Microsoft Form owned by the maintainer); "" hides it.
PUBLISH_SIGNUP_URL = os.environ.get("LT_SIGNUP_FORM", "https://forms.cloud.microsoft/Pages/ResponsePage.aspx?id=BEZCZixZbke0r7VZ_PPM2ziRxushhIFNjXFi107FN7dUQVlQQjRaME5ENFdLSDhVN1hYVzkzV0ZLOS4u")


class _MaskingFormatter(logging.Formatter):
    """Last line of defence: nothing written to the log, tracebacks included, keeps patient initials."""

    def format(self, record):
        return data.mask(super().format(record))


def setup_logging():
    LOGS.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    handler = logging.FileHandler(LOGS / f"run_{stamp}_{getpass.getuser()}.log", encoding="utf-8")
    handler.setFormatter(_MaskingFormatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


# ---------- theme from the logo ----------

def find_logo():
    exts = (".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp")
    files = [p for p in ASSETS.iterdir() if p.suffix.lower() in exts and p.is_file()] if ASSETS.is_dir() else []
    files.sort(key=lambda p: (p.stem.lower() != "logo", "logo" not in p.name.lower(), p.name.lower()))
    return files[0] if files else None


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, c))) for c in rgb)


def _lum(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def theme_from_colours(colours):
    """colours: [(count, (r, g, b))]. Brand = most common saturated colour, darkened until white text reads on it;
    accent = most common dark neutral (or a deeper brand shade)."""
    import colorsys
    sat, dark = [], []
    for count, rgb in colours:
        h, light, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        if s > 0.35 and 0.15 < light < 0.85:
            sat.append((count, rgb))
        elif light < 0.35:
            dark.append((count, rgb))
    if not sat:
        return dict(DEFAULT_THEME)
    brand = max(sat)[1]
    while (1.05 / (_lum(brand) + 0.05)) < 4.5:  # contrast with white text
        brand = tuple(c * 0.9 for c in brand)
    deep = tuple(c * 0.62 for c in brand)
    accent = max(dark)[1] if dark else deep
    tint = tuple(255 - (255 - c) * 0.08 for c in brand)
    return {"brand": _hex(brand), "brandDark": _hex(deep), "accent": _hex(accent), "tint": _hex(tint)}


def logo_theme(path):
    if path is None:
        return dict(DEFAULT_THEME)
    try:
        if path.suffix.lower() == ".svg":
            import re
            found = re.findall(r"#([0-9a-fA-F]{6})\b", path.read_text(encoding="utf-8", errors="replace"))
            counts = {}
            for h in found:
                rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
                counts[rgb] = counts.get(rgb, 0) + 1
            return theme_from_colours([(n, rgb) for rgb, n in counts.items()])
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((96, 96))
            q = im.quantize(colors=10)
            pal = q.getpalette()
            return theme_from_colours([(n, tuple(pal[i * 3:i * 3 + 3])) for n, i in q.getcolors()])
    except Exception as e:
        log.warning("Could not read logo colours from %s: %s", path.name, e)
        return dict(DEFAULT_THEME)


# ---------- page ----------

_state = {"report_sig": None, "theme": None}


def build_page():
    """Re-reads the newest report and the resources folder. Returns (status, html)."""
    status, payload = page_data()
    if status != 200:
        return status, payload
    return 200, render_page(payload, logo_src="logo")


def render_page(payload, logo_src):
    """index.html with the page's data in it. logo_src: "logo" for the local server, a file name when published."""
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return (STATIC / "index.html").read_text(encoding="utf-8").replace("{{DATA}}", blob).replace("{{LOGO}}", logo_src)


# Data notes that only make sense on the H: drive (they name its folders or the exes): left off the published website.
INTERNAL_NOTES = {"Resource could not be read", "Dashboard running its backup code", "Callagy cases without a state",
                  "Automatic updates have stopped", "Automatic update not used"}


def page_data(published=False):
    """(200, the page's data) or (500, an error page). published: the version for the public website (docs\\ on
    GitHub Pages) - no Callagy case counts, no files from H: (only Resources that link to public sources), no sign-up
    code, no refresh check, and no notes about the H: drive."""
    found = data.newest_report(REPORTS) if REPORTS.is_dir() else None
    if not found:
        msg = f"No report found in {REPORTS}. Save a file named like NSA_Enforcement_Litigation_Dashboard_Source_YYYY-MM-DD.xlsx there, then refresh."
        log.error(msg)
        return 500, error_page(msg)
    path, date = found
    try:
        report = data.load(path, AUTO)
    except data.ReportError as e:
        log.error("Report %s cannot be used: %s", path.name, e)
        return 500, error_page(str(e), path.name)
    sig = (path.name, path.stat().st_mtime)
    if sig != _state["report_sig"]:
        _state["report_sig"] = sig
        c = report["counts"]
        log.info("Report used: %s (dated %s)", path.name, date)
        log.info("Rows read %d, included %d, excluded %d (wins %d, losses %d)",
                 c["read"], c["included"], c["excluded"], c["wins"], c["losses"])
        for d in report["excludedList"]:
            log.info("Excluded under methodology: %s", d["id"])
        for v in ("state", "federal", "appellate"):
            log.info("View %s: %s", v, json.dumps(report["views"][v]["summary"]))
        for n in report["notes"]:
            log.warning("%s: %s", n["kind"], n["text"])
        if report["dol"] is None:
            log.info("No DOL Actions sheet in this report")
        if not report["hasPendingSheet"]:
            log.info("No Pending Cases sheet in this report")
    items, problems = resources.listing(RESOURCES)
    notes = report["notes"] + [{"kind": "Resource could not be read", "text": p} for p in problems]
    if os.environ.get("LT_CODE_PROBLEM"):  # set by launcher.py when the shared code could not be loaded
        notes.insert(0, {"kind": "Dashboard running its backup code", "text": os.environ["LT_CODE_PROBLEM"] +
                         ". Everything still works from the copy built into the launcher; tell whoever maintains the dashboard."})
    callagy = data.load_callagy(REPORTS, CALLAGY)
    if callagy and callagy["unplaced"]:
        notes.append({"kind": "Callagy cases without a state", "text": f"{len(callagy['unplaced'])} of {callagy['total']} cases in "
                      f"{callagy['file']} have no state, so they are not counted on the map. Dockets: " + ", ".join(callagy["unplaced"])})
    logo = find_logo()
    if published:
        notes = [n for n in notes if n["kind"] not in INTERNAL_NOTES]
        items = [i for i in items if i.get("type") == "Link" and i.get("url")]
        callagy = None
    payload = {
        "report": {"name": path.name, "date": date.isoformat(), "autoRun": report.get("autoRun")},
        **{k: report[k] for k in ("counts", "views", "decisions", "excludedList", "pending", "hasPendingSheet",
                                  "dol", "methodology")},
        "notes": notes,
        "callagy": callagy and {k: callagy[k] for k in ("file", "byState", "byInsurer", "total")},
        "resources": [{k: i[k] for k in ("title", "type", "date", "token", "url", "category", "source", "summary") if k in i}
                      for i in items],
        "theme": logo_theme(logo),
        "hasLogo": logo is not None,
        "signup": {"formUrl": PUBLISH_SIGNUP_URL} if published else signup_info(),
        "version": None if published else data_version(),
        "published": published,
    }
    if published:
        for r in payload["resources"]:
            r.pop("token", None)
        payload["report"]["name"] = "report"  # the file name is not shown; only the local filter needs it
    return 200, payload


def data_version():
    """A fingerprint of everything the page shows: the newest report, the daily update's finds and summaries, the
    Resources folder and the Callagy list. The page compares it with /version to offer a refresh when it changes."""
    parts = []
    found = data.newest_report(REPORTS) if REPORTS.is_dir() else None
    paths = [found[0]] if found else []
    paths += [AUTO / data.AUTO_FILE, AUTO / data.SUMMARY_FILE]
    for folder in (RESOURCES, CALLAGY):
        if folder.is_dir():
            paths += list(folder.iterdir())
    if REPORTS.is_dir():
        paths += list(REPORTS.glob("*.csv"))
    for p in paths:
        try:
            st = p.stat()
            parts.append(f"{p.name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{p.name}:-")
    import hashlib
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()[:16]


def signup_info():
    """What the Sign up button needs: the session code, this Windows user's likely work email and whether it is signed up."""
    email, name = signups.guess(getpass.getuser())
    try:
        state = signups.status(ROOT, email) if email else None
    except Exception:  # an unreadable list must not stop the page
        state = None
    return {"token": SIGNUP_TOKEN, "email": email, "name": name, "status": state, "domains": list(signups.DOMAINS)}


def signup_request(body, token):
    """(status, json) for POST /signup {"email", "action": "subscribe" | "unsubscribe" | "status"}."""
    if not secrets.compare_digest(token or "", SIGNUP_TOKEN):
        return 403, json.dumps({"error": "Refresh the page and try again."})
    try:
        req = json.loads(body or b"{}")
        email, action = str(req.get("email") or ""), req.get("action")
        if action == "subscribe":
            result = signups.subscribe(ROOT, email, signups.guess(getpass.getuser())[1], getpass.getuser())
        elif action == "unsubscribe":
            result = signups.unsubscribe(ROOT, email)
        elif action == "status":
            result = None
        else:
            return 400, json.dumps({"error": "Unknown request."})
        state = signups.status(ROOT, signups.clean_email(email))
    except signups.SignupError as e:
        return 400, json.dumps({"error": str(e)})
    except ValueError:
        return 400, json.dumps({"error": "Unknown request."})
    if result in ("added", "resubscribed", "removed"):
        log.info("Newsletter sign-up list: %s (%s)", result, signups.clean_email(email))
    return 200, json.dumps({"result": result, "status": state})


def filtered_views(query):
    """(status, body, type) for /views?report=<name>&insurer=<company>&insurer=...: the three map views for the chosen
    insurers. If the newest report is no longer the one the page was built from, answer 409 so the page asks for a refresh."""
    found = data.newest_report(REPORTS) if REPORTS.is_dir() else None
    if not found or query.get("report", [""])[0] != found[0].name:
        return 409, json.dumps({"error": "The report has changed. Refresh the page."}), "application/json"
    try:
        report = data.load(found[0], AUTO)
    except data.ReportError as e:
        return 409, json.dumps({"error": str(e)}), "application/json"
    views = data.views(list(report["decisions"].values()), list(report["pending"].values()), query.get("insurer", []))
    return 200, json.dumps(views, ensure_ascii=False), "application/json"


def error_page(message, report_name=""):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Litigation Tracker - problem</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/static/app.css"></head>
<body class="error-body"><main class="error-card"><h1>The dashboard cannot show this report</h1>
<p class="error-msg">{html.escape(message)}</p>{f'<p>Report: {html.escape(report_name)}</p>' if report_name else ''}
<p>Fix the report in <code>{html.escape(str(REPORTS))}</code>, then refresh this page. Details are in
<code>{html.escape(str(LOGS))}</code>.</p></main></body></html>"""


# ---------- server ----------

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "LitigationTracker"
    sys_version = ""

    def log_message(self, fmt, *args):  # no console in the exe; keep access lines out of the run log
        pass

    def _send(self, status, body, ctype, extra=None):
        body = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urllib.parse.urlsplit(self.path).path
        if route != "/version":  # the page's 5-minute "anything new?" check must not keep an unused dashboard running
            self.server.last_request = time.monotonic()
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):  # refuse DNS-rebinding requests from other sites
            return self._send(403, "Forbidden", "text/plain")
        try:
            if route == "/version":
                return self._send(200, json.dumps({"version": data_version()}), "application/json")
            if route in ("/", "/index.html"):
                status, page = build_page()
                return self._send(status, page, "text/html; charset=utf-8")
            if route == "/ping":
                return self._send(200, PING, "text/plain")
            if route == "/views":
                return self._send(*filtered_views(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)))
            if route == "/logo":
                logo = find_logo()
                if logo:
                    return self._send(200, logo.read_bytes(), mimetypes.guess_type(logo.name)[0] or "application/octet-stream")
            if route.startswith("/static/"):
                name = urllib.parse.unquote(route[len("/static/"):])
                f = STATIC / name
                if "/" not in name and "\\" not in name and f.is_file():
                    return self._send(200, f.read_bytes(), mimetypes.guess_type(name)[0] or "application/octet-stream")
            if route.startswith("/download/"):
                tok = route[len("/download/"):]
                items, _ = resources.scan(RESOURCES)
                item = next((i for i in items if i["token"] == tok), None)
                if item:
                    name = item["name"]
                    ascii_name = name.encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
                    disp = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(name)}"
                    return self._send(200, (RESOURCES / name).read_bytes(), "application/octet-stream",
                                      {"Content-Disposition": disp})
            return self._send(404, "Not found", "text/plain")
        except Exception:
            log.exception("Request failed: %s", route)
            return self._send(500, error_page("Something unexpected went wrong. The details are in the log."),
                              "text/html; charset=utf-8")


    def do_POST(self):
        self.server.last_request = time.monotonic()
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 2000:
            self.close_connection = True
            return self._send(400, json.dumps({"error": "Unknown request."}), "application/json")
        # Read the body before any answer: closing with unread bytes makes Windows reset the connection, so the
        # browser would see "connection reset" instead of the refusal.
        raw = self.rfile.read(length)
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self._send(403, "Forbidden", "text/plain")
        if urllib.parse.urlsplit(self.path).path != "/signup":
            return self._send(404, "Not found", "text/plain")
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._send(400, json.dumps({"error": "Unknown request."}), "application/json")
        try:
            status, body = signup_request(raw, self.headers.get("X-LT-Token"))
        except Exception:
            log.exception("Sign-up failed")
            status, body = 500, json.dumps({"error": "Something went wrong; the details are in the log."})
        return self._send(status, body, "application/json")


def running_port():
    """Port of this user's running instance, or None."""
    try:
        port = json.loads(INSTANCE.read_text())["port"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=2) as r:
            return port if r.read() == PING else None
    except Exception:
        return None


def serve(idle_seconds=IDLE_SECONDS, open_browser=True, ready=None):
    """Runs the server until it has had no requests for idle_seconds."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("LT_PORT", 0))), Handler)  # LT_PORT: dev preview only
    srv.daemon_threads = True
    srv.last_request = time.monotonic()
    port = srv.server_address[1]
    APPDATA.mkdir(parents=True, exist_ok=True)
    INSTANCE.write_text(json.dumps({"port": port, "pid": os.getpid()}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    log.info("Serving %s", url)
    if ready:
        ready(port)
    if open_browser:
        webbrowser.open(url)
    while time.monotonic() - srv.last_request < idle_seconds:
        time.sleep(min(15, idle_seconds / 4))
    log.info("No requests for %d minutes; shutting down", idle_seconds // 60)
    srv.shutdown()
    srv.server_close()
    try:
        if json.loads(INSTANCE.read_text()).get("pid") == os.getpid():
            INSTANCE.unlink()
    except (OSError, ValueError):
        pass


def main():
    setup_logging()
    log.info("Started by %s from %s (code: %s)", getpass.getuser(), ROOT, os.environ.get("LT_CODE", "this file"))
    if os.environ.get("LT_CODE_PROBLEM"):
        log.warning("Running the launcher's backup code: %s", os.environ["LT_CODE_PROBLEM"])
    open_browser = os.environ.get("LT_NO_BROWSER") != "1"
    port = running_port()
    if port:
        log.info("Already running on port %d; opening the browser there", port)
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return
    status, _ = build_page()  # validate and log the report up front
    log.info("Startup check: %s", "report OK" if status == 200 else "report has a problem (shown on the page)")
    serve(open_browser=open_browser)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Litigation Tracker stopped with an error")
        raise
