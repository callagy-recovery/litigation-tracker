"""The "To check" lists: what the two AI readers could not confirm goes into "To check\\To check <date>.xlsx" for a
person (or the legal team) to answer. The next daily update reads the answers and shows them on the dashboard, marked
"Checked by a person". A row is taken off the To check sheet once it is settled - answered by a person, or decided by
the daily update itself (`settle`) - and kept on the file's "Settled" sheet, where its answer can still be changed.
A file with no rows left to check moves to "To check\\Done\\".

Each item's full details stay in auto\\to_check.json (the workbook only shows them), keyed by a stable key such as
"docket:<CourtListener id>", "rd:<entry id>" or "state:<file name>", so nothing is asked twice.
"""
import datetime as dt
import json
import os
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

import data

FOLDER, DONE, STORE = "To check", "Done", "to_check.json"
PENDING, WIN, LOSS, LEAVE = "Pending case", "Win", "Loss", "Leave out"
ANSWERS = (PENDING, WIN, LOSS, LEAVE)
COLUMNS = ["Case", "Court", "State", "Date", "What it is", "Why it needs a person", "What the readers found", "Link",
           "Your answer", "Note (optional)", "Key"]
SETTLED, SETTLED_COLUMNS = "Settled", ["Settled on", "Settled by"]
WIDTHS = (46, 32, 7, 12, 22, 44, 50, 44, 16, 36, 4)
HEAD = PatternFill("solid", fgColor="1B2F6B")
ANSWER = PatternFill("solid", fgColor="FFF7E6")
READ_ME = [
    "What this is: cases and rulings the two AI readers could not confirm on their own. Everything they did confirm is "
    "already on the dashboard.",
    "What to do: for each row, open the link, then pick Your answer: Pending case (a suit to enforce an IDR award, not "
    "decided yet), Win or Loss (a ruling on enforcing the award), or Leave out (not one for the tracker). Add a note if "
    "you like; for a Win or Loss it is shown as the holding. If the Case, Court, State or Date is wrong, correct it in "
    "the row.",
    "Then: save the file here, under the same name. The next daily update puts the answers on the dashboard, marked "
    "'Checked by a person', and moves the answered rows to the Settled sheet. Leave a row empty if you are not sure; "
    "it stays on the list. The daily update also settles rows by itself when it finds the answer (a ruling both "
    "readers agree on, a settlement, or a case that is not an enforcement suit); those move to the Settled sheet too, "
    "with the reason in the Note. To change any answer, change it on the Settled sheet. Once no rows are left to "
    "check, the file moves to the Done folder.",
]


def folder(root):
    return Path(root) / FOLDER


def load(root):
    return data.read_json(Path(root) / "auto" / STORE, {})  # unreadable: the backup, or the run stops


def save(root, store):
    p = Path(root) / "auto" / STORE
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def item(key, kind, why, row, readers=""):
    """One thing for a person to check. row has the dashboard fields: case, court, level, circuit, state, docket, date,
    url, payer (and docketId for a CourtListener docket)."""
    return {"key": key, "kind": kind, "why": data.mask(why), "readers": data.mask(readers),
            **{k: (data.mask(v) if k in ("case", "payer") else v) for k, v in row.items()}}


def add(root, store, items, today=None):
    """Write the items not asked before into today's file. Returns (file or None, how many were added)."""
    new = [i for i in items if i["key"] not in store]
    if not new:
        return None, 0
    today = today or dt.date.today()
    folder(root).mkdir(exist_ok=True)
    names = [f"To check {today.isoformat()}.xlsx"] + [f"To check {today.isoformat()} ({n}).xlsx" for n in range(2, 10)]
    for name in names:
        try:
            return _write(folder(root) / name, store, new, today)
        except PermissionError:  # open in Excel: the rows go into the day's next file instead of being lost
            continue
    raise PermissionError(f"Every To check file for {today.isoformat()} is open in Excel; close them and run again.")


