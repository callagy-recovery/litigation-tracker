"""Newsletter: an Outlook draft listing the new rulings and new pending cases, for the user to review and send.

Run at the end of each daily update (daily_update.py). At most once a day (MIN_DAYS), it compares what the
dashboard shows (the newest report plus auto\\found.json) with what earlier newsletters already listed
(auto\\newsletter.json). If there is something new, it saves a draft in the default Outlook account's Drafts folder;
it never sends. Nothing new: no draft, and it looks again next run. The first run only notes what exists.

Recipients: everyone subscribed on newsletter\\Newsletter sign-ups.xlsx (signups.py; the dashboard's Sign up button).
"""
import datetime as dt
import html
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import data

MIN_DAYS = 1  # at most one draft a day; a draft only when something is new
MAX_RULINGS = 5  # rulings listed one line each; the rest are counted
STATE_FILE = "newsletter.json"


def snapshot(report):
    """{"rulings": {key: decision}, "pending": {key: case}} of what the dashboard shows."""
    rulings = {data.ruling_key(d): d for d in report["decisions"].values() if d["included"] and d["counted"]}
    pending = {f"{(data.norm_docket(p.get('docket')) or [p['case'].lower()])[0]}|{p.get('state')}": p for p in report["pending"].values()}
    return {"rulings": rulings, "pending": pending}


def due(state, today):
    last = state.get("lastDraft") or state.get("baseline")
    return bool(last) and (today - dt.date.fromisoformat(last[:10])).days >= MIN_DAYS


_SUFFIX = re.compile(r",?\s*\b(L\.?L\.?C|L\.?L\.?P|P\.?L\.?L\.?C|Inc|Co|Corp|Company|P\.?C|P\.?A|M\.?D|L\.?P|Ltd)\b\.?", re.I)


def short_name(case, insurer=None):
    """'Shareef Jandali Plastic Surgery, LLC v. Cigna Health and Life Insurance Co.' -> 'Shareef Jandali Plastic Surgery v. Cigna'
    (the insurer's standard name from insurers.py when given, without any parent company in brackets)."""
    def side(s):
        s = re.split(r",| d/b/a | a/s/o | et al", s, maxsplit=1)[0]
        s = _SUFFIX.sub("", s).strip()
        words = s.split()
        return " ".join(words[:4]) if words else s
    parts = re.split(r"\s+v\.?\s+", case or "", maxsplit=1)
    if len(parts) != 2:
        return side(case or "")
    other = re.sub(r"\s*\(.*?\)", "", insurer).strip() if insurer else side(parts[1])
    return f"{side(parts[0])} v. {other}"


def where(d):
    """'CT, federal', '2nd Circuit', 'NY, state'."""
    if d.get("appellate") and d.get("circuit"):
        c = d["circuit"]
        return "D.C. Circuit" if c == "DC" else f"{c}{'st' if c == '1' else 'nd' if c == '2' else 'rd' if c == '3' else 'th'} Circuit"
    return f"{d.get('state')}, {d.get('level') or 'federal'}"


LOGO_CID = "lt-logo"
THEME = {"brand": "#276ba8", "brandDark": "#184268", "tint": "#edf3f8"}  # the dashboard's colours, taken from the logo
WIN, LOSS, PEND, INK, MUTED, LINE = "#047857", "#b91c1c", "#2563eb", "#172033", "#667085", "#e3e8f0"
FONT = 'font-family:"Segoe UI",Arial,Helvetica,sans-serif'  # double quotes: the HTML attributes use single ones


def _court_short(d):
    """'U.S. District Court, District of Connecticut' -> 'Federal district court'; appellate -> its circuit."""
    if d.get("appellate") or "appeal" in (d.get("court") or "").lower():
        return where(d) if d.get("circuit") else "Appeals court"
    return "Federal district court" if d.get("level") == "federal" else "State court"


