"""The seeder's GST-returns stage carries on past a finding about the product and stops for a run that cannot succeed.

WHAT WAS WRONG
    The stage that files the seeded returns caught every `SystemExit` from the HTTP client as "a finding about the
    product" and went on. That is right for a 422 on one month the engine will not build and wrong for everything that
    means the next call fails too: an expired login (401), a missing permission (403), a rate limit (429) or a server
    error (5xx) came out as twenty-two lines of "refused" and an exit code of 0, with the failures buried in a printed
    list. A call that got no answer in time (`URLError`, `TimeoutError`) was not caught at all and killed the run after
    every document was written, and the seeder cannot resume (it refuses to run into a firm that has clients).
    The due dates were also restated in the script, and a QRMP client's GSTR-3B (due the 22nd or the 24th by STATE,
    Rule 61A) was recorded filed on the 24th for a Maharashtra registration, two days late; and the build was given
    the filing date for a quarter although Table 5.1's interest takes the MONTHLY due date for any period key, so a
    quarter filed on time would have been saved claiming months of interest.

WHAT IS HELD
    * a refusal that is a finding (400, 409, 422, the workspace's own 200 with success false, the engine's validation
      errors) is reported, counted, and the next return is still tried;
    * 401, 403, 429 and every 5xx stop the run; a call with no answer is reported as such, saying the server may have
      saved the return;
    * the run exits non-zero when any return was not filed;
    * a window whose filing date is still to come is skipped and counted, not left saved-and-approved but unfiled;
    * every filing date is the engine's due date for that registration's state (and a quarterly one is not late), the
      draft month and its quarter are not filed, a monthly 3B is built with its filing date and a quarterly one without.
"""
from __future__ import annotations

import importlib.util
import urllib.error
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.demo import fixture
from services.compliance_engine import MONTHLY, QUARTERLY, gstr1_due_date, gstr3b_due_date

_API_ROOT = Path(__file__).resolve().parents[1]


