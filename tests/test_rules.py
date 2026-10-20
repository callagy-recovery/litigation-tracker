import os
import time

import pytest

import data


@pytest.mark.parametrize("pct, colour", [
    (0, "red"), (19.9, "red"), (20, "orange"), (49.9, "orange"),
    (50, "lightgreen"), (79.9, "lightgreen"), (80, "green"), (100, "green"),
])
def test_colour_bands_at_each_boundary(pct, colour):
    assert data.band(pct / 100) == colour


def test_exact_fractions_land_on_the_upper_band():
    assert data.state_colour(1, 5) == "orange"      # exactly 20%
    assert data.state_colour(1, 2) == "lightgreen"  # exactly 50%
    assert data.state_colour(4, 5) == "green"       # exactly 80%
    assert data.state_colour(1, 3) == "orange"      # the Florida case, 33%


def test_no_decisions_is_blue_when_pending_else_grey():
    assert data.state_colour(0, 0, pending=1) == "blue"
    assert data.state_colour(0, 0, pending=0) == "grey"


@pytest.mark.parametrize("n, expected", [(0, False), (1, True), (2, True), (3, False), (12, False)])
def test_hatch_rule(n, expected):
    assert data.hatched(n) is expected


@pytest.mark.parametrize("raw, key", [
    ("3d", "3"), ("3rd", "3"), ("Third", "3"), ("third circuit", "3"), ("3", "3"), (" 3rd Cir. ", "3"),
    ("2d", "2"), ("2nd", "2"), ("Second", "2"), ("1st", "1"), ("5th Cir.", "5"), ("11th", "11"),
    ("Eleventh", "11"), ("10th Circuit", "10"), ("D.C.", "DC"), ("DC", "DC"), ("D.C. Cir.", "DC"),
    ("District of Columbia", "DC"), ("N/A", None), ("", None), (None, None), ("12th", None),
    ("Federal", None), ("0", None),
])
def test_circuit_normalisation(raw, key):
    assert data.norm_circuit(raw) == key


def test_circuit_mapping_covers_50_states_and_dc_once_each():
    listed = [s for states in data.CIRCUIT_STATES.values() for s in states]
    assert sorted(listed) == sorted(data.STATE_NAMES)
    assert len(listed) == 51
    assert data.CIRCUIT_STATES["5"] == ["LA", "MS", "TX"]
    assert data.CIRCUIT_STATES["2"] == ["CT", "NY", "VT"]
    assert data.CIRCUIT_STATES["9"] == ["AK", "AZ", "CA", "HI", "ID", "MT", "NV", "OR", "WA"]


def test_circuit_labels():
    assert [data.circuit_label(k) for k in ("1", "2", "3", "4", "11", "DC")] == [
        "1st Circuit", "2nd Circuit", "3rd Circuit", "4th Circuit", "11th Circuit", "D.C. Circuit"]


@pytest.mark.parametrize("raw, masked", [
    ("GPS of New Jersey M.D., P.C. a/s/o X.Y. v. Horizon", "GPS of New Jersey M.D., P.C. a/s/o *** v. Horizon"),
    ("Clinic o/b/o J.R.S. v. Plan", "Clinic o/b/o *** v. Plan"),
    ("Clinic as subrogee of A.B., v. Plan", "Clinic as subrogee of ***, v. Plan"),
    ("Clinic as assignee of X. Y. v. Plan", "Clinic as assignee of *** v. Plan"),
    ("Clinic on behalf of XY v. Plan", "Clinic on behalf of *** v. Plan"),
    ("Clinic A/S/O X.Y. v. Plan", "Clinic A/S/O *** v. Plan"),
    ("Clinic a/s/o X.Y. and J.K. v. Plan", "Clinic a/s/o *** v. Plan"),
    ("Clinic a/s/o X.Y.", "Clinic a/s/o ***"),
])
def test_masking(raw, masked):
    assert data.mask(raw) == masked
    assert "X.Y" not in data.mask(raw)


@pytest.mark.parametrize("text", [
    "Brief filed on behalf of the Plan", "Motion on behalf of itself and others", "Horizon Blue Cross v. Aetna",
])
def test_masking_leaves_ordinary_text_alone(text):
    assert data.mask(text) == text


