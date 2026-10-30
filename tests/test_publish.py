"""The public website (app/publish.py -> docs\\): nothing private in it, and its in-page insurer filter
(app/static/views.js) gives exactly what the dashboard's own Python (data.views) gives."""
import io
import json
import re
import shutil
import subprocess

import pytest

import data
import main
from conftest import REPORT, ROOT


def payload_of(page):
    return json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S)[1].replace("<\\/", "</"))


@pytest.mark.skipif(not REPORT.exists(), reason="acceptance report not in reports\\")
def test_the_website_carries_nothing_private(tmp_path, monkeypatch):
    import publish
    reports, callagy = tmp_path / "reports", tmp_path / "callagy"
    reports.mkdir(), callagy.mkdir()
    shutil.copy(REPORT, reports / REPORT.name)
    (callagy / "cases.csv").write_text("Secret Client Medical PC v. Plan,District Court,1:25-cv-1,NJ,NJLIT,1,2025-01-01,Open\n",
                                       encoding="utf-8")
    res = tmp_path / "resources"
    res.mkdir()
    (res / "Internal memo.html").write_text("<title>Internal memo</title>", encoding="utf-8")
    for name, value in (("REPORTS", reports), ("CALLAGY", callagy), ("RESOURCES", res), ("AUTO", tmp_path / "auto")):
        monkeypatch.setattr(main, name, value)
    auto = tmp_path / "auto"
    auto.mkdir()
    (auto / data.AUTO_FILE).write_text('{"rows": [{"case": "Clinic a/s/o X.Y. v. Plan"}]}', encoding="utf-8")
    out = tmp_path / "docs"
    (out / "static").mkdir(parents=True)
    (out / "old-logo.png").write_bytes(b"x")  # left from an earlier publish
    (out / "data").mkdir()
    (out / "data" / "litigation-tracker-data.xlsx").write_bytes(b"x")  # the download offered until 2026-10-30
    monkeypatch.setattr(publish, "points_to_github", lambda name: False)  # the firm's DNS not switched yet
    files = publish.publish(out)
    assert "CNAME" not in files  # publishing it early would send the github.io address to a domain not set up
    assert {"index.html", "robots.txt", ".nojekyll", "static/app.js", "static/views.js", "static/us_states.json"} <= set(files)
    assert not any(f.startswith("data/") for f in files) and not (out / "data").exists()  # no data files, no download
    assert not (out / "old-logo.png").exists()
    page = (out / "index.html").read_text(encoding="utf-8")
    d = payload_of(page)
    assert d["published"] and d["callagy"] is None and d["version"] is None and "token" not in d["signup"]
    assert "Secret Client" not in page and "Internal memo" not in page and "/download/" not in page
    assert "dataDownload" not in d and ".xlsx" not in page and "X.Y." not in page
    assert 'name="robots" content="noindex' in page and (out / "robots.txt").read_text() == "User-agent: *\nDisallow: /\n"
    assert 'src="static/app.js"' in page and 'href="/static' not in page  # works from a GitHub project address
    assert '<p class="disclaimer" role="note">' in page and "not legal advice" in page
    assert publish.still_internal(page) == []  # no instructions for whoever builds or runs the dashboard
    assert not any(publish.HIDDEN_FIELDS.match(m["field"]) for m in d["methodology"])
    (out / "CNAME").write_text(publish.DOMAIN + "\n")  # switched on by an earlier run: a DNS hiccup must not undo it
    assert "CNAME" in publish.publish(out) and (out / "CNAME").read_text() == publish.DOMAIN + "\n"


def test_the_custom_domain_is_used_only_once_it_points_to_github(monkeypatch):
    import socket
    import publish
    answers = {"tracker.callagyrecovery.com": ["129.121.74.237"]}  # today: the wildcard to the firm's own web host
    monkeypatch.setattr(socket, "gethostbyname_ex", lambda name: (name, [], answers[name]))
    assert not publish.points_to_github(publish.DOMAIN)
    answers[publish.DOMAIN] = ["185.199.108.153", "185.199.109.153"]  # after IT adds the CNAME record
    assert publish.points_to_github(publish.DOMAIN)
    answers[publish.DOMAIN] = []
    assert not publish.points_to_github(publish.DOMAIN)


