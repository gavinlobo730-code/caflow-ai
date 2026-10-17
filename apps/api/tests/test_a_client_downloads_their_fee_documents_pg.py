"""A client downloads their own fee statement and fee invoice, produced from the practice's books (ledger POST-A-236, POST-A-237).

THE DEFECT
    The client portal serves two PDFs: the fee statement (`/statement/pdf`) and a fee invoice (`/invoices/{id}/pdf`). Both
    are the PRACTICE's document, issued by the firm's internal client. Both ran every read on the portal contact's own
    sign-in (`USE_USER_JWT` is on in production). A portal contact has no `users` row, so row security hides the internal
    client's `clients` row, the invoice lines and the e-invoice record from them:
      * the statement read the account holder's letterhead from `clients`, found nothing and the route answered 500
        "PDF generation failed";
      * the invoice read the supplier from `clients`, found nothing and the route answered 404 for an invoice the client
        owns; the lines and the e-invoice record were empty on the same sign-in.
    Migration 443 recorded the first as "flagged, not fixed"; the test it left asserted that the statement still failed.

WHAT IS HELD (a real database; the real service functions, run unmodified through a duck-typed client that sends each
query as the portal contact's own sign-in)
    * what the contact CAN read (their invoice with its customer, the statement's rows) and what they CANNOT (the practice's
      `clients` row, the lines, the e-invoice record) — which is why the privileged client is used for exactly those;
    * the statement PDF is produced, headed with the practice's name, when the letterhead is read with the privileged
      client; with the letterhead read on the contact's own sign-in it still refuses (the old failure, kept as the
      negative control);
    * the invoice PDF is produced with its line description and its IRN when the supplier, lines and e-invoice record are
      read with the privileged client; read on the contact's own sign-in the supplier is missing and it refuses;
    * the ownership check stays with row security: another client's invoice is not found even with the privileged client
      handed in, because the invoice row itself is read on the contact's sign-in.

Runs only when HARNESS_PG is set + psql on PATH.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.test_r443_portal_client_reads_own_fee_documents_pg import (
    CUST1, EXT1, FIRM, INTERNAL_CLIENT, INVOICE_1, INVOICE_2, PARTNER_ID, PORTAL_AUTH_1, _SEED_SQL,
)

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="the portal fee-document proofs require HARNESS_PG + psql",
)

DRAFT_INVOICE = "e4430000-0000-0000-0000-0000000000d7"
LINE_TEXT = "Retainer fee for April"
IRN = "a" * 64
_EXTRA_SEED = f"""
UPDATE clients SET legal_name = 'Practice Advisors LLP', gstin = '27AAACI1234A1Z6', state_code = '27',
                   address_line1 = '1 Marine Drive', city = 'Mumbai', state = 'Maharashtra', pincode = '400001'
 WHERE id = '{INTERNAL_CLIENT}';
INSERT INTO client_sales_invoices
  (id, firm_id, client_id, customer_id, invoice_no, invoice_date, due_date,
   taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, total_paise, status)
  VALUES ('{DRAFT_INVOICE}', '{FIRM}', '{INTERNAL_CLIENT}', '{CUST1}', 'DRAFT-0001',
          '2026-05-01', '2026-05-31', 100000, 9000, 9000, 0, 118000, 'draft');
INSERT INTO client_sales_invoice_lines (sales_invoice_id, description, hsn_sac, quantity, rate_paise,
                                        taxable_amount_paise, gst_rate_bps, cgst_paise, sgst_paise, line_total_paise)
  VALUES ('{INVOICE_1}', '{LINE_TEXT}', '998211', 1, 100000, 100000, 1800, 9000, 9000, 118000);
INSERT INTO einvoice_records (firm_id, client_id, sales_invoice_id, invoice_number, invoice_date, status, irn, created_by)
  VALUES ('{FIRM}', '{INTERNAL_CLIENT}', '{INVOICE_1}', 'FEE/0001', '2026-04-01', 'generated', '{IRN}', '{PARTNER_ID}');
