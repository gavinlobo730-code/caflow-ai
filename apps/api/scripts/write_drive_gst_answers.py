"""Write the GST answers the browser drive's stub serves, from the real builders.

The money-editor drive (`apps/web/scripts/driveMoneyEditors.mjs`) opens the GSTR-1 and GSTR-3B screens against a stub. Its
answers to `POST /api/gst/gstr1/from-books`, `POST /api/gst/gstr3b/from-books` and the filing's `PATCH .../status` used to be
hand-typed copies with parts left out (the amendments block, the credit ledger and set-off workings, the compliance
calendar's answer), so those screens were driven in a lighter layout than the one a CA sees (POST-A-396). This writes
`apps/web/scripts/drive/gst-answers.json` from the builders themselves, run over the in-memory books of
`tests/test_gst_return_reconciliation.py` with one issued invoice and one received bill in September 2026, and the routes'
own additions (the amendments block `routers/gst._with_outstanding_amendments` folds in, and the compliance calendar's
answer `services/gst_return_closes_obligation.close_for_filed_return` gives when no obligation is on the calendar).
A scenario may override a figure; the SHAPE is the routes'. `tests/test_the_drives_gst_answers_have_the_routes_shape.py`
fails when the two differ; rerun this from `apps/api` to bring the file back:

    APP_ENV=development python3 scripts/write_drive_gst_answers.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

API = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))
os.environ.setdefault("APP_ENV", "development")

FIXTURE = API.parent / "web" / "scripts" / "drive" / "gst-answers.json"

FIRM = "FIRM-A"
CLIENT = "CLI"
GSTIN = "27AAACA1234A1ZK"   # the drive's client (scripts/drive/scenarios/dates.mjs GSTIN_OF_THE_CLIENT)
PERIOD = "092026"           # the month the drive's GST openers build (the clock is pinned at 8 October 2026)


def real_answers(monkeypatch) -> dict:
    """The four answers, computed over a fresh in-memory book. `monkeypatch` is pytest's (a test passes its own)."""
    import routers.gst as gst
    import services.gst_return_service as grs
    from services import gst_return_closes_obligation as closes
    from tests import test_gst_return_reconciliation as rec

    monkeypatch.setattr(rec, "GSTIN", GSTIN)
    db = rec._setup(monkeypatch)
    rec._issue_invoice(db, "INV-0001", 1000000, 90000, 90000, date="2026-09-10")
    rec._receive_bill(db, "GS/2026/114", 500000, date="2026-09-12")
    g3 = grs.gstr3b_from_books(db, FIRM, CLIENT, PERIOD, GSTIN)
    g1 = grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD, GSTIN)
    payload, block = gst._with_outstanding_amendments(db, FIRM, CLIENT, PERIOD, g1)
    g1 = {**g1, "payload": payload, "amendments": block}
    # The client GST tab's openers file August as well as September, so the calendar's answer is kept for both months.
    obligation = {
        kind: {month: closes.close_for_filed_return(
            db, firm_id=FIRM, client_id=CLIENT, obligation_type=kind, period=month, frequency="monthly",
            filed_date="2026-10-07", arn=None, actor=None, may_write_compliance=True) for month in ("082026", PERIOD)}
        for kind in ("GSTR1", "GSTR3B")
    }
    return {"gstr1_from_books": g1, "gstr3b_from_books": g3,
            "gstr1_submitted_obligation": obligation["GSTR1"], "gstr3b_submitted_obligation": obligation["GSTR3B"]}


def main() -> None:
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        answers = real_answers(mp)
    finally:
        mp.undo()
    FIXTURE.write_text(json.dumps(answers, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(API.parents[1])}")


if __name__ == "__main__":
    main()
