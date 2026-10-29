"""Litigation Tracker daily update: finds new NSA enforcement rulings, cases and DOL actions, reads each new ruling with
the two-level Claude reader (reader.py), and saves what it found for the dashboard in auto\\found.json. It also
follows every case already on the dashboard for new rulings, and reads the files saved by hand in "State cases\\New".
What the two readers agree on goes straight on the dashboard; the rest goes on a dated list in "To check\\"
(to_check.py) for a person, whose answers the next run puts on the dashboard.

Run "Daily Update\\Litigation Tracker Daily Update.exe" once a day, or from source:
    .venv\\Scripts\\python app\\daily_update.py [--since YYYY-MM-DD] [--max-reads N]

Needs, on this Windows account: Claude Code installed and signed in; COURTLISTENER_TOKEN, and API_DATA_GOV_KEY for
GovInfo, as user environment variables (never in files). Never changes reports\\ or resources\\: the report always wins
over what this finds. Progress is kept in auto\\state.json, so an order not read today (usage limit, network) is read
next time.
"""
import argparse
import datetime as dt
import getpass
import html
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import data  # noqa: E402
import insurers  # noqa: E402
import nj_stay  # noqa: E402
import reader  # noqa: E402
import state_cases  # noqa: E402
import to_check  # noqa: E402
import find_updates as fu  # noqa: E402
import check_dockets as cd  # noqa: E402

import pypdf  # noqa: E402

# The exe sits in <project>\Daily Update\; from source this file is <project>\app\daily_update.py.
ROOT = Path(sys.executable).resolve().parent.parent if FROZEN else HERE.parent
fu.ROOT = ROOT  # find_updates.read_report() looks in ROOT\reports
AUTO, DRAFTS, LOGS = ROOT / "auto", ROOT / "drafts", ROOT / "logs"
FOUND, STATE = AUTO / data.AUTO_FILE, AUTO / "state.json"
CURL = r"C:\Windows\System32\curl.exe"  # Python's SSL fails on some court hosts behind the office proxy
MAX_READS = 30  # orders read per run; the rest wait for the next run
MAX_SCREENS = 40  # new dockets whose first filing is checked per run
PAYERS = {insurers.INS, insurers.BLUE, insurers.NET, insurers.PLAN, insurers.EMP}
NOT_PAYERS = {insurers.GOV, insurers.PROV, insurers.IDR, insurers.OUT, insurers.IND}
MAX_PAGES = 4  # search result pages per source
OVERLAP_DAYS = 3  # search a little before the last run, in case a court posted a ruling late
DOCKET_LOOKBACK_DAYS = 60  # court entries on followed cases often reach CourtListener weeks after their filing date
RULING_LABELS = {"Ruling: award confirmed / judgment for provider", "Ruling: petition to confirm denied", "Ruling: dismissed",
                 "Ruling: motion to dismiss denied", "Ruling: report and recommendation adopted", "Appeal decided (mandate)",
                 "Ruling: opinion"}

log = logging.getLogger("lt.daily")


def say(msg=""):
    print(data.mask(msg), flush=True)
    log.info(msg)


class _Masking(logging.Formatter):
    def format(self, record):
        return data.mask(super().format(record))


