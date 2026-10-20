"""Two-level ruling reader for the daily update: decides Win, Loss or Pending from a court order's text.

Level 1 (Sonnet) and Level 2 (Opus) each read the order on their own through the signed-in Claude Code command line.
If they disagree, or a quote is not found word for word in the order, or the answer contradicts the court's docket
wording, both read again with the other's reason. Up to ROUNDS rounds; no agreement means the ruling is not decided
here ("could not agree") and the case stays pending.

Each call runs with no tools, in safe mode (no plugins, hooks, CLAUDE.md or MCP servers) and saves no session, so a
court document's text can only ever be read, never acted on. Tested on the 47 rulings of the 2026-09-30 report.
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

L1, L2 = "sonnet", "opus"
ROUNDS = 3
TIMEOUT = 900  # seconds per call

RULES = """You read United States court orders for a litigation tracker. The tracker follows lawsuits in which a medical
provider asks a court to confirm or enforce a No Surprises Act IDR (independent dispute resolution, arbitration) award
against an insurer or health plan.

Decide, using only the order's text:
- relevant: true only if the order directly decides whether or how an NSA IDR award can be confirmed, enforced or
  turned into a judgment.
- result:
  "Win"     = the court confirmed or enforced the IDR award, or let the provider's claim to enforce or confirm the award
              go forward (for example it denied a motion to dismiss that claim).
  "Loss"    = the court rejected the provider's enforcement or confirmation theory, dismissed the enforcement claim, or
              affirmed such a dismissal on appeal.
  "Pending" = the order does not decide the enforcement claim (for example a magistrate judge's report and
              recommendation, or a scheduling or procedural order).
  If the court grants a motion to dismiss only in part, judge the claim to enforce or confirm the award itself.
- final: true for a final judgment or a final appellate decision; false for a denial of a motion to dismiss, other
  interim rulings, and recommendations.
- quote: copy word for word, exactly as written, the one sentence of the order that states the result (usually in the
  conclusion or the "ORDERED" paragraph). Do not paraphrase.
- reason: one or two sentences explaining the result.
- holding: one plain-English sentence summarising what the court decided. Never name a patient or give a patient's
  initials, even where the order does.

Scope, as the tracker's editor applies it:
- Also relevant: an order deciding whether a provider can use a court at all to enforce or collect on IDR
  determinations, for example a holding that the No Surprises Act gives providers no private right of action to enforce
  IDR awards. Such a holding against the provider is a "Loss".
- Not relevant: cases where the award favoured the insurer, or orders only about vacating an award.
"""

SCHEMA = {"type": "object", "required": ["relevant", "result", "final", "quote", "reason", "holding"], "properties": {
    "relevant": {"type": "boolean"}, "result": {"type": "string", "enum": ["Win", "Loss", "Pending"]},
    "final": {"type": "boolean"}, "quote": {"type": "string"}, "reason": {"type": "string"},
    "holding": {"type": "string"}}}

# What a court's own docket wording implies, from check_dockets.entry_label. Only clear-cut labels are used as a check;
# "dismissed" is left out because a partial dismissal can still let the enforcement claim go forward.
DOCKET_RESULT = {"Ruling: award confirmed / judgment for provider": "Win", "Ruling: motion to dismiss denied": "Win",
                 "Ruling: petition to confirm denied": "Loss", "Recommendation (not final)": "Pending"}


class ReaderError(Exception):
    """Claude could not be run (not installed, not signed in, usage limit). Unread orders wait for the next run."""


class Declined(ReaderError):
    """Claude declined this one document (its content filter flagged it). Skip the document, not the run."""


_DECLINED = re.compile(r"usage polic|support\.claude\.com/en/articles/8106465|\[bio\]|content filter|violat", re.I)


def _failure(message):
    """The right error for a failed call: a refusal of this document, or a problem with Claude itself."""
    return Declined(message) if _DECLINED.search(message) and not re.search(r"rate limit|usage limit|quota", message, re.I) else ReaderError(message)


def examples(decisions):
    """The editor's own coding of the report's rulings, as 'holding -> result' lines that show the reader her line."""
    lines = []
    for d in decisions:
        if not d.get("holding"):
            continue
        res = "not relevant" if not d["included"] else {"Positive": "Win", "Negative": "Loss"}.get(d["outcome"], d["outcome"])
        lines.append(f"- {d['holding']} -> {res}" + (" (not final)" if "interlocutory" in d["status"].lower() else ""))
    return "\n".join(lines)


def system_prompt(decisions):
    return RULES + "\nExamples of how the editor coded other rulings (holding -> result):\n" + examples(decisions)


def clean(text):
    text = re.sub(r"(?:\b\d{1,2}\s+){10,}", " ", text or "")  # pleading-paper line numbers 1..28
    return re.sub(r"\s+", " ", text).strip()


def norm(s):
    """Letters and digits only, for checking that a quote is word for word in the order. Spaces and hyphens are dropped
    because PDF text splits words at line ends ("con- firm", "out -of- network")."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def claude_exe():
    """The native claude.exe. The npm claude.cmd wrapper would mangle multi-line arguments, so call what it points at."""
    cmd = shutil.which("claude.cmd")
    if cmd:
        exe = Path(cmd).parent / "node_modules/@anthropic-ai/claude-code/bin/claude.exe"
        if exe.exists():
            return str(exe)
    return shutil.which("claude.exe") or shutil.which("claude")


