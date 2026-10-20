"""Reading CourtListener docket entries: what kind of entry it is (ruling, dismissal, settlement, remand, stay), and
finding a case's docket id. Used by the daily update (app\\daily_update.py). Not run on its own any more.
"""
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import find_updates as fu  # noqa: E402  (shared helpers: CL, norm_docket, split_parties)


CHUNK = 25  # dockets per search request
DECISIVE = ('description:(dismiss* OR judgment OR opinion OR confirm* OR remand* OR stipulat* OR "report and recommendation" '
            'OR transferr* OR "motion to stay" OR "order staying" OR settle* OR vacat*)')

# What kind of entry it is decides whether it can be a ruling at all: only the court's own orders, opinions and
# judgments count. Motions, notices and briefs are filings, whatever words they contain.
PARTY_END = re.compile(r"^\W*((joint )?stipulat\w*.{0,60}dismiss|notice of (voluntary )?dismissal)", re.I)
APPEAL = re.compile(r"^\W*notice of appeal", re.I)
FILING = re.compile(r"^\W*(motion|brief|response|reply|letter|declaration|affidavit|summons|complaint|answer|certificate|"
                    r"transcript|exhibit|case assignment|clerk'?s? notice|notice|memorandum (of law|in support|in opposition)|"
                    r"stipulation|consent|proposed|appeal)\b", re.I)
COURT = re.compile(r"^\W*(\S+\W+){0,4}?(order|opinion|ruling|decision|judgment|report and recommendation|mandate)\b", re.I)
NOT_ON_MERITS = re.compile(r"\bexten(d|ds|ded|sion)\b|leave to file|enlarge|time to (respond|answer)|schedul|page limit|briefing", re.I)
# Orders that only mention an outcome: referrals, conference requests, "in the event the motion is denied".
NOISE = re.compile(r"pre-motion conference|motion for conference|referr\w*\b.{0,30}magistrate|in the event", re.I)
VOLUNTARY = re.compile(r"voluntar|stipulat\w* (of|for) dismissal|41\(a\)", re.I)
# Words between the verb and "petition to confirm", none of them "dismiss" ("granting motion to dismiss petition to confirm").
_W = r"((?!\S*dismiss)\S+\s+)"
_PTC = r"(?<!dismiss )(?<!dismiss the )(petition|motion)\s+(to|for)\s+confirm\w*"
# Court entries, checked in this order.
RULES = [
    ("Appeal decided (mandate)", r"\bmandate\b|order of usca"),
    ("Ruling: report and recommendation adopted", r"adopt\w*\s+(\S+\s+){0,3}report and recommendation"),
    ("Ruling: award confirmed / judgment for provider",
     rf"grant\w*\s+{_W}{{0,8}}(petition|motion)\s+(to|for)\s+confirm|{_PTC}.{{0,80}}?\b(is|are)\s+granted|"
     r"award\w*\s+(is|are|be)\s+(hereby\s+)?confirmed|confirming\s+(the\s+)?(\S+\s+){0,2}award|"
     r"judgment\s.{0,40}in favor of (the )?(plaintiff|petitioner)"),
    ("Ruling: petition to confirm denied", rf"den\w*\s+{_W}{{0,3}}(petition|motion)\s+(to|for)\s+confirm|{_PTC}.{{0,80}}?\b(is|are)\s+denied"),
    ("Ruling: dismissed", r"grant\w*( in part)?\s+(\S+\s+){0,4}motions? to dismiss|motions? to dismiss.{0,100}?\b(is )?granted|"
     r"dismiss(ing|es|ed) (the )?(case|complaint|action|petition)|order of dismissal|dismissed (with|without) prejudice"),
    ("Ruling: motion to dismiss denied", r"den\w*( in part)?\s+(?!as moot)(\S+\s+){0,4}motions? to dismiss|motions? to dismiss.{0,100}?\bis denied"),
    # A bare opinion entry ("OPINION. Signed by Judge ... (vm)") names no outcome, but it is the ruling: read it.
    ("Ruling: opinion", r"^\W*(memorandum\s+(and\s+order\s+)?)?opinion\b"),
    ("Recommendation (not final)", r"report and recommendation"),
    ("Moved: remanded or transferred", r"remand\w*|transferr\w*"),
    ("Stayed", r"\bstay\w*"),
    ("Ended: judgment entered", r"\bjudgment\b"),
]
RULING_KINDS = {"Ruling: award confirmed / judgment for provider", "Ruling: petition to confirm denied", "Ruling: dismissed",
                "Ruling: motion to dismiss denied", "Ruling: report and recommendation adopted", "Ruling: opinion",
                "Recommendation (not final)",
                "Appeal filed", "Appeal decided (mandate)"}


def entry_label(text):
    t = text or ""
    if PARTY_END.search(t):
        return "Ended: voluntary dismissal or settlement"
    if APPEAL.search(t):
        return "Appeal filed"
    if FILING.search(t) or not COURT.search(t):
        return None
    for label, pat in RULES:
        if re.search(pat, t, re.I):
            if label.startswith("Ruling") and "to dismiss" in pat and NOT_ON_MERITS.search(t):
                continue  # e.g. "order granting extension of time to respond to motion to dismiss"
            if label != "Stayed" and NOISE.search(t):
                continue
            if label == "Ruling: dismissed" and VOLUNTARY.search(t):
                return "Ended: voluntary dismissal or settlement"  # court closing the case on the parties' own dismissal
            return label
    return None


