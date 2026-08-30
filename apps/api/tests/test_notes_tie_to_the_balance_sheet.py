"""
A sub-schedule must agree with the figure it supports.

A note that does not tie to the face of the Balance Sheet is worse than no
note: it is a second, contradictory number over the same signature, and
whichever one the reader believes, the other is in the same document saying
otherwise.

It matters most for Fixed Assets. That is the only auto note struck from a
source INDEPENDENT of the ledger — the asset register — so the two can
genuinely drift: an asset entered in the register but never posted, or posted
but never registered, and the Balance Sheet and the note disagree with nothing
anywhere saying so. Share Capital and Borrowings are read from the ledger
through the same engine the Balance Sheet uses, so they tie by construction;
they are checked anyway so a later refactor cannot quietly break that.

The difference is REPORTED, never reconciled. Nothing here knows which side is
right — the two failure modes above produce the same difference with opposite
fixes — so adopting either number would hide the discrepancy that is the point
of checking.
"""
import pytest

import routers.year_end_notes as yen


# ── The check itself ─────────────────────────────────────────────────────────

def test_a_note_that_agrees_ties():
    tie = yen._tie_to_balance_sheet(50_000_00, {"share_capital": 50_000_00}, "share_capital")
    assert tie["checked"] is True
    assert tie["ties"] is True
    assert tie["difference_paise"] == 0
    assert "agrees with" in yen._tie_out_sentence(tie, "Share Capital")


def test_a_note_that_disagrees_says_so_in_the_note_itself():
    """Not buried in note_data — on the face of the note a CA reads."""
    tie = yen._tie_to_balance_sheet(60_000_00, {"share_capital": 50_000_00}, "share_capital")
    assert tie["ties"] is False
    assert tie["difference_paise"] == 10_000_00
    sentence = yen._tie_out_sentence(tie, "Share Capital")
    assert "DOES NOT AGREE" in sentence
    assert "1000000 paise" in sentence
    assert "more than" in sentence
    assert "must be resolved before these statements are issued" in sentence


def test_the_direction_of_the_difference_is_stated():
    """"Out by 10,000" does not tell a CA which way to look."""
    under = yen._tie_to_balance_sheet(40_000_00, {"share_capital": 50_000_00}, "share_capital")
    assert "less than" in yen._tie_out_sentence(under, "Share Capital")


def test_a_note_spanning_several_schedule_lines_is_summed():
    """A fixed asset register does not distinguish tangible from intangible
    from capital work-in-progress, so its carrying amount supports the three
    together. Comparing it against tangible_assets alone would report a
    difference that is really just the other two lines."""
    gl = {"tangible_assets": 60_000_00, "intangible_assets": 30_000_00,
          "capital_wip": 10_000_00}
    tie = yen._tie_to_balance_sheet(
        100_000_00, gl, "tangible_assets", "intangible_assets", "capital_wip")
    assert tie["balance_sheet_paise"] == 100_000_00
    assert tie["ties"] is True


def test_an_unavailable_ledger_is_not_taken_for_agreement():
    """gl is None when the books do not balance yet. Treating a missing
    comparison as a passing one would print "agrees with the Balance Sheet"
    over a check that never ran."""
    tie = yen._tie_to_balance_sheet(50_000_00, None, "share_capital")
    assert tie["checked"] is False
    assert tie.get("ties") is not True
    assert "could not be checked" in yen._tie_out_sentence(tie, "Share Capital")


def test_a_missing_note_total_is_not_taken_for_agreement():
    tie = yen._tie_to_balance_sheet(None, {"share_capital": 50_000_00}, "share_capital")
    assert tie["checked"] is False


def test_a_schedule_line_absent_from_the_ledger_counts_as_nil_not_as_agreement():
    """An unmapped or unused line is genuinely nil on the Balance Sheet, so a
    note carrying a figure against it does NOT tie."""
    tie = yen._tie_to_balance_sheet(25_000_00, {"share_capital": 0}, "long_term_borrowings")
    assert tie["balance_sheet_paise"] == 0
    assert tie["ties"] is False


# ── Wired into the generated notes ───────────────────────────────────────────