def build(rulings, pending, report_name, today, since=None, theme=None, logo=True):
    """(subject, html body). A brief, branded newsletter in email-safe HTML (600 px tables, inline styles, no web
    fonts or external images), so it renders in desktop Outlook; readers open the dashboard for the details."""
    t = {**THEME, **(theme or {})}
    rulings = sorted(rulings, key=lambda d: d["date"], reverse=True)
    e = lambda s: html.escape(str(s or ""))  # noqa: E731
    n = lambda k, w: f"{k} new {w if k == 1 else w + 's'}"  # noqa: E731
    wins = sum(d["win"] for d in rulings)
    fmt = lambda d: f"{d:%b} {d.day}"  # noqa: E731
    subject = f"Litigation Tracker · {fmt(today)}, {today.year}: " + ", ".join(x for x in (rulings and n(len(rulings), "ruling"), pending and n(len(pending), "case")) if x)
    dated = f"{today:%A}, {fmt(today)}, {today.year}"

    def tile(value, label, colour):
        return (f"<td width='25%' style='padding:0 5px'><table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
                f"style='background:#ffffff;border:1px solid {LINE};border-top:4px solid {colour}'><tr><td style='padding:12px 10px;{FONT}'>"
                f"<div style='font-size:26px;line-height:30px;font-weight:700;color:{colour}'>{value}</div>"
                f"<div style='font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:600'>{label}</div>"
                "</td></tr></table></td>")

    def heading(text):
        return (f"<tr><td style='padding:22px 30px 8px;{FONT};font-size:12px;letter-spacing:.08em;text-transform:uppercase;"
                f"font-weight:700;color:{t['brandDark']}'>{text}</td></tr>")

    rows = []
    for d in rulings[:MAX_RULINGS]:
        colour = WIN if d["win"] else LOSS
        rows.append(
            f"<tr><td style='padding:0 30px'><table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
            f"style='border-bottom:1px solid {LINE}'><tr>"
            f"<td width='66' valign='top' style='padding:12px 0'><table role='presentation' cellpadding='0' cellspacing='0'><tr>"
            f"<td bgcolor='{colour}' style='background:{colour};color:#ffffff;{FONT};font-size:11px;font-weight:700;"
            f"letter-spacing:.05em;padding:4px 9px'>{'WIN' if d['win'] else 'LOSS'}</td></tr></table></td>"
            f"<td valign='top' style='padding:10px 0;{FONT}'>"
            f"<div style='font-size:15px;font-weight:600;color:{INK}'>{e(short_name(d['case'], (d.get('insurers') or [None])[0]))}</div>"
            f"<div style='font-size:12px;color:{MUTED}'>{e(_court_short(d))} · {e(d.get('state'))} · {e(fmt(dt.date.fromisoformat(d['date'])))}</div>"
            "</td></tr></table></td></tr>")
    if len(rulings) > MAX_RULINGS:
        rows.append(f"<tr><td style='padding:8px 30px 0;{FONT};font-size:13px;color:{MUTED}'>+ {len(rulings) - MAX_RULINGS} more rulings on the dashboard</td></tr>")

    bars = []
    if pending:
        by_state = {}
        for p in pending:
            by_state[p.get("state") or "?"] = by_state.get(p.get("state") or "?", 0) + 1
        top = sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))
        most = top[0][1]
        for st, k in top[:5]:
            w = max(4, round(100 * k / most))
            bars.append(
                f"<tr><td width='34' style='padding:4px 0;{FONT};font-size:13px;font-weight:600;color:{INK}'>{e(st)}</td>"
                f"<td style='padding:4px 8px 4px 0'><table role='presentation' width='{w}%' cellpadding='0' cellspacing='0'>"
                f"<tr><td height='14' style='background:{PEND};font-size:1px;line-height:14px'>&nbsp;</td></tr></table></td>"
                f"<td width='30' align='right' style='padding:4px 0;{FONT};font-size:13px;color:{INK}'>{k}</td></tr>")
        if len(top) > 5:
            bars.append(f"<tr><td colspan='3' style='padding:6px 0 0;{FONT};font-size:12px;color:{MUTED}'>+ {len(top) - 5} more states</td></tr>")

    logo_img = (f"<img src='cid:{LOGO_CID}' width='52' height='48' alt='Callagy Law' style='display:block;border:0'>" if logo is True
                else f"<img src='{logo}' width='52' height='48' alt='Callagy Law' style='display:block;border:0'>" if logo else "")
    preheader = (", ".join(x for x in (rulings and n(len(rulings), "ruling"), pending and n(len(pending), "pending case")) if x)
                 + (f" since {fmt(since)}." if since else " today."))
    body = (
        f"<div style='display:none;max-height:0;overflow:hidden'>{e(preheader)}</div>"
        f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='background:#f2f5f9'><tr><td align='center' style='padding:24px 12px'>"
        f"<table role='presentation' width='600' cellpadding='0' cellspacing='0' style='width:600px;max-width:600px;background:#ffffff;border:1px solid {LINE}'>"
        # header band
        f"<tr><td style='background:{t['brandDark']};padding:22px 30px'><table role='presentation' cellpadding='0' cellspacing='0'><tr>"
        f"<td style='background:#ffffff;padding:6px'>{logo_img}</td>"
        f"<td style='padding-left:16px;{FONT}'><div style='font-size:22px;font-weight:700;color:#ffffff'>Litigation Tracker</div>"
        f"<div style='font-size:13px;color:#cfe0f1'>Update · {e(dated)}</div></td></tr></table></td></tr>"
        f"<tr><td style='background:{t['brand']};height:4px;font-size:1px;line-height:4px'>&nbsp;</td></tr>"
        # intro + tiles
        f"<tr><td style='padding:22px 30px 6px;{FONT};font-size:15px;color:{INK}'>New on the NSA enforcement map {e(f'since the last update on {fmt(since)}' if since else 'today')}.</td></tr>"
        f"<tr><td style='padding:10px 25px 4px'><table role='presentation' width='100%' cellpadding='0' cellspacing='0'><tr>"
        + tile(len(rulings), "New rulings", t["brand"]) + tile(wins, "Wins", WIN) + tile(len(rulings) - wins, "Losses", LOSS)
        + tile(len(pending), "New cases", PEND) + "</tr></table></td></tr>"
        + (heading("New rulings") + "".join(rows) if rulings else "")
        + (heading("Where the new cases are") + f"<tr><td style='padding:0 30px'><table role='presentation' width='100%' cellpadding='0' cellspacing='0'>{''.join(bars)}</table></td></tr>" if pending else "")
        # call-out
        + f"<tr><td style='padding:24px 30px'><table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        f"style='background:{t['tint']};border-left:4px solid {t['brand']}'><tr><td style='padding:14px 16px;{FONT};font-size:14px;color:{INK}'>"
        f"<b style='color:{t['brandDark']}'>See the full details on the dashboard.</b><br>"
        f"Open <b>Litigation Tracker</b> from Callagy Hub for the map, each ruling's summary and its court order.</td></tr></table></td></tr>"
        # footer
        f"<tr><td style='padding:14px 30px 20px;border-top:1px solid {LINE};{FONT};font-size:11px;line-height:16px;color:{MUTED}'>"
        "Callagy Law · internal litigation research. Rulings come from court records and the reviewed report; "
        "cases found automatically are marked on the dashboard until they are reviewed.</td></tr>"
        "</table></td></tr></table>")
    return subject, body


