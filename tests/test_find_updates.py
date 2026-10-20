"""The matching rules of app/tools/find_updates.py (no network)."""
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "tools"))
import find_updates as fu  # noqa: E402


def test_docket_numbers_normalise_across_formats():
    assert fu.norm_docket("2:22-cv-06614-KM-JBC") == ["22cv6614"]
    assert fu.norm_docket("4:2025cv00466") == ["25cv466"]
    assert fu.norm_docket("1:25-cv-00054-HG") == fu.norm_docket("1:25-cv-54")
    assert fu.norm_docket("25 Civ. 499 / 1255 / 1264") == ["25cv499", "25cv1255", "25cv1264"]
    assert fu.norm_docket("24-10561") == ["24-10561"]
    assert fu.norm_docket("26-02269") == ["26-2269"]
    assert fu.norm_docket("C-250606") == ["250606"]
    assert fu.norm_docket("Index No. 604606/2026") == fu.norm_docket("604606/2026")
    assert fu.norm_docket("") == []


def test_court_codes_map_to_report_values():
    assert fu.court_info("nyed") == ("Federal District", "2", "NY")
    assert fu.court_info("ilnd") == ("Federal District", "7", "IL")
    assert fu.court_info("dcd") == ("Federal District", "DC", "DC")
    assert fu.court_info("ca5") == ("Federal Appellate", "5", "LA")
    assert fu.court_info("cadc") == ("Federal Appellate", "DC", "DC")
    assert fu.court_info("deb") is None  # bankruptcy
    assert fu.court_info("ohioctapp", "Ohio Court of Appeals", "SA") == ("State Appellate", None, "OH")
    assert fu.court_info("nysuprctfflk", "New York Supreme Court, Suffolk County", "ST") == ("State Trial", None, "NY")
    assert fu.court_info("wvactapp", "West Virginia Intermediate Court of Appeals", "SA")[2] == "WV"


def test_matching_needs_the_same_court_area():
    known = [("22cv6614", "3", "NJ", "NSA-001")]
    assert fu.match(known, ["22cv6614"], "3", "NJ") == "NSA-001"
    assert fu.match(known, ["22cv6614"], "9", "CA") is None  # same number, different court


def test_party_split():
    assert fu.split_parties("PHI Health, LLC v. Anthem Insurance Companies, Inc. et al") == ("PHI Health, LLC", "Anthem Insurance Companies, Inc.")


import check_dockets as cd  # noqa: E402


def test_docket_entries_classify_rulings_before_housekeeping():
    assert cd.classify([("2026-09-17", "Transcript"), ("2026-09-02", "Judgment - Clerk"),
                        ("2026-09-02", "MEMORANDUM DECISION AND ORDER granting defendant's 9 Motion to Dismiss.")])[0] == "Ruling: dismissed"
    assert cd.classify([("2026-05-01", "STIPULATION of Dismissal with prejudice by all parties")])[0] == "Ended: voluntary dismissal or settlement"
    assert cd.classify([("2026-07-21", "ORDER granting 19 Motion to Confirm Arbitration Award")])[0].startswith("Ruling: award confirmed")
    assert cd.classify([("2026-04-01", "ORDER denying 12 Motion to Dismiss")])[0] == "Ruling: motion to dismiss denied"
    assert cd.classify([("2026-03-02", "ORDER staying case pending appeal")])[0] == "Stayed"
    assert cd.classify([])[0] == "No ruling or closing entry found"


def test_court_names_and_docket_numbers_for_courtlistener():
    assert cd.court_code("U.S. District Court for the Northern District of Oklahoma") == "oknd"
    assert cd.court_code("U.S. District Court for the District of New Jersey") == "njd"
    assert cd.court_code("U.S. Court of Appeals for the Seventh Circuit") == "ca7"
    assert cd.cl_docket_number("4:2025cv00466") == "4:25-cv-00466"
    assert cd.cl_docket_number("26-2269") == "26-2269"


def test_docket_lookup_batches_federal_numbers_and_skips_state_courts():
    class FakeApi:
        calls = []

        def get(self, url, headers, cl=False):
            self.calls.append(url)
            return {"results": [{"court_id": "ctd", "docketNumber": "3:25-cv-01476", "docket_id": 71297718}], "next": None}

    api, ids, budget = FakeApi(), {}, {"left": 10}
    rows = [{"Court": "U.S. District Court for the District of Connecticut", "Docket No.": "3:25-cv-01476-VAB"},
            {"Court": "U.S. District Court for the District of New Jersey", "Docket No.": "2:25-cv-12682"},
            {"Court": "Supreme Court of New York, Nassau County", "Docket No.": "Index No. 604606/2026"}]
    cd.resolve_ids(api, "t", rows, ids, budget)
    assert len(api.calls) == 1  # both federal numbers in one search; the state case needs none
    assert list(ids.values()) == [None, "71297718", None]


