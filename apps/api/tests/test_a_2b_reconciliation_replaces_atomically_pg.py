"""Replacing a period's GSTR-2B reconciliation commits entirely or not at all.

WHAT THIS PROVES AND WHY IT NEEDS A REAL DATABASE

`reconcile_2b` used to replace a period with four separate PostgREST
statements — delete documents, insert documents, delete header, insert header —
and therefore four separate transactions. Anything interrupting the middle left
the period with its previous reconciliation DELETED and nothing in its place.

Both directions of harm are reachable and which one you get depends on where it
fails. Interrupted during the DOCUMENT insert, the documents are destroyed and
the PREVIOUS HEADER survives (it is deleted later), so `was_reconciled` is true
over zero documents and Rule 36(4) caps the month's ITC AT NIL. Interrupted
during the HEADER insert, the period reads back as never reconciled and nothing
caps, so the return claims credit §16(2)(aa) may withhold.

The first was measured on a real Postgres before this was written: a period
holding (1 document, 1 header) came back (0 documents, 1 header).

Atomicity is not something the mock suite can test: the in-memory FakeDB has no
transactions, so a test there would assert the property against a double that
cannot have it. Migration 366's `replace_gstr2b_reconciliation` is where the
guarantee lives, so this is where it is proved.

THE FAILURE IS INJECTED, not simulated. A document row carrying a
`purchase_bill_id` that no bill has violates the foreign key, so the INSERT
raises partway through — exactly the shape of a real interruption — and the
test then asserts the PREVIOUS reconciliation is still there, untouched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="atomicity can only be proved against a real Postgres",
)

FIRM = "f3660000-0000-0000-0000-000000000001"
OTHER_FIRM = "f3660000-0000-0000-0000-0000000000ff"
CLIENT = "c3660000-0000-0000-0000-000000000001"
PERIOD = "062026"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"recatom_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    seed = _psql(dsn, f"""
        INSERT INTO firms (id, name, email) VALUES
          ('{FIRM}', 'Atomic Recon', 'a@atomic.in'),
          ('{OTHER_FIRM}', 'Someone Else', 'b@atomic.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type)
          VALUES ('{CLIENT}', '{FIRM}', 'Atomic Co', 'Private Limited');
    """)
    assert seed.returncode == 0, seed.stderr
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _doc(number: str, *, doc_type: str = "INV", bill_id: str | None = None) -> dict:
    return {
        "section": "b2b", "document_type": doc_type,
        "supplier_gstin": "27AAAAA0000A1Z2", "supplier_name": "A Supplier",
        "supplier_trade_name": "A Supplier",
        "invoice_number": number, "invoice_date": "2026-06-10",
        "taxable_value_paise": 100000, "igst_paise": 18000,
        "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0,
        "invoice_value_paise": 118000,
        # "Y"/"N"/"" — the portal's own itcavl flag, and a str in
        # domain/gst/gstr2b.py because "2B did not say" is a third state.
        "itc_available": "Y", "is_amendment": False,
        "source": "upload", "match_status": "unmatched",
        "match_difference_paise": 0,
        **({"purchase_bill_id": bill_id} if bill_id else {}),
    }


def _header(**over) -> dict:
    h = {"gstin": "27AAAAA0000A1Z2", "file_return_period": PERIOD,
         "generated_on": "14-07-2026", "sections_seen": ["b2b"],
         "document_count": 0, "book_bill_count": 0,
         "parsed_ok": True, "problems": []}
    h.update(over)
    return h


def _replace(dsn: str, docs: list[dict], header: dict,
             firm: str = FIRM, client: str = CLIENT, period: str = PERIOD):
    return _psql(dsn, f"""
        SELECT public.replace_gstr2b_reconciliation(
            '{firm}'::uuid, '{client}'::uuid, '{period}',
            $j${json.dumps(docs)}$j$::jsonb,
            $h${json.dumps(header)}$h$::jsonb);
    """, tuples=True)


def _state(dsn: str) -> tuple[int, int, list[str]]:
    """(document rows, header rows, the document numbers) for the period."""
    r = _psql(dsn, f"""
        SELECT
          (SELECT count(*) FROM gstr2a_records
            WHERE firm_id = '{FIRM}' AND client_id = '{CLIENT}'
              AND return_period = '{PERIOD}'),
          (SELECT count(*) FROM gstr2b_reconciliations
            WHERE firm_id = '{FIRM}' AND client_id = '{CLIENT}'
              AND return_period = '{PERIOD}'),
          (SELECT coalesce(string_agg(invoice_number, ',' ORDER BY invoice_number), '')
             FROM gstr2a_records
            WHERE firm_id = '{FIRM}' AND client_id = '{CLIENT}'
              AND return_period = '{PERIOD}');
    """, tuples=True)
    assert r.returncode == 0, r.stderr
    docs, headers, numbers = r.stdout.strip().split("|")
    return int(docs), int(headers), [n for n in numbers.split(",") if n]


# ── the ordinary path ────────────────────────────────────────────────────────

def test_documents_and_header_land_together(db):
    r = _replace(db, [_doc("INV-1"), _doc("INV-2")], _header(document_count=2))
    assert r.returncode == 0, r.stderr
    assert _state(db) == (2, 1, ["INV-1", "INV-2"])


def test_a_header_is_written_even_with_no_documents(db):
    """A 2B in which nobody filed anything is a reconciliation that HAPPENED,
    and it must cap ITC at nil. That is the whole reason migration 341 exists,
    and losing it here would undo it."""
    r = _replace(db, [], _header())
    assert r.returncode == 0, r.stderr
    assert _state(db) == (0, 1, [])


def test_a_re_upload_replaces_rather_than_accumulating(db):
    assert _replace(db, [_doc("INV-1"), _doc("INV-2")], _header(document_count=2)).returncode == 0
    assert _replace(db, [_doc("INV-9")], _header(document_count=1)).returncode == 0
    assert _state(db) == (1, 1, ["INV-9"])


def test_a_credit_and_a_debit_note_may_share_a_number(db):
    """uq_gstr2a_records_document carries document_type since migration 341: a
    supplier numbers their credit-note and debit-note series independently, and
    the same number in both is ordinary."""
    r = _replace(db, [_doc("CN-1", doc_type="C"), _doc("CN-1", doc_type="D")],
                 _header(document_count=2))
    assert r.returncode == 0, r.stderr
    assert _state(db)[0] == 2


# ── the point of the migration ───────────────────────────────────────────────

def test_a_failed_replace_leaves_the_previous_reconciliation_intact(db):
    """THE DEFECT THIS CLOSES.

    A document referencing a purchase bill that does not exist violates the
    foreign key, so the INSERT raises partway through — the shape of any real
    interruption. Before migration 366 the DELETE had already committed and the
    period was destroyed.
    """
    assert _replace(db, [_doc("INV-1"), _doc("INV-2")], _header(document_count=2)).returncode == 0
    before = _state(db)
    assert before == (2, 1, ["INV-1", "INV-2"])

    ghost = "b3660000-0000-0000-0000-0000000000aa"
    failed = _replace(db, [_doc("INV-7"), _doc("INV-8", bill_id=ghost)],
                      _header(document_count=2))
    assert failed.returncode != 0, "a dangling purchase_bill_id must not be accepted"

    assert _state(db) == before, (
        "the previous reconciliation was destroyed by a replace that then "
        "failed — which is exactly the window migration 366 closes, and it "
        "reads back as NEVER RECONCILED, so Rule 36(4) does not cap")


def test_a_failed_replace_does_not_leave_a_header_over_no_documents(db):
    """THE SHARPER HALF, and the one measurement corrected the prose about.

    The old path deleted the documents first and the header LAST, so a failure
    in between left the previous header standing over an empty document set.
    `was_reconciled` then answers TRUE — a 2B was reconciled — while the totals
    it is read with are zero, so gstr3b_computer caps the month's ITC at NIL and
    the CA is told their client may claim no input credit at all.

    That is a wrong figure on a return, not merely a lost record, and it is why
    this case is asserted separately from the "nothing was written" one: a
    period can be half-written in two shapes and only one of them is empty.
    """
    assert _replace(db, [_doc("INV-1")], _header(document_count=1)).returncode == 0

    ghost = "b3660000-0000-0000-0000-0000000000cc"
    assert _replace(db, [_doc("INV-5", bill_id=ghost)], _header(document_count=1)).returncode != 0

    docs, headers, _ = _state(db)
    assert not (headers == 1 and docs == 0), (
        "a header survives over zero documents: was_reconciled() says this "
        "period WAS reconciled, the 2B totals read as nil, and Rule 36(4) then "
        "caps the whole month's ITC at nil")
    assert (docs, headers) == (1, 1), "and the original reconciliation must be intact"


def test_a_failed_replace_does_not_leave_a_period_half_written(db):
    """From nothing, too: a first upload that fails must write NOTHING, not a
    partial document set with no header."""
    ghost = "b3660000-0000-0000-0000-0000000000bb"
    failed = _replace(db, [_doc("INV-1"), _doc("INV-2", bill_id=ghost)], _header())
    assert failed.returncode != 0
    assert _state(db) == (0, 0, [])


# ── the tenant boundary, because it is SECURITY DEFINER ──────────────────────

def test_the_payload_cannot_address_another_firm(db):
    """The function runs with the definer's rights, so RLS does not protect it.
    firm_id, client_id and return_period come from the PARAMETERS; a payload
    naming another firm is ignored rather than honoured."""
    doc = _doc("INV-1")
    doc.update({"firm_id": OTHER_FIRM, "client_id": CLIENT, "return_period": "012026"})
    assert _replace(db, [doc], _header(document_count=1)).returncode == 0

    r = _psql(db, f"""
        SELECT count(*) FROM gstr2a_records WHERE firm_id = '{OTHER_FIRM}';
    """, tuples=True)
    assert r.stdout.strip() == "0", "a document row reached another firm"
    assert _state(db) == (1, 1, ["INV-1"]), "and it must have landed where asked"


def test_replacing_one_firms_period_leaves_another_firms_alone(db):
    """The DELETE is the destructive half, so it must be firm-scoped."""
    other_client = "c3660000-0000-0000-0000-0000000000ff"
    assert _psql(db, f"""
        INSERT INTO clients (id, firm_id, client_name, entity_type)
          VALUES ('{other_client}', '{OTHER_FIRM}', 'Other Co', 'Private Limited');
    """).returncode == 0
    assert _replace(db, [_doc("INV-1")], _header(document_count=1),
                    firm=OTHER_FIRM, client=other_client).returncode == 0
    assert _replace(db, [_doc("INV-2")], _header(document_count=1)).returncode == 0

    r = _psql(db, f"""
        SELECT count(*) FROM gstr2a_records WHERE firm_id = '{OTHER_FIRM}';
    """, tuples=True)
    assert r.stdout.strip() == "1", "the other firm's reconciliation was deleted"


# ── refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("period", ["", "   "])
def test_a_blank_period_is_refused(db, period):
    """A blank period would delete nothing and then write a header nothing can
    find — a reconciliation recorded against no month at all."""
    assert _replace(db, [], _header(), period=period).returncode != 0


def test_a_header_that_is_not_an_object_is_refused(db):
    r = _psql(db, f"""
        SELECT public.replace_gstr2b_reconciliation(
            '{FIRM}'::uuid, '{CLIENT}'::uuid, '{PERIOD}',
            '[]'::jsonb, '[]'::jsonb);
    """, tuples=True)
    assert r.returncode != 0, "a header must be exactly one object"
