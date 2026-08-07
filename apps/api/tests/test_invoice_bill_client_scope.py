"""
Client-assignment scope on the sales-invoice and purchase-bill routers.

Neither router imported `core.authz` at all, so every endpoint was firm-scoped
and nothing more. `core.authz` makes only the **Partner** firm-wide
(`_FIRMWIDE_ROLES`); a Manager, Executive or Reviewer sees only the clients in
`user_client_assignments`. That meant, for any authenticated member of the firm:

  * `GET /api/sales-invoices/?client_id=…` listed any client's invoices —
    **no id-guessing needed at all**, unlike the banking hole;
  * `POST /` created an invoice or bill in any client's books;
  * `/{invoice_id}/issue`, `/cancel` and `/{bill_id}/receive` posted and
    reversed real journals against them.

`tests/test_router_client_scope.py` proves no endpoint was missed. This proves
the guards actually refuse — and that they refuse in the right ORDER, which is
the part that decides whether a rejected request still wrote something.

`assert_client_access` is permissive in mock mode (no SUPABASE_URL, so no
assignments table), so a denying substitute is installed where the refusal
itself is the subject.
"""
import pytest
from fastapi import HTTPException

import routers.sales_invoices as si
import routers.purchase_bills as pb

FIRM, MINE, THEIRS = "firm-1", "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "role": "manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse exactly one client, allow the rest — closer to a real assignment
    boundary than refusing everything, and it catches a guard that checks the
    wrong id."""
    seen = []

    def _check(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(si, "assert_client_access", _check)
    monkeypatch.setattr(pb, "assert_client_access", _check)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# Named directly by a parameter — the worst of the two, no id needed
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_managers_client_invoices_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        si.list_invoices(client_id=THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_your_own_client_is_unaffected(deny):
    si.list_invoices(client_id=MINE, current_user=USER)
    assert deny == [MINE]


def test_the_outstanding_total_is_scoped_too(deny):
    """A single number still discloses the size of another client's book."""
    with pytest.raises(HTTPException):
        si.get_outstanding(client_id=THEIRS, current_user=USER)


def test_hsn_suggestions_are_scoped_too(deny):
    """It reads the client's own invoice history, so it leaks what they sell."""
    with pytest.raises(HTTPException):
        si.hsn_suggestions(client_id=THEIRS, query="cons", limit=5, current_user=USER)


def test_listing_another_managers_client_bills_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        pb.list_purchase_bills(client_id=THEIRS, current_user=USER)
    assert e.value.status_code == 404


def test_creating_an_invoice_in_another_clients_books_is_refused(deny, monkeypatch):
    """The check must run BEFORE the row is built — an invoice created and then
    rejected is not the same as one never created."""
    reached = []
    monkeypatch.setattr(si, "_create_invoice_core",
                        lambda *a, **k: reached.append(a) or {})

    class _Data:
        client_id = THEIRS
        def model_dump(self): return {"client_id": THEIRS}

    with pytest.raises(HTTPException):
        si.create_invoice(_Data(), current_user=USER)
    assert reached == [], "the invoice was created despite the refusal"


def test_creating_a_bill_in_another_clients_books_is_refused(deny, monkeypatch):
    reached = []
    monkeypatch.setattr(pb, "_create_purchase_bill_core",
                        lambda *a, **k: reached.append(a) or {})

    class _Data:
        client_id = THEIRS
        def model_dump(self): return {"client_id": THEIRS}

    with pytest.raises(HTTPException):
        pb.create_purchase_bill(_Data(), current_user=USER)
    assert reached == [], "the bill was created despite the refusal"


# ══════════════════════════════════════════════════════════════════════════════
# Bulk — one foreign id among many legitimate ones
# ══════════════════════════════════════════════════════════════════════════════

def test_a_bulk_batch_is_refused_WHOLE_when_one_row_belongs_elsewhere(deny, monkeypatch):
    """Not atomic across rows is the right call for VALIDATION failures — eight
    good invoices should not be lost because the ninth had a bad date. It is the
    wrong call for an authorization failure: checking per row would let every
    row before the foreign one land, and a half-applied batch is how a foreign
    client's books quietly acquire entries."""
    created = []
    monkeypatch.setattr(si, "_create_invoice_core",
                        lambda *a, **k: created.append(a) or {})

    class _Payload:
        invoices = [{"client_id": MINE}, {"client_id": MINE}, {"client_id": THEIRS}]

    with pytest.raises(HTTPException):
        si.bulk_create_invoices(_Payload(), current_user=USER)
    assert created == [], "rows landed before the batch was refused"


def test_a_bulk_batch_checks_each_distinct_client_once(deny, monkeypatch):
    """Fifty rows for one client is one check, not fifty."""
    monkeypatch.setattr(si, "_create_invoice_core", lambda *a, **k: {})

    class _Payload:
        invoices = [{"client_id": MINE} for _ in range(50)]

    si.bulk_create_invoices(_Payload(), current_user=USER)
    assert deny == [MINE]


def test_a_bulk_bill_batch_is_refused_whole_too(deny, monkeypatch):
    created = []
    monkeypatch.setattr(pb, "_create_purchase_bill_core",
                        lambda *a, **k: created.append(a) or {})

    class _Payload:
        bills = [{"client_id": MINE}, {"client_id": THEIRS}]

    with pytest.raises(HTTPException):
        pb.bulk_create_purchase_bills(_Payload(), current_user=USER)
    assert created == []


