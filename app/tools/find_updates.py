"""CourtListener, GovInfo and Federal Register searches, and the matching to the newest report, used by the daily update
(app\\daily_update.py). Not run on its own any more.

Keys are read from your Windows user environment, never from files in this shared folder:
  COURTLISTENER_TOKEN  (courtlistener.com)      API_DATA_GOV_KEY  (GovInfo)
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import data  # noqa: E402

import openpyxl  # noqa: E402

CL = "https://www.courtlistener.com"
CL_MIN_INTERVAL = 12.5  # seconds between CourtListener calls: its free tier allows about 5 a minute
CL_QUERY = '"No Surprises Act" AND (IDR OR "independent dispute resolution") AND (confirm OR enforce OR award)'
GOVINFO_QUERY = ('collection:(USCOURTS) AND "No Surprises Act" AND ("independent dispute resolution" OR IDR) '
                 'AND publishdate:range({since},)')
FR_AGENCIES = ["employee-benefits-security-administration", "centers-for-medicare-medicaid-services",
               "internal-revenue-service", "personnel-management-office", "health-and-human-services-department",
               "labor-department", "treasury-department"]
# Court State for a federal appeals court follows the report's convention: the state where the court sits.
CIRCUIT_SEAT = {"1": "MA", "2": "NY", "3": "PA", "4": "VA", "5": "LA", "6": "OH", "7": "IL", "8": "MO", "9": "CA",
                "10": "CO", "11": "GA", "DC": "DC"}
RELEVANT_FR = re.compile(r"independent dispute resolution|\bIDR\b|No Surprises|surprise bill|qualifying payment", re.I)
RULE_CHALLENGE = re.compile(r"\b(HHS|Health and Human Services|Department of Labor|Dep't of Labor|Becerra|Kennedy|"
                            r"Office of Personnel Management|Department of the Treasury)\b", re.I)


# ---------------- small helpers (pure; covered by tests) ----------------

# Federal "nature of suit" categories an award-enforcement suit never falls under (found in the To check list on
# 2026-10-20: a securities class action, an antitrust case, a rules challenge): torts and personal injury (3xx),
# civil rights, antitrust, RICO and the other 4xx, prisoner (5xx), forfeiture (6xx), copyright/patent/trademark,
# securities, social security and tax (82x-88x), agency review (899) and constitutional challenges (950).
OUT_OF_SCOPE_NATURE = re.compile(r"^\s*(3\d\d|4\d\d|5\d\d|6\d\d|8[2-8]\d|899|950)\b|securities|anti-?trust|civil rights|"
                                 r"prisoner|personal injury|patent|trademark|copyright|racketeer|administrative procedure|"
                                 r"social security|constitutionality|tax suits", re.I)
ARBITRATION_CASE = re.compile(r"arbitration|^\s*0?9:\d", re.I)  # nature 896 Arbitration, or a Federal Arbitration Act cause


def out_of_scope_nature(nature):
    return bool(nature) and bool(OUT_OF_SCOPE_NATURE.search(nature))


def docket_facts(nature, cause):
    """What the court's docket says about a case, in words for a person on the To check list."""
    parts = [f"nature of suit: {nature}" if nature else "", f"cause: {cause}" if cause else ""]
    text = "; ".join(p for p in parts if p)
    if not text:
        return ""
    hint = " This looks like a petition to confirm an arbitration award." if ARBITRATION_CASE.search(f"{nature} {cause}") else ""
    return f"The court's docket says {text}.{hint}"


def user_env(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0]).strip() or None
    except OSError:
        return None


norm_docket = data.norm_docket  # lives in data.py so the dashboard can match the daily update's finds to the report