def signed_in(exe):
    """(ok, message) for the Claude Code sign-in on this Windows account."""
    if not exe:
        return False, "Claude Code is not installed for this Windows account."
    try:
        p = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, encoding="utf-8", timeout=60)
        s = json.loads(p.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return False, f"Could not check the Claude sign-in ({e})."
    return (True, f"signed in as {s.get('email', '?')}") if s.get("loggedIn") else (False, "Claude Code is not signed in.")


def ask_claude(model, system, prompt, exe=None, workdir=None, schema=None):
    """One read: the order goes in on stdin, the answer comes back matching the schema (SCHEMA by default)."""
    cmd = [exe or claude_exe(), "-p", "--model", model, "--tools", "", "--safe-mode", "--strict-mcp-config",
           "--no-session-persistence", "--permission-prompts", "none", "--system-prompt", system,
           "--json-schema", json.dumps(schema or SCHEMA), "--output-format", "json"]
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT,
                           cwd=workdir or tempfile.gettempdir())
        if p.returncode:
            raise _failure(f"Claude stopped ({(p.stderr or p.stdout).strip()[-600:]})")
        out = json.loads(p.stdout)
        ans = out.get("structured_output") or json.loads(out["result"])
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        raise ReaderError(f"Claude could not be run ({e})") from None
    if out.get("is_error"):
        raise _failure(f"Claude reported an error: {str(out.get('result'))[:600]}")
    return ans


TRANSCRIBE = ("You transcribe scanned court documents exactly. Copy out all the text on the page, word for word, in "
              "reading order, even if the page is rotated. Output only the text; write [illegible] for anything you cannot read.")


