"""The local server, idle shutdown and single instance (no desktop shortcut: the app opens from Callagy Hub)."""
import http.client
import shutil
import threading
import time

import pytest

import main
import resources
from conftest import REPORT


@pytest.fixture
def server(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    if REPORT.exists():
        shutil.copy(REPORT, reports / REPORT.name)
    res = tmp_path / "resources"
    res.mkdir()
    (res / "Brief é.html").write_text("<title>Court brief</title>", encoding="utf-8")
    monkeypatch.setattr(main, "REPORTS", reports)
    monkeypatch.setattr(main, "RESOURCES", res)
    monkeypatch.setattr(main, "APPDATA", tmp_path / "appdata")
    monkeypatch.setattr(main, "INSTANCE", tmp_path / "appdata" / "instance.json")
    ports = []
    t = threading.Thread(target=main.serve, kwargs={"idle_seconds": 2, "open_browser": False, "ready": ports.append}, daemon=True)
    t.start()
    while not ports:
        time.sleep(0.01)
    yield ports[0], t, reports


def get(port, path, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path, headers={"Host": host or f"127.0.0.1:{port}"})
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


@pytest.mark.skipif(not REPORT.exists(), reason="acceptance report not in reports\\")
def test_pages_downloads_and_idle_shutdown(server):
    port, thread, reports = server
    status, headers, body = get(port, "/")
    assert status == 200 and b"Litigation Tracker" in body
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert b"https://cdn" not in body and b"googleapis" not in body

    assert get(port, "/ping")[2] == main.PING
    assert main.running_port() == port

    tok = resources.token("Brief é.html")
    status, headers, body = get(port, f"/download/{tok}")
    assert status == 200 and headers["Content-Disposition"].startswith("attachment;")
    assert "filename*=UTF-8''Brief%20%C3%A9.html" in headers["Content-Disposition"]
    assert get(port, "/download/0000000000000000")[0] == 404
    assert get(port, "/static/..%5Cmain.py")[0] == 404
    assert get(port, "/static/app.js")[0] == 200
    assert get(port, "/", host="evil.example")[0] == 403

    # A newly saved report is picked up on refresh, without a restart.
    shutil.copy(reports / REPORT.name, reports / "NSA_Enforcement_Litigation_Dashboard_Source_2026-10-06 (2).xlsx")
    assert b"NSA_Enforcement_Litigation_Dashboard_Source_2026-10-06 (2).xlsx" in get(port, "/")[2]

    thread.join(timeout=15)
    assert not thread.is_alive(), "server should stop after the idle timeout"
    assert main.running_port() is None


def post(port, path, body, token=None, host=None):
    import json
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": host or f"127.0.0.1:{port}", "Content-Type": "application/json"}
    if token:
        headers["X-LT-Token"] = token
    c.request("POST", path, body=json.dumps(body), headers=headers)
    r = c.getresponse()
    raw = r.read()
    return r.status, json.loads(raw) if r.getheader("Content-Type") == "application/json" else raw.decode()


def test_newsletter_signup_needs_the_pages_code(tmp_path, monkeypatch):
    import signups
    monkeypatch.setattr(main, "ROOT", tmp_path)  # never the real list
    monkeypatch.setattr(main, "APPDATA", tmp_path / "appdata")
    monkeypatch.setattr(main, "INSTANCE", tmp_path / "appdata" / "instance.json")
    ports = []  # its own server: the first sign-up loads openpyxl and can outlast the shared fixture's 2-second idle stop
    threading.Thread(target=main.serve, kwargs={"idle_seconds": 30, "open_browser": False, "ready": ports.append}, daemon=True).start()
    while not ports:
        time.sleep(0.01)
    port = ports[0]
    me = {"email": "Jane.Doe@CallagyLaw.com", "action": "subscribe"}
    assert post(port, "/signup", me)[0] == 403  # no code: another website cannot sign anyone up
    assert post(port, "/signup", me, token=main.SIGNUP_TOKEN, host="evil.example")[0] == 403
    assert post(port, "/other", me, token=main.SIGNUP_TOKEN)[0] == 404  # refusals read the body first: no connection reset
    assert post(port, "/signup", me, token=main.SIGNUP_TOKEN) == (200, {"result": "added", "status": "Subscribed"})
    assert post(port, "/signup", {**me, "email": "jane.doe@callagylaw.com"}, token=main.SIGNUP_TOKEN)[1]["result"] == "already"
    status, j = post(port, "/signup", {"email": "x@gmail.com", "action": "subscribe"}, token=main.SIGNUP_TOKEN)
    assert status == 400 and "work address" in j["error"]
    assert signups.recipients(tmp_path) == ["jane.doe@callagylaw.com"]


def test_version_changes_with_new_data_and_does_not_keep_the_server_alive(server, tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(main, "AUTO", tmp_path / "auto")
    monkeypatch.setattr(main, "CALLAGY", tmp_path / "callagy")
    port, thread, reports = server
    before = json.loads(get(port, "/version")[2])["version"]
    assert before == main.data_version()
    (tmp_path / "resources" / "New article.html").write_text("<title>New</title>", encoding="utf-8")
    assert main.data_version() != before
    (tmp_path / "auto").mkdir()
    after_resource = main.data_version()
    (tmp_path / "auto" / "found.json").write_text("{}", encoding="utf-8")  # the daily update ran
    assert main.data_version() != after_resource
    end = time.monotonic() + 15  # an open page checking every so often must not stop the 2-second idle shutdown
    while thread.is_alive() and time.monotonic() < end:
        try:
            get(port, "/version")
        except OSError:
            break
        time.sleep(0.5)
    thread.join(timeout=15)
    assert not thread.is_alive()


def test_error_page_when_no_report(server):
    port, thread, reports = server
    for p in reports.iterdir():
        p.unlink()
    status, _, body = get(port, "/")
    assert status == 500 and b"No report found" in body


def test_starting_makes_no_desktop_shortcut():
    # Opened from Callagy Hub only (2026-10-27): no shortcut code, and nothing slow before the server starts.
    import inspect
    assert not hasattr(main, "ensure_shortcut") and "powershell" not in inspect.getsource(main).lower()


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")


def test_the_callagy_ui_kit_is_served_and_kept_by_the_browser(server):
    # Callagy UI kit 1.0 (2026-11-13): its files sit in sub-folders, looked up by exact name, never joined into a path.
    port, _, _ = server
    for name, ctype in (("callagy.js", "text/javascript"), ("callagy.css", "text/css"),
                        ("vendor/manrope/manrope-latin-wght-normal.woff2", "font/woff2"), ("vendor/echarts/LICENSE", "application/octet-stream")):
        status, headers, body = get(port, f"/static/vendor/callagy-ui/1.0/{name}")
        assert status == 200 and headers["Content-Type"].startswith(ctype) and body
        assert headers["Cache-Control"] == "max-age=31536000, immutable"  # a version folder never changes
        assert headers["Content-Security-Policy"] == CSP  # the security policy is not changed for the kit
    for tricky in ("vendor/callagy-ui/1.0/../../app.js", "vendor/callagy-ui/1.0/%2e%2e/callagy.js", "vendor%5Ccallagy-ui%5C1.0%5Ccallagy.js",
                   "vendor/callagy-ui/1.0/nothing.js", "vendor/callagy-ui"):
        assert get(port, "/static/" + tricky)[0] == 404
    status, headers, _ = get(port, "/static/app.js")
    assert status == 200 and headers["Cache-Control"] == "no-store"  # the dashboard's own files are always fresh


def test_the_security_policy_is_unchanged():
    import inspect
    src = " ".join(inspect.getsource(main.Handler._send).split())  # the header text sits on two source lines
    assert all(part in src for part in CSP.split("; "))


def test_the_kit_copy_is_the_kit_unchanged():
    # Never edited: every file matches H:\Callagy UI\dist\ (where that folder can be reached).
    import hashlib
    from pathlib import Path
    src = Path(r"H:\Callagy UI\dist")
    copy = main.STATIC / "vendor" / "callagy-ui" / "1.0"
    if not src.is_dir():
        pytest.skip("H:\\Callagy UI not reachable")
    digest = lambda folder: {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
                             for p in folder.rglob("*") if p.is_file()}
    assert digest(copy) == digest(src)
    assert set(main.KIT_FILES) == {"vendor/callagy-ui/1.0/" + k for k in digest(src)}


def test_the_page_keeps_its_rounding_rule_and_high_contrast_support():
    js = (main.STATIC / "app.js").read_text(encoding="utf-8")
    assert "const v = Math.floor(share * 1000 + 1e-9) / 10; // never round up across a colour boundary" in js
    assert "format: pct" in js  # the states table's win share uses it, never the kit's rounding
    assert "@media (forced-colors: active) { .state { forced-color-adjust: none; } }" in (main.STATIC / "app.css").read_text(encoding="utf-8")
    page = (main.STATIC / "index.html").read_text(encoding="utf-8")
    assert 'href="static/vendor/callagy-ui/1.0/callagy.css"' in page and 'src="/static' not in page  # relative: website too
    order = [page.index(f'src="static/{f}"') for f in ("vendor/callagy-ui/1.0/vendor/echarts/echarts.min.js",
                                                         "vendor/callagy-ui/1.0/callagy.js", "views.js", "app.js")]
    assert order == sorted(order)  # ECharts, then the kit, then the dashboard's own scripts


@pytest.mark.skipif(not REPORT.exists(), reason="acceptance report not in reports\\")
def test_insurer_filter_views(server):
    import json
    import urllib.parse

    import data
    port, _, reports = server
    report = data.load(reports / REPORT.name)
    top = report["decisions"][report["views"]["federal"]["caseIds"][0]]["insurers"][0]
    q = urllib.parse.urlencode([("report", REPORT.name), ("insurer", top)])
    status, headers, body = get(port, "/views?" + q)
    assert status == 200 and headers["Content-Type"] == "application/json"
    views = json.loads(body)
    shown = views["federal"]["caseIds"] + views["state"]["caseIds"]
    assert shown and all(top in report["decisions"][i]["insurers"] for i in shown)
    assert views["federal"]["summary"]["included"] < report["views"]["federal"]["summary"]["included"]
    # A page built from an older report is told to refresh rather than mixing two reports.
    assert get(port, "/views?" + urllib.parse.urlencode([("report", "old.xlsx"), ("insurer", top)]))[0] == 409
    assert get(port, "/views?report=x", host="evil.example")[0] == 403