def court_info(court_id, court_name="", jurisdiction=""):
    """(Court Level, circuit key or None, Court State) for a CourtListener/GovInfo court code. None for bankruptcy courts."""
    cid = (court_id or "").lower()
    m = re.fullmatch(r"ca(\d{1,2}|dc)", cid)
    if m:
        key = "DC" if m[1] == "dc" else m[1]
        return ("Federal Appellate", key, CIRCUIT_SEAT[key])
    m = re.fullmatch(r"([a-z]{2})(d|nd|sd|ed|wd|md|cd)", cid)
    if m and (m[1].upper() in data.STATE_NAMES or m[1] == "dc"):
        st = "DC" if m[1] == "dc" else m[1].upper()
        return ("Federal District", data.CIRCUIT_STATES_BY_STATE.get(st), st)
    if re.fullmatch(r"[a-z]{2}(n|s|e|w|m|c)?b", cid) or jurisdiction.upper().startswith("FB"):
        return None  # bankruptcy
    name = court_name or ""
    st = next((ab for ab, full in sorted(data.STATE_NAMES.items(), key=lambda kv: -len(kv[1])) if full in name), "")
    j = jurisdiction.upper()
    if j == "ST" or re.search(r"Superior|Chancery|Supreme Court, [A-Z]|County|Trial|District Court of", name):
        level = "State Trial"
    else:
        level = "State Appellate"
    if "Supreme Court" in name and st == "NY":
        level = "State Trial"  # New York's Supreme Court is its trial court
    return (level, None, st)


def split_parties(case):
    parts = re.split(r"\s+v\.?\s+", case or "", maxsplit=1)
    clean = lambda s: re.sub(r",?\s+et al\.?$", "", s.strip(), flags=re.I)  # noqa: E731
    return (clean(parts[0]), clean(parts[1])) if len(parts) == 2 else (clean(case or ""), "")


