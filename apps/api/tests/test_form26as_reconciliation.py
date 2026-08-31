"""
Form 26AS reconciliation — the matching engine and the summary it produces.

WHAT WAS WRONG BEFORE (all four established from the code, not from a note):

  1. WRONG POPULATION. The books side read `tds_deductions` — tax the client
     DEDUCTED FROM ITS OWN VENDORS. Form 26AS lists tax OTHERS deducted out of
     payments made TO the client. Opposite directions of TDS: the client's own
     deductions appear in each vendor's 26AS, never in the client's.

  2. IMPOSSIBLE JOIN. The lookup was built keyed on `deductee_pan` and read back
     by `deductor_tan`. A PAN is 5 alpha + 4 numeric + 1 alpha; a TAN is 4 alpha
     + 5 numeric + 1 alpha, and is not derivable from a PAN. No row could match,
     so every 26AS entry was reported missing from the books.

  3. WRONG COLUMN. It summed `tds_amount_paise` off those rows. The column on
     tds_deductions is `tds_paise`, so every book amount read as 0 — which would
     have made even a corrected join produce a 100% variance.

  4. SELF-CONFIRMING TOTAL. `total_books_paise` accumulated only inside the
     match branch, so the "books total" was the MATCHED-books total and the
     variance agreed with itself by construction.

  and one more the audit note did not record:

  5. THE BOOKS→26AS DIRECTION WAS ABSENT. The loop only ever iterated 26AS, so a
     credit the books claim that no deductor reported — the thing that actually
     gets disallowed, Rule 37BA(1) — could not be reported at all.

IT Act references: s.285BB with Rule 114-I (26AS itself; s.203AA was omitted by
the Finance Act 2020 w.e.f. 01-06-2020), s.199(1) and Rule 37BA(1) (whose
information the credit rests on), s.205 (bar against direct demand).
"""
from __future__ import annotations

import pytest

from domain.income_tax import form26as_matcher as m
import domain.income_tax.form26as_service as svc


# ── Identity normalisation ─────────────────────────────────────────────────────

def test_tan_and_pan_are_different_formats_and_never_normalise_to_each_other():
    """Defect 2, at its root: the two identifiers cannot collide."""
    tan = "MUMA12345B"
    pan = "ABCDE1234F"
    assert m.normalise_tan(tan) == tan
    assert m.normalise_pan(pan) == pan
    # A PAN is not a TAN and a TAN is not a PAN — each is rejected by the other.
    assert m.normalise_tan(pan) is None
    assert m.normalise_pan(tan) is None


def test_a_malformed_tan_is_absent_not_a_matchable_key():
    """Two rows carrying the same typo must not match each other on it."""
    assert m.normalise_tan("MUM12345B") is None      # only 3 leading letters
    assert m.normalise_tan("") is None
    assert m.normalise_tan(None) is None


def test_tan_normalisation_survives_case_and_punctuation():
    assert m.normalise_tan(" muma-12345 b ") == "MUMA12345B"


def test_name_normalisation_expands_abbreviations_but_keeps_the_legal_form():
    """"Acme Pvt Ltd" and "ACME PRIVATE LIMITED" are one deductor..."""
    assert m.normalise_name("Acme Pvt. Ltd.") == m.normalise_name("ACME PRIVATE LIMITED")


def test_name_normalisation_does_not_merge_different_legal_persons():
    """...but a private limited company and an LLP are two, with two TANs."""
    assert m.normalise_name("Acme Pvt Ltd") != m.normalise_name("Acme LLP")


def test_a_blank_name_never_matches_a_blank_name():
    entry = m.Form26ASEntry("e1", 10000, deductor_name="", deductor_tan=None)
    credit = m.BookCredit("c1", 10000, deductor_name="")
    result = m.reconcile([entry], [credit])
    assert result.entry_outcomes[0].status == m.STATUS_MISSING_IN_BOOKS
    assert result.credit_outcomes[0].status == m.STATUS_NOT_IN_26AS


# ── Matching ───────────────────────────────────────────────────────────────────

def _entry(eid, paise, name="Acme Pvt Ltd", tan="MUMA12345B", date="2025-06-10", status="F"):
    return m.Form26ASEntry(eid, paise, deductor_name=name, deductor_tan=tan,
                           transaction_date=date, booking_status=status)


def _credit(cid, paise, name="Acme Pvt Ltd", tan="MUMA12345B", date="2025-06-10"):
    return m.BookCredit(cid, paise, deductor_name=name, deductor_tan=tan, credit_date=date)