def classify(entries):
    """entries: [(date, text)] newest first -> (status, date, text). Rulings beat later housekeeping entries."""
    found = []
    for date, text in entries:
        label = entry_label(text)
        if label:
            found.append((label, date, text))
    for label, date, text in found:  # newest ruling first
        if label in RULING_KINDS:
            return label, date, text
    return found[0] if found else ("No ruling or closing entry found", "", "")


def docket_link(did):
    """A link that opens: CourtListener 404s on /docket/<id>/ without the case-name slug, so search for the docket instead."""
    return f"{fu.CL}/?type=r&q=docket_id%3A{did}" if did else ""


def court_code(name):
    """'U.S. Court of Appeals for the Second Circuit' -> 'ca2'; 'U.S. District Court for the Northern District of Oklahoma' -> 'oknd'."""
    words = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
             "ninth": 9, "tenth": 10, "eleventh": 11}
    n = (name or "").replace(",", "")
    m = re.search(r"(\w+) Circuit", n)
    if "Appeals" in n and m:
        w = m[1].lower()
        return "cadc" if w in ("d.c.", "dc", "columbia") else f"ca{words.get(w, w.rstrip('stndrh'))}"
    m = re.search(r"(Northern|Southern|Eastern|Western|Middle|Central)?\s*District of ([A-Z][A-Za-z ]+)", n)
    if m:
        st = next((ab for ab, full in fu.data.STATE_NAMES.items() if full == m[2].strip()), None)
        if st:
            return st.lower() + (m[1][0].lower() if m[1] else "") + "d"
    return None


def cl_docket_number(s):
    """Report formats -> CourtListener's: '4:2025cv00466' -> '4:25-cv-00466'; '26-2269' stays."""
    m = re.search(r"(\d):(\d{2}|\d{4})-?cv-?0*(\d+)", str(s or ""), re.I)
    return f"{m[1]}:{m[2][-2:]}-cv-{int(m[3]):05d}" if m else str(s or "").strip()


def resolve_ids(api, token, rows, ids, budget):
    """Find the CourtListener docket id for each row (court + docket number), 20 numbers per search, remembered in ids."""
    todo, byname = {}, []
    for d in rows:
        key, code, num = f"{d.get('Court')}|{d.get('Docket No.')}", court_code(d.get("Court")), cl_docket_number(d.get("Docket No."))
        strict, keys = re.fullmatch(r"\d:\d{2}-cv-\d{5}|\d{2}-\d+", num), fu.norm_docket(d.get("Docket No."))
        if code and not strict and keys and ids.get(key) is None:
            byname.append((key, code, keys, d.get("Case Name")))  # '26-cv-00736-FWS-KES', '25 Civ. 499': find by party name
            continue
        if key in ids:
            continue
        if not code or not strict:
            ids[key] = None  # state courts: not in CourtListener's federal dockets
            continue
        todo[(code, num)] = key
    for key, code, keys, case in byname:
        words = re.findall(r"[A-Za-z]{4,}", fu.split_parties(case or "")[0])[:2]
        if not words or budget["left"] <= 0:
            continue
        q = urllib.parse.urlencode({"type": "r", "court": code, "q": "caseName:(" + " AND ".join(words) + ")"})
        url, found = f"{fu.CL}/api/rest/v4/search/?{q}", None
        for _ in range(3):  # a busy provider can have dozens of cases in one court
            if not url or found or budget["left"] <= 0:
                break
            budget["left"] -= 1
            try:
                j = api.get(url, {"Authorization": "Token " + token}, cl=True)
            except RuntimeError:
                return
            # Any number of a consolidated case will do ('25 Civ. 499 / 1255 / 1264 / 2049').
            found = next((str(r["docket_id"]) for r in j.get("results", []) if set(fu.norm_docket(r.get("docketNumber"))) & set(keys)), None)
            url = j.get("next")
        ids[key] = found or False  # False = looked up by name too and not found, so it isn't searched again every run
    pairs = list(todo)
    for i in range(0, len(pairs), 20):
        chunk = pairs[i:i + 20]
        q = urllib.parse.urlencode({"type": "r", "court": " ".join(sorted({c for c, _ in chunk})),
                                    "q": "docketNumber:(" + " OR ".join(f'"{n}"' for _, n in chunk) + ")"})
        url, hits = f"{fu.CL}/api/rest/v4/search/?{q}", {}
        while url and budget["left"] > 0:
            budget["left"] -= 1
            try:
                j = api.get(url, {"Authorization": "Token " + token}, cl=True)
            except RuntimeError:
                return  # rate limited: unresolved rows are tried again next run
            for r in j.get("results", []):
                hits.setdefault((r.get("court_id"), r.get("docketNumber")), str(r["docket_id"]))
            url = j.get("next")
        if url:
            return
        for pair in chunk:
            ids[todo[pair]] = hits.get(pair)