def _seeder():
    spec = importlib.util.spec_from_file_location("seed_demo_firm_returns", _API_ROOT / "scripts" / "seed_demo_firm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seeder = _seeder()

FY, LAST_MONTH = "2025-26", "2026-03"
MONTHLY_CLIENT = SimpleNamespace(name="Anand", gstin="27AABCA7412M1ZM", gst_filing_frequency="monthly")
QRMP_CLIENT = SimpleNamespace(name="Kavya", gstin="27AAGFK3159R1ZN", gst_filing_frequency="quarterly")


def _computed(body: dict) -> dict:
    return {
        "period": body["period"], "gstin": "27AAAAA0000A1Z5", "payload": {}, "summary": {}, "working": {},
        "validation_errors": [], "taxable_total_paise": 1, "total_igst_paise": 0, "total_cgst_paise": 1,
        "total_sgst_paise": 1, "total_cess_paise": 0, "tax_liability_paise": 2, "itc_claimed_paise": 0,
        "net_tax_paise": 2, "rcm_cash_paise": 0, "cash_payable_paise": 2, "credit_ledger": {},
    }


class FakeApi:
    """The seeder's client. `on` maps (method, path) to a function that may raise, called with the body."""

    def __init__(self, on=None, computed=_computed):
        self.on, self.computed, self.calls = on or {}, computed, []

    def _do(self, method, path, body):
        self.calls.append((method, path, body))
        hook = self.on.get((method, path))
        if hook:
            hook(body)
        if path.endswith("/from-books"):
            return {"success": True, "data": self.computed(body)}
        return {"success": True, "data": {"id": f"ret-{len(self.calls)}"}}

    def post(self, path, body):
        return self._do("POST", path, body)

    def patch(self, path, body):
        return self._do("PATCH", path, body)


def _written():
    return {"gstr1_filed": 0, "gstr3b_filed": 0, "returns_not_yet_due": 0, "returns_refused": []}


def _run(api, client=MONTHLY_CLIENT, written=None):
    written = written if written is not None else _written()
    seeder._gst_returns(api, client, "cid", FY, LAST_MONTH, written)
    return written


def _refusal(status, text="refused"):
    return seeder.ApiRefusal(f"\nPOST /x → HTTP {status}\n{text}\nNothing further was written.", status)


# ── what is a finding and what ends the run ─────────────────────────────────

@pytest.mark.parametrize("status", [400, 409, 422, 200])
def test_a_refusal_that_is_a_finding_is_reported_and_the_next_return_is_still_tried(status):
    seen = []

    def refuse_the_first_gstr1_build(body):
        if not seen:
            seen.append(body["period"])
            raise _refusal(status, "the engine will not build April")
    api = FakeApi({("POST", "/api/gst/gstr1/from-books"): refuse_the_first_gstr1_build})
    w = _run(api)
    assert len(w["returns_refused"]) == 1 and "GSTR-1" in w["returns_refused"][0] and seen[0] in w["returns_refused"][0]
    assert w["gstr1_filed"] == 10 and w["gstr3b_filed"] == 11, "one finding must not stop the other returns"


@pytest.mark.parametrize("status", [401, 403, 429, 500, 502, 503])
def test_an_answer_that_means_every_later_call_fails_too_stops_the_run(status):
    api = FakeApi({("POST", "/api/gst/gstr1/from-books"): lambda body: (_ for _ in ()).throw(_refusal(status))})
    with pytest.raises(seeder.ApiRefusal) as stop:
        _run(api)
    assert stop.value.status == status
    assert len(api.calls) == 1, "the run must stop at the first such answer, not list twenty-two of them"


@pytest.mark.parametrize("error", [TimeoutError("timed out"), urllib.error.URLError("connection reset")])
def test_a_call_with_no_answer_is_reported_as_that_and_says_the_return_may_have_been_saved(error):
    api = FakeApi({("PATCH", "/api/gst-workspace/gstr1/ret-2/status"): lambda body: (_ for _ in ()).throw(error)})
    w = _run(api)
    assert any("no answer" in m and "may have saved" in m for m in w["returns_refused"]), w["returns_refused"]


def test_validation_errors_from_the_engine_are_a_finding_not_a_filing():
    def computed(body):
        out = _computed(body)
        if body["period"] == "052025":
            out["validation_errors"] = ["B2B invoice INV-9 has no GSTIN"]
        return out
    w = _run(FakeApi(computed=computed))
    assert any("052025" in m and "validation errors" in m for m in w["returns_refused"])
    assert w["gstr1_filed"] == 10 and w["gstr3b_filed"] == 10


def test_a_refused_status_step_does_not_count_the_return_as_filed():
    api = FakeApi({("PATCH", "/api/gst-workspace/gstr3b/ret-7/status"): lambda body: (_ for _ in ()).throw(_refusal(422))})
    w = _run(api)
    assert len(w["returns_refused"]) == 1 and w["gstr3b_filed"] == 10


def test_main_exits_non_zero_when_any_return_was_not_filed(monkeypatch, capsys):
    argv = ["--api-url", "http://localhost:1", "--token", "t", "--confirm"]
    monkeypatch.setattr("sys.argv", ["seed_demo_firm.py", *argv])
    monkeypatch.setattr(seeder, "seed", lambda *a, **k: {**_written(), "returns_refused": ["Anand GSTR-1 042025: x"]})
    assert seeder.main() == 2
    assert "not filed" in capsys.readouterr().out
    monkeypatch.setattr(seeder, "seed", lambda *a, **k: _written())
    assert seeder.main() == 0


# ── a window not yet due ────────────────────────────────────────────────────

def test_a_return_whose_filing_date_is_still_to_come_is_skipped_and_counted(monkeypatch):
    import core.ist_clock
    monkeypatch.setattr(core.ist_clock, "ist_today", lambda: date(2025, 12, 15))
    api = FakeApi()
    w = _run(api)
    # Due: April..October's GSTR-1 (11th) and GSTR-3B (20th of the next month) have passed by 15 Dec; November's 3B is
    # the 20th of December, so November and everything after it is not yet due.
    assert w["gstr1_filed"] == w["gstr3b_filed"] == 7
    assert w["returns_not_yet_due"] == 4
    assert w["returns_refused"] == []
    # Not one status step carries a date after the (patched) today.
    dates = [b["filed_date"] for m, p, b in api.calls if m == "PATCH" and b["status"] == "submitted"]
    assert dates and max(dates) <= "2025-12-15"


# ── the dates are the engine's ──────────────────────────────────────────────

def _gst_clients():
    return [c for c in fixture.build(FY).clients if c.gstin]


def test_there_are_gst_clients_of_both_frequencies_to_check():
    freqs = {c.gst_filing_frequency for c in _gst_clients()}
    assert freqs >= {"monthly", "quarterly"}, freqs


def test_every_seeded_filing_date_is_the_engines_due_date_for_that_registrations_state():
    for c in _gst_clients():
        quarterly = c.gst_filing_frequency == "quarterly"
        frequency = QUARTERLY if quarterly else MONTHLY
        windows = seeder._return_windows(FY, quarterly, LAST_MONTH, c.gstin[:2])
        assert windows, c.name
        for key, _end, gstr1_on, gstr3b_on in windows:
            month, year = int(key[:2]), int(key[2:])
            assert gstr1_on == gstr1_due_date(year, month, frequency).isoformat(), (c.name, key)
            assert gstr3b_on == gstr3b_due_date(year, month, frequency, c.gstin[:2]).isoformat(), (c.name, key)


def test_a_quarterly_gstr3b_for_a_maharashtra_registration_is_filed_on_the_22nd_and_not_the_24th():
    """The regression: the 24th is a category-Y state's date (Rule 61A), and 27 is category X."""
    windows = seeder._return_windows(FY, True, LAST_MONTH, "27")
    assert [w[3] for w in windows] == ["2025-07-22", "2025-10-22", "2026-01-22"]
    assert [w[2] for w in windows] == ["2025-07-13", "2025-10-13", "2026-01-13"]


def test_an_unknown_state_gets_the_earlier_quarterly_date_as_the_engine_does():
    assert [w[3] for w in seeder._return_windows(FY, True, LAST_MONTH, None)] == \
        ["2025-07-22", "2025-10-22", "2026-01-22"]


def test_the_month_left_in_draft_and_its_quarter_are_not_filed():
    monthly = [w[0] for w in seeder._return_windows(FY, False, LAST_MONTH, "27")]
    quarterly = [w[0] for w in seeder._return_windows(FY, True, LAST_MONTH, "27")]
    assert len(monthly) == 11 and "032026" not in monthly
    assert quarterly == ["042025", "072025", "102025"], "the January-March quarter contains the draft month"


def test_a_monthly_gstr3b_is_built_with_its_filing_date_and_a_quarterly_one_without():
    monthly, quarterly = FakeApi(), FakeApi()
    _run(monthly, MONTHLY_CLIENT)
    _run(quarterly, QRMP_CLIENT)
    m3b = [b for m, p, b in monthly.calls if p == "/api/gst/gstr3b/from-books"]
    q3b = [b for m, p, b in quarterly.calls if p == "/api/gst/gstr3b/from-books"]
    assert len(m3b) == 11 and all("filed_on" in b for b in m3b)
    assert len(q3b) == 3 and not any("filed_on" in b for b in q3b), (
        "Table 5.1's interest takes the monthly due date for any period key, so a quarter built with a filing date "
        "would be saved claiming interest")
    assert not any("filed_on" in b for m, p, b in monthly.calls if p == "/api/gst/gstr1/from-books")