# ══════════════════════════════════════════════════════════════════════════════
# Named indirectly by a row id — resolve the owner, then check
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def seeded(monkeypatch):
    """One invoice and one bill belonging to a client the caller is not on."""
    monkeypatch.setattr(si, "MOCK_SALES_INVOICES",
                        [{"id": "INV-9", "client_id": THEIRS, "status": "issued"}])
    monkeypatch.setattr(pb, "MOCK_PURCHASE_BILLS",
                        [{"id": "PB-9", "client_id": THEIRS, "status": "draft"}])


def test_an_invoice_belonging_to_another_client_is_refused(deny, seeded):
    with pytest.raises(HTTPException) as e:
        si.get_invoice("INV-9", current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_issuing_another_clients_invoice_is_refused_before_any_journal(deny, seeded):
    """`/issue` posts a real journal. The refusal has to come first."""
    with pytest.raises(HTTPException) as e:
        si.issue_invoice("INV-9", current_user=USER)
    assert e.value.status_code == 404


def test_receiving_another_clients_bill_is_refused(deny, seeded):
    """`/receive` posts the bill and its input GST credit (CGST Act §16)."""
    with pytest.raises(HTTPException) as e:
        pb.receive_purchase_bill("PB-9", current_user=USER)
    assert e.value.status_code == 404


def test_the_pdf_of_another_clients_invoice_is_refused(deny, seeded):
    """A rendered invoice carries the customer's name, GSTIN and amounts."""
    with pytest.raises(HTTPException):
        si.download_sales_invoice_pdf("INV-9", current_user=USER)


def test_an_invoice_on_your_own_client_still_resolves(deny, monkeypatch):
    monkeypatch.setattr(si, "MOCK_SALES_INVOICES",
                        [{"id": "INV-1", "client_id": MINE}])
    assert si._assert_invoice_scope(USER, "INV-1") == MINE
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# The owner lookup itself
# ══════════════════════════════════════════════════════════════════════════════

def test_a_row_that_exists_without_a_client_id_is_not_reported_as_missing():
    """"No such invoice" and "a projection that didn't select client_id" are
    different answers. Collapsing them turned a live fake-DB test into a 404."""
    found, client_id = si._invoice_owner(USER, "INV-1")
    assert (found, client_id) == (False, None)

    si.MOCK_SALES_INVOICES.append({"id": "INV-1", "invoice_no": "X"})
    try:
        assert si._invoice_owner(USER, "INV-1") == (True, None)
    finally:
        si.MOCK_SALES_INVOICES.clear()


def test_the_owner_lookup_ignores_soft_deletion():
    """Who owns a soft-deleted invoice is still the right answer to "may this
    caller act on it" — whether the row is actionable is the handler's call, and
    filtering here would hand a deleted row's endpoints an unscoped pass."""
    si.MOCK_SALES_INVOICES.append(
        {"id": "INV-D", "client_id": MINE, "deleted_at": "2026-01-01"})
    try:
        assert si._invoice_owner(USER, "INV-D") == (True, MINE)
    finally:
        si.MOCK_SALES_INVOICES.clear()


def test_the_owner_lookup_is_still_firm_scoped(monkeypatch):
    """Assignment scope is an ADDITION to tenant scope, not a replacement. Mock
    mode never touches Supabase, so this drives the real query path and inspects
    the filters it built."""
    filters = {}

    class _Q:
        def select(self, *_a): return self
        def eq(self, k, v): filters[k] = v; return self
        def limit(self, _n): return self
        def execute(self): return type("R", (), {"data": [{"client_id": MINE}]})()

    class _DB:
        def table(self, _n): return _Q()

    monkeypatch.setattr(si, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _DB())
    assert si._invoice_owner(USER, "INV-1") == (True, MINE)
    assert filters == {"id": "INV-1", "firm_id": FIRM}


def test_the_firm_wide_unposted_view_is_narrowed_to_your_own_book(monkeypatch):
    """`/maintenance/unposted` takes an OPTIONAL client_id. With one, it is
    checked; without one it would otherwise hand an Executive every client's
    unposted invoices — so the firm-wide branch narrows instead."""
    calls = []
    monkeypatch.setattr(si, "filter_by_client",
                        lambda user, rows: calls.append(len(rows)) or [])
    monkeypatch.setattr(si, "MOCK_SALES_INVOICES", [
        {"id": "A", "client_id": MINE, "status": "issued", "journal_entry_id": None},
        {"id": "B", "client_id": THEIRS, "status": "issued", "journal_entry_id": None},
    ])
    out = si.list_unposted(client_id=None, current_user=USER)
    assert calls == [2], "the firm-wide view was not narrowed"
    assert out["data"]["unposted"] == []


def test_asking_for_one_client_checks_it_instead_of_narrowing(deny, monkeypatch):
    """Narrowing a single-client request would silently return an empty list
    rather than saying no, which reads as "this client has nothing"."""
    monkeypatch.setattr(si, "filter_by_client",
                        lambda *_a: pytest.fail("should not narrow a named request"))
    monkeypatch.setattr(si, "MOCK_SALES_INVOICES", [])
    with pytest.raises(HTTPException):
        si.list_unposted(client_id=THEIRS, current_user=USER)
    assert deny == [THEIRS]


def test_an_unknown_id_never_reaches_the_client_check(deny):
    """Nothing to scope, so nothing is asserted — and in mock mode each handler
    still raises its own 404."""
    assert si._assert_invoice_scope(USER, "nope") is None
    assert pb._assert_bill_scope(USER, "nope") is None
    assert deny == []