"""


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"fee_m236_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        for sql in (_SEED_SQL, _EXTRA_SEED):
            seeded = _psql(dsn, sql)
            assert seeded.returncode == 0, seeded.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


# ── a duck-typed Supabase client over real SQL ──────────────────────────────────────────────────────────────────────

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """The chainable builder the PDF services use, translated to SQL. `customers(cols)` embedded in a select becomes a
    join, as PostgREST does it (and under the caller's row security)."""

    def __init__(self, table: str, run):
        self._table, self._run = table, run
        self._select, self._where, self._order, self._limit, self._single = "*", [], None, None, False

    def select(self, cols, *a, **k):
        self._select = cols
        return self

    @staticmethod
    def _q(v) -> str:
        return "'" + str(v).replace("'", "''") + "'"

    def eq(self, col, val):
        self._where.append(f"t.{col} IS NULL" if val is None else f"t.{col} = {self._q(val)}")
        return self

    def in_(self, col, vals):
        vals = list(vals)
        self._where.append("1=0" if not vals else f"t.{col} IN ({','.join(self._q(v) for v in vals)})")
        return self

    def is_(self, col, val):
        self._where.append(f"t.{col} IS NULL")
        return self

    def order(self, col, desc=False):
        self._order = f"t.{col} {'DESC' if desc else 'ASC'}"
        return self

    def limit(self, n):
        self._limit = int(n)
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        select, joins = self._select, ""
        if "customers(" in select:
            head, _, rest = select.partition("customers(")
            cols = rest.rstrip(") ").split(",")
            joins = (" LEFT JOIN LATERAL (SELECT row_to_json(c) AS j FROM (SELECT "
                     + ",".join(f"cu.{x.strip()}" for x in cols) + " FROM customers cu WHERE cu.id = t.customer_id) c) emb ON true")
            select = (head.strip().rstrip(",") or "*")
            select = "t.*" if select == "*" else ",".join(f"t.{x.strip()}" for x in select.split(","))
            select += ", emb.j AS customers"
        else:
            select = "t.*" if select == "*" else ",".join(f"t.{x.strip()}" for x in select.split(","))
        sql = f"SELECT {select} FROM {self._table} t{joins}"
        if self._where:
            sql += " WHERE " + " AND ".join(self._where)
        if self._order:
            sql += f" ORDER BY {self._order}"
        if self._limit is not None:
            sql += f" LIMIT {self._limit}"
        rows = self._run(sql)
        return _Result((rows[0] if rows else None) if self._single else rows)


class _SignInDb:
    """Every query goes out as `auth_uid`'s own sign-in (authenticated role + that JWT subject), or on the privileged
    connection when no uid is given."""

    def __init__(self, dsn: str, auth_uid: str | None):
        self._dsn, self._uid = dsn, auth_uid

    def _run(self, sql: str):
        # jsonb_agg, because json_agg pretty-prints more than one row over several lines and only one line is read back
        wrapped = f"SELECT coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb)::text FROM ({sql}) t;"
        if self._uid:
            wrapped = f"SET request.jwt.claims = '{{\"sub\": \"{self._uid}\"}}'; SET ROLE authenticated; " + wrapped
        r = subprocess.run(["psql", self._dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", wrapped],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip())
        lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
        try:
            return json.loads(lines[-1]) if lines else []
        except json.JSONDecodeError as e:                          # say which query, not just that it broke
            raise RuntimeError(f"unreadable answer to {sql!r}: {lines[-1][:300]!r}") from e

    def table(self, name: str):
        return _Query(name, self._run)


def _portal(dsn):
    return _SignInDb(dsn, PORTAL_AUTH_1)


def _privileged(dsn):
    return _SignInDb(dsn, None)


def _pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)


# ── what the portal contact can and cannot read ─────────────────────────────────────────────────────────────────────

def test_the_contact_reads_their_invoice_and_its_customer_but_not_the_practices_row_the_lines_or_the_irn(db):
    portal = _portal(db)
    assert len(portal.table("client_sales_invoices").select("id").eq("id", INVOICE_1).execute().data) == 1
    assert len(portal.table("customers").select("id").eq("id", CUST1).execute().data) == 1
    assert portal.table("clients").select("id").eq("id", INTERNAL_CLIENT).execute().data == []
    assert portal.table("client_sales_invoice_lines").select("id").eq("sales_invoice_id", INVOICE_1).execute().data == []
    assert portal.table("einvoice_records").select("id").eq("sales_invoice_id", INVOICE_1).execute().data == []
    # and the privileged connection sees all three, so the empty answers above are row security and not a missing seed
    admin = _privileged(db)
    assert len(admin.table("clients").select("id").eq("id", INTERNAL_CLIENT).execute().data) == 1
    assert len(admin.table("client_sales_invoice_lines").select("id").eq("sales_invoice_id", INVOICE_1).execute().data) == 1
    assert len(admin.table("einvoice_records").select("id").eq("sales_invoice_id", INVOICE_1).execute().data) == 1


# ── the fee statement ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def internal_client(monkeypatch):
    import services.internal_client_service as internal_client_service

    monkeypatch.setattr(internal_client_service, "get_internal_client_id", lambda firm_id: INTERNAL_CLIENT)


def test_the_statement_pdf_is_produced_when_the_letterhead_is_read_with_the_privileged_client(db, internal_client):
    from services import portal_data_service

    pdf, filename = portal_data_service.statement_pdf(
        FIRM, EXT1, "2026-04-01", "2026-04-30", db=_portal(db), holder_db=_privileged(db))
    assert pdf[:4] == b"%PDF" and filename.startswith("statement-")
    assert "Practice Advisors LLP" in _pdf_text(pdf)


def test_the_statement_pdf_used_to_fail_and_still_does_when_the_letterhead_is_read_on_the_contacts_sign_in(db, internal_client):
    from services import portal_data_service

    portal = _portal(db)
    with pytest.raises(ValueError, match="not found"):
        portal_data_service.statement_pdf(FIRM, EXT1, "2026-04-01", "2026-04-30", db=portal, holder_db=portal)


def test_the_statement_route_path_uses_the_privileged_client_by_default(db, internal_client, monkeypatch):
    """No `holder_db` handed in: `statement_pdf` must reach for the privileged client itself, as the route does."""
    from core import db_provider
    from services import portal_data_service

    monkeypatch.setattr(db_provider, "service_db", lambda: _privileged(db))
    pdf, _ = portal_data_service.statement_pdf(FIRM, EXT1, "2026-04-01", "2026-04-30", db=_portal(db))
    assert "Practice Advisors LLP" in _pdf_text(pdf)


# ── the fee invoice ────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_invoice_pdf_is_produced_with_its_line_and_its_irn(db, monkeypatch):
    import core.supabase_client as supabase_client
    from services import invoice_pdf_service

    monkeypatch.setattr(supabase_client, "get_supabase", lambda: _portal(db))
    pdf, filename = invoice_pdf_service.get_sales_invoice_pdf(INVOICE_1, FIRM, rest_db=_privileged(db))
    assert pdf[:4] == b"%PDF" and filename == "invoice-FEE/0001.pdf"
    text = _pdf_text(pdf)
    assert LINE_TEXT in text, "the line items are what the client is being asked to pay for"
    assert "Practice Advisors LLP" in text
    assert IRN[:20] in text.replace("\n", ""), "the IRN printed on the document is the one the IRP issued"


def test_the_invoice_pdf_used_to_refuse_when_every_read_was_on_the_contacts_sign_in(db, monkeypatch):
    import core.supabase_client as supabase_client
    from services import invoice_pdf_service

    monkeypatch.setattr(supabase_client, "get_supabase", lambda: _portal(db))
    with pytest.raises(ValueError, match="Supplier record not found"):
        invoice_pdf_service.get_sales_invoice_pdf(INVOICE_1, FIRM)


def test_another_clients_invoice_is_not_found_even_with_the_privileged_client_handed_in(db, monkeypatch):
    """Row security on the invoice row, read on the contact's own sign-in, stays a second check on whose invoice it is."""
    import core.supabase_client as supabase_client
    from services import invoice_pdf_service

    monkeypatch.setattr(supabase_client, "get_supabase", lambda: _portal(db))
    with pytest.raises(ValueError, match="not found"):
        invoice_pdf_service.get_sales_invoice_pdf(INVOICE_2, FIRM, rest_db=_privileged(db))


# ── a draft is the practice's working copy, never the client's ──────────────────────────────────────────────────────

def test_a_draft_fee_invoice_is_neither_listed_nor_downloadable_by_the_client(db, internal_client):
    """Making the PDF work turned a draft's download from a 404 into a tax invoice carrying a placeholder number, and the
    list had always shown it. The portal serves what the client has been GIVEN: issued, part-paid, paid, or cancelled."""
    from services import portal_data_service

    portal = _portal(db)
    listed = {row["id"] for row in portal_data_service.list_invoices(FIRM, EXT1, db=portal)}
    assert INVOICE_1 in listed
    assert DRAFT_INVOICE not in listed, "the contact can read the draft row under row security; the service must not list it"
    assert portal.table("client_sales_invoices").select("id").eq("id", DRAFT_INVOICE).execute().data, \
        "premise: row security alone would have shown it"
    assert portal_data_service.invoice_in_scope(FIRM, EXT1, INVOICE_1, db=portal) is True
    assert portal_data_service.invoice_in_scope(FIRM, EXT1, DRAFT_INVOICE, db=portal) is False