def test_tan_and_amount_agreeing_is_a_clean_match():
    result = m.reconcile([_entry("e1", 10_000_00)], [_credit("c1", 10_000_00)])
    outcome = result.entry_outcomes[0]
    assert outcome.status == m.STATUS_MATCHED
    assert outcome.basis == m.BASIS_TAN
    assert outcome.needs_confirmation is False
    assert outcome.variance_paise == 0
    assert result.credit_outcomes[0].status == m.STATUS_MATCHED


def test_name_only_match_is_accepted_but_flagged_for_confirmation():
    """No TAN on the customer master is the common case, so refusing to match
    would be useless — but the CA has to be told the identity was a name."""
    entry = _entry("e1", 10_000_00, tan="MUMA12345B")
    credit = _credit("c1", 10_000_00, tan=None)
    result = m.reconcile([entry], [credit])
    outcome = result.entry_outcomes[0]
    assert outcome.status == m.STATUS_MATCHED
    assert outcome.basis == m.BASIS_NAME
    assert outcome.needs_confirmation is True
    assert result.needs_confirmation_count == 1


def test_same_tan_different_amount_is_a_variance_not_a_missing_row():
    result = m.reconcile([_entry("e1", 10_000_00)], [_credit("c1", 9_000_00)])
    outcome = result.entry_outcomes[0]
    assert outcome.status == m.STATUS_VARIANCE
    assert outcome.basis == m.BASIS_TAN
    assert outcome.variance_paise == 1_000_00       # signed: 26AS minus books
    assert "26AS higher" in outcome.reason


def test_variance_sign_points_the_other_way_when_the_books_are_higher():
    result = m.reconcile([_entry("e1", 9_000_00)], [_credit("c1", 10_000_00)])
    outcome = result.entry_outcomes[0]
    assert outcome.variance_paise == -1_000_00
    assert "books higher" in outcome.reason


def test_no_identity_agreement_is_never_matched_on_amount_alone():
    """The old engine picked the closest amount from a pool it built wrongly.
    Two unrelated deductors with the same TDS must NOT match."""
    entry = _entry("e1", 10_000_00, name="Acme Pvt Ltd", tan="MUMA12345B")
    credit = _credit("c1", 10_000_00, name="Zeta Traders", tan="DELZ99999X")
    result = m.reconcile([entry], [credit])
    assert result.entry_outcomes[0].status == m.STATUS_MISSING_IN_BOOKS
    assert result.credit_outcomes[0].status == m.STATUS_NOT_IN_26AS


def test_one_book_credit_cannot_be_claimed_by_two_26as_rows():
    """Two quarterly 26AS rows, one receipt. The second must not re-use it."""
    entries = [_entry("e1", 10_000_00, date="2025-06-10"),
               _entry("e2", 10_000_00, date="2025-09-10")]
    result = m.reconcile(entries, [_credit("c1", 10_000_00, date="2025-06-11")])
    statuses = {o.entry_id: o.status for o in result.entry_outcomes}
    assert statuses["e1"] == m.STATUS_MATCHED
    assert statuses["e2"] == m.STATUS_MISSING_IN_BOOKS
    matched_ids = [o.matched_credit_id for o in result.entry_outcomes if o.matched_credit_id]
    assert matched_ids == ["c1"]


def test_an_exact_amount_match_wins_over_a_variance_match_for_the_same_credit():
    """Pass ordering: the exact-amount passes run before any variance pass, so a
    row that differs on amount cannot take a credit another row matches exactly."""
    entries = [_entry("e_variance", 9_000_00, date="2025-05-01"),
               _entry("e_exact", 10_000_00, date="2025-12-01")]
    result = m.reconcile(entries, [_credit("c1", 10_000_00, date="2025-05-02")])
    by_id = {o.entry_id: o for o in result.entry_outcomes}
    assert by_id["e_exact"].status == m.STATUS_MATCHED
    assert by_id["e_exact"].matched_credit_id == "c1"
    assert by_id["e_variance"].status == m.STATUS_MISSING_IN_BOOKS


def test_the_nearest_dated_credit_wins_when_several_qualify():
    entry = _entry("e1", 10_000_00, date="2025-09-10")
    credits = [_credit("c_far", 10_000_00, date="2025-04-01"),
               _credit("c_near", 10_000_00, date="2025-09-12")]
    result = m.reconcile([entry], credits)
    assert result.entry_outcomes[0].matched_credit_id == "c_near"


