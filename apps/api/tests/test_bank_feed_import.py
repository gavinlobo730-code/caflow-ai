"""
Banking B.1 — Bank Feed Foundation tests.

Covers: CSV import, XLSX import, malformed files, duplicate files, duplicate
rows, and large imports. Exercises the pure normalizer + dedup and the
banking_service import core against an in-memory fake Supabase client.
"""
import io
import pytest

from domain.banking import (
    parse_statement, parse_csv, detect_format, StatementParseError,
    transaction_hash, file_hash,
)
import services.banking_service as bsvc
from services.banking_service import banking_service


# ── In-memory fake Supabase (only what the import core / reads use) ───────────

class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store, table):
        self._store = store
        self._table = table
        self._eq = []
        self._in = None
        self._gte = []
        self._lte = []
        self._payload = None
        self._op = None

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def eq(self, k, v):
        self._eq.append((k, v))
        return self

    def in_(self, k, vals):
        self._in = (k, list(vals))
        return self

    def gte(self, k, v):
        self._gte.append((k, v))
        return self

    def lte(self, k, v):
        self._lte.append((k, v))
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        rows = self._store.setdefault(self._table, [])
        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for p in payload:
                rec = dict(p)
                rec.setdefault("id", f"{self._table}-{len(rows) + 1}")
                rows.append(rec)
                inserted.append(rec)
            return _Resp(inserted)
        # select
        out = rows
        for k, v in self._eq:
            out = [r for r in out if r.get(k) == v]
        if self._in:
            k, vals = self._in
            vs = set(vals)
            out = [r for r in out if r.get(k) in vs]
        for k, v in self._gte:
            out = [r for r in out if str(r.get(k)) >= str(v)]
        for k, v in self._lte:
            out = [r for r in out if str(r.get(k)) <= str(v)]
        return _Resp(list(out))


class FakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Query(self.store, name)


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    # Timeline/audit writes hit external services — make them no-ops in tests.
    monkeypatch.setattr(bsvc.timeline_service, "log", lambda *a, **k: None)
    yield


FIRM, CLIENT = "firm-1", "client-1"


# ── Normalizer: CSV ───────────────────────────────────────────────────────────

def test_csv_generic_parse():
    csv = "Date,Description,Debit,Credit,Balance\n01/04/2026,Opening,,1000.00,1000.00\n05/04/2026,ATM,500.00,,500.00\n"
    txns = parse_csv(csv)
    assert len(txns) == 2
    assert txns[0].transaction_date == "2026-04-01"
    assert txns[0].credit_paise == 100000 and txns[0].debit_paise == 0
    assert txns[1].debit_paise == 50000 and txns[1].balance_paise == 50000


def test_csv_hdfc_format_detected():
    csv = ("Date,Narration,Value Dt,Chq/Ref No,Debit,Credit,Balance\n"
           "01-04-2026,NEFT IN,01-04-2026,REF1,,11800.00,11800.00\n")
    assert detect_format(["Date", "Narration", "Value Dt", "Chq/Ref No", "Debit", "Credit", "Balance"]) == "hdfc"
    txns = parse_csv(csv)
    assert len(txns) == 1 and txns[0].credit_paise == 1180000 and txns[0].reference_no == "REF1"


def test_csv_integer_paise_no_float_drift():
    # 0.1 + 0.2 style values must be exact in paise.
    csv = "Date,Description,Debit,Credit,Balance\n01/04/2026,x,0.10,,0.10\n02/04/2026,y,0.20,,0.20\n"
    txns = parse_csv(csv)
    assert txns[0].debit_paise == 10 and txns[1].debit_paise == 20


def test_parse_statement_dispatch_csv():
    content = b"Date,Description,Debit,Credit,Balance\n01/04/2026,x,,100.00,100.00\n"
    txns = parse_statement("hdfc_apr.csv", content)
    assert len(txns) == 1


# ── Normalizer: XLSX ──────────────────────────────────────────────────────────