def _write(f, store, new, today):
    """Append the new items to f and only then record them as asked, so a file that cannot be saved loses nothing."""
    if f.exists():  # a second run on the same day adds to that day's file
        wb = openpyxl.load_workbook(f)
        ws = wb["To check"]
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "To check"
        ws.append(COLUMNS)
        for c in ws[1]:
            c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), HEAD, Alignment(wrap_text=True, vertical="top")
        for i, w in enumerate(WIDTHS, start=1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
        ws.column_dimensions["K"].hidden = True  # the key, so answers can be matched even if rows are sorted
        ws.freeze_panes = "A2"
        dv = DataValidation(type="list", formula1='"' + ",".join(ANSWERS) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add("I2:I2000")
        how = wb.create_sheet("Read me")
        how.column_dimensions["A"].width = 120
        for line in READ_ME:
            how.append([line])
            how.cell(how.max_row, 1).alignment = Alignment(wrap_text=True, vertical="top")
    for i in new:
        ws.append([i["case"], i.get("court"), i.get("state"), i.get("date"), i["kind"], i["why"], i["readers"],
                   i.get("url"), None, None, i["key"]])
        for c in ws[ws.max_row]:
            c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(ws.max_row, 9).fill = ANSWER
    wb.save(f)
    for i in new:
        store[i["key"]] = {**i, "file": f.name, "asked": today.isoformat()}
    return f, len(new)


def collect(root, store, say=lambda m: None):
    """Read Your answer from every file in To check\\ (both its To check and Settled sheets) into the store. Returns
    the keys whose answer is new or changed. An answer a person changes overrides one the daily update gave."""
    changed = []
    for f in sorted(folder(root).glob("*.xlsx")):
        if f.name.startswith("~$"):  # Excel's lock file
            continue
        try:
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            sheets = [list(wb[n].iter_rows(values_only=True)) for n in ("To check", SETTLED) if n in wb.sheetnames]
            wb.close()
        except Exception as e:  # damaged, or not one of ours
            say(f"  {f.name} could not be read ({e}); left as it is.")
            continue
        for rows in sheets:
            changed += _answers(rows, store)
    return changed


def _answers(rows, store):
    if not rows:
        return []
    col = {h: n for n, h in enumerate(rows[0]) if h}
    if "Key" not in col or "Your answer" not in col:
        return []
    changed = []
    for r in rows[1:]:
        key = r[col["Key"]] if len(r) > col["Key"] else None
        if not key or key not in store:
            continue
        ans = str(r[col["Your answer"]] or "").strip()
        ans = next((a for a in ANSWERS if a.casefold() == ans.casefold()), "")
        if not ans:
            continue
        note = str(r[col["Note (optional)"]] or "").strip() if "Note (optional)" in col else ""
        # The person may have corrected what the readers made of the case.
        fixes = {k: _cell(r[col[h]]) for h, k in (("Case", "case"), ("Court", "court"), ("State", "state"), ("Date", "date"))
                 if h in col and _cell(r[col[h]])}
        fixes = {k: (data.mask(v) if k == "case" else v.upper() if k == "state" else v) for k, v in fixes.items()}
        if store[key].get("answer") != ans or store[key].get("note", "") != data.mask(note) or any(store[key].get(k) != v for k, v in fixes.items()):
            store[key].update(answer=ans, note=data.mask(note), answered=dt.date.today().isoformat(), **fixes)
            store[key].pop("auto", None)  # a person's answer from now on
            changed.append(key)
    return changed


def settle(store, key, answer, note):
    """The daily update found the answer itself (a ruling both readers agree on, a settlement, not an enforcement
    suit): the row leaves the To check sheet at the end of the run. What the readers found is already on the dashboard,
    so dashboard_rows adds nothing for it."""
    store[key].update(answer=answer, note=data.mask(note), answered=dt.date.today().isoformat(), auto=True)


def tidy(root, store, say=lambda m: None):
    """Move every settled row from the To check sheet to the Settled sheet of its file; a file with no rows left to
    check moves to To check\\Done\\. A file open in Excel is left as it is and tidied next time. Returns rows moved."""
    moved = 0
    for f in sorted(folder(root).glob("*.xlsx")):
        if f.name.startswith("~$"):
            continue
        try:
            wb = openpyxl.load_workbook(f)
        except Exception as e:
            say(f"  {f.name} could not be read ({e}); left as it is.")
            continue
        if "To check" not in wb.sheetnames:
            continue
        ws = wb["To check"]
        col = {c.value: c.column for c in ws[1] if c.value}
        if "Key" not in col:
            continue
        done = wb[SETTLED] if SETTLED in wb.sheetnames else _settled_sheet(wb)
        gone, left = [], 0
        for r in range(2, ws.max_row + 1):
            key = ws.cell(r, col["Key"]).value
            if not key:
                continue
            i = store.get(key)
            if not i or not i.get("answer"):
                left += 1
                continue
            values = [ws.cell(r, col[h]).value if h in col else None for h in COLUMNS]
            values[COLUMNS.index("Your answer")], values[COLUMNS.index("Note (optional)")] = i["answer"], i.get("note") or None
            done.append(values + [i.get("answered"), "the daily update" if i.get("auto") else "a person"])
            for c in done[done.max_row]:
                c.alignment = Alignment(wrap_text=True, vertical="top")
            gone.append(r)
        if not gone and left:
            continue
        for r in reversed(gone):
            ws.delete_rows(r)
        try:
            wb.save(f)
        except PermissionError:
            say(f"  {f.name} is open in Excel: its settled rows are moved next time.")
            continue
        moved += len(gone)
        if not left:
            (f.parent / DONE).mkdir(exist_ok=True)
            try:
                os.replace(f, f.parent / DONE / f.name)
                say(f"  every row of {f.name} is settled: moved to {FOLDER}\\{DONE}")
            except OSError:
                say(f"  every row of {f.name} is settled; close it in Excel and it moves to {DONE} next time.")
    return moved


def _settled_sheet(wb):
    ws = wb.create_sheet(SETTLED, 1)
    ws.append(COLUMNS + SETTLED_COLUMNS)
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), HEAD, Alignment(wrap_text=True, vertical="top")
    for i, w in enumerate(WIDTHS + (12, 16), start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    ws.column_dimensions["K"].hidden = True
    ws.freeze_panes = "A2"
    dv = DataValidation(type="list", formula1='"' + ",".join(ANSWERS) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("I2:I5000")
    return ws


def _cell(v):
    return v.date().isoformat() if isinstance(v, dt.datetime) else v.isoformat() if isinstance(v, dt.date) else str(v or "").strip()


def dashboard_rows(store):
    """What the answered items add to found.json: ({"decisions": [...], "pending": [...]}, keys answered Leave out)."""
    out, leave = {"decisions": [], "pending": []}, set()
    for key, i in store.items():
        a = i.get("answer")
        if not a:
            continue
        if a == LEAVE:
            leave.add(key)
            continue
        if i.get("auto"):
            continue  # settled by the daily update: the readers' own row is already on the dashboard
        row = {k: i.get(k) for k in ("case", "court", "level", "circuit", "state", "docket", "url", "payer")}
        row.update(byHand=True, toCheck=key)
        if a == PENDING:
            out["pending"].append({**row, "filed": i.get("filed") or i.get("date"), "docketId": i.get("docketId"),
                                   "status": "Checked by a person: an enforcement suit with no ruling yet."})
        else:
            out["decisions"].append({**row, "date": i.get("date"), "result": a, "final": None,
                                     "holding": i.get("note") or f"A {a.lower()} for the provider, checked by a person."})
    return out, leave


def open_count(store):
    return sum(1 for i in store.values() if not i.get("answer"))