def transcribe_page(png, exe=None, workdir=None):
    """The text of one scanned page (PNG bytes), copied out by Sonnet. Still no tools: the image travels in the request."""
    import base64
    msg = {"type": "user", "message": {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}},
        {"type": "text", "text": "Transcribe this page."}]}}
    cmd = [exe or claude_exe(), "-p", "--model", L1, "--tools", "", "--safe-mode", "--strict-mcp-config",
           "--no-session-persistence", "--permission-prompts", "none", "--system-prompt", TRANSCRIBE,
           "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
    try:
        p = subprocess.run(cmd, input=json.dumps(msg) + "\n", capture_output=True, text=True, encoding="utf-8",
                           timeout=TIMEOUT, cwd=workdir or tempfile.gettempdir())
        result = next((e for e in map(json.loads, p.stdout.splitlines()) if e.get("type") == "result"), None)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        raise ReaderError(f"Claude could not be run ({e})") from None
    if p.returncode or not result or result.get("is_error"):
        raise _failure(f"Claude stopped ({(p.stderr or str(result))[-600:]})")
    return result.get("result") or ""


def _recheck(other, quote_ok, docket=None):
    if not quote_ok:
        return "Your quote was not found word for word in the order. Read again and copy the sentence exactly."
    note = (f"Another reader concluded result={other['result']}, relevant={other['relevant']}, final={other['final']}. "
            f"Their reason: {other['reason']} Their quote: \"{other['quote']}\". ")
    if docket:
        note += f'The court\'s own docket entry for this order says: "{docket}". '
    return note + "Read the order again carefully and give your answer. Change it only if the order's text supports the change."


SCREEN_RULES = """You check whether a new lawsuit belongs in a litigation tracker of suits in which a medical
provider asks a court to confirm or enforce a No Surprises Act IDR (independent dispute resolution, arbitration) award
against an insurer or health plan, or to make the insurer pay an IDR award.

Using only the filing's text, answer:
- enforcement: true if the provider is asking the court to confirm, enforce or collect on one or more IDR awards or
  determinations; false for anything else (for example challenges to the rules, suits over the original payment amount,
  or suits by an insurer).
- quote: copy word for word one sentence of the filing that shows this.
- reason: one sentence."""
SCREEN_SCHEMA = {"type": "object", "required": ["enforcement", "quote", "reason"], "properties": {
    "enforcement": {"type": "boolean"}, "quote": {"type": "string"}, "reason": {"type": "string"}}}


def screen(text, case, ask=None, detail=False):
    """Is a newly found docket an IDR award enforcement suit? Two readers, like read(): Sonnet and Opus each read its
    first filing on their own, both quotes must be in the text and both must agree; if not, each reads again with the
    other's reason, up to ROUNDS rounds. True / False, or None when they cannot tell or do not agree.
    With detail=True: (that answer, the agreed quote or "")."""
    filing = clean(text)
    if len(filing.split()) < 60:
        return (None, "") if detail else None
    prompt = f"CASE: {case}\n\nFILING TEXT:\n\n{filing[:120000]}"
    ask = ask or (lambda model, system, p: ask_claude(model, system, p, schema=SCREEN_SCHEMA))
    text_n = norm(filing[:120000])
    found = lambda a: len(norm(a["quote"])) > 15 and norm(a["quote"]) in text_n  # noqa: E731

    def again(other, quote_ok):
        if not quote_ok:
            return "\n\nYour quote was not found word for word in the filing. Read again and copy the sentence exactly."
        return (f"\n\nAnother reader concluded enforcement={other['enforcement']}. Their reason: {other['reason']} "
                f"Their quote: \"{other['quote']}\". Read the filing again and give your answer. Change it only if the "
                "filing's text supports the change.")

    a, b = ask(L1, SCREEN_RULES, prompt), ask(L2, SCREEN_RULES, prompt)  # round 1: both read blind
    for rnd in range(1, ROUNDS + 1):
        if found(a) and found(b) and a["enforcement"] == b["enforcement"]:
            return (a["enforcement"], a["quote"]) if detail else a["enforcement"]
        if rnd == ROUNDS:
            return (None, "") if detail else None
        a, b = ask(L1, SCREEN_RULES, prompt + again(b, found(a))), ask(L2, SCREEN_RULES, prompt + again(a, found(b)))


IDENTIFY_RULES = """You read the first pages of one court document that a person saved for a litigation tracker, and copy
out what it is. Using only the document's text, answer:
- case: the case name as "First plaintiff v. First defendant" (drop "et al."). If a party is a patient or other
  private person, write "Patient" instead of the name. Never give a patient's name or initials.
- court: the court's full name, as printed (for example "Supreme Court of the State of New York, County of Nassau").
- level: "State Trial", "State Appellate" (any state appeals court or state supreme court that hears appeals; New
  York's "Supreme Court" is a trial court, its "Appellate Division" is appellate) or "Federal" (any United States court).
- state: the two-letter code of the court's state, for example NY.
- docket: the index, docket or case number exactly as printed; "" if none is shown.
- date: YYYY-MM-DD. For a ruling, the date it was decided or signed; for a complaint or petition, the date it was filed;
  "" if no date is shown.
- kind: "ruling" for a court's decision, order or judgment; "complaint" for a complaint or petition that starts a case;
  "other" for anything else (a docket sheet, a brief, a motion, a news article).
- quote: copy word for word the line of the document that shows the case number or, if there is none, the court's name."""
IDENTIFY_SCHEMA = {"type": "object", "required": ["case", "court", "level", "state", "docket", "date", "kind", "quote"],
                   "properties": {k: {"type": "string"} for k in ("case", "court", "level", "state", "docket", "date", "kind", "quote")}}


def identify(text, ask=None):
    """What a saved court document is: case, court, level, state, docket, date and kind, read by both readers on their
    own. They must agree on level, state, kind, date and the docket number's digits, and the quote must be in the text;
    if not, each reads again with the other's answer, up to ROUNDS rounds. Returns the answer plus "agreed" and "note"."""
    doc = clean(text)
    if len(doc.split()) < 60:
        return {"agreed": False, "note": "The file has no readable text."}
    prompt = f"DOCUMENT TEXT (first pages):\n\n{doc[:30000]}"
    ask = ask or (lambda model, system, p: ask_claude(model, system, p, schema=IDENTIFY_SCHEMA))
    text_n = norm(doc[:30000])
    found = lambda a: len(norm(a["quote"])) > 3 and norm(a["quote"]) in text_n  # noqa: E731
    key = lambda a: (a["level"], a["state"].upper(), a["kind"], a["date"], re.sub(r"\D", "", a["docket"]))  # noqa: E731
    a, b = ask(L1, IDENTIFY_RULES, prompt), ask(L2, IDENTIFY_RULES, prompt)
    for rnd in range(1, ROUNDS + 1):
        if found(a) and found(b) and key(a) == key(b):
            return {**a, "state": a["state"].upper(), "agreed": True, "note": ""}
        if rnd == ROUNDS:
            return {**a, "state": a["state"].upper(), "agreed": False,
                    "note": "The two readers did not agree on what this document is (court, state, date or case number)."}
        again = lambda other, ok: ("\n\nYour quote was not found word for word in the document. Read again and copy the line exactly."  # noqa: E731
                                   if not ok else f"\n\nAnother reader answered: {json.dumps({k: other[k] for k in IDENTIFY_SCHEMA['required']})}. "
                                   "Read the document again and give your answer. Change it only if the text supports the change.")
        a, b = ask(L1, IDENTIFY_RULES, prompt + again(b, found(a))), ask(L2, IDENTIFY_RULES, prompt + again(a, found(b)))


SUMMARY_RULES = """You write the summary of one court ruling for a litigation tracker that follows lawsuits in which
medical providers ask courts to confirm or enforce No Surprises Act IDR (arbitration) awards. Readers are lawyers who
want to know quickly what happened.

Write, using only the order's text:
- summary: two or three plain-English sentences, at most 70 words: what the provider asked for, what the court decided
  and the main reason, and whether it is final. Name the court's key holding (for example, whether the No Surprises Act
  gives providers a right to sue to enforce awards). No opinions, no predictions, nothing the order does not say.
  Privacy: never name a patient or give a patient's initials, even where the order does; write "a patient" instead.
  Do not say whether the ruling is final or can be appealed: the tracker shows that separately (you may say that the
  court allowed an amended complaint).
- result: "Win" if the provider won on enforcing or confirming the award (including a denial of a motion to dismiss
  that claim), "Loss" if it lost.
- quote: one sentence copied word for word from the order that shows the result.
- conflict: if the order does not support the editor's result given below, say why; otherwise leave it empty."""
SUMMARY_SCHEMA = {"type": "object", "required": ["summary", "result", "quote", "conflict"], "properties": {
    "summary": {"type": "string"}, "result": {"type": "string", "enum": ["Win", "Loss"]},
    "quote": {"type": "string"}, "conflict": {"type": "string"}}}
CHECK_RULES = """You check a short summary of a court ruling against the ruling itself, for a litigation tracker.
Read the order first, then the summary. Approve it (ok = true) only if every statement in the summary is supported by
the order's text, nothing important about the outcome is left out or misdescribed, and its result (Win = the provider
won on enforcing or confirming the award; Loss = it lost) matches the order. Also set ok = false if the summary names a
patient or gives a patient's initials, or says whether the ruling is final. Otherwise ok = false and list each problem
in 'problems', saying what the order actually says."""
CHECK_SCHEMA = {"type": "object", "required": ["ok", "problems"], "properties": {
    "ok": {"type": "boolean"}, "problems": {"type": "string"}}}


# Dotted initials such as "L.T." or "J. D." in a summary are most likely a patient's; allowed: abbreviations like these.
_INITIALS = re.compile(r"(?<![A-Za-z.])((?:[A-Z]\.\s?){2,4})(?![A-Za-z])")
_ALLOWED = {"US", "DC", "PC", "PA", "MD", "DO", "LP", "LLC", "LLP", "PLLC", "NA", "NJ", "NY", "SD", "ND", "ED", "WD", "CD",
            "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
            "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NM", "NC", "OH", "OK", "OR", "RI", "SC", "TN", "TX", "UT",
            "VT", "VA", "WA", "WV", "WI", "WY", "USC", "CFR"}


def initials_in(text):
    """The first dotted initials in text that are not a known abbreviation, or None."""
    for m in _INITIALS.finditer(text or ""):
        letters = re.sub(r"[.\s]", "", m[1])
        if letters not in _ALLOWED:
            return m[1].strip()
    return None


def summarise(text, case, date, outcome, ask=None):
    """Two-layer summary of one ruling. Sonnet writes it; Opus checks every statement against the order; the quote must
    be in the order and the result must match the editor's coded outcome ("Win"/"Loss"). Up to ROUNDS rounds.
    Returns {"agreed", "summary", "quote", "rounds", "note"}; only an agreed summary should be shown."""
    order = clean(text)
    if len(order.split()) < 60:
        return {"agreed": False, "rounds": 0, "note": "No readable text."}
    ask = ask or (lambda model, system, p, schema: ask_claude(model, system, p, schema=schema))
    base = f"RULING: {case} (decided {date}). The editor coded the result as: {outcome}.\n\nORDER TEXT:\n\n{order[:120000]}"
    text_n, extra, note = norm(order), "", ""
    for rnd in range(1, ROUNDS + 1):
        a = ask(L1, SUMMARY_RULES, base + extra, SUMMARY_SCHEMA)
        if a.get("conflict", "").strip():
            return {"agreed": False, "rounds": rnd, "note": "The order may not support the coded result: " + a["conflict"]}
        quote_ok = len(norm(a["quote"])) > 15 and norm(a["quote"]) in text_n
        initials = initials_in(a["summary"])
        if not quote_ok or a["result"] != outcome or initials:
            note = ("the quote was not found in the order" if not quote_ok else f"it gave {a['result']}, not {outcome}"
                    if a["result"] != outcome else f"it gives initials ({initials}) that may identify a patient")
            extra = (f"\n\nYour last summary was rejected because {note}. Write it again: copy the quote exactly from the "
                     "order, and describe the result the order shows.")
            if not quote_ok:  # courts state the result at the end: give the closing words to copy from
                extra += ("\nThe order ends with these words, where the result is usually stated; copy one sentence from "
                          "them exactly, without changing a word:\n\n" + " ".join(order.split()[-700:]))
            continue
        c = ask(L2, CHECK_RULES, f"ORDER TEXT:\n\n{order[:120000]}\n\nSUMMARY TO CHECK:\n{a['summary']}\n(Result given: {a['result']})",
                CHECK_SCHEMA)
        if c["ok"]:
            return {"agreed": True, "summary": a["summary"], "quote": a["quote"], "rounds": rnd, "note": ""}
        note = "the checker found problems: " + c["problems"]
        extra = (f"\n\nA second reader checked your last summary against the order and found these problems: {c['problems']}\n"
                 f"Your last summary was: {a['summary']}\nWrite a corrected summary that the order's text fully supports.")
    return {"agreed": False, "rounds": ROUNDS, "note": f"No agreed summary after {ROUNDS} rounds ({note})."}


def read(text, case, date, system, docket_label=None, docket_text="", ask=ask_claude):
    """Two-level reading of one order. Returns the agreed answer plus "agreed", "rounds" and "note".

    Not agreed (or no readable text) means: do not use it as a ruling; keep the case pending."""
    order = clean(text)
    if len(order.split()) < 60:
        return {"agreed": False, "rounds": 0, "note": "No readable text (a scanned image or an empty document)."}
    prompt = f"TRACKER ROW: {case} (decision dated {date}). Judge the result for this provider and this defendant only.\n\nORDER TEXT:\n\n{order}"
    text_n = norm(order)
    found = lambda a: len(norm(a["quote"])) > 15 and norm(a["quote"]) in text_n  # noqa: E731
    expected = DOCKET_RESULT.get(docket_label or "")
    a, b = ask(L1, system, prompt), ask(L2, system, prompt)  # round 1: both read blind
    rounds = 1
    while True:
        same = a["result"] == b["result"] and a["relevant"] == b["relevant"]
        docket_ok = not expected or not a["relevant"] or a["result"] == expected
        if found(a) and found(b) and same and docket_ok:
            return {**a, "agreed": True, "rounds": rounds, "note": ""}
        if rounds == ROUNDS:
            why = ("the two readers did not agree" if not same else "a quote was not found in the order"
                   if not (found(a) and found(b)) else f"the answer ({a['result']}) contradicts the docket entry")
            return {**a, "agreed": False, "rounds": rounds, "note": f"Could not agree after {rounds} rounds: {why}."}
        hint = docket_text if not docket_ok else None
        a = ask(L1, system, prompt + "\n\n" + _recheck(b, found(a), hint))
        b = ask(L2, system, prompt + "\n\n" + _recheck(a, found(b), hint))
        rounds += 1
