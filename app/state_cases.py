"""State court cases found by hand. A person saves the court's document (a ruling, or the complaint of a new case) as a
PDF in "State cases\\New\\" - nothing to type. Each daily update reads every file there: both readers pick out the
case, court, state, docket number and date (reader.identify), then read it like any other ruling or new case. What they
agree on goes on the dashboard; the rest goes on the day's To check list. Each file then moves to "State cases\\Done\\".

State court records cannot be searched by a script (logins, CAPTCHAs, sites that block scripts), so a person finds the
cases with "How to find state cases.docx" in the same folder; everything after that is automatic.
"""
import datetime as dt
import html
import os
import re
from pathlib import Path

import data
import reader

FOLDER, NEW, DONE = "State cases", "New", "Done"
GUIDE = "How to find state cases.docx"
SOURCE = "State cases (saved by hand)"
KINDS = (".pdf", ".htm", ".html")
MAX_FILES = 30  # files read per run; the rest wait for the next run


def folder(root):
    return Path(root) / FOLDER


def make_folders(root):
    for sub in (NEW, DONE):
        (folder(root) / sub).mkdir(parents=True, exist_ok=True)


def text_of(f, file_text):
    """A saved PDF (scans copied out by Claude) or web page."""
    if f.suffix.lower() in (".htm", ".html"):
        raw = f.read_text(encoding="utf-8", errors="replace")
        return html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)))
    return file_text(f)


def file_away(f):
    """Move a read file to Done\\, named with today's date so two files with the same name never clash."""
    done = f.parent.parent / DONE
    done.mkdir(exist_ok=True)
    target, n = done / f"{dt.date.today().isoformat()} {f.name}", 1
    while target.exists():
        n += 1
        target = done / f"{dt.date.today().isoformat()} ({n}) {f.name}"
    os.replace(f, target)
    return target


def check_file(text, system, payer_of):
    """(what happened, entries for found.json, why it needs a person or "", the details read)."""
    info = reader.identify(text)
    if not info["agreed"]:
        return "to check", {}, info["note"], info
    if info["level"] == "Federal":
        return "to check", {}, ("This is a federal court document. Federal cases are found automatically; answer Leave "
                                "out unless it is missing from the dashboard."), info
    if info["kind"] not in ("ruling", "complaint"):
        return "to check", {}, "The readers say this is not a ruling or a complaint (for example a docket sheet or a brief).", info
    if info["state"] not in data.STATE_NAMES or not info["date"]:
        return "to check", {}, "The readers could not find the court's state or the date on the document.", info
    case = data.mask(info["case"])
    row = {"case": case, "court": info["court"], "level": info["level"], "circuit": "", "state": info["state"],
           "docket": info["docket"], "payer": data.mask(payer_of(case)), "url": "", "source": SOURCE}
    pending = {**{k: row[k] for k in ("case", "court", "level", "circuit", "state", "docket", "url", "payer")},
               "filed": info["date"],
               "status": "State case saved by hand; both readers confirmed it is an enforcement suit. No ruling yet."}
    if info["kind"] == "complaint":
        verdict = reader.screen(text, case)
        if verdict:
            return "new case: shown as pending", {"pending": [pending]}, "", info
        if verdict is False:  # a person chose to save it, so a person has the last word
            return "to check", {}, "Both readers say this is not a suit to enforce an IDR award. If they are right, answer Leave out.", info
        return "to check", {}, "The two readers could not tell whether this is a suit to enforce an IDR award.", info
    res = reader.read(text, case, info["date"], system)
    if not res["agreed"]:
        return "to check", {}, res["note"], info
    if not res["relevant"]:  # a person chose to save it, so a person has the last word
        return "to check", {}, ("Both readers say this ruling does not decide whether an IDR award can be enforced. If "
                                "they are right, answer Leave out. " + res.get("reason", "")).strip(), info
    if res["result"] not in ("Win", "Loss"):
        pending["status"] = "State case saved by hand; the order read does not decide enforcement yet."
        return "no decision on enforcement yet: shown as pending", {"pending": [pending]}, "", info
    return (f"{res['result']} ({'final' if res['final'] else 'not final'}): shown as a ruling",
            {"decisions": [{**row, "date": info["date"], "result": res["result"], "final": res["final"],
                            "holding": data.mask(res["holding"]), "rounds": res["rounds"]}]}, "", info)


def run(root, found, state, system, file_text, say, summaries=None, limit=MAX_FILES, asks=None, progress=None):
    """Read every file in State cases\\New\\, oldest first; update found in place and file each one away.
    Returns (counts, items for the To check list). Stops early (rest next run) if Claude stops."""
    import to_check
    from find_updates import split_parties
    make_folders(root)
    state.pop("stateCases", None)  # the old workbook's progress (before 2026-10-19)
    files = sorted((f for f in (folder(root) / NEW).iterdir() if f.is_file() and f.suffix.lower() in KINDS),
                   key=lambda f: f.stat().st_mtime)
    counts = {"read": 0, "rulings": 0, "pending": 0, "to check": 0, "waiting": max(0, len(files) - limit)}
    asks = [] if asks is None else asks  # the run's own list, so its checkpoint saves these rows too
    for n, f in enumerate(files[:limit]):
        say(f"  reading: {f.name}")
        try:
            text = text_of(f, file_text)
            what, adds, why, info = check_file(text, system, lambda case: split_parties(case)[1])
        except reader.Declined:  # this file only
            what, adds, why, info = "to check", {}, "Claude declined to read this document.", {}
        except reader.ReaderError as e:
            say(f"  Claude stopped: {e}. The remaining files are read next run.")
            counts["waiting"] += len(files[:limit]) - n
            break
        done = file_away(f)
        for k, items in adds.items():
            found.setdefault(k, []).extend(items)
        if why:
            case = info.get("case") or f.stem
            asks.append(to_check.item(
                f"state:{done.name}", "State case (saved by hand)",
                why + " Check the Case, Court, State and Date columns and correct them if they are wrong.",
                {"case": data.mask(case), "court": info.get("court", ""), "level": info.get("level") or "State Trial",
                 "circuit": "", "state": (info.get("state") or "").upper(), "docket": info.get("docket", ""),
                 "date": info.get("date", ""), "payer": data.mask(split_parties(case)[1]), "url": str(done)}))
        counts["read"] += 1
        counts["rulings"] += len(adds.get("decisions", []))
        counts["pending"] += len(adds.get("pending", []))
        counts["to check"] += bool(why)
        say(f"    -> {what}" + (f" ({why})" if why else "") + f"; moved to {DONE}")
        if progress:
            progress()  # the file has moved to Done: its result must be saved before anything else can fail
        if summaries is not None and adds.get("decisions"):
            d = adds["decisions"][0]
            summaries(text, d["case"], d["date"], d["result"], d)
    return counts, asks