def test_masking_passes_non_text_through():
    assert data.mask(None) is None and data.mask(12) == 12


def _touch(folder, name, mtime):
    p = folder / name
    p.write_bytes(b"x")
    os.utime(p, (mtime, mtime))
    return p


def test_newest_report_by_date_in_name(tmp_path):
    now = time.time()
    _touch(tmp_path, "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-29.xlsx", now - 100)
    _touch(tmp_path, "NSA_Enforcement_Litigation_Dashboard_Source_2026-10-06.xlsx", now - 5000)  # newer date, older file
    _touch(tmp_path, "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-15.xlsx", now)
    path, date = data.newest_report(tmp_path)
    assert path.name.endswith("2026-10-06.xlsx") and date.isoformat() == "2026-10-06"


def test_newest_report_accepts_copy_suffix_and_breaks_ties_by_mtime(tmp_path):
    now = time.time()
    _touch(tmp_path, "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-29.xlsx", now - 100)
    _touch(tmp_path, "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-29 (3).xlsx", now)
    _touch(tmp_path, "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-29 (2).xlsx", now - 50)
    assert data.newest_report(tmp_path)[0].name == "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-29 (3).xlsx"


def test_copy_suffix_on_an_older_date_does_not_win(tmp_path):
    now = time.time()
    _touch(tmp_path, "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-01 (7).xlsx", now)
    _touch(tmp_path, "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-29.xlsx", now - 100)
    assert data.newest_report(tmp_path)[0].name == "NSA_Enforcement_Litigation_Dashboard_Source_2026-09-29.xlsx"


def test_other_files_are_ignored(tmp_path):
    now = time.time()
    for name in ("~$NSA_Enforcement_Litigation_Dashboard_Source_2026-12-01.xlsx",
                 "NSA_Enforcement_Litigation_Dashboard_Source_2026-13-01.xlsx",
                 "NSA_Enforcement_Litigation_Dashboard_Source_2026-12-01.csv",
                 "Other report 2026-12-01.xlsx", "Thumbs.db"):
        _touch(tmp_path, name, now)
    assert data.newest_report(tmp_path) is None
    _touch(tmp_path, "nsa_enforcement_litigation_dashboard_source_2026-09-29.XLSX", now)
    assert data.newest_report(tmp_path)[0].name.lower().startswith("nsa_enforcement")


def test_callagy_list_counts_cases_per_state(tmp_path):
    assert data.load_callagy(tmp_path / "missing") is None
    old = tmp_path / "old.csv"
    old.write_text('"A v. B","x","1",NJ,"CI","1","2020-01-01","Returned"\n', encoding="utf-8")
    os.utime(old, (time.time() - 100, time.time() - 100))
    (tmp_path / "new.csv").write_text(
        "case_name_constructed,court_inferred_from_docket,docket_index_number,state_inferred,claim_types_on_docket,"
        "pad_cases_on_docket,first_pad_case_opened,pad_status\n"
        '"P v. Aetna","NJ Superior Court, Bergen County, Law Division","BER-L-1-22","NJ","CI","1","2021-01-01","Returned"\n'
        '"P v. Cigna","not identified","MRS--L-1750-24",,"CI","1","2023-01-09","Returned"\n'   # NJ from the docket prefix
        '"Q v. UHC","not identified","22-003583-CO",,"FLCIOON","1","2021-02-08","Returned"\n'  # FL from the claim type
        '"R v. Aetna","not identified","22-cv-83",,"CI","1","2020-02-10","Returned"\n'          # no way to tell
        "\n", encoding="utf-8")
    c = data.load_callagy(tmp_path)
    assert c["file"] == "new.csv"                      # the newest export wins
    assert c["byState"] == {"NJ": 2, "FL": 1}
    assert c["unplaced"] == ["22-cv-83"] and c["total"] == 4
    assert c["byInsurer"] == {"Aetna (CVS Health)": {"NJ": 1}, "Cigna": {"NJ": 1}, "UnitedHealth Group": {"FL": 1}}