def test_staff_names_and_internal_paths_are_reworded():
    import publish
    note = {"n": ["Added 2026-10-16 from Pat Lee's review of 2026-10-12.",
                  "Items still under review are in drafts\\Pat_Review_2_2026-10-16.xlsx.", "Clinic a/s/o X.Y. v. Plan"]}
    assert publish.public(note) == {"n": ["",  # a note about who added a row is not for readers
                                          "Items still under review are in an internal file.", "Clinic a/s/o *** v. Plan"]}


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_push_sends_changes_only_from_main(tmp_path, monkeypatch):
    import publish
    remote, proj = tmp_path / "remote.git", tmp_path / "proj"
    git = lambda *a, cwd=proj: subprocess.run(publish.GIT + list(a), cwd=cwd, capture_output=True, text=True, check=True).stdout  # noqa: E731
    git("init", "-q", "--bare", str(remote), cwd=tmp_path)
    proj.mkdir()
    git("init", "-q", "-b", "main")
    git("remote", "add", "origin", str(remote))
    (proj / ".gitignore").write_text("CLAUDE.md\n", encoding="utf-8")
    (proj / "CLAUDE.md").write_text("private", encoding="utf-8")
    (proj / "notes.txt").write_text("not a public path", encoding="utf-8")
    site = proj / "docs" / "index.html"
    monkeypatch.setattr(main, "ROOT", proj)
    monkeypatch.setattr(publish, "publish", lambda: site.parent.mkdir(exist_ok=True) or site.write_text(site.name + "x", encoding="utf-8"))
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_test")
    assert publish.push("Daily update 1") == "website updated on GitHub"  # a local remote: no build request
    api = "https://api.github.com/repos/callagy-recovery/litigation-tracker/pages/builds"
    asked, latest, slept = [], [{"commit": "abc123"}], []

    def urlopen(req, timeout):
        asked.append((req.get_method(), req.full_url))
        return io.BytesIO(json.dumps(latest[0]).encode() if req.get_method() == "GET" else b"")
    monkeypatch.setattr(publish.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(publish.time, "sleep", slept.append)
    remote_url = "https://github.com/callagy-recovery/litigation-tracker.git"
    # GitHub started the build of the pushed commit by itself: no second request (it would show as "errored").
    assert publish.request_build(remote_url, "t", "abc123") == "" and asked == [("GET", api + "/latest")] and slept == []
    # It never did (still showing the previous commit): wait the minute, then ask once.
    asked.clear()
    latest[0] = {"commit": "old999"}
    assert publish.request_build(remote_url, "t", "abc123") == ""
    assert asked == [("GET", api + "/latest")] * 7 + [("POST", api)] and sum(slept) == publish.BUILD_WAIT
    assert git("ls-tree", "-r", "--name-only", "main", cwd=remote).split() == [".gitignore", "docs/index.html"]
    monkeypatch.setattr(publish, "publish", lambda: None)
    assert publish.push("Daily update 2") == "website already up to date on GitHub"
    assert git("rev-list", "--count", "main", cwd=remote).strip() == "1"
    git("checkout", "-q", "-b", "local-history")
    assert "not pushed" in publish.push("Daily update 3")
    monkeypatch.delenv("GITHUB_TOKEN")
    git("checkout", "-q", "main")
    assert "no GITHUB_TOKEN" in publish.push("Daily update 4")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
@pytest.mark.skipif(not REPORT.exists(), reason="acceptance report not in reports\\")
def test_the_in_page_filter_matches_the_python_one(tmp_path):
    report = data.load(REPORT)
    decisions, pending = list(report["decisions"].values()), list(report["pending"].values())
    counts = {}
    for d in decisions + pending:
        for c in d["insurers"]:
            counts[c] = counts.get(c, 0) + 1
    top = sorted(counts, key=lambda c: -counts[c])[:6]
    choices = [[c] for c in top] + [top[:2], top[2:5], ["Nobody At All"]]
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"decisions": decisions, "pending": pending, "choices": choices,
                                 "base": data.views(decisions, pending)}), encoding="utf-8")
    script = tmp_path / "run.mjs"
    script.write_text(f"""import {{ readFileSync }} from 'node:fs';
eval(readFileSync({json.dumps(str(ROOT / 'app' / 'static' / 'views.js'))}, 'utf8'));
const c = JSON.parse(readFileSync({json.dumps(str(cases))}, 'utf8'));
console.log(JSON.stringify(c.choices.map((only) => globalThis.LTViews.views(c.decisions, c.pending, only, c.base))));
""", encoding="utf-8")
    got = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True, encoding="utf-8").stdout)
    for only, js in zip(choices, got):
        assert js == json.loads(json.dumps(data.views(decisions, pending, only))), only


