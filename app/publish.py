"""Writes the public website version of the dashboard into docs\\ (GitHub Pages serves that folder).

    .venv\\Scripts\\python app\\publish.py        (the daily update does this after each run)

The page is the same dashboard with its data built in, so it needs no server and no H: drive. It leaves out what is
not for the public (main.page_data(published=True)): the Callagy case counts, files from H: (Resources that link to
public sources stay), the sign-up code and the notes about the H: drive. Search engines are asked not to list it.
"""
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main  # noqa: E402

import logging  # noqa: E402
logging.getLogger("lt").addHandler(logging.NullHandler())  # the dashboard's own log lines are not for this window

STATIC_FILES = ("app.css", "app.js", "views.js", "us_states.json", "litigation_tracker.ico", "us-atlas-LICENSE.txt")
NOINDEX = '<meta name="robots" content="noindex, nofollow">'


def _write(path, content):
    """Write via a temporary file, so a visitor never gets half a page."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(content, bytes):
        tmp.write_bytes(content)
    else:
        tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


DATA_XLSX = "data/litigation-tracker-data.xlsx"  # a neutral name: the report's own file name is not published
DATA_FILES = {"data/daily-update-results.json": main.data.AUTO_FILE, "data/ai-summaries.json": main.data.SUMMARY_FILE}
# Staff names and internal file paths in the report's notes and change log, reworded for the public copy only.
PUBLIC_EDITS = [(re.compile(r"\bKatie(?: Varner)?'s review"), "an internal review"),
                (re.compile(r"\bdrafts\\+[^\s\"<]+?(?=\.?(?:\s|$|[\"<]))"), "an internal file")]


def public(value):
    """value (a string, or lists and dicts of them) with patient initials masked and PUBLIC_EDITS applied."""
    if isinstance(value, str):
        value = main.data.mask(value)
        for pattern, new in PUBLIC_EDITS:
            value = pattern.sub(new, value)
        return value
    if isinstance(value, list):
        return [public(v) for v in value]
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items()}
    return value


def masked_report(path):
    """The report workbook as bytes, with every text cell masked (patient initials -> ***), cell comments removed and
    the author and editor names cleared. The original in reports\\ is only read."""
    import io

    import openpyxl
    wb = openpyxl.load_workbook(path)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and not c.value.startswith("="):
                    c.value = public(c.value)
                if c.comment:  # merged cells have none (and cannot take one)
                    c.comment = None
    wb.properties.creator = wb.properties.lastModifiedBy = "Litigation Tracker"
    wb.properties.title = "NSA enforcement litigation data"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def publish(out=None):
    """Build the website in out (default <project>\\docs). Returns the files written, relative to out."""
    out = Path(out or main.ROOT / "docs")
    status, payload = main.page_data(published=True)
    if status != 200:
        raise RuntimeError("The dashboard cannot be built: no usable report (see the dashboard's own error page).")
    payload = public(payload)
    logo = main.find_logo()
    logo_name = f"logo{logo.suffix.lower()}" if logo else ""
    page = main.render_page(payload, logo_src=logo_name).replace("<head>", "<head>\n" + NOINDEX, 1)
    written = {"index.html": page, "robots.txt": "User-agent: *\nDisallow: /\n", ".nojekyll": ""}
    for name in STATIC_FILES:
        written[f"static/{name}"] = (main.STATIC / name).read_bytes()
    if logo:
        written[logo_name] = logo.read_bytes()
    found = main.data.newest_report(main.REPORTS)
    if found:
        written[DATA_XLSX] = masked_report(found[0])
    for rel, name in DATA_FILES.items():  # the daily update's results
        src = main.AUTO / name
        if src.is_file():
            written[rel] = json.dumps(public(json.loads(src.read_text(encoding="utf-8"))), indent=1, ensure_ascii=False)
    for rel, content in written.items():
        _write(out / rel, content)
    # Anything else in out was written by an earlier publish and is no longer part of the site (an old logo name).
    keep = {out / rel for rel in written}
    for f in [p for p in out.rglob("*") if p.is_file()]:
        if f not in keep:
            f.unlink()
    for d in sorted((p for p in out.rglob("*") if p.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    return sorted(written)


PUBLIC_PATHS = ["docs", "app", "tests", "README.md", "requirements.txt", ".gitignore"]  # .gitignore still applies
GIT = ["git", "-c", "safe.directory=*", "-c", "user.name=Litigation Tracker daily update",
       "-c", "user.email=litigation-tracker@users.noreply.github.com"]


def push(message):
    """Build the website, then commit what changed (the site, and any program change) and push it to the public GitHub
    repository (origin, branch main). Returns a one-line result; raises RuntimeError when the push fails. The token is
    the GITHUB_TOKEN user variable, handed to git for this push only: never printed or stored in git's settings."""
    publish()
    git = lambda *a, **kw: subprocess.run(GIT + list(a), cwd=main.ROOT, capture_output=True, text=True, **kw)  # noqa: E731
    branch = git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
    if branch != "main":  # e.g. local-history, which must never reach GitHub
        return f"website built in docs\\, not pushed: the project is on branch {branch or '?'}, not main"
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return "website built in docs\\, not pushed: no GITHUB_TOKEN user variable on this computer"
    git("add", "-A", "--", *[p for p in PUBLIC_PATHS if (main.ROOT / p).exists()])  # a missing path fails the add
    changed = git("diff", "--cached", "--quiet").returncode == 1
    if changed:
        git("commit", "-q", "-m", message)
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1",
           "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader", "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"}
    p = git("-c", "credential.helper=", "push", "-q", "origin", "main", env=env)
    if p.returncode:
        raise RuntimeError("git push failed: " + p.stderr.replace(token, "[token]").replace(basic, "[token]").strip()[-300:])
    return "website updated on GitHub" if changed else "website already up to date on GitHub"


if __name__ == "__main__":
    for f in publish():
        print(f)
