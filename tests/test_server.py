"""The local server, idle shutdown, single instance and the desktop shortcut."""
import http.client
import shutil
import subprocess
import sys
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcut")
def test_desktop_shortcut_created_once_and_repaired(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "APPDATA", tmp_path / "appdata")
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    exe = sys.executable
    icon = main.STATIC / main.ICON_NAME
    assert main.ensure_shortcut(exe, icon, desktop) == "created"
    assert main.ensure_shortcut(exe, icon, desktop) == "ok"
    (desktop / main.SHORTCUT_NAME).unlink()
    assert main.ensure_shortcut(exe, icon, desktop) == "created"
    target = subprocess.run(["powershell", "-NoProfile", "-Command",
                             f"(New-Object -ComObject WScript.Shell).CreateShortcut('{desktop / main.SHORTCUT_NAME}').TargetPath"],
                            capture_output=True, text=True).stdout.strip()
    assert target.lower() == exe.lower()
    assert (tmp_path / "appdata" / main.ICON_NAME).exists()


def test_unc_leaves_unmapped_paths_alone():
    assert main.unc(r"\\server\share\x.exe") == r"\\server\share\x.exe"


def test_theme_from_logo_colours():
    t = main.theme_from_colours([(500, (255, 255, 255)), (200, (40, 90, 200)), (90, (60, 60, 60))])
    assert t["accent"] == "#3c3c3c"
    assert main.theme_from_colours([(10, (255, 255, 255))]) == main.DEFAULT_THEME


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