def test_tolerance_is_zero_by_default_and_is_honoured_when_set():
    entry, credit = _entry("e1", 10_000_00), _credit("c1", 9_999_00)
    assert m.reconcile([entry], [credit]).mismatch_count == 1
    assert m.reconcile([entry], [credit], tolerance_paise=100).matched_count == 1


# ── The books → 26AS direction (defect 5) ──────────────────────────────────────

def test_a_book_credit_no_deductor_reported_is_surfaced_and_priced():
    """Rule 37BA(1) gives credit on the deductor's information. A credit the
    books claim that 26AS does not carry is not claimable until the deductor
    corrects their statement — the figure a CA needs before filing."""
    credits = [_credit("c1", 10_000_00), _credit("c_orphan", 7_000_00,
                                                 name="Delta Consulting", tan="BLRD22222Y")]
    result = m.reconcile([_entry("e1", 10_000_00)], credits)
    assert result.not_in_26as_count == 1
    assert m.unsupported_credit_paise(result, credits) == 7_000_00
    orphan = next(o for o in result.credit_outcomes if o.credit_id == "c_orphan")
    assert "Rule 37BA(1)" in orphan.reason


# ── Totals (defect 4) ──────────────────────────────────────────────────────────

def test_totals_cover_the_whole_of_both_populations_not_the_matched_subset():
    entries = [_entry("e1", 10_000_00), _entry("e2", 3_000_00,
                                               name="Gamma Traders", tan="CHEG11111Z")]
    credits = [_credit("c1", 10_000_00), _credit("c2", 7_000_00,
                                                 name="Delta Consulting", tan="BLRD22222Y")]
    result = m.reconcile(entries, credits)
    assert result.matched_count == 1                     # only Acme lines up
    assert result.total_26as_paise == 13_000_00          # both 26AS rows
    assert result.total_books_paise == 17_000_00         # both book credits
    assert result.net_variance_paise == -4_000_00
    assert result.variance_paise == 4_000_00


# ── Booking status (s.205) ─────────────────────────────────────────────────────

def test_only_booking_status_F_is_a_settled_credit():
    entries = [_entry("e_final", 10_000_00, status="F"),
               _entry("e_unmatched", 5_000_00, name="Beta LLP", tan="DELB98765C", status="U"),
               _entry("e_provisional", 2_000_00, name="Gov Dept", tan="CHEG11111Z", status="P")]
    assert m.provisional_credit_paise(entries) == 7_000_00


def test_a_blank_booking_status_is_not_assumed_final():
    """26AS text pasted without the status column is missing the information.
    Reading absence as 'settled' fails in the optimistic direction."""
    assert m.provisional_credit_paise([_entry("e1", 10_000_00, status=None)]) == 10_000_00


# ── Deductor rollup ────────────────────────────────────────────────────────────

def test_the_deductor_rollup_shows_a_total_that_agrees_when_the_lines_do_not():
    """The common real outcome: quarterly 26AS rows against monthly receipts."""
    entries = [_entry("e1", 6_000_00, date="2025-06-30"),
               _entry("e2", 6_000_00, date="2025-09-30")]
    credits = [_credit("c1", 4_000_00, date="2025-05-15"),
               _credit("c2", 4_000_00, date="2025-07-15"),
               _credit("c3", 4_000_00, date="2025-08-15")]
    result = m.reconcile(entries, credits)
    acme = next(d for d in result.by_deductor if d.tan == "MUMA12345B")
    assert acme.entry_count == 2 and acme.credit_count == 3
    assert acme.total_26as_paise == 12_000_00
    assert acme.total_books_paise == 12_000_00
    assert acme.variance_paise == 0                      # the total agrees...
    assert result.matched_count == 0                     # ...while no line does


# ── The service layer ──────────────────────────────────────────────────────────