def test_docket_lookup_falls_back_to_party_name_for_incomplete_numbers():
    class FakeApi:
        calls = []

        def get(self, url, headers, cl=False):
            self.calls.append(url)
            return {"results": [{"docketNumber": "8:26-cv-00735", "docket_id": 1},
                                {"docketNumber": "8:26-cv-00736", "docket_id": 2}], "next": None}

    api, ids = FakeApi(), {}
    rows = [{"Court": "U.S. District Court, Central District of California", "Docket No.": "26-cv-00736-FWS-KES",
             "Case Name": "Savalia v. Anthem Blue Cross Life & Health Insurance Co."}]
    cd.resolve_ids(api, "t", rows, ids, {"left": 5})
    assert "Savalia" in urllib.parse.unquote_plus(api.calls[0]) and "court=cacd" in api.calls[0]
    assert list(ids.values()) == ["2"]
    cd.resolve_ids(api, "t", [{**rows[0], "Docket No.": "26-cv-09999"}], ids, {"left": 5})
    assert ids["U.S. District Court, Central District of California|26-cv-09999"] is False  # not searched again next run


def test_filings_and_notices_are_never_rulings():
    no = cd.entry_label
    assert no("MOTION to Dismiss Plaintiff's First Amended Complaint by Zotec Partners, LLC.") is None
    assert no("Clerks Notice Re: Consent. A magistrate judge has been assigned ... enter final judgment") is None
    assert no("CASE ASSIGNMENT: District Judge assigned. If the District Judge issues an Order of dismissal") is None
    assert no("PAPERLESS ORDER granting 20 Motion for Extension of Time to Respond to Defendant's Motion to Dismiss.") != "Ruling: dismissed"
    assert no("MOTION to Remand Case to State Court by Plaintiffs") is None
    assert no("NOTICE re: Notice of Supplemental Authority") is None
    assert no("NOTICE OF APPEAL to the Fifth Circuit as to Order on Motion to Dismiss") == "Appeal filed"
    assert no("NOTICE of Voluntary Dismissal without prejudice by ROWE PLASTIC SURGERY") == "Ended: voluntary dismissal or settlement"
    assert no(" MINUTE (IN CHAMBERS) ORDER REMANDING ACTION by Judge Olguin") == "Moved: remanded or transferred"
    assert no("ORDER denying 23 Motion to Vacate. This action remains stayed pending a decision by the Second Circuit") == "Stayed"
    assert no("ORDER (1) GRANTING IN PART DEFENDANT'S MOTION TO DISMISS, AND (2) DISMISSING ACTION WITHOUT PREJUDICE") == "Ruling: dismissed"
    assert no("Judgment - Clerk") == "Ended: judgment entered"


def test_orders_that_only_name_an_outcome_are_read_correctly():
    no = cd.entry_label
    # The filing's title "Petition to Confirm Arbitration Award" is not a confirmation.
    assert no('ORDER. "Anthem\'s Motion to Dismiss Petition to Confirm Arbitration Award and Incorporated Memorandum" (Doc. 16) '
              'is granted. "Petition to Confirm Arbitration Award" (Doc. 1) and this action are dismissed without prejudice.') == "Ruling: dismissed"
    assert no('ORDER. "Second Amended Petition to Confirm Arbitration Award" (Doc. 40) is denied.') == "Ruling: petition to confirm denied"
    assert no("ORDER denying 5 Petition to Confirm Arbitration Award") == "Ruling: petition to confirm denied"
    assert no("ORDER denying 9 Motion to Dismiss the Petition to Confirm Arbitration Award") == "Ruling: motion to dismiss denied"
    assert no("Ruling on Motion to Dismiss. The court denies Cigna's Motion to Dismiss, and grants New England PA, LLCs Cross "
              "Motion for Confirmation") \
        .startswith("Ruling: award confirmed")
    assert no("ORDER DISMISSING CASE re 18 Notice of Voluntary Dismissal filed by Plaintiff") == "Ended: voluntary dismissal or settlement"
    assert no("ORDER DISMISSING CASE: The 22 Stipulation of Dismissal is So Ordered.") == "Ended: voluntary dismissal or settlement"
    assert no("ORDER re: 25 Motion to Stay is GRANTED. In the event the motion to dismiss is denied, file a joint letter") == "Stayed"
    assert no("PAPERLESS ORDER REFERRING MOTION. Motion to Dismiss is REFERRED to Magistrate Judge for a report and recommendation") is None
    assert no("ORDER: Defendants intend to seek a pre-motion conference on an anticipated motion for summary judgment") is None
    assert no("APPEAL OF MAGISTRATE JUDGE DECISION to District Court by UHC re 4 Order of Dismissal") is None
    assert no("ORDER denying as moot 21 Motion to Dismiss; granting 23 Motion to Remand to State Court") == "Moved: remanded or transferred"
    assert no("Order of USCA; Judgment issued as mandate 7/3/25. IT IS ORDERED we AFFIRM the order dismissing") == "Appeal decided (mandate)"
    assert no("ORDER ADOPTING REPORT AND RECOMMENDATION: recommending denial of the petition") == "Ruling: report and recommendation adopted"
    assert no("ENDORSED ORDER: The plaintiff moves (Doc. 14) to extend the time within which to respond to the motion to "
              "dismiss. The motion is GRANTED.") is None


def test_plural_motions_to_dismiss():
    assert cd.entry_label("ORDER granting 15 Joint Motions to Dismiss Pursuant to Rules 12(b)(1) and 12(b)(6); denying as moot "
                          "31 Motion to Stay Discovery") == "Ruling: dismissed"
