"""Lists the articles in resources\\: files, with a title taken from inside each document, and the web links in links.csv."""
import csv
import datetime as dt
import hashlib
import logging
import math
import re
from html.parser import HTMLParser
from pathlib import Path

from data import mask

log = logging.getLogger("lt")
TYPES = {".pdf": "PDF", ".docx": "Word", ".html": "HTML", ".htm": "HTML"}
LINKS_FILE = "links.csv"  # columns: Title, Type, Source, Date (YYYY-MM-DD), URL, Summary
CATEGORIES = {"court opinion": "Court opinion", "government": "Government", "news": "News", "callagy": "Callagy"}
_logged = set()  # (name, mtime) already reported as unreadable, so a refresh does not repeat it in the log


def token(name):
    """Download id for a file: the page never carries raw file names in URLs, and only listed files are served."""
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]


def _clean(t):
    return " ".join(str(t or "").split())


def pdf_title(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    meta = reader.metadata
    if meta and _clean(meta.title):
        return _clean(meta.title)
    if not reader.pages:
        return ""
    chunks = []

    def visit(text, cm, tm, font_dict, font_size):
        if text and text.strip():
            size = font_size * math.hypot(tm[2], tm[3]) * math.hypot(cm[2], cm[3])
            chunks.append((round(size, 1), text))

    reader.pages[0].extract_text(visitor_text=visit)
    if not chunks:
        return ""
    biggest = max(s for s, _ in chunks)
    # First run of text at the largest size, then its first line.
    run, started = [], False
    for size, text in chunks:
        if size == biggest:
            run.append(text)
            started = True
        elif started:
            break
    return next((_clean(line) for line in "".join(run).splitlines() if line.strip()), "")


def docx_title(path):
    import docx
    doc = docx.Document(str(path))
    if _clean(doc.core_properties.title):
        return _clean(doc.core_properties.title)
    for p in doc.paragraphs:
        style = (p.style.name if p.style is not None else "") or ""
        if (style.startswith("Heading") or style == "Title") and p.text.strip():
            return _clean(p.text)
    return ""


class _HtmlTitle(HTMLParser):
    """Text of the first non-empty <title> and first non-empty <h1>, nested tags included."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = {"title": "", "h1": ""}
        self._in = None

    def handle_starttag(self, tag, attrs):
        if tag in self.found and self._in is None and not self.found[tag].strip():
            self._in = tag

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in:
            self.found[self._in] += data


def html_title(path):
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    p = _HtmlTitle()
    p.feed(text)
    return _clean(p.found["title"]) or _clean(p.found["h1"])


_EXTRACT = {"PDF": pdf_title, "Word": docx_title, "HTML": html_title}


def scan(folder):
    """Every PDF, Word and HTML file in the folder, newest first. Unreadable files are kept under their file name."""
    items, problems = [], []
    folder = Path(folder)
    if not folder.is_dir():
        return items, problems
    for p in folder.iterdir():
        kind = TYPES.get(p.suffix.lower())
        if not kind or not p.is_file() or p.name.startswith("~$"):
            continue
        mtime = p.stat().st_mtime
        try:
            title = _EXTRACT[kind](p)
        except Exception as e:  # damaged, password-protected, mid-copy: still list it
            title = ""
            problems.append(f"{mask(p.name)} could not be read ({type(e).__name__}: {e}); listed under its file name.")
            if (p.name, mtime) not in _logged:
                _logged.add((p.name, mtime))
                log.warning("Resource could not be read: %s (%s: %s)", p.name, type(e).__name__, e)
        items.append({
            "name": p.name, "title": mask(title or p.stem), "type": kind, "mtime": mtime,
            "date": dt.datetime.fromtimestamp(mtime).date().isoformat(), "token": token(p.name),
        })
    items.sort(key=lambda i: i["mtime"], reverse=True)
    return items, problems


def links(folder):
    """Web links listed in links.csv. Rows without a title or an http(s) URL are skipped and reported."""
    path = Path(folder) / LINKS_FILE
    items, problems = [], []
    if not path.is_file():
        return items, problems
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            r = {str(k).strip().casefold(): _clean(v) for k, v in row.items() if k}
            title, url, date = r.get("title", ""), r.get("url", ""), r.get("date", "")
            if not title or not re.match(r"https?://", url, re.I):
                if any(r.values()):
                    problems.append(f"{LINKS_FILE} row {n} skipped: it needs a Title and a URL starting with http:// or https://.")
                continue
            items.append({
                "title": mask(title), "type": "Link", "url": url,
                "date": date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else "",
                "category": CATEGORIES.get(r.get("type", "").casefold(), r.get("type", "")),
                "source": mask(r.get("source", "")), "summary": mask(r.get("summary", "")),
            })
    return items, problems


def listing(folder):
    """Files and links together, newest first; undated links go last."""
    files, problems = scan(folder)
    linked, more = links(folder)
    items = sorted(files + linked, key=lambda i: (i["date"], i.get("mtime", 0)), reverse=True)
    return items, problems + more
