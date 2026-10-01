"""A provider that is DOWN is not a statement that cannot be read (ai-04).

WHAT WAS WRONG
    The scanned-statement reader called Gemini with no timeout and no retry, and
    wrapped whatever it raised in "the statement could not be read from page N".
    Worse, the FIRST call — the totals probe — swallowed its failure by design
    ("a totals call that fails is not fatal"), so with the provider down and no
    balances typed the CA was told "this scan does not print its own totals": a
    false reason for an outage, and the classified failure the page reads would
    have given never appeared.

WHAT THIS ASSERTS
    A `ProviderFailed` from the vision door passes through both readers
    unwrapped and reaches the CA as the classified sentence with the status that
    goes with it (504 for a timeout) — and nothing is written. An ordinary
    exception from a model call is still wrapped as before, so the older rule
    ("the CA is not told which vendor") is untouched where it applies. And the
    call is attributed to the firm through the scope the router sets, which does
    not leak past the request.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from domain.ai import gateway
from domain.banking import vision
from tests.test_statement_vision import _Model, _scan_pdf, _setup, _upload, FIRM


def _timeout():
    return gateway.timeout_failure(gateway.GEMINI, 30)


def test_a_scan_whose_provider_times_out_is_the_classified_504_not_a_422(monkeypatch):
    db, model = _setup(monkeypatch, model=_Model(raises=_timeout()))
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
                opening=1_00_000_00, closing=1_30_000_00)
    assert e.value.status_code == 504
    assert "did not answer within 30 seconds" in str(e.value.detail)
    assert not db.rows("bank_transactions") and not db.rows("bank_statements")


def test_an_outage_is_not_reported_as_a_statement_that_prints_no_totals(monkeypatch):
    db, model = _setup(monkeypatch, model=_Model(raises=_timeout()))
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True)
    assert e.value.status_code == 504
    assert "does not print its own totals" not in str(e.value.detail)


def test_the_classified_failure_passes_through_both_readers_unwrapped():
    boom = _Model(raises=_timeout())
    with pytest.raises(gateway.ProviderFailed):
        vision.read_statement([b"p1"], call_model=boom)
    with pytest.raises(gateway.ProviderFailed):
        vision.read_printed_totals(b"p1", call_model=boom)


def test_an_ordinary_exception_is_still_wrapped_and_the_totals_probe_still_soft():
    """What the older tests pin, restated beside the new rule so neither moves the
    other: only the gateway's classified failure is let through."""
    ordinary = _Model(raises=RuntimeError("quota exceeded for project 42"))
    with pytest.raises(vision.StatementParseError):
        vision.read_statement([b"p1"], call_model=ordinary)
    assert vision.read_printed_totals(b"p1", call_model=ordinary) is None


def test_the_vision_call_is_attributed_to_the_firm_through_the_scope(monkeypatch):
    seen = []

    class _Spy(_Model):
        def __call__(self, *, image, mime, prompt):
            seen.append(gateway.current_scope())
            return super().__call__(image=image, mime=mime, prompt=prompt)

    _setup(monkeypatch, model=_Spy())
    _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
            opening=1_00_000_00, closing=1_30_000_00)
    assert seen, "the model was never called"
    assert all(s.firm_id == FIRM and s.user_id == "u-int-1" and s.feature == "statement_scan"
               for s in seen)
    assert gateway.current_scope().firm_id is None, "the scope must not leak past the request"
