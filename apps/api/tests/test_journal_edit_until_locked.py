"""
A posted journal entry may be corrected until the period closes — not before,
not after.

THE RULE THIS ENCODES
    Migration 251 made a posted entry absolutely immutable. That was stricter
    than Indian law. The proviso to Rule 3(1) of the Companies (Accounts) Rules
    2014, in force from 1 April 2023, requires accounting software to keep

        "an edit log of each change made in books of account along with the date
         when such changes were made"

    and to make that trail undisableable. It PRESUMES the books change; an edit
    log of an unchangeable ledger would be an empty file. Nothing in the
    Companies Act 2013 or the Income Tax Act 1961 forbids correcting a posted
    entry. Tally, the incumbent, allows exactly this.

    What ends the right to edit is a human act:

      * the CA locks the financial year, or
      * a return covering the period has been filed with the government — after
        which the document at the portal cannot be recalled, so the books behind
        it must stop moving too.

WHAT MUST NOT REGRESS
    account_period_balances is maintained by additive-only triggers built on
    "a posted entry never changes". Editing therefore goes through exactly one
    database function, which rebuilds the client's buckets and asserts no drift
    inside the same transaction. These tests pin that the service uses that path
    and never rewrites a posted entry itself — because doing it in Python would
    be several statements with no transaction around them, which is how the
    passbook drifted the last time (migration 249 repaired it by hand).

    Fail-closed is pinned too: if the lock cannot be established, the answer is
    "locked", never "probably fine".
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.manual_journal_service import manual_journal_service as svc


FIRM, CLIENT, ENTRY = "firm-1", "client-1", "entry-1"


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, rows, sink, name):
        self._rows, self._sink, self._name = rows, sink, name

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self._rows = [r for r in self._rows if r.get(c) == v]
        return self

    def is_(self, c, _v):
        self._rows = [r for r in self._rows if r.get(c) is None]
        return self

    def limit(self, _n):
        return self

    def execute(self):
        return _Result([dict(r) for r in self._rows])

    def update(self, patch):
        self._sink.writes.append((self._name, "update", patch))
        return self

    def delete(self):
        self._sink.writes.append((self._name, "delete", None))
        return self

    def insert(self, rows):
        self._sink.writes.append((self._name, "insert", rows))
        return self


class _DB:
    """Records every write, and every RPC, so a test can assert which PATH a
    change took and not merely that it happened."""

    def __init__(self, entry: dict, lock_reason=None, rpc_raises=None):
        self.entry = entry
        self.lock_reason = lock_reason
        self.rpc_raises = rpc_raises
        self.writes: list = []
        self.rpcs: list = []

    def table(self, name):
        rows = [self.entry] if name == "journal_entries" else []
        return _Table(rows, self, name)

    def rpc(self, fn, params):
        # The real client returns a BUILDER from .rpc() that the caller then
        # .execute()s. The stub must do the same, or it tests a shape the
        # production code never sees.
        self.rpcs.append((fn, params))
        if fn == "journal_period_lock_reason":
            return _Deferred(self.lock_reason)
        if fn == "edit_posted_journal":
            return _Deferred({"id": ENTRY}, raises=self.rpc_raises)
        raise AssertionError(f"unexpected rpc {fn}")


class _Deferred:
    def __init__(self, data, raises=None):
        self._data, self._raises = data, raises

    def execute(self):
        if self._raises:
            raise self._raises
        if isinstance(self._data, Exception):
            raise self._data
        return _Result(self._data)


def _entry(**over) -> dict:
    e = {
        "id": ENTRY, "firm_id": FIRM, "client_id": CLIENT, "entry_date": "2026-06-15",
        "reference_no": "MJ-1", "narration": "Rent", "entry_type": "Journal",
        "is_posted": True, "is_reversed": False, "source_type": "manual",
        "created_at": "2026-06-15T00:00:00Z", "deleted_at": None,
        "lines": [
            {"id": "l1", "account_id": "a1", "debit_paise": 5000000, "credit_paise": 0, "narration": ""},
            {"id": "l2", "account_id": "a2", "debit_paise": 0, "credit_paise": 5000000, "narration": ""},
        ],
    }
    e.update(over)
    return e


def _lines(debit=5000000, credit=5000000):
    return [
        {"account_id": "a1", "debit_paise": debit, "credit_paise": 0},
        {"account_id": "a2", "debit_paise": 0, "credit_paise": credit},
    ]


# ── reading ──────────────────────────────────────────────────────────────────

def test_an_open_posted_entry_reports_itself_editable():
    db = _DB(_entry())
    got = svc.get(db, FIRM, ENTRY)

    assert got["editable"] is True
    assert got["lock_reason"] is None
    assert got["status"] == "posted"
    # Integer paise, summed from the lines — never a float.
    assert got["total_debit_paise"] == 5000000 == got["total_credit_paise"]
    assert isinstance(got["total_debit_paise"], int)


def test_a_locked_year_is_reported_with_its_reason():
    """`lock_reason` rather than a bare boolean: 'the year is locked' and 'GSTR-3B
    was filed' call for different actions, and `false` tells the CA neither."""
    db = _DB(_entry(), lock_reason="Financial year 2026-27 is locked.")
    got = svc.get(db, FIRM, ENTRY)

    assert got["editable"] is False
    assert "2026-27 is locked" in got["lock_reason"]


