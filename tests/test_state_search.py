"""The state case search (app/state_search.py): matching leads to dashboard cases, NJ's opinion lists, and the two
readers' agreement on a news page."""
import state_search as ss

PAGE = """<nav>menu</nav><main> <a href="/system/files/court-opinions/2026/ESX-L-000418-26.pdf">
E. Coast Advanced Plastic Surgery, LLC v. Cigna Health &amp; Life Ins. Co.</a> ESX-L-000418-26 Unpublished Trial Sept. 30, 2026
<a href="/system/files/court-opinions/2026/roman.pdf">Roman v. Del Valle</a> ESX-L-9668-21</main>"""


def test_nj_list_pages_and_captions():
    rows = list(ss.nj_rows(PAGE))
    assert rows[0][0] == "https://www.njcourts.gov/system/files/court-opinions/2026/ESX-L-000418-26.pdf"
    assert rows[0][1].startswith("E. Coast Advanced Plastic Surgery, LLC v. Cigna Health & Life Ins. Co.")
    assert ss.CAPTION.search(rows[0][1]) and not ss.CAPTION.search(rows[1][1])


def test_a_lead_matches_a_dashboard_case_only_on_both_parties():
    cases = ["AA Med., P.C. v. Aetna Life Insurance Co.", "True North Medical of Manhasset v. Empire HealthChoice"]
    assert ss.known_case("AA Med. P.C. v. Aetna", cases) == cases[0]
    assert ss.known_case("True North Medical v. Anthem", cases) is None
    assert ss.known_case("Two medical providers", cases) is None


def test_news_readers_must_agree_and_quote_the_page():
    text = ("Suffolk County Supreme Court Justice Paul Hennings granted the motion to dismiss on Sept. 17, 2026, "
            "throwing out all seven claims. " + "filler words here " * 30)
    ans = {"reported": True, "case": "True North Medical v. Anthem", "court": "Supreme Court, Suffolk County", "state": "ny",
           "date": "2026-09-17", "kind": "ruling", "result": "Loss", "holding": "The court dismissed the suit.",
           "quote": "Justice Paul Hennings granted the motion to dismiss on Sept. 17, 2026"}
    res = ss.read_news(text, {"case": "True North v. Anthem"}, ask=lambda model, system, p: dict(ans))
    assert res["agreed"] and res["state"] == "NY"
    what, adds, why = ss.news_result(res, "https://example.org/a")
    assert what.startswith("Loss") and not why and adds["decisions"][0]["fromNews"]
    calls = []

    def disagree(model, system, p):
        calls.append(model)
        return {**ans, "result": "Loss" if model == "sonnet" else "Pending"}
    assert not ss.read_news(text, {"case": "x"}, ask=disagree)["agreed"] and len(calls) == 2 * ss.reader.ROUNDS
    assert ss.news_result({**res, "date": ""}, "u")[0] == "to check"  # no full date: a person decides


def test_a_lead_found_again_adds_its_sources_instead_of_a_second_lead():
    leads = []
    assert ss.add_lead(leads, {"case": "True North Medical v. Anthem", "sources": ["a"]})
    assert ss.add_lead(leads, {"case": "True North Med. PLLC v. Anthem Inc.", "sources": ["b"]}) is None
    assert ss.add_lead(leads, {"case": "Two practices v. Elevance", "sources": ["b", "c"]}) is None  # same article
    assert len(leads) == 1 and leads[0]["sources"] == ["a", "b", "c"]


def test_web_search_check_needs_both_readers_to_quote_the_same_words():
    assert "using web search only" in ss.SEARCH_READ_RULES and "page's text" not in ss.SEARCH_READ_RULES
    said = "Suffolk County Supreme Court Justice Paul Hennings granted the motion to dismiss on Sept. 17, 2026"
    ans = {"reported": True, "case": "True North Medical v. Anthem", "court": "Supreme Court, Suffolk County",
           "state": "NY", "date": "2026-09-17", "kind": "ruling", "result": "Loss", "holding": "Dismissed.",
           "quote": said, "source": "https://example.org/a"}
    lead = {"case": "True North Medical v. Anthem"}
    assert ss.read_by_search(lead, ask=lambda model, t="": dict(ans))["agreed"]
    made_up = lambda model, t="": {**ans, "quote": said if model == "sonnet" else "The court threw the case out in September."}
    assert not ss.read_by_search(lead, ask=made_up)["agreed"]
    other = lambda model, t="": {**ans, "result": "Loss" if model == "sonnet" else "Win"}
    assert not ss.read_by_search(lead, ask=other)["agreed"]

    one_date = lambda model, t="": {**ans, "date": "" if model == "sonnet" else ans["date"]}
    res = ss.read_by_search(lead, ask=one_date)
    assert res["agreed"] and res["date"] == "" and ss.news_result(res, "u")[0] == "to check"  # a person checks it
    tasks = []

    def settles(model, t=""):  # different dates at first; Sonnet then sees Opus's answer (never its quotes)
        tasks.append(t)
        return {**ans, "date": "2025-09-17" if model == "sonnet" and not t else ans["date"]}
    assert ss.read_by_search(lead, ask=settles)["agreed"] and said not in tasks[2]


