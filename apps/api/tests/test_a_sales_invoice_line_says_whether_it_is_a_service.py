"""
A FIELD DECLARED, VALIDATED AND DROPPED ON THE FLOOR (migration 411).

`models/invoices.InvoiceLineIn.is_service` has existed since the model was
written. `client_sales_invoice_lines` had no such column, so a caller set it,
Pydantic accepted it, `_create_invoice_core` computed with it and the INSERT
never mentioned it. A field offered and silently discarded is the shape this
repository keeps finding — the team grid's localStorage toggles,
`invoice_templates`, `account_group_mappings`.

WHY IT IS NOT TIDINESS. The e-invoice portal's own item validations turn on it,
and `domain/gst/irp_validations.NOT_HELD` named TWO refusals that existed only
because the column did not:

    "If Is Service is selected, then the HSN codes must belong to services."
    "Quantity and Unit Quantity Code are mandatory for Goods and optional for
     Services."

The second is built now. Without the column, a service line with no unit and a
goods line missing one were the same row, so the rule could not be asked at all
— and CGST Rule 46(h) asks for the quantity and unit on a supply OF GOODS.

THE THIRD STATE IS THE POINT. The column is nullable with no default and no
backfill, and the model's default moved from `False` to `None`. Every row that
predates 411 was written with no such field, so `false` would not be a recorded
fact — it would be an assertion that every line ever raised was goods, which on
a practice whose clients are mostly professionals is wrong on nearly all of
them, and the first rule to read it would then demand a UQC on each.

The sibling columns on migration 392's tables ARE `NOT NULL DEFAULT false`, and
that is not an inconsistency: those tables were new, so every row in them was
written by a door that sets the value.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from models.invoices import InvoiceLineIn, PurchaseBillLineIn, SalesInvoiceIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

API = Path(__file__).resolve().parents[1]
FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test",
          "role": "Partner"}


def _setup(monkeypatch):
    import routers.sales_invoices as si
    import services.sales_numbering_service as sn
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, sn])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme Buyer", "state_code": "27",
                          "gstin": "27XYZAB5678C1Z2", "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Consulting", "kind": "service"})
    return si, db


def _create(si, *, is_service):
    line = dict(service_catalogue_id="SVC-1", description="Consulting",
                hsn_sac="998313", quantity=1, rate_paise=1_000_000,
                gst_rate_percent=18.0)
    if is_service is not _ABSENT:
        line["is_service"] = is_service
    payload = SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10",
        due_date="2026-05-10", invoice_no="INV/2026-27/001",
        lines=[InvoiceLineIn(**line)],
    ).model_dump()

    class _P:
        """Mimics the FastAPI-parsed SalesInvoiceIn body for a direct call."""
        def __init__(self, d):
            self._d = d
            self.client_id = d["client_id"]
        def model_dump(self): return dict(self._d)
    res = si.create_invoice(_P(payload), CALLER)
    assert res["success"] is True, res
    return res


_ABSENT = object()


def _stored_line(db):
    rows = db.rows("client_sales_invoice_lines")
    assert len(rows) == 1, rows
    return rows[0]


# ── the round trip, which is the whole finding ───────────────────────────────

@pytest.mark.parametrize("value", [True, False])
def test_what_the_caller_said_is_what_is_STORED(monkeypatch, value):
    """The defect, stated as the thing that was not true.

    Before 411 this line reached the INSERT without `is_service` at all, so
    both values stored identically — as nothing.
    """
    si, db = _setup(monkeypatch)
    _create(si, is_service=value)
    assert _stored_line(db)["is_service"] is value


def test_saying_NOTHING_stores_NOTHING(monkeypatch):
    """The third state survives the round trip rather than becoming False.

    This is what the model's default decides, and it is why the default moved:
    `bool = False` recorded a fact nobody stated on every line of every invoice
    raised by a caller that does not send the field — which is every caller
    that predates 411.
    """
    si, db = _setup(monkeypatch)
    _create(si, is_service=_ABSENT)
    assert _stored_line(db)["is_service"] is None


def test_the_model_default_is_the_THIRD_STATE_and_not_False():
    assert InvoiceLineIn.model_fields["is_service"].default is None
    line = InvoiceLineIn(description="x", quantity=1, rate_paise=1,
                         gst_rate_percent=18.0, service_catalogue_id="S")
    assert line.is_service is None


def test_the_PURCHASE_line_deliberately_KEEPS_its_False_default():
    """A different column with a different history.

    `purchase_bill_lines.is_service` is NOT NULL with a default and has been
    written by a door that sets it since it was created, so `False` there is a
    recorded answer rather than an assumption. Changing it would be a change
    for symmetry's sake against a column that does not need one.
    """
    assert PurchaseBillLineIn.model_fields["is_service"].default is False


def test_the_INSERT_names_the_column(monkeypatch):
    """Asserted on the payload as well as on the stored row.

    The stored-row test above would still pass if the harness were lenient
    about an absent key, and the original defect was exactly an absent key.
    """
    src = (API / "routers/sales_invoices.py").read_text()
    tree = ast.parse(src)
    payload_keys = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if "sales_invoice_id" in keys and "line_total_paise" in keys:
            payload_keys |= keys
    assert "is_service" in payload_keys, \
        "the line INSERT does not carry is_service, so the column is unreachable"


def test_nothing_COERCES_it_on_the_way_through(monkeypatch):
    """`bool(ln.get("is_service"))` would fold the third state into False as
    surely as the model default did, one line further on."""
    src = (API / "routers/sales_invoices.py").read_text()
    assert 'bool(ln.get("is_service"))' not in src
    assert 'ln.get("is_service", False)' not in src


# ── nothing computes money from it ───────────────────────────────────────────

def test_the_LINE_TAX_engine_does_not_read_it():
    """The GST on a line comes from its own rate. Whether a supply is of goods
    or services changes the PLACE OF SUPPLY rules (IGST §§10-13), which is a
    statutory question about the transaction rather than a label on a line, and
    wiring this column to those would decide it in the wrong place.
    """
    from domain.sales import line_tax
    assert "is_service" not in inspect.getsource(line_tax)


def test_the_GSTR1_builder_does_not_read_it_either():
    from domain.gst import gstr1_builder
    assert "is_service" not in inspect.getsource(gstr1_builder)


# ── the migration says what it did and what it deliberately did not ──────────

def test_the_migration_is_nullable_with_no_default_and_no_backfill():
    sql = (API / "migrations/411_an_invoice_line_says_whether_it_is_a_service.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS is_service BOOLEAN;" in sql
    lowered = sql.lower()
    assert "default" not in lowered.split("add column")[1].split(";")[0]
    assert "update" not in lowered.split("alter table")[1], "no backfill"
    assert "COMMENT ON COLUMN" in sql


def test_the_rollback_exists_and_says_what_it_loses():
    sql = (API / "migrations/411_an_invoice_line_says_whether_it_is_a_service_rollback.sql").read_text()
    assert "DROP COLUMN IF EXISTS is_service" in sql
    assert "loses" in sql