def test_the_reports_notes_for_the_dashboard_builder_are_reworded_for_readers():
    import publish
    said = {
        "Companion to NSA-042; likely affected on appeal. Added 2026-10-16 from Pat Lee's review of 2026-10-12.":
            "Companion to NSA-042; likely affected on appeal.",
        "Do not heat-map this R&R as a final decision; track final district disposition separately when verified.":
            "Listed as of the magistrate judge's recommendation; see the status for the district judge's later ruling.",
        "Consolidated disposition; analyst may count as one decision event rather than four cases.":
            "Consolidated disposition, covering four cases.",
        "Strong positive district outcome, but later Second Circuit authority should be displayed.":
            "Strong positive district outcome, but later Second Circuit authority should be considered.",
    }
    for before, after in said.items():
        assert publish.public(before) == after and not publish.still_internal(after)
    assert publish.still_internal("Items still under review are in an internal file.") == ["internal file"]


def test_a_partys_claim_reads_as_its_claim_and_process_words_are_plain():
    import publish
    assert publish.public("Two air ambulance providers sued an insurer for failing to timely pay 33 IDR awards.") == (
        "Two air ambulance providers sued an insurer, alleging it failed to timely pay 33 IDR awards.")
    for before in ("Enforcement suit confirmed by both readers; no ruling yet.",
                   "New enforcement suit found by the daily update; no ruling yet.",
                   'Rows marked "Read automatically" come from it; the report always wins where both have a case.',
                   "Read automatically by the daily update: two AI readers agreed on it. Not reviewed by a person.",
                   data.HAND_CAUTION, data.NEWS_CAUTION.format("news report")):
        assert publish.still_internal(before) or "report" in before  # each is internal wording today...
        assert not publish.still_internal(publish.public(before))  # ...and plain on the website
        assert "the report" not in publish.public(before)



def test_nonpayment_and_motives_read_as_what_a_party_said():
    import publish
    said = {
        "A provider sought to enforce IDR awards of $206,723.80 that the insurer had not paid.":
            "A provider sought to enforce IDR awards of $206,723.80 that the provider said the insurer had not paid.",
        "A provider asked the court to confirm and enforce a $31,500 IDR award that Cigna had not paid.":
            "A provider asked the court to confirm and enforce a $31,500 IDR award that the provider said Cigna had not paid.",
        "Providers sued CareFirst to recover unpaid IDR awards.": "Providers sued CareFirst to recover allegedly unpaid IDR awards.",
        "Healthcare providers sued an insurer to enforce an unpaid No Surprises Act IDR award.":
            "Healthcare providers sued an insurer to enforce an allegedly unpaid No Surprises Act IDR award.",
        "The court held the Act gives providers an implied private right of action to enforce unpaid final IDR awards.":
            "The court held the Act gives providers an implied private right of action to enforce unpaid final IDR awards.",
        "Negative ruling on a different theory: the provider sued only under state law to collect the unpaid IDR award, to "
        "get around the NSA private-right question, and the court barred the claims on election of remedies, not preemption.":
            "Negative ruling on a different theory: the provider brought only state-law claims to collect the IDR award, and "
            "the court barred them on election of remedies, not preemption.",
        "Negative result, and the order also threatens Rule 11 sanctions.":
            "Negative result, and the order also refers to possible Rule 11 sanctions.",
        "Superseded by Fifth Circuit affirmance; retain as separate decision event.": "Superseded by Fifth Circuit affirmance.",
        "Appeal pending: appeal from M.D. Fla. dismissal (NSA-053); appeal docket number not yet confirmed.":
            "Appeal pending: appeal from M.D. Fla. dismissal (NSA-053).",
    }
    for before, after in said.items():
        assert publish.public(before) == after and not publish.still_internal(after)