def find_logo(root):
    """The logo the dashboard uses (assets\\logo.* first, then any image with "logo" in its name), as an email-safe file."""
    folder = Path(root) / "assets"
    files = sorted((p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif")), key=lambda p:
                   (p.stem.lower() != "logo", "logo" not in p.name.lower(), p.name.lower())) if folder.is_dir() else []
    return files[0] if files else None


def outlook_draft(subject, body, bcc="", logo=None):
    """Save a draft in the default Outlook account's Drafts folder (classic Outlook, through PowerShell). Never sends.
    The logo is attached as an inline image (content id LOGO_CID) and hidden from the attachment list."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "mail.json"
        f.write_text(json.dumps({"subject": subject, "body": body, "bcc": bcc, "logo": str(logo) if logo else "", "cid": LOGO_CID}),
                     encoding="utf-8")
        script = ("$m = Get-Content -Raw -Encoding UTF8 $env:LT_MAIL | ConvertFrom-Json; $o = New-Object -ComObject Outlook.Application; "
                  "$i = $o.CreateItem(0); $i.Subject = $m.subject; if ($m.bcc) { $i.BCC = $m.bcc }; "
                  "if ($m.logo) { $a = $i.Attachments.Add($m.logo); "
                  "$a.PropertyAccessor.SetProperty('http://schemas.microsoft.com/mapi/proptag/0x3712001F', $m.cid); "
                  "$i.PropertyAccessor.SetProperty('http://schemas.microsoft.com/mapi/id/{00062008-0000-0000-C000-000000000046}/8514000B', $true) }; "
                  "$i.HTMLBody = $m.body; $i.Save(); 'saved'")
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                           timeout=180, env={**os.environ, "LT_MAIL": str(f)})
    if "saved" not in p.stdout:
        raise RuntimeError(f"Outlook could not save the draft: {(p.stderr or p.stdout).strip()[-300:]}")


def run(report, report_name, auto, say, today=None, make_draft=outlook_draft):
    """The newsletter step. Returns what it did, for the run summary."""
    today = today or dt.date.today()
    path = Path(auto) / STATE_FILE
    state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    now = snapshot(report)
    if not state:  # first run: note what exists, draft nothing
        state = {"baseline": today.isoformat(), "rulings": sorted(now["rulings"]), "pending": sorted(now["pending"])}
        path.write_text(json.dumps(state, indent=1), encoding="utf-8")
        return "started: the first draft lists what is new from today"
    if not due(state, today):
        return f"not due (last draft {state.get('lastDraft') or 'none'}; at most one draft a day)"
    new_r = [d for k, d in now["rulings"].items() if k not in set(state["rulings"])]
    new_p = [p for k, p in now["pending"].items() if k not in set(state["pending"])]
    if not new_r and not new_p:
        return "due, but nothing new: no draft"
    since = dt.date.fromisoformat((state.get("lastDraft") or state["baseline"])[:10])
    logo = find_logo(Path(auto).parent)
    subject, body = build(new_r, new_p, report_name, today, since=since, logo=bool(logo))
    import signups
    bcc = "; ".join(signups.recipients(Path(auto).parent))  # everyone subscribed on newsletter\Newsletter sign-ups.xlsx
    make_draft(subject, body, bcc, logo)
    state.update({"lastDraft": today.isoformat(), "rulings": sorted(set(state["rulings"]) | set(now["rulings"])),
                  "pending": sorted(set(state["pending"]) | set(now["pending"]))})
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    say(f"  Outlook draft saved: {subject}")
    return f"draft saved ({len(new_r)} rulings, {len(new_p)} cases)"
