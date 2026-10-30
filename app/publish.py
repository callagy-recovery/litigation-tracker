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
import time
import urllib.request
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
    main.data.swap_in(tmp, path)


# Staff names and internal file paths in the report's notes and change log, reworded for the public copy only.
PUBLIC_EDITS = [(re.compile(r"\bfrom [A-Z][a-z]+(?: [A-Z][a-z]+)?'s review"), "from an internal review"),  # names no one
                (re.compile(r"\bdrafts\\+[^\s\"<]+?(?=\.?(?:\s|$|[\"<]))"), "an internal file"),
                # The report's case notes hold instructions for whoever builds the dashboard; clients get the facts.
                (re.compile(r"\s*Added \d{4}-\d\d-\d\d from an internal review(?: of \d{4}-\d\d-\d\d)?\."), ""),
                (re.compile(r"For geographic heat map, Court State is (\w+) \(([^)]*)\); Origin State is (\w+) and may be "
                            r"preferable for state shading\."), r"The court sits in \1 (\2); the case came from \3."),
                (re.compile(r";\s*verify PACER citation if displaying document link publicly\."), "."),
                (re.compile(r";\s*analyst may count as one decision event rather than (\w+) cases\."), r", covering \1 cases."),
                (re.compile(r"Do not heat-map this R&R as a final decision; track final district disposition separately "
                            r"when verified\."),
                 "Listed as of the magistrate judge's recommendation; see the status for the district judge's later ruling."),
                (re.compile(r";\s*retain as separate decision event\."), "."),
                (re.compile(r"\bCode as negative\b"), "Counted as negative"),
                (re.compile(r";\s*show appellate status\."), "."),
                (re.compile(r";\s*appeal docket number not yet confirmed\."), "."),
                (re.compile(r";\s*replaces the (\S+) R&R for heat-map purposes\."), r"; replaces the \1 magistrate judge's recommendation."),
                (re.compile(r"\bshould be displayed\b"), "should be considered"),
                (re.compile(r";\s*keep appellate status updated\."), "."),
                (re.compile(r"\s*Verify direct docket link before public publication\."), ""),
                (re.compile(r"\bas of workbook date\b"), "as of the report date"),
                (re.compile(r"flagged out of the recommended heat-map universe"), "left out of the map and the counts"),
                (re.compile(r"noted in Dashboard Caution / Notes"), "noted on the case"),
                # A party's claim is said to be its claim, never stated as fact.
                (re.compile(r"\bsued (an? [\w ]+?) for failing to\b"), r"sued \1, alleging it failed to"),
                (re.compile(re.escape("the provider sued only under state law to collect the unpaid IDR award, to get around "
                                      "the NSA private-right question, and the court barred the claims")),  # before "unpaid"
                 "the provider brought only state-law claims to collect the IDR award, and the court barred them"),
                (re.compile(r"\bthat (the insurer|[A-Z][\w&.-]*) had not paid\b"), r"that the provider said \1 had not paid"),
                (re.compile(r"(?<!action to )\b((?:recover|enforce|collect|confirm|payment of)(?: and enforce)? (?:an |the )?)"
                            r"unpaid\b"), r"\1allegedly unpaid"),  # not a holding's "right of action to enforce unpaid awards"
                (re.compile(r"\$3M in unpaid awards"), "$3M in awards the provider said were unpaid"),
                (re.compile(r"\bclaims for nonpayment\."), "claims seeking payment."),
                (re.compile(r"\bthe order also threatens Rule 11 sanctions\b"), "the order also refers to possible Rule 11 sanctions"),
                # One-line descriptions of opinion articles, kept neutral and attributed (the titles are the articles' own).
                (re.compile(re.escape("Criticizes carriers paying few IDR awards within 30 days, some unpaid after a year, "
                                      "and rejects their justifications.")),
                 "Callagy Recovery commentary on the timing of IDR award payments and on CMS enforcement."),
                (re.compile(re.escape("AMA leader details plans delaying IDR payments, reopening closed cases and shifting "
                                      "cost-sharing, and urges federal enforcement.")),
                 "AMA commentary on IDR payment practices, urging federal enforcement."),
                # The tracker's own process words, in plain language for readers.
                (re.compile(r"Read automatically by the daily update:"), "Read automatically:"),
                (re.compile(r"Checked by a person on a To check list \(the AI readers could not confirm it\)\. Not in the "
                            r"report yet\."), "Checked by a person (the AI readers could not confirm it)."),
                (re.compile(r"; replaced by the court's order or the report when either has it\."),
                 "; replaced by the court's own order when it is available."),
                (re.compile(r"Enforcement suit confirmed by both readers; no ruling yet\."),
                 "Enforcement suit (read automatically by two AI readers); no ruling yet."),
                (re.compile(r"New enforcement suit found by the daily update; no ruling yet\."),
                 "Enforcement suit found automatically; no ruling yet."),
                (re.compile(r" come from it; the report always wins where both have a case\."),
                 " come from it and have not been reviewed by a person.")]