def strip_tags(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", s or "")).split())


# ---------------- network ----------------

class Api:
    def __init__(self):
        self.last_cl = 0.0
        self.problems = []

    def get(self, url, headers=None, body=None, cl=False):
        for attempt in range(3):
            if cl:
                wait = self.last_cl + CL_MIN_INTERVAL - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self.last_cl = time.monotonic()
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "LitigationTracker/1.0 (internal research)",
                                                                  **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(min(90, int(e.headers.get("Retry-After") or 60)))
                    continue
                if e.code >= 500 and attempt < 2:  # the site's own trouble: usually gone in a minute
                    time.sleep(20 * (attempt + 1))
                    continue
                raise RuntimeError(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}") from None
            except OSError:  # a timeout or a dropped connection (HTTPError, also an OSError, is handled above)
                if attempt < 2:
                    time.sleep(20 * (attempt + 1))
                    continue
                raise  # the original error, which callers treat as "no answer" (not as the request limit)
        raise RuntimeError("rate limited")


def courtlistener(api, token, since, kind, max_pages, query=CL_QUERY):
    """Search results (opinions 'o' or RECAP dockets 'r') filed on or after `since`."""
    q = urllib.parse.urlencode({"q": query, "type": kind, "filed_after": since.isoformat(), "order_by": "dateFiled desc"})
    url, out = f"{CL}/api/rest/v4/search/?{q}", []
    for _ in range(max_pages):
        j = api.get(url, {"Authorization": "Token " + token}, cl=True)
        out += j.get("results", [])
        url = j.get("next")
        if not url:
            break
    return out


def govinfo(api, key, since, max_pages):
    body = {"query": GOVINFO_QUERY.format(since=since.isoformat()), "pageSize": 100, "offsetMark": "*",
            "sorts": [{"field": "publishdate", "sortOrder": "DESC"}]}
    out = []
    for _ in range(max_pages):
        j = api.get("https://api.govinfo.gov/search", {"X-Api-Key": key, "Content-Type": "application/json"},
                    json.dumps(body).encode())
        out += j.get("results", [])
        nxt = j.get("offsetMark") or j.get("nextOffsetMark")
        if not nxt or not j.get("results") or nxt == body["offsetMark"]:
            break
        body["offsetMark"] = nxt
    return out


def federal_register(api, since, max_pages):
    params = [("conditions[term]", '"independent dispute resolution" | "No Surprises Act"'),
              ("conditions[publication_date][gte]", since.isoformat()), ("per_page", "100"), ("order", "newest")]
    params += [("conditions[agencies][]", a) for a in FR_AGENCIES]
    params += [("fields[]", f) for f in ("title", "type", "publication_date", "effective_on", "html_url", "abstract",
                                          "agencies", "document_number")]
    url, out = "https://www.federalregister.gov/api/v1/documents.json?" + urllib.parse.urlencode(params), []
    for _ in range(max_pages):
        j = api.get(url)
        out += j.get("results", [])
        url = j.get("next_page_url")
        if not url:
            break
    return out


# ---------------- the newest report, for matching ----------------

def read_report():
    found = data.newest_report(ROOT / "reports")
    if not found:
        raise SystemExit("No report found in reports\\")
    path, as_of = found
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    def rows(sheet):
        ws = next((w for w in wb.worksheets if w.title.strip().casefold() == sheet.casefold()), None)
        if ws is None:
            return []
        it = ws.iter_rows(values_only=True)
        head = [str(h).strip() if h is not None else "" for h in next(it, ())]
        return [dict(zip(head, r)) for r in it if r and any(v is not None for v in r)]

    decisions, pending, dol = rows(data.DECISIONS_SHEET), rows(data.PENDING_SHEET), rows(data.DOL_SHEET)
    method = " ".join(str(v) for r in rows(data.METHODOLOGY_SHEET) for v in r.values() if v).casefold()
    wb.close()
    known = []  # (docket key, circuit key or None, state, label)
    for d in decisions:
        for k in norm_docket(d.get("Docket No.")):
            known.append((k, data.norm_circuit(d.get("Circuit")), str(d.get("Court State") or "").upper(), d.get("Decision ID")))
    for p in pending:
        for k in norm_docket(p.get("Docket No.")):
            known.append((k, data.norm_circuit(p.get("Circuit")), str(p.get("Court State") or "").upper(),
                          "Pending: " + str(p.get("Case Name") or "")[:60]))
    dol_titles = [re.sub(r"[^a-z0-9 ]", "", str(a.get("Title") or "").lower()) for a in dol]
    return path, as_of, known, dol_titles, method


def match(known, keys, circuit, state):
    for k, c, s, label in known:
        if k in keys and ((circuit and c == circuit) or (state and s == state)):
            return label
    return None


# ---------------- build candidate rows ----------------

def candidate_from_cl(r, kind):
    info = court_info(r.get("court_id"), r.get("court") or "", r.get("court_jurisdiction") or "")
    if info is None:
        return None
    level, circ, state = info
    url = CL + (r.get("absolute_url") or r.get("docket_absolute_url") or "")
    snippet = ""
    if kind == "o" and r.get("opinions"):
        snippet = strip_tags(r["opinions"][0].get("snippet"))[:400]
    return {"case": r.get("caseName") or r.get("caseNameFull") or "", "court": r.get("court") or "", "level": level,
            "circuit": circ, "state": state, "docket": r.get("docketNumber") or "", "date": r.get("dateFiled") or "",
            "url": url, "snippet": snippet, "via": "CourtListener " + ("opinions" if kind == "o" else "dockets")}


def candidate_from_govinfo(r):
    m = re.match(r"USCOURTS-([a-z0-9]+)-(\d)_(\d{2})-([a-z]+)-0*(\d+)", r.get("packageId") or "")
    if not m:
        return None
    info = court_info(m[1])
    if info is None:
        return None
    level, circ, state = info
    pid, gid = r["packageId"], r.get("granuleId") or r["packageId"]
    author = r.get("governmentAuthor") or []
    court = author[-1] if author else m[1].upper()
    return {"case": r.get("title") or "", "court": court, "level": level, "circuit": circ, "state": state,
            "docket": f"{m[2]}:{m[3]}-{m[4]}-{int(m[5]):05d}", "date": (r.get("dateIssued") or "")[:10],
            "url": f"https://www.govinfo.gov/content/pkg/{pid}/pdf/{gid}.pdf", "snippet": "", "via": "GovInfo court opinions"}