def test_a_reversed_entry_is_never_editable():
    db = _DB(_entry(is_reversed=True))

    assert svc.get(db, FIRM, ENTRY)["editable"] is False


# ── the locks ────────────────────────────────────────────────────────────────

def test_editing_a_locked_year_is_refused_with_the_reason():
    db = _DB(_entry(), lock_reason="Financial year 2026-27 is locked.")
    with pytest.raises(HTTPException) as exc:
        svc.update(db, FIRM, ENTRY, {"lines": _lines()})

    assert exc.value.status_code == 422
    assert "locked" in exc.value.detail
    assert not [r for r in db.rpcs if r[0] == "edit_posted_journal"], \
        "a locked period must be refused BEFORE the ledger is touched"


def test_editing_a_filed_period_is_refused():
    db = _DB(_entry(), lock_reason=(
        "GSTR-3B covering this date was filed on 18 May 2026. Correct it with a "
        "reversal and an amendment in the next return."))
    with pytest.raises(HTTPException) as exc:
        svc.update(db, FIRM, ENTRY, {"lines": _lines()})

    assert "filed" in exc.value.detail
    assert "reversal" in exc.value.detail, "refusing must say what to do instead"


def test_the_lock_check_fails_closed():
    """If the period's status cannot be established, the answer is 'locked'.

    The alternative is assuming it is open, and an edit wrongly let into a filed
    period cannot be undone from the UI — the return has already gone."""
    db = _DB(_entry(), lock_reason=RuntimeError("connection reset"))
    got = svc.get(db, FIRM, ENTRY)

    assert got["editable"] is False
    assert got["lock_reason"], "an unresolvable lock must still give the CA a reason"

    with pytest.raises(HTTPException):
        svc.update(db, FIRM, ENTRY, {"lines": _lines()})


def test_moving_an_entry_into_a_locked_period_is_refused():
    """The entry sits in an open month; the CA tries to redate it into a closed
    one. Checking only the CURRENT date would let a locked year be quietly
    filled — or, in reverse, emptied."""
    calls = []

    class _MovingDB(_DB):
        def rpc(self, fn, params):
            if fn == "journal_period_lock_reason":
                calls.append(params["p_date"])
                # Open where it is, locked where it is going.
                return _Deferred(None if params["p_date"] == "2026-06-15"
                                 else "Financial year 2025-26 is locked.")
            return super().rpc(fn, params)

    db = _MovingDB(_entry())
    with pytest.raises(HTTPException) as exc:
        svc.update(db, FIRM, ENTRY, {"entry_date": "2025-12-01", "lines": _lines()})

    assert "locked" in exc.value.detail
    assert "2025-12-01" in calls, "the destination period was never checked"


# ── the path a posted edit takes ─────────────────────────────────────────────