# "About this data" entries that are instructions for whoever builds the dashboard, and notes for whoever runs it.
HIDDEN_FIELDS = re.compile(r"Heat Map Include|Court State vs\.|Decision counting|Update recommendation|Update \d", re.I)
HIDDEN_NOTES = {"Automatic updates have stopped", "Automatic update not used", "Outcome and Heat Map Code disagree"}
# A report's new internal wording that PUBLIC_EDITS does not cover yet: the run says so (still_internal).
INTERNAL = re.compile(r"internal review|internal file|\banalyst\b|heat[- ]?map|workbook|should be displayed|"
                      r"public publication|if displaying|Daily Update folder|To check|saved by hand|both readers|"
                      r"by the daily update|report always wins|retain as|code as|show appellate|not yet confirmed|"
                      r"threatens|to get around the NSA", re.I)
DISCLAIMER = ("For general information only; not legal advice, and using this site does not create an attorney-client "
              "relationship. It summarizes public court records and agency documents. Some entries are read with AI "
              "assistance and are marked as such; any entry may contain errors or be out of date, so check the court's own "
              "documents before relying on it. Prior results do not guarantee a similar outcome.")


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


DOMAIN = "tracker.callagyrecovery.com"
GITHUB_PAGES_IPS = {"185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153"}


def still_internal(page):
    """The internal phrases left in a built page (new wording in a report that PUBLIC_EDITS does not cover yet)."""
    return sorted({m.group(0).lower() for m in INTERNAL.finditer(page)})


def points_to_github(name):
    """True once the firm's DNS sends name to GitHub Pages. Until then (*.callagyrecovery.com is a wildcard to the
    firm's own web host) the site keeps its github.io address: GitHub sends that address to the custom domain as
    soon as the CNAME file is published, so publishing it early would take the site down."""
    import socket
    try:
        ips = set(socket.gethostbyname_ex(name)[2])
    except OSError:
        return False
    return bool(ips) and ips <= GITHUB_PAGES_IPS


def publish(out=None):
    """Build the website in out (default <project>\\docs). Returns the files written, relative to out."""
    out = Path(out or main.ROOT / "docs")
    status, payload = main.page_data(published=True)
    if status != 200:
        raise RuntimeError("The dashboard cannot be built: no usable report (see the dashboard's own error page).")
    payload = public(payload)
    payload["methodology"] = [m for m in payload.get("methodology") or [] if not HIDDEN_FIELDS.match(m.get("field") or "")]
    payload["notes"] = [n for n in payload.get("notes") or [] if n.get("kind") not in HIDDEN_NOTES]
    logo = main.find_logo()
    logo_name = f"logo{logo.suffix.lower()}" if logo else ""
    page = (main.render_page(payload, logo_src=logo_name).replace("<head>", "<head>\n" + NOINDEX, 1)
            .replace("</header>", f'</header>\n<p class="disclaimer" role="note">{DISCLAIMER}</p>', 1))
    written = {"index.html": page, "robots.txt": "User-agent: *\nDisallow: /\n", ".nojekyll": ""}
    if (out / "CNAME").is_file() or points_to_github(DOMAIN):  # once on, it stays on (a DNS hiccup must not undo it)
        written["CNAME"] = DOMAIN + "\n"
    for name in STATIC_FILES:
        written[f"static/{name}"] = (main.STATIC / name).read_bytes()
    if logo:
        written[logo_name] = logo.read_bytes()
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
    left = still_internal((main.ROOT / "docs" / "index.html").read_text(encoding="utf-8"))
    note = f" (check the website: internal wording left: {', '.join(left)}; add it to publish.PUBLIC_EDITS)" if left else ""
    git = lambda *a, **kw: subprocess.run(GIT + list(a), cwd=main.ROOT, capture_output=True, text=True, **kw)  # noqa: E731
    branch = git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
    if branch != "main":  # e.g. local-history, which must never reach GitHub
        return f"website built in docs\\, not pushed: the project is on branch {branch or '?'}, not main" + note
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return "website built in docs\\, not pushed: no GITHUB_TOKEN user variable on this computer" + note
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
    if not changed:
        return "website already up to date on GitHub" + note
    return "website updated on GitHub" + request_build(git("remote", "get-url", "origin").stdout.strip(), token,
                                                       git("rev-parse", "HEAD").stdout.strip()) + note


BUILD_WAIT, BUILD_POLL = 60, 10  # seconds to wait for GitHub to start the site build by itself, and how often to look


def request_build(remote, token, sha=""):
    """Ask GitHub Pages to build the site, but only if GitHub has not started a build of the pushed commit (sha) by
    itself within BUILD_WAIT seconds: it usually does, and a second request only makes a duplicate build that GitHub
    cancels and lists as "errored". Returns "" when a build is under way, or a note saying why not (the push itself
    has worked either way)."""
    m = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    if not m:
        return ""  # not a GitHub repository (the tests' stand-in)
    api = f"https://api.github.com/repos/{m[1]}/{m[2]}/pages/builds"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    for i in range(BUILD_WAIT // BUILD_POLL + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(api + "/latest", headers=headers), timeout=30) as r:
                if sha and json.loads(r.read() or b"{}").get("commit") == sha:
                    return ""  # GitHub started it by itself
        except (OSError, ValueError):  # no build yet (404), or GitHub not answering: keep waiting, then ask
            pass
        if i < BUILD_WAIT // BUILD_POLL:
            time.sleep(BUILD_POLL)
    try:
        urllib.request.urlopen(urllib.request.Request(api, method="POST", headers=headers), timeout=30).close()
        return ""
    except OSError as e:  # urllib's HTTPError and URLError are OSErrors
        return f" (the site rebuild could not be requested: {e}; GitHub usually rebuilds by itself)"


if __name__ == "__main__":
    for f in publish():
        print(f)
