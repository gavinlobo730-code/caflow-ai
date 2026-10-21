"""A "newest plus one" number that is one line for the whole FIRM is read with the whole firm in view (POST-A-311).

WHAT WAS WRONG
    Three places take the newest number of a firm-wide line and add one, and read it with the CALLER's own client while the
    table carries the assignment scope:
      * the vendor-payment number (`services/numbering.next_sequence` for `purchase_payments`, the one series of that table
        whose unique key is the FIRM alone: migration 159), so a Manager assigned to client A read only A's payments (and
        none of the practice's own internal client, which only a Partner reads) and was handed a number client B's payment
        already held; the insert failed on 23505, the route answered 409 "A payment numbering collision was detected; please
        retry." after the journal had been posted and compensated, and each time the person retried it recomputed the same
        number, because their own maximum never passes the numbers they cannot see (the single-bill route and the multi-bill
        path behind the bank match queue both do this);
      * the next free bank-account ledger code (`routers/banking._next_bank_account_code`, scanned "across the whole firm"
        with the caller's client while `chart_of_accounts` is unique on (firm_id, account_code) and assignment-scoped), so
        the five attempts of `_ensure_bank_ledger` proposed the same taken code and the account was saved unlinked;
      * the proposal number (`routers/lifecycle._next_proposal_no`), which has no unique key, so the result was a duplicate
        number rather than a failed insert.
    It is the defect of the engagement-letter number (`engagement_letters._numbering_db`, migration 529) in three more places.
    The other numbered series are per (firm, client) and the caller has that client's access, so their own view IS the series.

WHAT THIS HOLDS
    * a firm-wide series is read with the privileged client when there is one and the caller's own only where there is no
      other, and a per-client series is never moved off the caller's client; judged against the scope `NUMBER_SERIES` records
      and not against the function that classifies it, so a series added later is held without anyone remembering to add it,
      and a series wrongly classified is caught;
    * the privileged reads carry the firm (the double applies the filters, and holds another firm's higher number to prove
      it), the proposal read takes the NEWEST proposal (the double honours the order), and the bank-code scan pages past the
      thousand rows PostgREST would cut a response at;
    * the bank-account code is scanned with the privileged client by the function itself, the ledger row is still INSERTED by
      the caller, and with an insert that refuses a taken code the control shows the five-attempt wedge and the fix a single
      attempt;
    * each, run with no privileged client, shows the defect (the control).

Runs in the mock-mode job: no database is needed.
"""
from __future__ import annotations

import inspect

import pytest

import routers.banking as banking
import routers.lifecycle as lc
from core import db_provider
from core.ist_clock import ist_today
from services import numbering, purchase_payment_service

PAGE = 1000          # PostgREST's response cap (core.db_paging.PAGE)


class _Query:
    """A query chain that applies what the code under test asks for: equality filters, a `like` prefix, `gt` for keyset paging,
    the order, the limit (and the server's own cap of PAGE rows), and records every read. A chain method it does not model
    (`range`, `is_`, `in_` ...) is recorded and ignored, so a legitimate change of the chain does not crash a test for the
    wrong reason."""

    def __init__(self, store, name):
        self._store, self._name = store, name
        self._eqs, self._likes, self._gts, self._order, self._limit, self._insert = [], [], [], None, None, None

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._eqs.append((column, value))
        return self

    def like(self, column, pattern):
        self._likes.append((column, pattern.rstrip("%")))
        return self

    def gt(self, column, value):
        self._gts.append((column, value))
        return self

    def order(self, column, desc=False, **_k):
        self._order = (column, bool(desc))
        return self

    def limit(self, count, *_a, **_k):
        self._limit = count
        return self

    def insert(self, payload):
        self._insert = payload
        return self

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *_a, **_k: self

    def execute(self):
        if self._insert is not None:
            code = self._insert.get("account_code")
            if code in self._store.refuses:
                raise Exception(f"duplicate key value violates unique constraint (23505): account_code {code}")
            self._store.inserted.append((self._name, dict(self._insert)))
            return type("R", (), {"data": [{"id": "NEW"}]})()
        self._store.reads.append((self._name, list(self._eqs)))
        rows = [r for r in self._store.rows.get(self._name, [])
                if all(r.get(c) == v for c, v in self._eqs)
                and all(str(r.get(c)).startswith(p) for c, p in self._likes)
                and all(str(r.get(c)) > str(v) for c, v in self._gts)]
        if self._order:
            rows.sort(key=lambda r: str(r.get(self._order[0])), reverse=self._order[1])
        return type("R", (), {"data": [dict(r) for r in rows[:min(self._limit or PAGE, PAGE)]]})()