def test_a_posted_edit_goes_through_the_rpc_and_never_writes_directly():
    """The whole safety argument. edit_posted_journal rebuilds the reporting
    passbook and asserts no drift inside one transaction. A service that wrote
    the rows itself would be several statements with no transaction around them
    — which is how the passbook drifted before (migration 249 repaired by hand)."""
    db = _DB(_entry())
    svc.update(db, FIRM, ENTRY, {"lines": _lines(), "narration": "Rent, corrected"})

    edits = [p for (fn, p) in db.rpcs if fn == "edit_posted_journal"]
    assert len(edits) == 1, "a posted edit must go through edit_posted_journal exactly once"
    assert edits[0]["p_entry_id"] == ENTRY
    assert edits[0]["p_firm"] == FIRM
    assert [l["debit_paise"] for l in edits[0]["p_lines"]] == [5000000, 0]

    touched = {t for (t, _op, _d) in db.writes}
    assert "journal_lines" not in touched, "a posted entry's lines were rewritten outside the RPC"
    assert "journal_entries" not in touched, "a posted entry's header was rewritten outside the RPC"


def test_a_draft_is_edited_directly_without_the_rpc():
    """Nothing is on the books yet, so there is no passbook to repair and no
    immutability trigger to satisfy. Sending a draft through the posted path
    would be pointless work and a misleading audit trail."""
    db = _DB(_entry(is_posted=False))
    svc.update(db, FIRM, ENTRY, {"lines": _lines(), "narration": "Fixed"})

    assert not [r for r in db.rpcs if r[0] == "edit_posted_journal"]
    ops = [(t, op) for (t, op, _d) in db.writes]
    assert ("journal_lines", "delete") in ops and ("journal_lines", "insert") in ops


def test_the_rpcs_error_reaches_the_ca_unchanged():
    """The database function raises for a locked period, an unbalanced entry and
    passbook drift alike, and its messages are written for a CA. Replacing them
    with 'something went wrong' throws away the only useful part."""
    db = _DB(_entry(), rpc_raises=RuntimeError(
        "Passbook drift detected for client client-1 after edit."))
    with pytest.raises(HTTPException) as exc:
        svc.update(db, FIRM, ENTRY, {"lines": _lines()})

    assert exc.value.status_code == 422
    assert "drift" in exc.value.detail


# ── double entry, which an edit is still subject to ──────────────────────────

def test_an_unbalanced_edit_is_refused_before_it_reaches_the_ledger():
    db = _DB(_entry())
    with pytest.raises(HTTPException) as exc:
        svc.update(db, FIRM, ENTRY, {"lines": _lines(debit=5000000, credit=4000000)})

    assert "Unbalanced" in exc.value.detail
    assert "5000000" in exc.value.detail and "4000000" in exc.value.detail
    assert not db.rpcs or not [r for r in db.rpcs if r[0] == "edit_posted_journal"]


def test_an_edit_cannot_reduce_an_entry_below_two_lines():
    db = _DB(_entry())
    with pytest.raises(HTTPException) as exc:
        svc.update(db, FIRM, ENTRY, {"lines": [{"account_id": "a1", "debit_paise": 1, "credit_paise": 0}]})

    assert "2 lines" in exc.value.detail


def test_an_edit_cannot_zero_an_entry_out():
    """Balanced at zero is still balanced, and would leave an entry that says
    nothing while remaining on the books. A deletion is a reversal."""
    db = _DB(_entry())
    with pytest.raises(HTTPException) as exc:
        svc.update(db, FIRM, ENTRY, {"lines": _lines(debit=0, credit=0)})

    assert "empty" in exc.value.detail.lower()


def test_editing_a_posted_entry_requires_the_complete_set_of_lines():
    """edit_posted_journal REPLACES the lines, so a partial set would silently
    delete the rest. Refused rather than guessed at."""
    db = _DB(_entry())
    with pytest.raises(HTTPException) as exc:
        svc.update(db, FIRM, ENTRY, {"narration": "typo fixed"})

    assert "full set of lines" in exc.value.detail


def test_a_reversed_entry_cannot_be_edited():
    db = _DB(_entry(is_reversed=True))
    with pytest.raises(HTTPException) as exc:
        svc.update(db, FIRM, ENTRY, {"lines": _lines()})

    assert "reversed" in exc.value.detail
