# Litigation Tracker

A heat map of the United States showing, state by state, how courts have ruled when providers try to enforce
No Surprises Act IDR (arbitration) awards. It is for the litigation practice only, to help decide whether to file in a
state or keep a dispute in arbitration.

## Using it

- **Open it from Callagy Hub** (its link starts `Litigation Tracker.exe` in `\\crfiles\ALL\Litigation Tracker`). The
  dashboard opens in your browser. If it is already running, the link just opens it again. The app makes no desktop
  shortcut (removed 2026-10-27); a shortcut left on a desktop from before still works, but Callagy Hub is the way in.
- **Refresh the browser** to pick up a newly saved report or article. You don't need to restart it.
- **An open page checks for new data** every 5 minutes and when you switch back to it. When there's a new report, article, Callagy list or daily update, a yellow banner says *New data is available* with a **Refresh** button. If the dashboard has closed itself after an hour of no use, the banner says so.
- The dashboard stops on its own after 60 minutes with no activity. Open it from Callagy Hub to start it again.
- It works offline and sends nothing outside your computer.

## Adding a report

Save the Excel file in `reports\`. Name it like
`NSA_Enforcement_Litigation_Dashboard_Source_YYYY-MM-DD.xlsx`. A copy suffix such as ` (3)` is fine.

- The dashboard uses the file with the **latest date in its name**. If two files share a date, it uses the one
  saved most recently.
- Required sheet: **NSA Enforcement Decisions**, with headers on row 1. The dashboard matches headers after trimming
  spaces and ignoring case. If a sheet or column is missing, the page names it; fix the file and refresh.
- Optional sheets, used as soon as they appear: **Pending Cases** (these turn states blue) and **DOL Actions**
  (the Department of Labor section). Their columns are listed in `CLAUDE.md`.
- Save the report from Excel. *Heat Map Code* is a formula, and the dashboard reads the value Excel last calculated.
  A file saved by a tool that doesn't calculate formulas shows every row under "Outcome and Heat Map Code disagree".
- The dashboard never changes, moves or deletes anything in `reports\` or `resources\`.

## Updating the Callagy case count

1. Run `app\tools\callagy_cases.sql` against the case management database with your own login.
2. Export the result as CSV and save it in `reports\` (or the older `callagy\` folder). Any file name works, with or
   without a header row; the newest CSV in either folder is used.
3. Refresh the browser.

The dashboard shows only counts per state, never case names. When the export leaves the state blank, it is taken from
the claim type (FLCIOON = Florida, GACIOON = Georgia, TXLIT = Texas) or from an NJ docket prefix such as `BER-L-`.
Cases that still have no state are listed by docket number under Data notes.

## Adding resources (articles)

Save PDF, Word (`.docx`) or HTML (`.html`, `.htm`) files in `resources\`. They appear in the Resources panel,
newest first, on the next refresh. Clicking one downloads it.

The title shown comes from inside the document:

- **PDF:** the Title property, then the largest text on page 1.
- **Word:** the Title property, then the first heading.
- **HTML:** the `<title>`, then the first `<h1>`.

If none of these is found, the file name is used. A file that can't be read is still listed under its file name,
and appears under Data notes.

**Web links** go in `resources\links.csv` (open it in Excel). One row per item, with the columns
**Title, Type, Source, Date, URL, Summary**:

- **Type** is Court opinion, Government, News or Callagy. It sets the badge (CASE, GOV, NEWS, CLG).
- **Date** is YYYY-MM-DD. Undated links go to the bottom.
- **URL** must start with `http://` or `https://`. Rows without a title or a valid URL are skipped and listed under
  Data notes.

Links open in a new browser tab, so they need internet access; files still download offline. Files and links are
listed together, newest first, and the search box above the list filters by title, type, source and summary.

What belongs in the library, as set by the legal team (Oct 12, 2026): court opinions, industry news, and closely related CMS,
HHS and DOL updates. No outside law-firm analysis; Callagy's own pieces are fine. The focus is enforcement of IDR
awards, plus the wider IDR rules.

## Logo and colours

