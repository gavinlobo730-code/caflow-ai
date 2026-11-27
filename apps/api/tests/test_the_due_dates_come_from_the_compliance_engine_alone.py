"""
R3.1a — statutory rules-as-data registry consolidation (quick wins), following
the R3.1 re-scoping audit.

Capital-gains rate migration (itr_engine.py -> statutory_rates.py) is covered
by test_itr_engine.py/test_statutory_rates.py. This file covers the
due-date-calculation consolidations:
  - gst_workspace.py's GSTR-1/GSTR-3B due dates, which used to hand-roll their
    own next-month arithmetic instead of calling services/compliance_engine.py
    (the canonical source every other GST/TDS/ITR due date already used).
  - The Companies Act AOC-4/MGT-7/ADT-1 AGM-offset days, which used to be
    hardcoded independently in both compliance_obligation_service.py's
    _roc_obligations (AOC-4/MGT-7 only) and mca_workspace.py's /calendar
    endpoint (all three) -- now both read compliance_engine.MCA_AGM_OFFSET_DAYS
    via compliance_engine.mca_due_date().

DIR-3 KYC (30 Sep annually) has no backend implementation at all today (only
independent frontend copies) -- out of scope for this consolidation pass,
which only touches due dates that already existed in the backend.
"""
from datetime import date

from routers.gst_workspace import _gstr1_due_date, _gstr3b_due_date
from services.compliance_engine import mca_due_date, MCA_AGM_OFFSET_DAYS
from services.compliance_obligation_service import _roc_obligations


class TestGstr1Gstr3bDueDatesDelegateToComplianceEngine:
    def test_gstr1_due_11th_of_following_month(self):
        assert _gstr1_due_date("042026") == "2026-05-11"

    def test_gstr3b_due_20th_of_following_month(self):
        assert _gstr3b_due_date("042026") == "2026-05-20"

    def test_gstr1_december_period_rolls_to_january(self):
        assert _gstr1_due_date("122026") == "2027-01-11"

    def test_gstr3b_december_period_rolls_to_january(self):
        assert _gstr3b_due_date("122026") == "2027-01-20"


class TestMcaDueDatesShareOneOffsetTable:
    def test_offsets_match_companies_act_sections(self):
        assert MCA_AGM_OFFSET_DAYS == {"ADT-1": 15, "AOC-4": 30, "MGT-7": 60}

    def test_mca_due_date_adds_the_right_offset(self):
        agm = date(2026, 8, 15)
        assert mca_due_date(agm, "ADT-1") == date(2026, 8, 30)
        assert mca_due_date(agm, "AOC-4") == date(2026, 9, 14)
        assert mca_due_date(agm, "MGT-7") == date(2026, 10, 14)

    def test_roc_obligations_use_the_same_offsets(self):
        """compliance_obligation_service.py's tracked-obligation generator
        must agree with mca_workspace.py's /calendar endpoint -- both now
        read the same table, so this proves they can't drift again."""
        agm = "2026-08-15"
        specs = _roc_obligations("2025-26", agm_date=agm)
        by_type = {s["obligation_type"]: s["due_date"] for s in specs}
        assert by_type["MCA_AOC4"] == mca_due_date(date(2026, 8, 15), "AOC-4").isoformat()
        assert by_type["MCA_MGT7"] == mca_due_date(date(2026, 8, 15), "MGT-7").isoformat()