def _notes(monkeypatch, fa_net_block, gl):
    """Generate the note set with a chosen register total and ledger."""
    monkeypatch.setattr(yen, "_compute_fixed_assets_note_data",
                        lambda *a, **k: {"gross_block_paise": fa_net_block,
                                         "accumulated_dep_paise": 0,
                                         "net_block_paise": fa_net_block,
                                         "depreciation_charge_paise": 0,
                                         "note_type": "fixed_assets",
                                         "is_auto_generated": True})
    monkeypatch.setattr(yen, "_compute_gl_schedule_balances", lambda *a, **k: gl)
    monkeypatch.setattr(yen, "_compute_accounting_policies_data",
                        lambda *a, **k: {"ca_input_required": [], "requires_ca_review": True})
    eng = {"financial_year": "2024-25", "client_id": "C1",
           "fy_start": "2024-04-01", "fy_end": "2025-03-31"}
    computed = {
        "accounting_policies": yen._compute_accounting_policies_data(None, "F", "C1", None),
        "fixed_assets": yen._compute_fixed_assets_note_data(None, "F", "C1", None),
        "gl_balances": yen._compute_gl_schedule_balances(None, "F", "C1", None, None),
    }
    return {t: yen._generate_note_content(t, eng, computed)
            for t in ("fixed_assets", "share_capital", "loans")}


def test_a_register_that_agrees_with_the_ledger_says_so(monkeypatch):
    gl = {"tangible_assets": 80_000_00, "intangible_assets": 0, "capital_wip": 0,
          "share_capital": 100_000_00, "long_term_borrowings": 0,
          "short_term_borrowings": 0}
    notes = _notes(monkeypatch, 80_000_00, gl)
    fa = notes["fixed_assets"]
    assert fa["note_data"]["ties_to_balance_sheet"]["ties"] is True
    assert "agrees with" in fa["content"]


def test_a_register_that_has_drifted_from_the_ledger_is_reported(monkeypatch):
    """The case this exists for: an asset in the register that was never
    posted, or posted and never registered. Both leave the Balance Sheet and
    the Fixed Assets note disagreeing, and nothing said so."""
    gl = {"tangible_assets": 80_000_00, "intangible_assets": 0, "capital_wip": 0,
          "share_capital": 100_000_00, "long_term_borrowings": 0,
          "short_term_borrowings": 0}
    notes = _notes(monkeypatch, 95_000_00, gl)          # register 15,000 higher
    tie = notes["fixed_assets"]["note_data"]["ties_to_balance_sheet"]
    assert tie["ties"] is False
    assert tie["difference_paise"] == 15_000_00
    assert "DOES NOT AGREE" in notes["fixed_assets"]["content"]


def test_borrowings_are_checked_against_both_borrowing_lines(monkeypatch):
    gl = {"tangible_assets": 0, "intangible_assets": 0, "capital_wip": 0,
          "share_capital": 0,
          "long_term_borrowings": 30_000_00, "short_term_borrowings": 20_000_00}
    tie = _notes(monkeypatch, 0, gl)["loans"]["note_data"]["ties_to_balance_sheet"]
    assert tie["balance_sheet_paise"] == 50_000_00
    assert tie["ties"] is True


def test_every_figure_bearing_auto_note_carries_a_tie_out(monkeypatch):
    """Adding a note with figures and no tie-out is the regression this
    guards: the next one should not silently skip the check."""
    gl = {"tangible_assets": 0, "intangible_assets": 0, "capital_wip": 0,
          "share_capital": 0, "long_term_borrowings": 0, "short_term_borrowings": 0}
    for note_type, note in _notes(monkeypatch, 0, gl).items():
        assert "ties_to_balance_sheet" in note["note_data"], note_type


def test_an_unavailable_ledger_does_not_claim_the_notes_tie(monkeypatch):
    notes = _notes(monkeypatch, 80_000_00, None)
    for note_type, note in notes.items():
        tie = note["note_data"]["ties_to_balance_sheet"]
        assert tie["checked"] is False, note_type
        assert "agrees with" not in note["content"], note_type


def test_the_register_is_checked_against_all_three_asset_lines_end_to_end(monkeypatch):
    """With intangibles and capital work-in-progress on the sheet, comparing
    the register against tangible_assets alone reports a difference that is
    really just the other two lines — a false finding sent to a CA, which
    costs more trust than a missed one."""
    gl = {"tangible_assets": 60_000_00, "intangible_assets": 25_000_00,
          "capital_wip": 15_000_00, "share_capital": 0,
          "long_term_borrowings": 0, "short_term_borrowings": 0}
    notes = _notes(monkeypatch, 100_000_00, gl)          # register == 60+25+15
    tie = notes["fixed_assets"]["note_data"]["ties_to_balance_sheet"]
    assert tie["balance_sheet_paise"] == 100_000_00
    assert tie["ties"] is True, (
        "the register was compared against only part of the fixed-asset lines"
    )
    assert "DOES NOT AGREE" not in notes["fixed_assets"]["content"]