@pytest.fixture
def seeded():
    svc._MOCK_UPLOADS.clear()
    svc._MOCK_RECORDS.clear()
    svc._MOCK_RECONS.clear()
    svc._MOCK_BOOK_CREDITS.clear()
    svc._MOCK_GL_CONTROL.clear()
    upload = svc.create_upload("f1", "c1", "2025-26", "u1")
    records = svc.parse_26as_text(
        "PART A\n"
        "Sr.\tName of Deductor\tTAN\tDate\tAmount Paid\tTDS\tStatus\n"
        "1\tAcme Pvt Ltd\tMUMA12345B\t10/06/2025\t100000.00\t10000.00\tF\n"
        "2\tBeta Services LLP\tDELB98765C\t12/09/2025\t50000.00\t5000.00\tU\n"
        "3\tGamma Traders\tCHEG11111Z\t01/01/2026\t20000.00\t2000.00\tF\n"
    )
    svc.save_parsed_records("f1", upload["id"], "c1", "2025-26", records)
    svc.seed_mock_books("f1", "c1", "2025-26", [
        {"credit_id": "r1", "tds_paise": 10_000_00, "deductor_name": "ACME PRIVATE LIMITED",
         "deductor_tan": "MUMA12345B", "credit_date": "2025-06-11"},
        {"credit_id": "r2", "tds_paise": 4_000_00, "deductor_name": "Beta Services LLP",
         "deductor_tan": None, "credit_date": "2025-09-12"},
        {"credit_id": "r3", "tds_paise": 7_000_00, "deductor_name": "Delta Consulting",
         "deductor_tan": "BLRD22222Y", "credit_date": "2025-12-01"},
    ], gl_control_paise=21_000_00)
    return upload


def test_mock_mode_runs_the_real_engine(seeded):
    """The previous mock branch returned a hardcoded 'everything is missing from
    the books' whatever the input — a different answer from production's, and
    the reason none of this logic was testable."""
    result = svc.run_reconciliation("f1", "c1", seeded["id"], "2025-26", "u1")
    assert result["matched_count"] == 1                  # Acme, on TAN
    assert result["mismatch_count"] == 1                 # Beta, name match, ₹1,000 short
    assert result["missing_in_books_count"] == 1         # Gamma
    assert result["not_in_26as_count"] == 1              # Delta
    assert result["needs_confirmation_count"] == 1       # Beta matched on name only


def test_the_summary_prices_the_unclaimable_credit(seeded):
    result = svc.run_reconciliation("f1", "c1", seeded["id"], "2025-26", "u1")
    assert result["unsupported_credit_paise"] == 7_000_00
    assert result["provisional_credit_paise"] == 5_000_00     # Beta's status is 'U'


def test_the_summary_totals_are_over_both_full_populations(seeded):
    result = svc.run_reconciliation("f1", "c1", seeded["id"], "2025-26", "u1")
    assert result["total_tds_26as_paise"] == 17_000_00        # 10,000 + 5,000 + 2,000
    assert result["total_tds_books_paise"] == 21_000_00       # 10,000 + 4,000 + 7,000
    assert result["variance_paise"] == 4_000_00
    assert result["net_variance_paise"] == -4_000_00


def test_the_ledger_control_total_catches_credits_outside_the_receipt_population(seeded):
    """A manual journal straight to TDS Receivable is not a receipt. Without the
    tie-out it would sit outside the reconciliation with the summary still
    claiming to cover the books."""
    svc._MOCK_GL_CONTROL[("f1", "c1", "2025-26")] = 25_000_00
    result = svc.run_reconciliation("f1", "c1", seeded["id"], "2025-26", "u1")
    assert result["gl_control_paise"] == 25_000_00
    assert result["unreconciled_gl_paise"] == 4_000_00


def test_every_summary_row_records_which_books_population_it_read(seeded):
    """NULL identifies a row produced by the pre-291 comparison against
    tds_deductions, which was the wrong direction of TDS entirely."""
    result = svc.run_reconciliation("f1", "c1", seeded["id"], "2025-26", "u1")
    assert result["books_source"] == svc.BOOKS_SOURCE == "receipts.tds_paise"


def test_each_26as_record_records_how_it_matched(seeded):
    svc.run_reconciliation("f1", "c1", seeded["id"], "2025-26", "u1")
    rows = {r["deductor_name"]: r for r in svc._MOCK_RECORDS[seeded["id"]]}
    assert rows["Acme Pvt Ltd"]["reconciliation_status"] == "matched"
    assert rows["Acme Pvt Ltd"]["match_basis"] == "tan"
    assert rows["Acme Pvt Ltd"]["matched_receipt_id"] == "r1"
    assert rows["Beta Services LLP"]["match_basis"] == "name"
    assert rows["Beta Services LLP"]["variance_paise"] == 1_000_00
    assert rows["Gamma Traders"]["match_basis"] is None