def _xlsx_bytes(rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_parse():
    content = _xlsx_bytes([
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["01/04/2026", "Opening", None, 1000.00, 1000.00],
        ["05/04/2026", "Rent", 500.00, None, 500.00],
    ])
    txns = parse_statement("statement.xlsx", content)
    assert len(txns) == 2
    assert txns[0].credit_paise == 100000
    assert txns[1].debit_paise == 50000


# ── Malformed files ───────────────────────────────────────────────────────────

def test_unsupported_extension_raises():
    with pytest.raises(StatementParseError):
        parse_statement("statement.pdf", b"%PDF-1.4")


def test_csv_without_transactions_raises():
    with pytest.raises(StatementParseError):
        parse_csv("Date,Description,Debit,Credit,Balance\n")  # header only


def test_garbage_xlsx_raises():
    with pytest.raises(StatementParseError):
        parse_statement("x.xlsx", b"not a real xlsx")


# ── Dedup hashing ─────────────────────────────────────────────────────────────

def test_transaction_hash_deterministic_and_balance_sensitive():
    a = transaction_hash(CLIENT, None, "2026-04-01", 0, 100000, 100000, "NEFT", "R1")
    b = transaction_hash(CLIENT, None, "2026-04-01", 0, 100000, 100000, "NEFT", "R1")
    c = transaction_hash(CLIENT, None, "2026-04-01", 0, 100000, 200000, "NEFT", "R1")  # diff balance
    assert a == b and a != c


def test_file_hash_changes_with_content():
    assert file_hash(b"abc") == file_hash(b"abc")
    assert file_hash(b"abc") != file_hash(b"abd")


# ── Service import core: dedup + idempotency + large + duplicate file ─────────

def _txns_from_csv(csv):
    return parse_csv(csv)


def test_import_dedups_duplicate_rows_within_file():
    db = FakeDB()
    csv = ("Date,Description,Debit,Credit,Balance\n"
           "01/04/2026,DUP,500.00,,500.00\n"
           "01/04/2026,DUP,500.00,,500.00\n")   # identical row twice
    res = banking_service.import_normalized(db, FIRM, CLIENT, "HDFC", "123", _txns_from_csv(csv))
    assert res["imported"] == 1
    assert res["duplicates_skipped"] == 1
    assert len(db.store["bank_transactions"]) == 1


def test_reimport_same_file_is_idempotent():
    db = FakeDB()
    csv = ("Date,Description,Debit,Credit,Balance\n"
           "01/04/2026,A,500.00,,500.00\n"
           "02/04/2026,B,,700.00,1200.00\n")
    first = banking_service.import_normalized(db, FIRM, CLIENT, "HDFC", "123", _txns_from_csv(csv))
    assert first["imported"] == 2
    second = banking_service.import_normalized(db, FIRM, CLIENT, "HDFC", "123", _txns_from_csv(csv))
    assert second["imported"] == 0
    assert second["duplicates_skipped"] == 2
    assert second["statement_id"] is None
    assert len(db.store["bank_transactions"]) == 2  # unchanged


def test_distinct_same_day_same_amount_kept():
    db = FakeDB()
    # same date/amount/desc but different running balance → distinct txns.
    csv = ("Date,Description,Debit,Credit,Balance\n"
           "01/04/2026,ATM,500.00,,9500.00\n"
           "01/04/2026,ATM,500.00,,9000.00\n")
    res = banking_service.import_normalized(db, FIRM, CLIENT, "HDFC", "123", _txns_from_csv(csv))
    assert res["imported"] == 2


def test_large_import_chunks_all_rows():
    db = FakeDB()
    lines = ["Date,Description,Debit,Credit,Balance"]
    bal = 0
    for i in range(1500):
        bal += 1
        lines.append(f"01/04/2026,TXN{i},,1.00,{bal}.00")
    res = banking_service.import_normalized(db, FIRM, CLIENT, "HDFC", "123", parse_csv("\n".join(lines)))
    assert res["imported"] == 1500
    assert len(db.store["bank_transactions"]) == 1500


def test_duplicate_file_second_upload_adds_nothing():
    db = FakeDB()
    csv = ("Date,Description,Debit,Credit,Balance\n"
           "01/04/2026,A,500.00,,500.00\n")
    fm = {"file_name": "s.csv", "file_size_bytes": 10, "source_format": "csv", "file_hash": file_hash(csv.encode())}
    banking_service.import_normalized(db, FIRM, CLIENT, "HDFC", "123", parse_csv(csv), file_meta=fm)
    res2 = banking_service.import_normalized(db, FIRM, CLIENT, "HDFC", "123", parse_csv(csv), file_meta=fm)
    assert res2["imported"] == 0 and res2["duplicates_skipped"] == 1
    assert len(db.store["bank_statements"]) == 1  # no empty second statement


def test_empty_rows_rejected():
    db = FakeDB()
    with pytest.raises(Exception):
        banking_service.import_normalized(db, FIRM, CLIENT, "HDFC", "123", [])