def test_daily_step_puts_verified_cases_on_the_dashboard_and_the_rest_on_to_check(monkeypatch):
    report = {"decisions": {}, "pending": {"P1": {"case": "Alpha Surgery LLC v. Cigna"}}}
    found = {"decisions": [{"case": "Alpha Surgery v. Cigna Health", "fromNews": "news report"}], "pending": []}
    row = {"case": "True North Medical v. Anthem", "state": "NY", "date": "2026-09-17", "result": "Loss",
           "fromNews": "web search"}

    def fake_search(leads, known, system, done, say, nj_seen):
        assert "Alpha Surgery LLC v. Cigna" in known
        done({"case": "True North Medical v. Anthem", "court": "", "state": "New York", "sources": [], "evidence": "",
              "firstSeen": "2026-10-28"},
             {"what": "Loss", "why": "", "adds": {"decisions": [row]}, "readFrom": "u", "tried": [], "details": {}})
        done({"case": "University Spine Center v. UnitedHealthcare", "court": "NJ Superior Court", "state": "New Jersey",
              "sources": ["https://example.org/s"], "evidence": "sued July 24", "firstSeen": "2026-10-28"},
             {"what": "to check", "why": "No full date.", "adds": {}, "readFrom": "", "tried": [], "details": {}})
    monkeypatch.setattr(ss, "search", fake_search)
    monkeypatch.setattr(ss.reader, "system_prompt", lambda decisions: "")
    asks, saves = [], []
    counts = ss.update(report, {}, found, {}, asks, say=lambda m: None, progress=lambda: saves.append(1))
    assert found["decisions"] == [row]  # the report now has Alpha Surgery: its news row gave way
    assert counts["dashboard"] == 1 and counts["to check"] == 1 and len(saves) == 2
    assert asks[0]["kind"] == "State case (found online)" and asks[0]["state"] == "NJ"
    assert asks[0]["url"] == "https://example.org/s"


def test_dashboard_says_where_a_news_ruling_came_from(tmp_path):
    import json
    (tmp_path / ss.data.AUTO_FILE).write_text(json.dumps({"lastRun": "2026-10-28T10:00:00", "decisions": [
        {"case": "True North Medical v. Anthem", "court": "Supreme Court, Suffolk County", "level": "State Trial",
         "state": "NY", "date": "2026-09-17", "result": "Loss", "final": False, "fromNews": "web search"}]}))
    decisions, pending, notes = [], [], []
    ss.data.merge_auto(tmp_path, decisions, pending, None, notes)
    d = decisions[0]
    assert d["fromNews"] == "web search" and d["status"] == "Not final (from a web search)"
    assert "not the court's own order" in d["caution"]


def test_paid_services_and_sites_that_forbid_scripts_are_never_fetched():
    import pytest
    for url in ("https://unicourt.com/case/pc-db1-x", "https://law.justia.com/cases/x",
                "https://iapps.courts.state.ny.us/nyscef/x"):
        with pytest.raises(ss.Blocked):
            ss.Web().get(url)  # refused before any request is made
    assert not ss.NOT_USED.search("www.njcourts.gov") and not ss.NOT_USED.search("www.courtlistener.com")


def test_a_leads_to_check_row_settles_once_the_courts_own_order_is_on_the_dashboard():
    import to_check as tc
    store = {"statelead:true|anthem|2026-10-28": {"case": "True North Medical of Manhasset v. Anthem companies"},
             "statelead:alpha|cigna|2026-10-28": {"case": "Alpha Surgery v. Cigna"},
             "statelead:other|aetna|2026-10-28": {"case": "Other Clinic v. Aetna"}}
    found = {"decisions": [{"case": "True North Medical of Manhasset, P.C. v. Anthem HealthChoice Assurance, Inc.",
                            "date": "2026-09-17", "result": "Loss", "source": "State cases (saved by hand)"}], "pending": []}
    assert ss.settle_leads(store, found, ["Alpha Surgery LLC v. Cigna"]) == 2
    assert store["statelead:true|anthem|2026-10-28"]["answer"] == "Loss"
    assert store["statelead:alpha|cigna|2026-10-28"]["answer"] == tc.LEAVE
    assert "answer" not in store["statelead:other|aetna|2026-10-28"]
    rows, _ = tc.dashboard_rows(store)
    assert rows == {"decisions": [], "pending": []}  # the order's own row is the only one on the dashboard