def test_any_unsupported_credit_raises_an_insight_however_small(seeded):
    """Not a threshold question: credit the deductor never reported is not
    claimable under Rule 37BA(1) whatever its size."""
    assert svc._ai_insight_due(total_26as_paise=1_00_00_000, variance_paise=0,
                               unsupported_paise=1) is True


def test_the_variance_threshold_is_evaluated_in_integers():
    """1% of ₹10,00,000 is ₹10,000 — the threshold is exceeded above it, not at
    it, and no division by zero needs a separate guard."""
    assert svc._ai_insight_due(10_00_000_00, 10_000_00, 0) is False
    assert svc._ai_insight_due(10_00_000_00, 10_000_01, 0) is True
    assert svc._ai_insight_due(0, 0, 0) is False


def test_the_financial_year_window_is_april_to_march():
    assert svc._fy_window("2025-26") == ("2025-04-01", "2026-03-31")


def test_the_ledger_buckets_read_are_the_twelve_months_of_that_year():
    months = svc._fy_month_firsts("2025-26")
    assert len(months) == 12
    assert months[0] == "2025-04-01" and months[-1] == "2026-03-01"


# ── The shared table (found by grepping for the same pattern elsewhere) ────────

def test_the_26as_upload_list_excludes_the_tds_workspace_rows(seeded):
    """`form_26as_uploads` is written by two different features.

    `POST /api/form-26as/uploads` is the client's OWN 26AS — upload, parse,
    reconcile. `POST /api/tds-workspace/form26as/upload` is the caller-supplied
    deductor-side comparison: it posts both sides itself, reads nothing from the
    database, and has no parse step. It writes a row here and never sets
    parse_status, which defaults to 'pending' (migration 234) — so its rows
    appeared in the 26AS page's Upload History as spinners that never resolved,
    over "0 records". `source` (migration 291) separates them.
    """
    svc._MOCK_UPLOADS["foreign"] = {
        "id": "foreign", "firm_id": "f1", "client_id": "c1",
        "financial_year": "2025-26", "parse_status": "pending",
        "total_records": 0, "source": "tds_workspace",
    }
    listed = svc.list_uploads("f1", "c1", "2025-26")
    assert [u["id"] for u in listed] == [seeded["id"]]


def test_an_upload_this_module_creates_is_stamped_with_its_own_source(seeded):
    assert svc._MOCK_UPLOADS[seeded["id"]]["source"] == svc.UPLOAD_SOURCE
    assert svc.UPLOAD_SOURCE == "form_26as_pipeline"


# ── The live-database shape (found when migration 291 failed in production) ───

class _CapturingTable:
    """Minimal PostgREST stand-in that records the row an insert was given."""

    def __init__(self, sink):
        self._sink = sink

    def insert(self, row):
        self._sink.append(row)
        return self

    def execute(self):
        return type("Res", (), {"data": []})()


class _CapturingClient:
    def __init__(self):
        self.rows: list[dict] = []

    def table(self, name):
        assert name == "form_26as_uploads"
        return _CapturingTable(self.rows)


def test_the_upload_insert_names_both_identity_columns(monkeypatch):
    """form_26as_uploads' shape diverged between the repo and the live database.

    Migration 052 declares `created_by` and no `uploaded_by`. Production has
    `uploaded_by` NOT NULL and no `created_by`. The CI template is built from
    the migrations, so every local run and every column check only ever saw the
    052 shape — while the live table has always been the other one, and nothing
    compared them.

    That is not cosmetic: this insert named `created_by` alone, so on the live
    database it violated a NOT NULL on a column the code did not know existed.
    `form_26as_uploads` holds zero rows in production as a result. Migration 291
    adds whichever column each side is missing, nullable, and the insert now
    names both — which is what this test pins, so neither is tidied away.
    """
    client = _CapturingClient()
    monkeypatch.setattr(svc, "_USE_MOCK", False)
    monkeypatch.setattr(svc, "_supabase", lambda: client)

    svc.create_upload("f1", "c1", "2025-26", "user-1")

    assert len(client.rows) == 1
    row = client.rows[0]
    assert row["uploaded_by"] == "user-1"
    assert row["created_by"] == "user-1"
    assert row["source"] == svc.UPLOAD_SOURCE


def test_mock_mode_builds_the_same_identity_columns_as_production(seeded):
    """Mock mode must not be the only place the row looks right."""
    row = svc._MOCK_UPLOADS[seeded["id"]]
    assert row["uploaded_by"] == "u1"
    assert row["created_by"] == "u1"