class _Db:
    """Holds `rows` per table, answers a select with the rows the chain asks for, and records reads and inserts. `refuses` is
    a set of account codes whose insert fails the way the unique key does."""

    def __init__(self, rows, refuses=()):
        self.rows, self.refuses, self.reads, self.inserted = rows, set(refuses), [], []

    def table(self, name):
        return _Query(self, name)


def _payment(number, firm="F1"):
    return {"firm_id": firm, "payment_no": number}


def _privileged(monkeypatch, server):
    monkeypatch.setattr(db_provider, "service_db_or_none", lambda: server)


def _eqs_of_the_read(db):
    """The filters of the one read a double recorded."""
    assert len(db.reads) >= 1, "the double was never read"
    return db.reads[0][1]


# ── the vendor-payment number, and the rule over every series ───────────────────────────────────────────────────────

def test_the_vendor_payment_number_follows_the_newest_payment_of_the_firm(monkeypatch):
    caller = _Db({"purchase_payments": [_payment("VPMT-2627-0003"), _payment("VPMT-2627-0002")]})    # a Manager's view
    server = _Db({"purchase_payments": [_payment("VPMT-2627-0005"), _payment("VPMT-2627-0004"), _payment("VPMT-2627-0003"),
                                        _payment("VPMT-2627-0030", firm="F2")]})                  # the firm's, and another firm's
    _privileged(monkeypatch, server)
    assert numbering.next_sequence(caller, "purchase_payments", "VPMT-2627-", firm_id="F1") == 6
    assert caller.reads == [] and server.reads, "the series was read with the caller's client"
    assert ("firm_id", "F1") in _eqs_of_the_read(server), "the privileged read does not name the firm: it would read every firm's"


def test_both_vendor_payment_paths_read_the_number_through_the_one_function(monkeypatch):
    """The service the bank match queue and the cheque conversion use asks the same function as the router does."""
    caller = _Db({"purchase_payments": [_payment("VPMT-2627-0001")]})
    server = _Db({"purchase_payments": [_payment("VPMT-2627-0004")]})
    _privileged(monkeypatch, server)
    assert purchase_payment_service._next_payment_seq(caller, "F1", "2627") == 5
    assert caller.reads == []


def test_read_as_the_caller_the_same_series_hands_out_a_taken_number_which_is_the_defect(monkeypatch):
    caller = _Db({"purchase_payments": [_payment("VPMT-2627-0003"), _payment("VPMT-2627-0002")]})
    _privileged(monkeypatch, None)
    assert numbering.next_sequence(caller, "purchase_payments", "VPMT-2627-", firm_id="F1") == 4      # client B holds 0004


def test_a_per_client_series_stays_on_the_callers_client(monkeypatch):
    caller = _Db({"credit_notes": [{"firm_id": "F1", "client_id": "C1", "credit_note_no": "CN-2627-0002"}]})
    server = _Db({"credit_notes": [{"firm_id": "F1", "client_id": "C1", "credit_note_no": "CN-2627-0009"}]})
    _privileged(monkeypatch, server)
    assert numbering.next_sequence(caller, "credit_notes", "CN-2627-", firm_id="F1", client_id="C1") == 3
    assert server.reads == [], "a per-client series was read with the privileged client"


def test_a_receipt_is_numbered_per_client_and_never_moved_off_the_callers_client(monkeypatch):
    """An independent anchor for the classification: this one is written down here and not derived from the function."""
    caller = _Db({"receipts": [{"firm_id": "F1", "client_id": "C1", "receipt_no": "RCPT-2627-0001"}]})
    _privileged(monkeypatch, _Db({}))
    assert numbering.next_sequence(caller, "receipts", "RCPT-2627-", firm_id="F1", client_id="C1") == 2
    assert not numbering.is_firm_wide("receipts") and numbering.is_firm_wide("purchase_payments")


def test_mock_mode_has_no_client_to_swap(monkeypatch):
    _privileged(monkeypatch, _Db({}))
    assert numbering._firm_wide_db(None) is None