def setup_logging():
    LOGS.mkdir(exist_ok=True)
    h = logging.FileHandler(LOGS / f"daily_{dt.datetime.now():%Y-%m-%d_%H%M%S}_{getpass.getuser()}.log", encoding="utf-8")
    h.setFormatter(_Masking("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


def load_json(path, default):
    """See data.read_json: an unreadable file falls back to its backup or stops the run, never starts from empty."""
    return data.read_json(path, default)


def save_json(path, obj):
    """Write to a temporary file, then swap it in, so the dashboard never reads half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    data.swap_in(tmp, path)


# ---------------- order text ----------------

MAX_SCAN_PAGES = 25  # pages of a scanned PDF copied out by Claude (about 2 cents a page)


def page_images(pdf):
    """PNG bytes of each page's scan image, grey and at most 1600 px, for a PDF that is pictures of pages."""
    import io

    from PIL import Image
    out = []
    for page in pdf.pages[:MAX_SCAN_PAGES]:
        imgs = list(page.images)
        if not imgs:
            continue
        im = Image.open(io.BytesIO(max(imgs, key=lambda i: len(i.data)).data)).convert("L")
        im.thumbnail((1600, 1600))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        out.append(buf.getvalue())
    return out


def file_text(f, transcribe=None):
    """A PDF file's text; a scan (no text layer, or only the court's page headers) is copied out page by page by
    Claude, so the readers can still read it. Raises reader.ReaderError if Claude cannot be run."""
    if not f.exists() or f.read_bytes()[:5] != b"%PDF-":
        return ""
    try:
        pdf = pypdf.PdfReader(f)
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if len(re.sub(r"Case \S+\s+Document \d+\s+Filed.*?Page \d+ of \d+", "", text).split()) >= 60:
            return text
        pages = page_images(pdf)
    except Exception:  # a damaged PDF is "no readable text", not a crash
        return ""
    if not pages:
        return text
    say(f"    (scanned PDF: copying out {len(pages)} pages)")
    return "\n\n".join((transcribe or reader.transcribe_page)(png) for png in pages)


def pdf_text(url):
    """The text of an order at url: a PDF (scans copied out by Claude) or a court's HTML page."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "order.pdf"
        subprocess.run([CURL, "-sL", "--max-time", "120", "-o", str(f), url], capture_output=True)
        if f.exists() and f.read_bytes()[:5] != b"%PDF-" and re.search(rb"<html|<body", f.read_bytes()[:3000], re.I):
            return fu.strip_tags(re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", f.read_text(encoding="utf-8", errors="replace")))
        return file_text(f)


# ---------------- AI summaries for the dashboard's Latest rulings card ----------------

SUMMARY_SOURCES = AUTO / "summary_sources.json"  # {ruling key: readable link} where the report's own link cannot be read
SUMMARY_NEWEST = None  # every ruling the Latest rulings card can show (all of each view); None = no limit
MAX_SUMMARIES = 10  # summaries written per run


def readable(url):
    """A link the daily update can read itself: not Justia (it blocks scripts), not an article, not a docket page."""
    return bool(url) and not re.search(r"justia\.com|americanbar\.org|courtlistener\.com/docket/", url)


def ruling_text(url):
    """The text of a ruling at url. A CourtListener opinion page is read through its API (the page itself is not for
    scripts, and its text loads separately); anything else as a PDF or court web page. The number in a page address
    /opinion/<n>/ is the CASE (CourtListener's "cluster"), not the opinion document: read as an opinion id it gives an
    unrelated order or a 404, so the case is looked up first and its opinion documents read."""
    m = re.search(r"courtlistener\.com/opinion/(\d+)/", url or "")
    if not m:
        return pdf_text(url)
    api, auth = fu.Api(), {"Authorization": "Token " + (fu.user_env("COURTLISTENER_TOKEN") or "")}
    cluster = api.get(f"{fu.CL}/api/rest/v4/clusters/{m[1]}/?fields=sub_opinions", auth, cl=True)
    text = ""
    for o in cluster.get("sub_opinions") or []:  # the lead opinion first; a concurrence or dissent only if it has none
        j = api.get(o.rstrip("/") + "/?fields=plain_text,html_with_citations,html,download_url", auth, cl=True)
        text = j.get("plain_text") or fu.strip_tags(j.get("html_with_citations") or j.get("html") or "")
        if len(text.split()) < 60 and j.get("download_url"):
            text = pdf_text(j["download_url"])
        if len(text.split()) >= 60:
            break
    return text


def same_case(text, case):
    """False when neither party's name is in the text: the copy fetched is some other case's order."""
    words = lambda s: [w for w in re.findall(r"[a-z]{4,}", s.lower()) if w not in NOT_NAMES][:1]  # noqa: E731
    names = [w for side in fu.split_parties(case) for w in words(side)]
    low = (text or "").lower()
    return not names or any(n in low for n in names)


NOT_NAMES = {"inc", "llc", "corp", "company", "the", "health", "medical", "services", "insurance", "group", "plan",
             "life", "care", "healthcare", "center", "associates", "professional", "physicians", "blue", "cross",
             "shield", "united", "national", "american", "foundation"}


def write_summaries(report, limit=MAX_SUMMARIES, newest=SUMMARY_NEWEST):
    """Two-reader summaries (reader.summarise) for the newest included rulings that have none for their current outcome.
    A ruling the readers could not agree on is remembered, and tried again only if its outcome changes."""
    store, sources = load_json(AUTO / data.SUMMARY_FILE, {}), load_json(SUMMARY_SOURCES, {})
    # The newest in each view, so the first cards on every tab have one: a federal-only list would leave the state tab
    # and the appellate view (older, fewer rulings) without summaries.
    views = report["views"]
    rulings, seen = [], set()
    for v in ("state", "federal", "appellate"):
        for i in views[v]["caseIds"][:newest]:
            if i not in seen:
                seen.add(i)
                rulings.append(report["decisions"][i])
    rulings.sort(key=lambda d: d["date"], reverse=True)
    done = {"written": 0, "could not agree": 0, "no readable copy": 0}
    for d in rulings:
        if done["written"] + done["could not agree"] >= limit:
            break
        key, outcome = data.ruling_key(d), "Win" if d["win"] else "Loss"
        if store.get(key, {}).get("outcome") == outcome:
            continue  # already summarised (or tried) for this outcome
        url = sources.get(key) or (d["url"] if readable(d["url"]) and not d.get("fromNews") else "")  # a news page is no order
        if not url:
            done["no readable copy"] += 1
            continue
        say(f"  summarising: {d['case'][:70]} ({d['date']})")
        try:
            text = ruling_text(url)
        except RuntimeError as e:  # nothing is recorded, so it is tried again next run
            if "429" in str(e) or "rate limited" in str(e):  # CourtListener's request limit: stop for today
                say(f"    stopped: {e}. The rest are written next run.")
                break
            say(f"    skipped: {e} (this ruling's copy could not be fetched)")  # e.g. a 404: only this one
            done["no readable copy"] += 1
            continue
        if not same_case(text, d["case"]):  # the wrong order: never summarise it as this case
            say("    skipped: the copy fetched is a different case's order")
            done["no readable copy"] += 1
            continue
        try:
            res = reader.summarise(text, d["case"], d["date"], outcome)
        except reader.Declined:  # this ruling only
            res = {"agreed": False, "note": "Claude declined to read this order."}
        entry = {"outcome": outcome, "case": d["case"], "date": d["date"], "source": url,
                 "written": dt.datetime.now().isoformat(timespec="seconds")}
        if res["agreed"]:
            store[key] = {**entry, "summary": data.mask(res["summary"])}  # the quote only checks it; it can hold names
            done["written"] += 1
        else:
            store[key] = {**entry, "failed": data.mask(res["note"])}
            done["could not agree"] += 1
            say(f"    no summary: {res['note'][:160]}")
        save_json(AUTO / data.SUMMARY_FILE, store)
    return done


def order_text(api, token, c):
    """The order's text from the first source that has it."""
    for kind, ref in c["fetch"]:
        try:
            if kind == "pdf":
                text = pdf_text(ref)
            else:  # CourtListener opinion id
                j = api.get(f"{fu.CL}/api/rest/v4/opinions/{ref}/?fields=plain_text,html_with_citations,html,download_url",
                            {"Authorization": "Token " + token}, cl=True)
                text = j.get("plain_text") or fu.strip_tags(j.get("html_with_citations") or j.get("html") or "")
                if len(text.split()) < 60 and j.get("download_url"):
                    text = pdf_text(j["download_url"])
        except RuntimeError:
            text = ""
        if len(text.split()) >= 60:
            return text
    return ""


# ---------------- finding things ----------------

# State-court opinions are worded more loosely than federal ones (AA Medical v. Aetna never says "IDR" near "confirm"),
# so state courts get a wider search of their own; the readers still decide what is relevant.
STATE_QUERY = '"No Surprises Act" OR "surprise billing" OR "300gg-111" OR "300gg-112" OR "independent dispute resolution"'
STATE_FROM = dt.date(2022, 1, 1)  # the first run of the state search looks back to when IDR began


def ruling_candidates(api, token, gi_key, since, known, state=None):
    """New rulings from CourtListener opinions and GovInfo, merged on docket and date, minus those in the report."""
    state = {} if state is None else state
    raw = []
    if token:
        raw += [("o", r) for r in fu.courtlistener(api, token, since, "o", MAX_PAGES)]
        state_since = since if state.get("stateSearchDone") else STATE_FROM
        raw += [("s", r) for r in fu.courtlistener(api, token, state_since, "o", MAX_PAGES, query=STATE_QUERY)]
    if gi_key:
        raw += [("gi", r) for r in fu.govinfo(api, gi_key, since, MAX_PAGES)]
    if token:
        state["stateSearchDone"] = True
    out = {}
    for kind, r in raw:
        c = fu.candidate_from_cl(r, "o") if kind in ("o", "s") else fu.candidate_from_govinfo(r)
        if c is None or not provider_v_payer(c["case"]) or (kind == "s" and not c["level"].startswith("State")):
            continue
        keys = fu.norm_docket(c["docket"]) or [re.sub(r"[^a-z0-9]", "", c["case"].lower())]
        hit = fu.match(known, keys, c["circuit"], c["state"])
        if hit and not str(hit).startswith("Pending:"):
            continue  # the report already has this ruling
        fetch = ([("pdf", c["url"])] if kind == "gi" else
                 [("cl_opinion", o["id"]) for o in r.get("opinions") or [] if o.get("id")])
        dkey = f"{keys[0]}|{c['circuit'] or c['state']}|{c['date']}"
        if dkey in out:
            out[dkey]["fetch"] += fetch
            continue
        out[dkey] = {**c, "case": data.mask(c["case"]), "key": dkey, "fetch": fetch,
                     "payer": data.mask(fu.split_parties(c["case"])[1]), "source": c["via"]}
    return list(out.values())


def docket_updates(api, token, since, report, state, found, history=None):
    """Court entries since `since` on every case being followed: the report's pending and decided cases, and the
    dockets found earlier. Returns ruling candidates; settlements and voluntary dismissals go straight into
    found["ended"]. A later ruling in a case the report has already decided is marked "decided" (a person decides it).
    `history` (docket id -> To check row): open To check cases searched once over their WHOLE docket, so a case that
    ended or was decided before the look-back still settles its row (state["historyChecked"] records which were)."""
    history = history or {}
    follow = {}  # docket id -> case details
    ids = state.setdefault("docketIds", {})
    cases = list(report["pending"].values()) + list(report["decisions"].values())
    rows = [{"Court": p["court"], "Docket No.": p["docket"], "Case Name": p["case"]} for p in cases if p.get("docket")]
    cd.resolve_ids(api, token, rows, ids, {"left": 40})
    for p in cases:
        did = ids.get(f"{p['court']}|{p.get('docket')}")
        if did:
            follow[did] = {"case": p["case"], "court": p["court"], "level": "Federal Appellate" if p["appellate"] else
                           ("Federal District" if p["level"] == "federal" else "State Trial"), "circuit": p["circuit"],
                           "state": p["state"], "docket": p["docket"], "payer": p["payer"], "decided": "outcome" in p}
    for did, p in state.get("dockets", {}).items():
        if p.get("enforcement") is not False and did not in follow and provider_v_payer(p["case"]):  # confirmed or not told
            follow[did] = {k: p[k] for k in ("case", "court", "level", "circuit", "state", "docket", "payer")}
    for did, i in history.items():
        follow.setdefault(did, {k: i.get(k) for k in ("case", "court", "level", "circuit", "state", "docket", "payer")})
    decided_on = [(set(data.norm_docket(d["docket"])), d["date"]) for d in report["decisions"].values()]
    recent, whole = sorted(d for d in follow if d not in history), sorted(history)
    batches = ([(recent[i:i + cd.CHUNK], since) for i in range(0, len(recent), cd.CHUNK)] +
               [(whole[i:i + cd.CHUNK], None) for i in range(0, len(whole), cd.CHUNK)])
    out = []
    for part, start in batches:
        when = f" AND entry_date_filed:[{start.isoformat()} TO *]" if start else ""
        q = urllib.parse.urlencode({"type": "rd", "order_by": "entry_date_filed desc",
                                    "q": f"docket_id:({' OR '.join(part)}) AND {cd.DECISIVE}{when}"})
        url, answered = f"{fu.CL}/api/rest/v4/search/?{q}", True
        for _ in range(MAX_PAGES):
            if not url:
                break
            try:
                j = api.get(url, {"Authorization": "Token " + token}, cl=True)
            except OSError as e:  # no answer even after Api.get's retries: only this batch waits for the next run
                say(f"  {len(part)} cases not checked today ({e}); they are checked on the next run")
                answered = False
                break
            for r in j.get("results", []):
                p, desc = follow.get(str(r.get("docket_id"))), r.get("description") or r.get("short_description") or ""
                label = cd.entry_label(desc)
                if not p or not label:
                    continue
                date = (r.get("entry_date_filed") or "")[:10]
                if label == "Ended: voluntary dismissal or settlement":
                    end = {**{k: p.get(k) for k in ("case", "docket", "circuit", "state")}, "date": date, "status": label}
                    if end not in found["ended"]:  # the long look-back sees the same entry on several runs
                        found["ended"].append(end)
                elif label in RULING_LABELS:
                    keys = set(data.norm_docket(p["docket"]))
                    if p.get("decided") and any(keys & k and _days(d, date) <= 3 for k, d in decided_on):
                        continue  # the ruling the report already has
                    pdf = r.get("filepath_local")
                    out.append({**p, "date": date, "key": f"rd:{r.get('id')}", "source": "CourtListener docket entry",
                                "url": "https://storage.courtlistener.com/" + pdf if pdf else fu.CL + (r.get("absolute_url") or ""),
                                "fetch": [("pdf", "https://storage.courtlistener.com/" + pdf)] if pdf else [],
                                "docketLabel": label, "docketText": desc[:400]})
            url = j.get("next")
        if start is None and answered:  # whole docket searched: from now on the look-back is enough
            state.setdefault("historyChecked", {}).update({d: dt.date.today().isoformat() for d in part})
    return out


def history_to_check(store, state):
    """The open To check cases (docket id -> row) whose whole docket has not been searched yet."""
    done = state.get("historyChecked", {})
    return {i["docketId"]: i for i in store.values() if i.get("docketId") and not i.get("answer") and i["docketId"] not in done}


def _days(a, b):
    try:
        return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)
    except (TypeError, ValueError):
        return 999


class RateLimited(Exception):
    """CourtListener's request limit was reached; what was searched so far is kept."""


def search_all(api, token, q, pages=6):
    """Every result of one CourtListener RECAP-document search, a few pages at most."""
    url, out = f"{fu.CL}/api/rest/v4/search/?" + urllib.parse.urlencode({"type": "rd", "q": q, "order_by": "entry_date_filed desc"}), []
    for _ in range(pages):
        if not url:
            break
        try:
            j = api.get(url, {"Authorization": "Token " + token}, cl=True)
        except OSError:  # no answer even after Api.get's retries: what was found so far is kept
            j = {}
        except RuntimeError as e:  # Api.get has already waited and retried on HTTP 429
            raise RateLimited(str(e)) from None
        out += j.get("results", [])
        url = j.get("next")
    return out


CATCH_UP_CHUNK = 10  # dockets per search; more made searches slow enough to time out
MAX_CATCH_UP = 40  # dockets caught up per run


def catch_up(api, token, state, found):
    """Dockets added without their history (state["dockets"][id]["history"] is False): find the first filing (main
    document only) and the latest decisive entry once. Returns ruling candidates, like docket_updates."""
    todo = [did for did, d in state.get("dockets", {}).items() if d.get("history") is False][:MAX_CATCH_UP]
    out = []
    for k in range(0, len(todo), CATCH_UP_CHUNK):
        part = todo[k:k + CATCH_UP_CHUNK]
        first, entries = {}, {i: [] for i in part}
        try:
            for r in search_all(api, token, f"docket_id:({' OR '.join(part)}) AND document_number:[1 TO 3]"):
                did, pdf, key = str(r.get("docket_id")), r.get("filepath_local"), r.get("document_number") or 99
                if did in state["dockets"]:  # the docket's nature of suit and cause, for the checks in screen_dockets
                    state["dockets"][did].setdefault("nature", r.get("suitNature") or "")
                    state["dockets"][did].setdefault("cause", r.get("cause") or "")
                if pdf and not r.get("attachment_number") and (did not in first or key < first[did][0]):
                    first[did] = (key, "https://storage.courtlistener.com/" + pdf)  # exhibits never: patient records
            for r in search_all(api, token, f"docket_id:({' OR '.join(part)}) AND {cd.DECISIVE}"):
                did, pdf = str(r.get("docket_id")), r.get("filepath_local")
                if did in entries:
                    entries[did].append(((r.get("entry_date_filed") or "")[:10], r.get("description") or r.get("short_description") or "",
                                         "https://storage.courtlistener.com/" + pdf if pdf else "", r.get("id")))
        except RateLimited:
            say("  CourtListener's request limit was reached; the rest are caught up next run.")
            break
        for did in part:
            d = state["dockets"][did]
            d["doc"], d["history"] = d.get("doc") or (first[did][1] if did in first else ""), True
            label, date, text = cd.classify([(e[0], e[1]) for e in entries[did]])
            p = {k2: d.get(k2) for k2 in ("case", "court", "level", "circuit", "state", "docket", "payer")}
            if label == "Ended: voluntary dismissal or settlement":
                found["ended"].append({**{k2: d.get(k2) for k2 in ("case", "docket", "circuit", "state")}, "date": date, "status": label})
            elif label in RULING_LABELS:
                e = next(e for e in entries[did] if e[0] == date and e[1] == text)
                out.append({**p, "date": date, "key": f"rd:{e[3]}", "source": "CourtListener docket entry",
                            "url": e[2] or cd.docket_link(did), "fetch": [("pdf", e[2])] if e[2] else [],
                            "docketLabel": label, "docketText": text[:400]})
    return out


def provider_v_payer(case):
    """A provider suing a payer: the plaintiff is not a payer, the defendant could be one, and it is not a rule challenge.
    A cheap first filter before anything is read; unrecognised names ("Check") are given the benefit of the doubt."""
    plaintiff, defendant = fu.split_parties(case)
    kinds = lambda side: {insurers.classify(x)[1] for x in insurers.split(side)}  # noqa: E731
    kp, kd = kinds(plaintiff), kinds(defendant)
    return not (kp & PAYERS) and bool(kd - NOT_PAYERS) and not fu.RULE_CHALLENGE.search(case or "")


def new_dockets(api, token, since, known, state):
    """CourtListener dockets filed since `since` that the report does not have, kept in state["dockets"] until their
    first filing has been checked (screen_dockets). Returns how many were new."""
    seen, added = state.setdefault("dockets", {}), 0
    for r in fu.courtlistener(api, token, since, "r", MAX_PAGES):
        c, did = fu.candidate_from_cl(r, "r"), str(r.get("docket_id"))
        if (c is None or did in seen or r.get("dateTerminated") or not provider_v_payer(c["case"])
                or fu.out_of_scope_nature(r.get("suitNature"))):
            continue
        if fu.match(known, fu.norm_docket(c["docket"]), c["circuit"], c["state"]):
            continue
        # The main document only (the complaint or petition), never its attachments: exhibits can hold a patient's
        # medical records, which must not be sent anywhere (and trip Claude's content filter).
        docs = sorted((d for d in r.get("recap_documents") or [] if d.get("filepath_local") and not d.get("attachment_number")),
                      key=lambda d: (d.get("document_number") or 0))
        seen[did] = {"case": data.mask(c["case"]), "court": c["court"], "level": c["level"], "circuit": c["circuit"],
                     "state": c["state"], "filed": c["date"], "docket": c["docket"], "url": c["url"],
                     "payer": data.mask(fu.split_parties(c["case"])[1]), "docketId": did,
                     "doc": "https://storage.courtlistener.com/" + docs[0]["filepath_local"] if docs else "",
                     "nature": r.get("suitNature") or "", "cause": r.get("cause") or "",
                     "enforcement": None, "screened": False}
        added += 1
    return added


def main_document(url):
    """A RECAP link to an attachment ('...moed.231846.1.2.pdf') -> the main document of that entry ('...1.0.pdf')."""
    return re.sub(r"(\.\d+)\.[1-9]\d*\.pdf$", r"\1.0.pdf", url or "")


def waiting_dockets(state):
    """New dockets whose first filing has not been checked by both readers yet (and that no person has answered)."""
    return [d for d in state.get("dockets", {}).values()
            if (not d["screened"] or d.get("layers") != 2) and not d.get("byHand") and d.get("history") is not False]


def screen_dockets(state, found, limit, asks, progress=lambda: None):
    """Read the first available filing of each new docket once: only confirmed enforcement suits are shown as pending.
    One the readers cannot tell goes on the To check list (asks), and is still followed, so a later ruling is read."""
    # Dockets checked before the second reader was added (2026-10-16) are checked again once, with both readers.
    # Cases with a first filing to read come first and count toward the limit; those still without one (the weekly
    # retries) cost no reading, so they never push a new case to the next run.
    waiting = waiting_dockets(state)
    todo = [d for d in waiting if d.get("doc")][:limit] + [d for d in waiting if not d.get("doc")]
    shown = 0
    for d in todo:
        # Settled without reading: an insurer suing, a suit against the government, or a nature of suit an
        # enforcement suit never has. Dockets added from a review file had not been through these checks.
        if not provider_v_payer(d["case"]) or fu.out_of_scope_nature(d.get("nature")):
            d["screened"], d["enforcement"], d["layers"] = True, False, 2
            found["pending"] = [p for p in found["pending"] if p.get("docketId") != d["docketId"] or p.get("byHand")]
            say(f"  {d['case'][:70]}: not an enforcement suit (parties or nature of suit)")
            continue
        d["doc"] = main_document(d["doc"])
        why = "The two readers could not tell whether this is a suit to enforce an IDR award."
        try:
            verdict = reader.screen(pdf_text(d["doc"]), d["case"]) if d["doc"] else None
            if not d["doc"]:
                why = "No free copy of the first filing on CourtListener."
        except reader.Declined:  # this filing only; the step carries on
            verdict = None
            d["declined"] = True
            why = "Claude declined to read the first filing."
            say(f"  {d['case'][:70]}: Claude declined to read this filing (still followed)")
        d["screened"], d["enforcement"], d["layers"] = True, verdict, 2
        found["pending"] = [p for p in found["pending"] if p.get("docketId") != d["docketId"] or p.get("byHand")]
        if verdict:
            found["pending"].append({k: d[k] for k in ("case", "court", "level", "circuit", "state", "filed", "docket",
                                                       "url", "payer", "docketId")} |
                                    {"status": "New enforcement suit found by the daily update; no ruling yet."})
            shown += 1
        elif verdict is None:
            asks.append(to_check.item(f"docket:{d['docketId']}", "New case", why,
                                      {**{k: d.get(k) for k in ("case", "court", "level", "circuit", "state", "docket",
                                                                "url", "payer", "docketId", "filed")}, "date": d.get("filed")},
                                      fu.docket_facts(d.get("nature"), d.get("cause"))))
        say(f"  {d['case'][:70]}: {'enforcement suit' if verdict else 'not an enforcement suit' if verdict is False else 'could not tell (still followed)'}")
        progress()
    return shown


GEORGETOWN_FEED = "https://litigationtracker.law.georgetown.edu/issues/no-surprises-act/feed/"  # robots.txt allows all
DOCKET_TEXT = re.compile(r"\b\d:\d{2}-cv-\d+|\b\d{2}-\d{3,5}\b|\b\d{5,6}/\d{4}\b")


def georgetown_leads(state, report, asks, fetch=None):
    """New cases on the No Surprises Act feed of Georgetown's Health Care Litigation Tracker that the dashboard does
    not have: each goes on the To check list as a lead for a person. The first run only remembers what is on the feed,
    so cases listed before then are not asked about. Returns how many leads were added."""
    import xml.etree.ElementTree as ET

    import to_check
    if fetch is None:
        fetch = lambda url: subprocess.run([CURL, "-sL", "--max-time", "60", "-A", "LitigationTracker/1.0 (internal research)", url],  # noqa: E731
                                           capture_output=True).stdout
    items = ET.fromstring(fetch(GEORGETOWN_FEED)).findall("./channel/item")
    first_run = "georgetown" not in state
    seen = state.setdefault("georgetown", [])
    rows = list(report["decisions"].values()) + list(report["pending"].values()) + list(state.get("dockets", {}).values())
    known = {k for x in rows for k in data.norm_docket(x.get("docket"))}
    name = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())[:25]  # noqa: E731
    names = {name(x.get("case")) for x in rows}
    added = 0
    for it in items:
        guid = it.findtext("guid") or it.findtext("link")
        if guid in seen:
            continue
        seen.append(guid)
        title = data.mask(html.unescape(it.findtext("title") or ""))
        body = html.unescape(re.sub(r"<[^>]+>", " ", it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""))
        dockets = DOCKET_TEXT.findall(body)
        if first_run or not provider_v_payer(title) or set(data.norm_docket(" ".join(dockets))) & known or name(title) in names:
            continue
        try:
            date = dt.datetime.strptime(it.findtext("pubDate")[:16], "%a, %d %b %Y").date().isoformat()
        except (TypeError, ValueError):
            date = ""
        federal = bool(dockets) and "cv" in dockets[0]
        asks.append(to_check.item(
            f"lead:{guid}", "Lead (Georgetown tracker)",
            "Georgetown's tracker lists this case and the dashboard may not have it. Open the link: if it is a suit to "
            "enforce an IDR award, fill in the Court, State and Date and answer; if it is not, or it is already on the "
            "dashboard, answer Leave out. For a state case you can also save its documents in State cases\\New.",
            {"case": title, "court": "", "level": "Federal District" if federal else "State Trial", "circuit": "",
             "state": "", "docket": dockets[0] if dockets else "", "date": date, "url": it.findtext("link") or "",
             "payer": data.mask(fu.split_parties(title)[1])}))
        added += 1
    return 0 if first_run else added


# CMS posts the IDR notices, guidance and FAQs under /initiatives/no-surprise-billing (robots.txt allows it; there is
# no feed or API). The /nosurprises pages are for consumers and are not watched.
CMS_SECTION = "https://www.cms.gov/initiatives/no-surprise-billing/"
CMS_START = [CMS_SECTION + "overview/notices", CMS_SECTION + "overview/policies-resources", CMS_SECTION + "overview/engaging-idr"]
CMS_MAX_PAGES = 30
# IDR material only: guidance, FAQs, notices, memos, fees, batching, eligibility, operations, attestations, reports.
CMS_RELEVANT = re.compile(r"\bIDR\b|independent dispute|batch|fee|operation|FAQ|guidance|memo|attestation|qualifying payment|"
                          r"\bQPA\b|arbitrat|eligib|reopening|technical assistance", re.I)
CMS_NOISE = re.compile(r"user guide|web form|help desk|call center|quarterly provider update|toolkit|template|quick reference|"
                       r"training|spanish|español|public use file|\bPUF\b|data dictionary|consumer|supplemental tables|"
                       r"\(xlsx\)", re.I)


def cms_title(text, url):
    """A link's text, or a title made from the file name when the link is only part of a sentence ("published an
    attestation (PDF)", "February 28 guidance (PDF)")."""
    text = re.sub(r"\s*\((PDF|DOCX?|XLSX?)\)\s*$", "", text, flags=re.I)
    name = re.sub(r"\.(pdf|docx?|xlsx?)(-\d+)?$", "", url.rsplit("/", 1)[-1], flags=re.I)
    if not text[:1].islower() and (len(text.split()) > 3 or len(re.split(r"[-_]+", name)) < 4):
        return text
    words = [w.upper() if w.lower() in ("idr", "faq", "faqs", "nsa", "qpa", "cms") else w for w in re.split(r"[-_]+", name) if w]
    title = " ".join(words)
    return title[:1].upper() + title[1:] if title else text


def cms_file_date(url):
    """The date CMS's server gives for a file (Last-Modified), as the pages themselves show no dates; '' if none."""
    head = subprocess.run([CURL, "-sIL", "--max-time", "60", "-A", "LitigationTracker/1.0 (internal research)", url],
                          capture_output=True).stdout.decode("utf-8", "replace")
    m = re.findall(r"(?im)^last-modified:\s*\w+,\s*(\d{1,2} \w{3} \d{4})", head)
    try:
        return dt.datetime.strptime(m[-1], "%d %b %Y").date().isoformat() if m else ""
    except ValueError:
        return ""


def faq_number(title):
    """'FAQs ... Part 71' and 'FAQs ... (Set 71)' are the same FAQs: their number, or None."""
    m = re.search(r"\bFAQ.*?\b(?:part|set)\s*(\d+)", title or "", re.I)
    return m[1] if m else None


def cms_guidance(state, dol_titles, found, fetch=None, date_of=None):
    """New IDR guidance documents on CMS's No Surprises billing pages (CMS_START and the section pages they link to,
    two levels down): each new, relevant PDF goes into the DOL actions, marked as read automatically. The first run
    only remembers the documents already there. Returns how many were added."""
    if fetch is None:
        fetch = lambda url: subprocess.run([CURL, "-sL", "--max-time", "60", "-A", "LitigationTracker/1.0 (internal research)", url],  # noqa: E731
                                           capture_output=True).stdout.decode("utf-8", "replace")
    first_run = "cms" not in state
    seen = state.setdefault("cms", [])
    pages, queue, docs = set(), [(u, 0) for u in CMS_START], {}
    while queue and len(pages) < CMS_MAX_PAGES:
        url, depth = queue.pop(0)
        if url in pages:
            continue
        pages.add(url)
        page = fetch(url)
        for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
            href = href.split("#")[0]
            if "?" in href or not href:  # robots.txt disallows query URLs
                continue
            absolute = href if href.startswith("http") else "https://www.cms.gov" + href if href.startswith("/") else ""
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()
            if re.match(r"https://www\.cms\.gov/files/", absolute) and text:
                docs.setdefault(absolute, text)
            elif absolute.startswith(CMS_SECTION) and depth < 2:
                queue.append((absolute, depth + 1))
    titles = [a["title"] for a in found["dol"]] + list(dol_titles)
    have = {re.sub(r"[^a-z0-9]", "", t.lower()) for t in titles}
    have_faqs = {faq_number(t) for t in titles} - {None}
    have_urls = {a.get("url") for a in found["dol"]}
    added = 0
    for url, title in docs.items():
        if url in seen:
            continue
        seen.append(url)
        if first_run or not CMS_RELEVANT.search(title) or CMS_NOISE.search(title):
            continue
        if re.sub(r"[^a-z0-9]", "", title.lower()) in have or faq_number(title) in have_faqs or url in have_urls:
            continue  # already on the dashboard, perhaps worded differently ("Part 71" / "Set 71")
        title = cms_title(title, url)
        found["dol"].append({"title": data.mask(title), "agency": "Centers for Medicare & Medicaid Services", "type": "Guidance",
                             "issued": (date_of or cms_file_date)(url) or dt.date.today().isoformat(), "effective": None,
                             "status": "Posted on CMS's No Surprises billing pages", "summary": "", "url": url})
        added += 1
    return 0 if first_run else added


IDR_TEXT = re.compile(r"independent dispute resolution|\bIDR\b", re.I)


def relevant_dol(r):
    """Closely related only (the library scope the legal team set): the title is about IDR or surprise billing, or the
    summary is about IDR itself. A passing mention of the No Surprises Act is not enough."""
    return bool(fu.RELEVANT_FR.search(r.get("title") or "") or IDR_TEXT.search(r.get("abstract") or ""))


def new_dol(api, since, dol_titles, found):
    have = {re.sub(r"[^a-z0-9 ]", "", a["title"].lower()) for a in found["dol"]}
    added = 0
    for r in fu.federal_register(api, since, MAX_PAGES):
        if not relevant_dol(r):
            continue
        t = re.sub(r"[^a-z0-9 ]", "", (r.get("title") or "").lower())
        if not t or t in have or any(t == x or t in x or x in t for x in dol_titles if x):
            continue
        have.add(t)
        found["dol"].append({"title": r.get("title"), "agency": ", ".join(a.get("name", "") for a in r.get("agencies") or []),
                             "type": r.get("type"), "issued": r.get("publication_date"), "effective": r.get("effective_on"),
                             "status": "Published in the Federal Register", "summary": r.get("abstract"), "url": r.get("html_url")})
        added += 1
    return added


# ---------------- the run ----------------

def read_queue(api, token, queue, state, found, system, max_reads, asks, progress=lambda: None):
    """Read queued orders, newest first. What both readers agree on goes on the dashboard; the rest, and any later
    ruling in a case the report has already decided, goes on the To check list (asks). Stops early (leaving the rest
    queued) if Claude cannot be run."""
    queue.sort(key=lambda c: c.get("date") or "", reverse=True)
    done, results = [], []
    for c in queue[:max_reads]:
        say(f"  reading: {c['case'][:80]} ({c.get('court', '')[:40]}, {c.get('date')})")
        try:
            text = order_text(api, token, c)  # a scan is copied out by Claude, so this can hit the usage limit too
            res = reader.read(text, data.mask(c["case"]), c.get("date"), system, c.get("docketLabel"), c.get("docketText", ""))
        except reader.Declined:  # this order only: it goes on the To check list, and the queue carries on
            res = {"agreed": False, "rounds": 0, "note": "Claude declined to read this document; check it by hand."}
        except reader.ReaderError as e:
            say(f"  Claude stopped: {e}. The remaining {len(queue) - len(done)} orders will be read next run.")
            break
        done.append(c["key"])
        state["seen"][c["key"]] = {"date": c.get("date"), "result": res.get("result"), "agreed": res["agreed"]}
        row = {"case": data.mask(c["case"]), "court": c.get("court"), "level": c.get("level"), "circuit": c.get("circuit"),
               "state": c.get("state"), "date": c.get("date"), "docket": c.get("docket"), "payer": data.mask(c.get("payer", "")),
               "url": c.get("url"), "source": c.get("source")}
        agreed_ruling = res["agreed"] and res["relevant"] and res["result"] in ("Win", "Loss")
        if agreed_ruling and c.get("decided"):
            outcome = f"{res['result']}: a later ruling in a case the report has decided (to check)"
            asks.append(to_check.item(c["key"], "Later ruling in a decided case",
                                      "The report already has a ruling in this case; a person decides whether this one is added.",
                                      row, f"Both readers: {res['result']} ({'final' if res['final'] else 'not final'}). {res['holding']}"))
        elif agreed_ruling:
            found["decisions"].append({**row, "result": res["result"], "final": res["final"],
                                       "holding": data.mask(res["holding"]), "rounds": res["rounds"]})
            outcome = f"{res['result']} ({'final' if res['final'] else 'not final'})"
        elif res["agreed"]:
            outcome = "not an enforcement ruling" if not res["relevant"] else "no decision yet (pending)"
        else:
            asks.append(to_check.item(c["key"], "Ruling", res["note"], row))
            outcome = "to check: " + res["note"]
        say(f"    -> {outcome}")
        results.append((c, res, outcome))
        queue[:] = [x for x in queue if x["key"] != c["key"]]  # read: off the queue now, so a crash does not read it again
        progress()
    queue[:] = [c for c in queue if c["key"] not in done]
    return results


def save_state_summary(text, case, date, outcome, ruling):
    """The AI summary of a state ruling read from a saved file: written now, as the file is not online for
    write_summaries to fetch later."""
    store = load_json(AUTO / data.SUMMARY_FILE, {})
    key = data.ruling_key(ruling)
    if store.get(key, {}).get("outcome") == outcome:
        return
    try:
        res = reader.summarise(text, case, date, outcome)
    except reader.Declined:
        res = {"agreed": False, "note": "Claude declined to read this order."}
    entry = {"outcome": outcome, "case": case, "date": date, "source": state_cases.SOURCE,
             "written": dt.datetime.now().isoformat(timespec="seconds")}
    store[key] = {**entry, "summary": data.mask(res["summary"])} if res["agreed"] else {**entry, "failed": data.mask(res["note"])}
    save_json(AUTO / data.SUMMARY_FILE, store)


def state_step(report, state, found, asks, progress=lambda: None):
    """The State cases rows (state_cases.run); None if it could not run. Never stops the rest of the update."""
    try:
        s, _ = state_cases.run(ROOT, found, state, reader.system_prompt(report["decisions"].values()), file_text, say,
                               save_state_summary, asks=asks, progress=progress)
    except Exception as e:  # a broken workbook must not stop the searches' results being saved
        say(f"  skipped: {e}")
        log.exception("State cases step failed")
        return None
    say(f"  {s['read']} files read: {s['rulings']} rulings and {s['pending']} pending cases added, "
        f"{s['to check']} on the To check list, {s['waiting']} waiting for the next run.")
    return s


def state_search_step(report, state, found, store, asks, progress=lambda: None):
    """State cases found online (state_search.update); None if it could not run. Never stops the rest of the update."""
    sys.modules.setdefault("daily_update", sys.modules[__name__])  # state_search imports this module by that name
    import state_search
    try:
        s = state_search.update(report, state, found, store, asks, say, progress)
    except Exception as e:  # a site or Claude problem must not stop the rest of the update
        say(f"  skipped: {e}")
        log.exception("State cases found online failed")
        return None
    say(f"  {s['dashboard']} put on the dashboard, {s['to check']} on the To check list, {s['known']} already known, "
        f"{s['open']} still open (tried again next run); {s['settled']} To check rows settled (the court's own document "
        "is on the dashboard now).")
    return s


def apply_answers(store, state, found):
    """Put the To check answers on the dashboard (found.json): Pending case, Win and Loss are shown, marked "Checked by
    a person"; Leave out takes the case off. The dockets answered are followed (or not) from now on."""
    rows, leave = to_check.dashboard_rows(store)
    for k in ("decisions", "pending"):
        found[k] = [x for x in found[k] if not x.get("toCheck")]
    answered = {i["docketId"]: i["answer"] for i in store.values() if i.get("answer") and i.get("docketId")}
    for did, ans in answered.items():
        d = state.get("dockets", {}).get(did)
        if d and not store.get(f"docket:{did}", {}).get("auto"):  # only a person's answer marks the docket as theirs
            d["byHand"], d["enforcement"] = ans, ans != to_check.LEAVE
    # The answer's own row (dashboard_rows, rebuilt every run) replaces what the readers made of the same docket.
    found["pending"] = [p for p in found["pending"] if p.get("docketId") not in answered]
    found["decisions"] += rows["decisions"]
    found["pending"] += rows["pending"]
    return len(rows["decisions"]) + len(rows["pending"]), len(leave)


RETRY_DAYS = 7  # how often a To check case with no free first filing is looked up again


def retry_missing_filings(store, state, today=None):
    """Open To check cases whose first filing was not free: once a week, look the docket up again (catch_up), in case
    the complaint has reached CourtListener since. If both readers can then read it, auto_settle answers the row."""
    today = today or dt.date.today()
    n = 0
    for i in store.values():
        d = state.get("dockets", {}).get(i.get("docketId") or "")
        if i.get("answer") or not d or d.get("doc") or d.get("enforcement") is not None or d.get("byHand"):
            continue
        last = d.get("retried")
        if last and (today - dt.date.fromisoformat(last)).days < RETRY_DAYS:
            continue
        d.update(history=False, screened=False, retried=today.isoformat())
        n += 1
    return n


def lead_case_rulings(results):
    """A line for the run's summary when a ruling both readers agreed on is in the New Jersey lead case."""
    lead = set(data.norm_docket(nj_stay.LEAD_CASE["docket"]))
    return [f"LEAD CASE RULING: {c['case'][:60]} ({c.get('date')}) was read as a {r['result']}. It governs the "
            f"{len(nj_stay.DOCKETS)} New Jersey cases stayed by the Jan 16, 2026 order; tell the legal team."
            for c, r, _ in results if r.get("agreed") and r.get("result") in ("Win", "Loss")
            and lead & set(data.norm_docket(c.get("docket") or ""))]


def on_nj_stay_list(i):
    """A District of New Jersey case listed in the court's own stay order of its NSA enforcement suits (app/nj_stay.py)."""
    return "new jersey" in (i.get("court") or "").lower() and bool(set(data.norm_docket(i.get("docket") or "")) & nj_stay.DOCKETS)


def auto_settle(store, state, found):
    """Answer the open To check rows this run has settled by itself, so they leave the list (to_check.tidy): a ruling
    both readers agreed on, a first filing both confirmed, a settlement or voluntary dismissal, a case found not to
    be an enforcement suit, or a New Jersey case on the court's stay list (shown as pending, marked "From court
    order"). The checks run in that order, so a ruling or an ending always wins over the stay. Returns how many."""
    n = 0
    decisions = [x for x in found.get("decisions", []) if not x.get("byHand")]
    on_dashboard = {p.get("docketId") for p in found.get("pending", []) if not p.get("byHand")}
    for key, i in store.items():
        did = i.get("docketId")
        if i.get("answer") or not did:
            continue
        d = state.get("dockets", {}).get(did, {})
        keys = set(data.norm_docket(i.get("docket")))
        same = lambda x: bool(keys & set(data.norm_docket(x.get("docket")))) and (x.get("state") or "") == (i.get("state") or "")  # noqa: E731
        ruling = next((x for x in decisions if same(x)), None)
        ended = next((x for x in found.get("ended", []) if same(x)), None)
        when = dt.date.today().strftime("%b %d, %Y")
        if ruling:
            to_check.settle(store, key, ruling["result"], f"Settled by the daily update on {when}: both readers read the "
                            f"ruling of {ruling['date']}. {ruling.get('holding') or ''}".strip())
        elif d.get("enforcement") is False:
            why = (f"its nature of suit is {d['nature']}" if fu.out_of_scope_nature(d.get("nature")) else
                   "the parties show it is not a provider suing an insurer" if not provider_v_payer(i.get("case")) else
                   "both readers read the first filing")
            to_check.settle(store, key, to_check.LEAVE, f"Settled by the daily update on {when}: not an enforcement suit ({why}).")
        elif ended:
            to_check.settle(store, key, to_check.LEAVE, f"Settled by the daily update on {when}: the case ended without a "
                            f"ruling ({ended.get('status', '').split(': ')[-1]}, {ended.get('date')}).")
        elif on_nj_stay_list(i):
            to_check.settle(store, key, to_check.PENDING, f"Settled by the daily update on {when}: {nj_stay.STATUS}")
            i.update(fromOrder=True, status=nj_stay.STATUS)  # kept, so every later run rebuilds the same dashboard row
            if did in state.get("dockets", {}):  # confirmed: never screened again (which would take it off the dashboard)
                state["dockets"][did].update(screened=True, enforcement=True, layers=2, stayed=True)
            found["pending"] = [p for p in found["pending"] if p.get("docketId") != did or p.get("byHand")]
            found["pending"].append({k: i.get(k) for k in ("case", "court", "level", "circuit", "state", "docket", "url",
                                                           "payer", "docketId")} |
                                    {"filed": i.get("filed") or i.get("date"), "status": nj_stay.STATUS, "fromOrder": True,
                                     "toCheck": key})
        elif did in on_dashboard:
            to_check.settle(store, key, to_check.PENDING, f"Settled by the daily update on {when}: both readers read the "
                            "first filing and confirmed it is an enforcement suit.")
        else:
            continue
        n += 1
    return n


def check_setup():
    """(claude exe, token, govinfo key) or exit with what to fix."""
    exe = reader.claude_exe()
    ok, msg = reader.signed_in(exe)
    token, gi_key = fu.user_env("COURTLISTENER_TOKEN"), fu.user_env("API_DATA_GOV_KEY")
    say(f"Claude Code: {msg}")
    say(f"CourtListener key: {'set' if token else 'MISSING'} · GovInfo key: {'set' if gi_key else 'missing (GovInfo skipped)'}")
    problems = []
    if not ok:
        problems.append("Claude Code: open a terminal, run  claude  and sign in with your Callagy account (/login).")
    if not token:
        problems.append("Set COURTLISTENER_TOKEN in your Windows user environment variables (from courtlistener.com).")
    return exe, token, gi_key, problems


LOCK_STALE_HOURS = 6  # a lock older than this is from a run that died without cleaning up


def acquire_lock():
    """Only one daily update at a time, whoever starts it: a lock file in auto\\ made atomically. Returns None when
    taken, or a message naming the run already going."""
    lock = AUTO / "daily_update.lock"
    me = {"user": getpass.getuser(), "computer": os.environ.get("COMPUTERNAME", "?"), "pid": os.getpid(),
          "started": dt.datetime.now().isoformat(timespec="seconds")}
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                other = json.loads(lock.read_text(encoding="utf-8"))
                age = dt.datetime.now() - dt.datetime.fromisoformat(other["started"])
            except (OSError, ValueError, KeyError):
                other, age = {}, dt.timedelta(hours=LOCK_STALE_HOURS)  # unreadable: treat as left over
            if age < dt.timedelta(hours=LOCK_STALE_HOURS):
                return (f"Another daily update is already running (started {other.get('started', '?').replace('T', ' ')} "
                        f"by {other.get('user', '?')} on {other.get('computer', '?')}). Wait for it to finish, then run "
                        "again if needed.")
            log.warning("Removing a lock left by a run that did not finish: %s", other)
            lock.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(me, f)
        return None
    return "The run lock could not be taken; try again in a minute."


def release_lock():
    (AUTO / "daily_update.lock").unlink(missing_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="look for items on or after this date (default: the last run, or a year before the report)")
    ap.add_argument("--max-reads", type=int, default=MAX_READS, help=f"orders to read this run (default {MAX_READS})")
    a = ap.parse_args(argv)
    setup_logging()
    AUTO.mkdir(exist_ok=True)
    say(f"Litigation Tracker daily update · {dt.datetime.now():%a %b %d %Y, %I:%M %p}")
    exe, token, gi_key, problems = check_setup()
    if problems:
        say("\nCannot run yet:\n  " + "\n  ".join(problems))
        return 2
    busy = acquire_lock()
    if busy:
        say("\n" + busy)
        return 3
    try:
        return run(a, token, gi_key)
    except data.DataFileError as e:
        say(f"\nStopped: {e}")
        return 2
    finally:
        release_lock()


def update_website(message):
    """Rebuild the public website from the project's data and push what changed to GitHub (publish.push). The tests
    replace this (tests\\conftest.py): a test run must never publish anything."""
    os.environ["LT_ROOT"] = str(ROOT)  # before publish imports main, which otherwise looks next to this exe
    import publish
    return publish.push(message)


def run(a, token, gi_key):
    """One daily update, holding the run lock. Progress is saved after every step and every document read, and again
    if anything goes wrong, so a crash loses at most the item being read."""
    found_report = data.newest_report(ROOT / "reports")
    if not found_report:
        say("No report in reports\\. Nothing to compare against, so nothing was done.")
        return 2
    report = data.load(found_report[0])  # the report alone: what is already known, and the editor's own coding
    _, as_of, known, dol_titles, _ = fu.read_report()
    state = load_json(STATE, {})
    state.setdefault("seen", {})
    queue = state.setdefault("queue", [])
    found = load_json(FOUND, {})
    for k in ("decisions", "pending", "ended", "dol"):
        found.setdefault(k, [])
    last = state.get("lastRun")
    since = (dt.date.fromisoformat(a.since) if a.since else
             dt.date.fromisoformat(last[:10]) - dt.timedelta(days=OVERLAP_DAYS) if last else as_of - dt.timedelta(days=365))
    say(f"Report: {found_report[0].name} · looking for items since {since}\n")

    say("Your answers in the To check folder…")
    store = to_check.load(ROOT)
    changed = to_check.collect(ROOT, store, say)
    shown, left_out = apply_answers(store, state, found)
    to_check.save(ROOT, store)
    say(f"  {len(changed)} new answers · {shown} cases on the dashboard from answers, {left_out} left out")
    retried = retry_missing_filings(store, state)
    if retried:
        say(f"  {retried} cases with no free first filing are looked up again today")
    say("")

    api, notes, asks, summary = fu.Api(), [], [], {}
    written = {"file": None, "added": 0}

    def save_progress():
        """Everything done so far: the finds, the progress, and the To check rows collected (asks). Called after every
        step and every document read, and if anything fails, so nothing found is lost and nothing is asked twice."""
        save_json(FOUND, found)
        save_json(STATE, state)
        if asks or to_check.unwritten(store):  # also rows held back last time because To check.xlsx was open
            f, n = to_check.add(ROOT, store, asks)
            written["file"], written["added"] = f or written["file"], written["added"] + n
            asks.clear()
        to_check.save(ROOT, store)

    try:
        steps = [("New rulings (CourtListener opinions incl. a wider state-court search, GovInfo)",
                  lambda: ruling_candidates(api, token, gi_key, since, known, state)),
                 ("Leads from Georgetown's Health Care Litigation Tracker", lambda: georgetown_leads(state, report, asks)),
                 ("New cases (CourtListener)", lambda: new_dockets(api, token, since, known, state)),
                 ("Updates on every case already followed (CourtListener)", lambda: docket_updates(api, token, since - dt.timedelta(days=DOCKET_LOOKBACK_DAYS), report, state, found,
                                        history_to_check(store, state))),
                 ("Earlier entries of newly added cases (CourtListener)", lambda: catch_up(api, token, state, found)),
                 ("DOL and agency actions (Federal Register)", lambda: new_dol(api, since, dol_titles, found)),
                 ("Guidance on CMS's No Surprises pages", lambda: cms_guidance(state, dol_titles, found))]
        queued = {c["key"] for c in queue}
        for label, fn in steps:
            say(f"Searching: {label}…")
            try:
                got = fn()
            except Exception as e:  # one source failing must not stop the others
                notes.append(f"{label}: failed ({e}). The other sources still ran.")
                say(f"  failed: {e}")
                continue
            if isinstance(got, list):
                new = [c for c in got if c["key"] not in state["seen"] and c["key"] not in queued and c.get("fetch") is not None]
                for c in new:
                    if not c["fetch"]:  # a ruling entry whose document is not on CourtListener
                        asks.append(to_check.item(
                            c["key"], "Later ruling in a decided case" if c.get("decided") else "Ruling",
                            "The court's docket shows a ruling, but no free copy of it is on CourtListener.",
                            {k: c.get(k) for k in ("case", "court", "level", "circuit", "state", "docket", "date", "url", "payer")},
                            c.get("docketText", "")))
                        state["seen"][c["key"]] = {"date": c.get("date"), "result": None, "agreed": False}
                        continue
                    queue.append(c)
                    queued.add(c["key"])
                say(f"  {len(new)} new to read")
            else:
                say(f"  {got} new")
            save_progress()

        waiting = len(waiting_dockets(state))
        if waiting:
            say(f"\nReading the first filing of {min(waiting, MAX_SCREENS)} of {waiting} new cases (two readers each)…")
            try:
                summary["New cases put on the dashboard"] = screen_dockets(state, found, MAX_SCREENS, asks, save_progress)
            except reader.ReaderError as e:
                say(f"  Claude stopped: {e}. The rest are read next run.")
        say("\nState cases saved by hand (State cases\\New)…")
        state_step(report, state, found, asks, save_progress)
        say("\nState cases found online (web search, NJ courts; two readers each)…")
        online = state_search_step(report, state, found, store, asks, save_progress)
        if online:
            summary["State cases found online put on the dashboard"] = online["dashboard"]
        say(f"\nReading {min(len(queue), a.max_reads)} of {len(queue)} rulings (two readers each)…")
        results = read_queue(api, token, queue, state, found, reader.system_prompt(report["decisions"].values()), a.max_reads, asks, save_progress)
        summary["Rulings put on the dashboard"] = sum(1 for c, r, _ in results if r["agreed"] and r.get("relevant")
                                                      and r.get("result") in ("Win", "Loss") and not c.get("decided"))
        notes.extend(lead_case_rulings(results))
        summary["To check rows settled by this run"] = auto_settle(store, state, found)
    except BaseException:  # a crash, Ctrl+C, the window closed: keep what was done
        save_progress()
        raise

    found.pop("unread", None)  # older files: what could not be read now goes on the To check list
    found["lastRun"] = state["lastRun"] = dt.datetime.now().isoformat(timespec="seconds")
    save_progress()  # before the summaries and the newsletter, which can fail without costing anything
    f, added = written["file"], written["added"]
    moved = to_check.tidy(ROOT, store, say)  # settled rows leave the To check sheet
    to_check.save(ROOT, store)
    say("\nWriting AI summaries for the latest rulings (two readers each)…")
    try:
        write_summaries(data.load(found_report[0], AUTO))  # the report plus what this run found
    except reader.ReaderError as e:
        say(f"  Claude stopped: {e}. The rest are written next run.")
    except Exception as e:  # a network or site problem: the summaries are only extras
        log.exception("Summaries failed")
        notes.append(f"AI summaries: stopped ({e}); the rest are written next run.")
        say(f"  stopped: {e}")
    say("\nNewsletter…")
    try:
        import newsletter
        say("  " + newsletter.run(data.load(found_report[0], AUTO), found_report[0].name, AUTO, say))
    except Exception as e:  # Outlook missing or closed: the rest of the run still counts
        notes.append(f"Newsletter: skipped ({e}).")
        say(f"  skipped: {e}")
    say("\nWebsite (GitHub Pages)…")
    try:
        say("  " + update_website(f"Daily update {found['lastRun'][:16].replace('T', ' ')}"))
    except Exception as e:  # no git, no network, GitHub down: the H: dashboard is up to date regardless
        log.exception("Website update failed")
        notes.append(f"Website: not updated ({e}). The H: dashboard is up to date.")
        say(f"  not updated: {e}")

    say("\n" + "=" * 60 + "\nDone.")
    for k, v in summary.items():
        say(f"  {v:>4}  {k}")
    say(f"  {added:>4}  New rows to check by hand" + (f": {f}" if f else ""))
    say(f"  {moved:>4}  Settled rows moved off the To check list (kept on each file's Settled sheet)")
    say(f"  {to_check.open_count(store):>4}  Rows waiting for an answer in {to_check.FOLDER}\\{to_check.FILE}")
    if to_check.unwritten(store):
        say(f"  {to_check.unwritten(store):>4}  Rows not added yet: {to_check.FILE} was open in Excel. Close it; the next run adds them.")
    later = len(queue) + len(waiting_dockets(state))
    if later:
        say(f"  {later:>4}  Not reached today: done automatically on the next run")
    for n in notes:
        say("  " + n)
    say("\nOpen dashboards show a 'New data is available' banner.")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # show the problem in the window instead of closing it
        log.exception("Daily update failed")
        print(f"\nThe daily update stopped with an error: {data.mask(str(e))}\nDetails are in {LOGS}.")
        code = 1
    if FROZEN:  # double-clicked: keep the window open to read the summary
        try:
            input("\nPress Enter to close this window.")
        except (EOFError, OSError):  # started without a keyboard (from a script)
            pass
    sys.exit(code)
