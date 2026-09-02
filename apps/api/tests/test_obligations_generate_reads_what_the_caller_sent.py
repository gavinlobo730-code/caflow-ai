"""
POST /api/compliance/obligations/generate has to use the financial year the
caller asked for, or say why it will not.

WHAT WAS WRONG
    Two silences, both of which produce a confident wrong answer.

    1. client_id and financial_year were QUERY parameters only. A caller that
       sent them in the JSON body — the natural shape for a POST, and what the
       foreign-vendor walkthrough sent — had them ignored, and generated the
       CURRENT year's obligations for the WHOLE FIRM. The response names the
       FY it used, which reads as confirmation rather than as a correction.

    2. The label was never validated. generate_due does
       `financial_year or _current_fy()`, and the FY is then read by a prefix
       parse that takes the first four characters. So '2026-28' generated FY
       2026-27's due dates under a label naming a year that does not exist,
       and 'garbage' raised ValueError out of the domain layer and reached the
       CA as a 500.

    Obligations are the due dates a CA plans a year around. Generating the
    wrong year's, silently, is worse than refusing.
"""
import pytest
from fastapi.testclient import TestClient

from main import app
from core.ist_clock import normalise_fy_label, ist_fy_label

pytestmark = pytest.mark.usefixtures("dev_header_auth")

client = TestClient(app)
HEADERS = {"X-User-Role": "partner", "X-Firm-Id": "firm-001", "X-User-Id": "user-001"}
URL = "/api/compliance/obligations/generate"


# ── The label validator ──────────────────────────────────────────────────────

@pytest.mark.parametrize("given,canonical", [
    ("2026-27", "2026-27"),
    ("2026-2027", "2026-27"),      # a CA writes both
    (" 2026-27 ", "2026-27"),
    ("1999-00", "1999-00"),        # the century turn still pairs
])
def test_a_label_that_unambiguously_names_a_year_is_accepted(given, canonical):
    assert normalise_fy_label(given) == canonical


@pytest.mark.parametrize("given", ["2026-28", "2026-99", "2026-26"])
def test_a_second_half_that_does_not_follow_the_first_is_refused(given):
    """This is the near-miss a prefix parse cannot see: it reads 2026, ignores
    the rest, and generates FY 2026-27 while the caller believes otherwise."""
    with pytest.raises(ValueError) as e:
        normalise_fy_label(given)
    assert "1 April to 31 March" in str(e.value)


@pytest.mark.parametrize("given", ["2026", "garbage", "", None, "26-27", "0000-01"])
def test_anything_that_is_not_a_financial_year_is_refused(given):
    with pytest.raises(ValueError):
        normalise_fy_label(given)


def test_the_current_label_is_one_this_accepts():
    """ist_fy_label is what generate_due falls back to. If the validator and
    the generator disagreed about the shape, the default would be unusable."""
    assert normalise_fy_label(ist_fy_label()) == ist_fy_label()


# ── The endpoint ─────────────────────────────────────────────────────────────

def test_the_financial_year_in_the_body_is_used():
    res = client.post(URL, headers=HEADERS, json={"financial_year": "2024-25"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["financial_year"] == "2024-25"


def test_the_financial_year_in_the_query_is_still_used():
    res = client.post(URL + "?financial_year=2024-25", headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["financial_year"] == "2024-25"


def test_a_body_year_is_canonicalised_before_it_is_stored():
    res = client.post(URL, headers=HEADERS, json={"financial_year": "2024-2025"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["financial_year"] == "2024-25", (
        "the obligations carry this label; two spellings of one year would "
        "read as two years")


def test_no_year_at_all_still_means_the_current_one():
    res = client.post(URL, headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["financial_year"] == ist_fy_label()


@pytest.mark.parametrize("bad", ["2026-28", "2026", "garbage"])
def test_a_bad_label_in_the_body_is_refused_not_guessed(bad):
    res = client.post(URL, headers=HEADERS, json={"financial_year": bad})
    assert res.status_code == 422, res.text
    assert "financial_year" in res.json()["detail"]


@pytest.mark.parametrize("bad", ["2026-28", "2026", "garbage"])
def test_a_bad_label_in_the_query_is_refused_the_same_way(bad):
    res = client.post(f"{URL}?financial_year={bad}", headers=HEADERS)
    assert res.status_code == 422, res.text
    assert "financial_year" in res.json()["detail"]


def test_sending_two_different_years_is_a_bug_and_says_so():
    """Preferring one silently is the same failure in a new place — the caller
    asked two questions and got an answer to one without being told which."""
    res = client.post(URL + "?financial_year=2024-25", headers=HEADERS,
                      json={"financial_year": "2025-26"})
    assert res.status_code == 422
    assert "sent twice" in res.json()["detail"]


def test_sending_the_same_year_twice_is_not_an_error():
    res = client.post(URL + "?financial_year=2024-25", headers=HEADERS,
                      json={"financial_year": "2024-25"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["financial_year"] == "2024-25"


def test_a_client_id_in_the_body_is_scope_checked_like_one_in_the_query():
    """The body path must not be a way around assert_client_access. Naming
    another firm's client has to fail whichever way it is named."""
    other = "client-belonging-to-nobody-here"
    q = client.post(f"{URL}?client_id={other}", headers=HEADERS)
    b = client.post(URL, headers=HEADERS, json={"client_id": other})
    assert b.status_code == q.status_code, (
        f"query said {q.status_code}, body said {b.status_code} — the body "
        f"path skipped a check the query path makes")