def test_the_firm_wide_series_are_the_ones_whose_scope_lacks_the_client():
    firm_wide = sorted(t for t in numbering.NUMBER_SERIES if numbering.is_firm_wide(t))
    per_client = sorted(t for t in numbering.NUMBER_SERIES if not numbering.is_firm_wide(t))
    assert firm_wide == ["purchase_payments"], firm_wide
    assert len(per_client) >= 5, per_client           # the scan sees the per-client series too, or it proves nothing
    assert all("client_id" in numbering.NUMBER_SERIES[t][1] for t in per_client)


@pytest.mark.parametrize("table", sorted(numbering.NUMBER_SERIES))
def test_every_series_is_read_with_the_client_its_scope_calls_for(table, monkeypatch):
    """The expectation comes from the scope NUMBER_SERIES records, not from `is_firm_wide`: a firm-wide series is read with
    the privileged client and every column of its scope reaches the query; a per-client one never leaves the caller's."""
    number_field, scope = numbering.NUMBER_SERIES[table]
    firm_wide = "client_id" not in scope
    assert numbering.is_firm_wide(table) is firm_wide
    mine = {column: "v" for column in scope}
    caller = _Db({table: [{**mine, number_field: "X-0001"}]})
    server = _Db({table: [{**mine, number_field: "X-0009"}]})
    _privileged(monkeypatch, server)
    assert numbering.next_sequence(caller, table, "X-", **mine) == (10 if firm_wide else 2)
    read_by = server if firm_wide else caller
    other = caller if firm_wide else server
    assert read_by.reads and not other.reads, f"{table} was read with the wrong client"
    assert all((column, "v") in _eqs_of_the_read(read_by) for column in scope), (
        f"{table}: a column of the series' scope did not reach the query: {_eqs_of_the_read(read_by)}")


# ── the bank-account ledger code ────────────────────────────────────────────────────────────────────────────────────

def _chart(*codes, firm="F1", start=0):
    return [{"id": f"id-{start + i:06d}", "firm_id": firm, "account_code": c} for i, c in enumerate(codes)]


def test_the_bank_ledger_code_is_scanned_across_the_firm_and_the_row_is_inserted_by_the_caller(monkeypatch):
    caller = _Db({"chart_of_accounts": _chart("1101")})                          # a Manager's view: their client's ledger
    server = _Db({"chart_of_accounts": _chart("1101", "1102", "1103") + _chart("1104", firm="F2", start=50)})
    monkeypatch.setattr(banking, "_service_db", lambda: server)
    ledger_id = banking._ensure_bank_ledger(caller, "F1", "C1", "HDFC Bank", "000012347890")
    assert ledger_id == "NEW"
    assert [row["account_code"] for _t, row in caller.inserted] == ["1104"], caller.inserted     # F2's 1104 is not F1's
    assert server.inserted == [], "the ledger row was inserted with the privileged client"
    assert ("firm_id", "F1") in _eqs_of_the_read(server)
    assert caller.reads == [], "the code was scanned with the caller's client"


def test_the_function_itself_asks_for_the_whole_firm_whatever_client_it_is_handed(monkeypatch):
    """The swap is inside `_next_bank_account_code`, so a second caller passing the request client cannot bring the defect back."""
    caller = _Db({"chart_of_accounts": _chart("1101")})
    server = _Db({"chart_of_accounts": _chart("1101", "1102")})
    monkeypatch.setattr(banking, "_service_db", lambda: server)
    assert banking._next_bank_account_code(caller, "F1") == "1103"
    assert caller.reads == []


def test_read_as_the_caller_the_bank_ledger_code_is_a_taken_one_and_every_attempt_proposes_it(monkeypatch):
    """The control, with an insert that refuses a taken code the way the unique key does: five attempts, one code, and the
    account is saved unlinked."""
    caller = _Db({"chart_of_accounts": _chart("1101")}, refuses=("1102", "1103"))      # 1102 and 1103 are other clients' ledgers
    monkeypatch.setattr(banking, "_service_db", lambda: None)
    assert banking._ensure_bank_ledger(caller, "F1", "C1", "HDFC Bank", "000012347890") is None
    assert caller.inserted == [], "an insert the double refuses was recorded"
    assert len(caller.reads) == 5, "the scan did not run once per attempt"