Put the logo in `assets\`. The dashboard looks for `logo.*` first, then any image with "logo" in its name
(`.png`, `.svg`, `.jpg`, `.jpeg`, `.gif`, `.webp`). The header and accent colours are taken from the logo's dominant
colours. The map colours are fixed and do not change with the logo.

If the logo changes, also rebuild the exe icon: see *For maintainers*.

## Reading the map

| Colour | Meaning |
|---|---|
| Red | Win share under 20% |
| Orange | 20% to under 50% |
| Light green | 50% to under 80% |
| Green | 80% and above |
| Blue | No included decisions, but cases pending at that court level |
| Grey | No decisions and nothing pending |
| Hatched | Only 1 or 2 decisions: limited data |

- **Hovering a state** shows Total cases (included decisions plus pending cases in that view), then Callagy cases
  (all litigation), then decisions, wins, losses, win share and pending cases.
- **Insurers dropdown** (just above the map; on the Federal tab, beside All decisions / Appellate): tick one or more
  insurers to show only cases against them. The map, the numbers, the hover box, the table, the side panel, the cases
  list and the Callagy count all follow it. The list shows only insurers with cases in the current view, with that
  view's count. Switching view keeps an insurer ticked if it has cases there and unticks it if not. Search the list by
  typing; **Clear selection** shows everyone again. Payer names
  from the report are grouped by parent company (for example Oxford, UMR and the Empire Plan under UnitedHealth
  Group), using the rules in `app\insurers.py`.
- **Latest rulings** (right column, above Resources): the five newest rulings in the current tab, view and insurer
  filter, with "Show 5 more". Each shows an **AI summary** when there is one, otherwise the report's own holding. The
  daily update writes a summary for every ruling the card can show (up to 10 new ones a run): Sonnet writes two or three sentences
  from the order, Opus checks every statement against the order, the quote must be in the order and the result must
  match the report. A summary written for a different result than the report now shows is not displayed. Summaries are
  in `auto\summaries.json`; where the report's link cannot be read (Justia), `auto\summary_sources.json` gives a free
  copy.
- **Number cards:** click one to show only its data on the map (Wins: states with a win in green; Losses: red;
  Pending cases: blue; Decisions included or States with decisions: win-share colours without pending; Excluded: the
  states of rulings kept off the map). The other cards and states turn grey; click the card again to show everything.
- **All cases in this view** (under the map) lists every ruling and pending case in the current tab and view, newest
  first, with court, state, insurer, result, status and a source link. The search box at its top finds cases by name,
  court, state, insurer, docket, result or holding (every word must match the start of a word). Rows excluded under the methodology are not
  listed there; they stay under About this data.
- **Department of Labor actions** is collapsed; click its heading to open it.
- **Callagy cases (all litigation)** counts the firm's own lawsuits in that state, from the case list in `callagy\`.
  It is not limited to the court rulings in the report, and it is the same on every tab.
- **Win share** is wins divided by included decisions.
- Only rows with *Heat Map Include (Recommended)* = Yes count.
- Positive counts as a win, Negative as a loss. Interlocutory denials of dismissal count as wins; the side panel
  marks them "Not final".
- **Federal tab, appellate view:** each Federal Appellate decision colours every state in its circuit.
- Territories are not drawn.

**Federal circuits.** On the Federal courts tab, dark lines mark where the 12 regional circuits meet, and a numbered
badge (1st to 11th, D.C.) sits in each one; the small-state boxes show their circuit too ("NJ · 3rd"). Hovering a
state names its circuit, and its side panel links to that circuit court's website. Untick **Show circuits** to hide
the overlay; the choice is remembered in that browser. Under the map, **States in each federal circuit** opens a table of
every circuit's states (click one to open it), its territories and its court's website, with the Federal Circuit last. The Federal Circuit hears appeals by subject, nationwide, so it
has no region on the map. Requested by the legal team, 2026-10-20.

## Daily update (the one thing to run)

Run **`Daily Update\Litigation Tracker Daily Update.exe`** once a day. A window shows what it does and ends with a
short summary; press Enter to close it. Open dashboards then show a *New data is available* banner.

1. **Reads your answers** in the `To check` folder (below) and puts them on the dashboard.
2. **Finds** new rulings (CourtListener opinions, GovInfo), new enforcement cases, and new IDR rules and notices
   (Federal Register), plus new IDR guidance, FAQs, notices and reports posted on CMS's No Surprises billing pages
   (cms.gov/initiatives/no-surprise-billing; there is no feed, so the pages are checked for new documents; consumer
   leaflets, portal manuals and data tables are skipped). These go in the DOL actions, marked "Read automatically". State courts get a wider CourtListener search of their own ("No Surprises Act", "surprise
   billing", the statute numbers), because their rulings are worded more loosely. New cases on the No Surprises Act feed
   of Georgetown's free Health Care Litigation Tracker go on the To check list as leads. It also checks **every case already followed** (the report's pending and decided cases, and every
   case it found earlier) for new court entries: rulings, settlements and voluntary dismissals. It looks back to a few
   days before its last run.
3. **Has two AI readers check each one,** using your own signed-in Claude account: Sonnet first, then Opus on its own,
   without seeing the first answer. Each must quote the document word for word; if they disagree, each reads again with
   the other's reason, up to 3 rounds. Scanned PDFs are copied out page by page first. The PDFs saved in State cases\New (below) are
   read the same way.
   Cases that clearly are not award-enforcement suits are left out without reading: an insurer suing, a suit against
   the government, or a federal nature of suit such a case never has (securities, antitrust, agency review, civil
   rights, personal injury and similar).
4. **Confirmed goes straight on the dashboard.** A ruling both readers agree on (Win or Loss) and a case both agree is
   an enforcement suit are shown, marked **Read automatically**. What both agree is not relevant is left out.
5. **Not confirmed goes on the To check list.** Anything the readers could not agree on, could not read, or where the
   ruling has no free copy, is added at the bottom of `To check\To check.xlsx` for a person, with the day it was found
   in *Added on*. So is a later ruling in a case the report has already decided.
6. **Updates the website** (https://callagy-recovery.github.io/litigation-tracker/, for staff without the H: drive). It
   rebuilds `docs\` (`app\publish.py`: patient initials masked, no Callagy case counts, no H:-only files, staff names
   in notes reworded, the report's notes for whoever builds the dashboard reworded or left out, a disclaimer under the
   header; if a new report brings internal wording the rules do not cover, the window says so) and pushes what changed, with any program change, to the public GitHub repository
   `callagy-recovery/litigation-tracker`. GitHub only shows the files; it runs nothing. This needs git and the
   `GITHUB_TOKEN` Windows user variable (a fine-grained token for that repository only: Contents and Pages, read and
   write; it expires after a year and is then replaced). If the push fails, the window says so; the H: dashboard is
   up to date regardless. Only the `main` branch is ever pushed; `local-history` (the history before the repository
   went public) stays on H:. Its own address will be **tracker.callagyrecovery.com**: once the firm's DNS has a
   `CNAME` record `tracker` -> `callagy-recovery.github.io`, the next run publishes the `CNAME` file and GitHub moves
   the site there (the github.io link forwards to it). Until then (callagyrecovery.com has a wildcard record to the
   firm's web host) the site stays at the github.io address, so it is never sent to a domain that is not set up.

Anything not reached in one run (Claude's usage limit, CourtListener's 125 searches a day) is simply done on the next
run; nothing needs to be done by hand. The report always wins: a ruling or case the report already has is not added
twice. Data notes show when the update last ran, and warn if it has not run for 3 days.

## To check (answers from a person)

One file, `To check\To check.xlsx`, has one row per case or ruling: the case, court, docket number, date, a link, why
it needs a person, what the readers found, and *Added on* (the day the daily update found it). Check a saved page's
docket number against the row before answering: a plaintiff often has several cases against the same insurer. Each run adds its new rows at the
bottom. (Until 2026-10-27 each day had its own file; those were merged into this one and are kept in `To check\Done\`.)

1. Open the link and pick **Your answer**: *Pending case* (an enforcement suit, no ruling yet), *Win* or *Loss* (a ruling
   on enforcing the award), or *Leave out* (not one for the tracker). A note is optional; for a Win or Loss it is shown
   as the holding. Not sure? Leave it empty; it stays on the list.
2. Save the file in the same folder, under the same name, and close it. It can be sent to the legal team and saved
   back. If it is open in Excel during a run, that run's new rows are kept and added on the next run; the run's
   summary says how many are waiting.
3. The next daily update puts the answers on the dashboard, marked **Checked by a person**, and moves answered rows to
   the file's **Settled** sheet. It also settles rows by itself when it finds the answer: a ruling both readers agree
   on, a first filing both confirm, a settlement or voluntary dismissal, or a case that is not an enforcement suit. The
   reason is in the Note. A District of New Jersey case listed in the court's stay order of Jan 16, 2026 (Schedule A,
   329 suits to enforce IDR awards, stayed pending the lead case East Coast Plastic Surgery v. Aetna, 25-15052; list in
   `app\nj_stay.py`) is settled as a *Pending case* and shown on the dashboard marked **From court order** (a ruling or
   an ending found for it comes first). A ruling read in the lead case is called out in the run's summary.
   Cases with no free first filing are looked up again once a week. To change any answer, change
   it on the Settled sheet. *Leave out* takes the case off and it is not asked again. The To check sheet only holds
   open work.

The details of each row are kept in `auto\to_check.json`.

- **Before the first run:** install Claude Code and sign in (`claude`, then `/login`), and set `COURTLISTENER_TOKEN`
  and `API_DATA_GOV_KEY` as Windows user environment variables. The window says what is missing.
- **Usage:** each order costs about 20¢ of your Claude plan's usage (tested on the 47 rulings of the 2026-09-30 report:
  42 of 45 readable ones matched the report's coding). It reads at most 30 orders a run; the rest wait for the next run,
  as do orders left unread if Claude stops (for example at a usage limit).
- **Safety:** Claude runs with no tools, so an order's text can only be read. Only public court documents are sent.
- It never changes `reports\` or `resources\`. To undo everything it added, delete `auto\found.json`.
- **Newsletter:** at the end of a daily run that found something new (at most one a day), it saves an **Outlook draft**
  (in your Drafts folder; it never sends), dated that day: a brief, branded newsletter of what is new since the last one. A header with
  the logo, four number tiles (new rulings, wins, losses, new cases), one line per new ruling with a WIN/LOSS label
  (five at most), a bar chart of the new cases by state, and a pointer to the dashboard for the details. It is built
  in email-safe HTML (600 px tables, logo embedded) so it looks the same in desktop Outlook. Subject: "Litigation Tracker ·
  Oct 16, 2026: 2 new rulings, 1 new case". If nothing is new, no draft is made. If you run the update again the same
  day and it finds more, it adds them to that day's draft, but only while the draft is still unsent in your Drafts
  folder and nobody has edited it; otherwise the new items go in the next day's draft. Everyone signed up (below) is put in
  BCC, so recipients do not see each other's addresses. What has been listed is kept in `auto\newsletter.json`.
- **Newsletter sign-up:** the **Get the newsletter** button at the top right of the dashboard adds the person's work email
  (@callagyrecovery.com or @callagylaw.com; it suggests theirs from their Windows login) to
  `newsletter\Newsletter sign-ups.xlsx`: Email, Name, Windows user, Signed up, Status, Changed. Each address is on the list
  once; signing up again says so, and an unsubscribed person signing up again is switched back on. The same button
  unsubscribes. Everyone Subscribed goes in the BCC of every draft. Open the list read-only, or close it soon: while it is
  open in Excel, sign-ups are refused with "try again in a minute".

## State court cases found online (automatic)

Each daily update also looks for state cases itself (`app\state_search.py`). Claude Code, with only its web search,
runs searches by state, on news and law-firm sites and on the courts' own sites. The update also checks New Jersey's
opinion lists and multicounty litigation page. For each case found, it opens the court's document or a free article,
only where the site allows scripts. It never uses paid services or sites that block scripts. If every page blocks
scripts, both readers check the case through their own web searches, and their quotes must match word for word.
What both readers agree on goes on the dashboard marked **"From news report"** or **"From web search"** (not the
court's own order). The report or the court's own order replaces such a row when either has the case. Anything else
goes on the To check list as "State case (found online)". A case found once is tried again on each run (up to 10 a
run) until it is checked, and goes to To check after 5 tries. To try the search without changing anything, run
`.venv\Scripts\python app\state_search.py`: results go to `State cases\Search trial\`.

## State court cases (found by hand)

Many state court records can't be searched by a script: the court sites need logins, show CAPTCHAs or block scripts.
So a person can still find state cases and save them; everything else is automatic. The printable guide
`State cases\How to find state cases.docx` has the weekly checklist (which website, what to type, what to save).

1. **Find** new state rulings or new state enforcement cases, using the guide's checklist.
2. **Save** the court's document as a PDF in `State cases\New\`. Any file name; nothing to type. Only the main
   document: never exhibits, medical records or anything about a patient.
3. **Run** the daily update.

For each file, both AI readers first pick out the case name, court, state, docket number and date, and whether it is
a ruling or a new case. Then they read it like any other ruling or case. What they agree on goes on the State courts
tab, marked "Read automatically"; anything else, including a file both readers think is not relevant (a person chose to save it, so a person decides), goes on the To check list, where the case details can be
corrected before answering. Every file read moves to `State cases\Done\`, its name starting with the date it was read.
Up to 30 files are read per run; the rest wait for the next run.

## Logs

Each run writes `logs\run_<date>_<time>_<user>.log`. It records the report used, row counts, excluded rows, unknown
values, disagreements and unreadable resources. Patient initials never appear in the logs.

## For maintainers

**Changing the dashboard needs no rebuild.** `Litigation Tracker.exe` is a launcher: each time someone opens the
dashboard it runs `main.py`, `data.py`, `resources.py`, `signups.py` and `insurers.py` from `app\` on the share, and
the page files from `app\static\`. Save a change (tests first), and everyone gets it the next time they open the
dashboard. If the shared code cannot be loaded, the launcher runs the copy it was built with and the page shows a
"Dashboard running its backup code" note saying why. Rebuild (`app\tools\build.ps1`, everyone off the dashboard) only
when the dashboard starts using a new library; the note says so when that is the reason. Closing the browser tab
does not close the dashboard: it runs in the background for up to an hour (Task Manager: Litigation Tracker,
End task).

The app is Python 3.12 using the standard-library HTTP server, with plain JavaScript and SVG. It uses no JavaScript
libraries and no CDN.

| Path | What it is |
|---|---|
| `app\launcher.py` | What `Litigation Tracker.exe` runs: loads the dashboard code below from the share at each start, with a built-in backup copy |
| `app\main.py` | Launcher: single instance, server bound to 127.0.0.1, idle shutdown, logo colours, refresh check, sign-up |
| `app\data.py` | Finds and reads the report, masking, circuits, colour bands, counts, merging the daily update's finds |
| `app\insurers.py` | Insurer names: standard names and payer types |
| `app\resources.py` | Resources scan and title extraction |
| `app\daily_update.py` | The daily update (built as `Daily Update\Litigation Tracker Daily Update.exe`) |
| `app\reader.py` | Two-level Claude reader the daily update uses |
| `app\to_check.py` | The To check list (`To check\To check.xlsx`) and the answers from it |
| `app\state_cases.py` | State cases saved by hand (`State cases\New\`) |
| `app\state_search.py` | State cases found online (web search, NJ courts), verified by the two readers |
| `app\newsletter.py`, `app\signups.py` | Newsletter draft and the sign-up list |
| `app\tools\find_updates.py`, `app\tools\check_dockets.py` | Searches, report matching and docket-entry reading the daily update uses |
| `app\tools\callagy_cases.sql` | The query for the Callagy case count |
| `app\static\` | Page (`index.html`, `app.js`, `app.css`), map shapes (`us_states.json`), icon |
| `app\tools\build.ps1` | Runs the tests, then builds both exes |
| `app\tools\make_map.cjs` | Regenerates `us_states.json` from the us-atlas package (one-off; needs Node) |
| `tests\` | pytest suite, including the acceptance checks against the 2026-09-29 report |

```bash
"\\crfiles\ALL\Litigation Tracker\.venv\Scripts\python.exe" -m pytest -q "\\crfiles\ALL\Litigation Tracker\tests"
```

```bash
powershell -ExecutionPolicy Bypass -File "\\crfiles\ALL\Litigation Tracker\app\tools\build.ps1"
```

**Running from source:** `.venv\Scripts\python.exe app\main.py`. Two environment variables help with testing:

- `LT_PORT=8765` fixes the port.
- `LT_NO_BROWSER=1` stops it opening a browser.

**New icon after a logo change:**

```bash
"\\crfiles\ALL\Litigation Tracker\.venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, r'\\crfiles\ALL\Litigation Tracker\app'); import main; from PIL import Image; im = Image.open(main.find_logo()).convert('RGBA'); s = max(im.size); sq = Image.new('RGBA', (s, s), 'white'); sq.paste(im, ((s - im.width) // 2, (s - im.height) // 2)); sq.save(main.STATIC / main.ICON_NAME, sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])"
```

Then rebuild the exe.

Map shapes are © us-atlas contributors (ISC licence, `app\static\us-atlas-LICENSE.txt`), derived from US Census
Bureau cartographic boundaries.