def test_with_the_whole_firm_in_view_the_first_attempt_takes(monkeypatch):
    caller = _Db({"chart_of_accounts": _chart("1101")}, refuses=("1102", "1103"))
    server = _Db({"chart_of_accounts": _chart("1101", "1102", "1103")})
    monkeypatch.setattr(banking, "_service_db", lambda: server)
    assert banking._ensure_bank_ledger(caller, "F1", "C1", "HDFC Bank", "000012347890") == "NEW"
    assert [row["account_code"] for _t, row in caller.inserted] == ["1104"]
    assert len(server.reads) == 1, "more than one attempt was needed"


def test_a_bank_ledger_code_fills_the_first_gap_and_skips_codes_that_are_not_numbers(monkeypatch):
    server = _Db({"chart_of_accounts": _chart("1101", "1102", "abc", None, "1104")})
    monkeypatch.setattr(banking, "_service_db", lambda: server)
    assert banking._next_bank_account_code(server, "F1") == "1103"


def test_the_bank_code_scan_reads_past_the_thousand_rows_a_response_is_cut_at(monkeypatch):
    """PostgREST answers at most a thousand rows and says nothing; the codes 1101 to 3600 are all taken, so a scan that stopped
    at the first page would propose 2101, which is taken."""
    server = _Db({"chart_of_accounts": _chart(*[str(c) for c in range(1101, 3601)])})
    monkeypatch.setattr(banking, "_service_db", lambda: server)
    assert banking._next_bank_account_code(server, "F1") == "3601"
    assert len(server.reads) == 3, "the scan did not page"


# ── the proposal number ─────────────────────────────────────────────────────────────────────────────────────────────

def _proposal(number, created, firm="F1"):
    return {"firm_id": firm, "proposal_no": number, "created_at": created}


def test_the_proposal_number_follows_the_firms_newest_proposal(monkeypatch):
    year = ist_today().year
    caller = _Db({"proposals": [_proposal(f"PROP-{year}-0003", "2026-10-01")]})
    server = _Db({"proposals": [_proposal(f"PROP-{year}-0007", "2026-10-10"), _proposal(f"PROP-{year}-0005", "2026-10-05"),
                                _proposal(f"PROP-{year}-0003", "2026-10-01"),
                                _proposal(f"PROP-{year}-0030", "2026-10-20", firm="F2")]})
    _privileged(monkeypatch, server)
    assert lc._next_proposal_no(caller, "F1") == f"PROP-{year}-0008"       # the newest of THIS firm, not F2's, not the oldest
    assert caller.reads == [], "the proposal number was read with the caller's client"
    assert ("firm_id", "F1") in _eqs_of_the_read(server)


def test_read_as_the_caller_the_proposal_number_is_a_duplicate_which_is_the_defect(monkeypatch):
    year = ist_today().year
    caller = _Db({"proposals": [_proposal(f"PROP-{year}-0003", "2026-10-01")]})
    _privileged(monkeypatch, None)
    assert lc._next_proposal_no(caller, "F1") == f"PROP-{year}-0004"        # a prospect already holds 0004


def test_the_first_proposal_of_a_firm_is_number_one(monkeypatch):
    year = ist_today().year
    _privileged(monkeypatch, _Db({"proposals": []}))
    assert lc._next_proposal_no(_Db({}), "F1") == f"PROP-{year}-0001"


def test_mock_mode_numbers_proposals_from_the_in_memory_list_and_never_reaches_for_a_client(monkeypatch):
    year = ist_today().year
    server = _Db({"proposals": [_proposal(f"PROP-{year}-0099", "2026-10-10")]})
    _privileged(monkeypatch, server)
    assert lc._next_proposal_no(None, "F1") == f"PROP-{year}-{len(lc._MOCK_PROPOSALS) + 1:04d}"
    assert server.reads == []


def test_each_function_that_finds_a_firm_wide_number_asks_for_the_privileged_client_itself():
    """The rule is in the function and not at one call site, so a second caller cannot hand it the request's client."""
    assert "_service_db()" in inspect.getsource(banking._next_bank_account_code)
    assert "service_db_or_none()" in inspect.getsource(lc._next_proposal_no)
    assert "_firm_wide_db(" in inspect.getsource(numbering.next_sequence)
