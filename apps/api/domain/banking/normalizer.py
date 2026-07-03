"""
Bank statement normalization engine (Banking B.1, Part C).

Converts CSV / XLSX exports from Indian banks into ONE internal format
(NormalizedTxn: date, description, reference, debit, credit, balance). All
bank-specific column layouts live in `_ADAPTERS` — no bank-specific logic exists
anywhere else (the dispatcher and parsers are format-agnostic).

Money is integer paise via Decimal (never binary float — CLAUDE.md). Dates are
normalised to ISO YYYY-MM-DD.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional


class StatementParseError(ValueError):
    """Raised when a file cannot be parsed into transactions (malformed / unsupported)."""


@dataclass(frozen=True)
class NormalizedTxn:
    transaction_date: str          # ISO YYYY-MM-DD
    description: str
    reference_no: Optional[str]
    debit_paise: int
    credit_paise: int
    balance_paise: int


# ── Bank adapters — the ONLY place that knows bank-specific column layouts ─────
# Each adapter maps a detected format to 0-based column indices. "ref"/"balance"
# may be None when a bank export omits them. An adapter with an "amount" key
# (instead of separate "debit"/"credit" keys) uses a single signed-amount
# column plus a separate Dr/Cr indicator column — see "generic_amount_drcr".
_ADAPTERS: dict[str, dict[str, Optional[int]]] = {
    # Date, Narration, Value Dt, Ref No, Debit, Credit, Balance
    "hdfc":    {"date": 0, "desc": 1, "ref": 3, "debit": 4, "credit": 5, "balance": 6},
    # Txn Date, Value Date, Description, Ref/Cheque No, Debit, Credit, Balance
    "sbi":     {"date": 0, "desc": 2, "ref": 3, "debit": 4, "credit": 5, "balance": 6},
    # Transaction Date, Value Date, Transaction Remarks, Ref No, Debit, Credit, Balance
    "icici":   {"date": 0, "desc": 2, "ref": 3, "debit": 4, "credit": 5, "balance": 6},
    # Tran Date, CHQNO, Narration, Debit, Credit, Balance
    "axis":    {"date": 0, "ref": 1, "desc": 2, "debit": 3, "credit": 4, "balance": 5},
    # Generic: Date, Description, Debit, Credit, Balance
    "generic": {"date": 0, "desc": 1, "ref": None, "debit": 2, "credit": 3, "balance": 4},
    # R2.11: some exports use ONE signed-amount column plus a separate Dr/Cr
    # indicator instead of separate Debit/Credit columns — Date, Description,
    # Amount, Dr/Cr, Balance. Previously unsupported: every row misparsed as a
    # debit (the fixed debit/credit indices pointed at the wrong columns, or
    # at nothing at all).
    "generic_amount_drcr": {
        "date": 0, "desc": 1, "ref": None,
        "debit": None, "credit": None, "amount": 2, "drcr": 3, "balance": 4,
    },
}


def detect_format(headers: list[str]) -> str:
    """Pick a bank adapter from the header row.

    Order matters (F8): a cheque/reference column exists under DIFFERENT names in
    several banks — HDFC "Chq/Ref No", Axis "CHQNO", SBI "Ref/Cheque No" — so the
    generic "chq"/"cheque" heuristic must run LAST. Matching it first routed every
    Axis and SBI statement to the HDFC adapter, and Axis's different column order
    then corrupted debit/credit direction and amounts (a ₹500 debit became a
    ₹10,000 credit). Bank-specific date/remarks columns are the reliable
    discriminators, so they are tested first, most-specific to least.
    """
    h = [str(x).lower().strip() for x in headers]
    blob = " ".join(h)
    # A combined Dr/Cr indicator column header is an unambiguous signal for the
    # single-amount layout — distinct from having separate Debit AND Credit
    # columns — so it's checked first, same as ICICI's equally unambiguous
    # "transaction remarks" signal below.
    if any(re.fullmatch(r"dr\s*/\s*cr|dr\s+or\s+cr|cr\s*/\s*dr", x) for x in h):
        return "generic_amount_drcr"
    if "transaction remarks" in blob:      # ICICI ("Transaction Remarks")
        return "icici"
    if "txn date" in blob:                 # SBI ("Txn Date")
        return "sbi"
    if "tran date" in blob:                # Axis ("Tran Date"); note: distinct
        return "axis"                      # from SBI "txn date" and ICICI "transaction date"
    if "narration" in blob or "chq" in blob or "cheque" in blob:  # HDFC (shared cheque/narration signal, last)
        return "hdfc"
    return "generic"


_DEBIT_TOKENS = ("debit", "withdrawal", "withdraw")
_CREDIT_TOKENS = ("credit", "deposit")
_DRCR_HEADER_TOKENS = ("dr", "cr", "type")


def _validate_adapter(fmt: str, headers: list[str]) -> None:
    """Fail loud when the detected adapter does not actually fit the header.

    detect_format uses fuzzy header signals; if a file's real layout differs from
    the chosen adapter — an unsupported bank, or a variant with a shifted column
    order — the fixed index map would silently read debit/credit off the wrong
    columns (the F8 class of corruption). So verify the adapter fits: every mapped
    column exists within the header width, and the debit/credit columns really are
    labelled debit/withdrawal and credit/deposit. Otherwise raise, so a CA sees an
    'unsupported format' error instead of silently wrong numbers.
    """
    a = _ADAPTERS[fmt]
    n = len(headers)
    low = [str(x).lower().strip() for x in headers]
    for key, idx in a.items():
        if idx is not None and idx >= n:
            raise StatementParseError(
                f"Bank statement layout doesn't match the detected '{fmt}' format "
                f"(needs a '{key}' column at position {idx + 1}, but the file has {n} columns). "
                "Supported: HDFC, SBI, ICICI, Axis, a generic "
                "Date/Description/Debit/Credit/Balance CSV, or a generic "
                "Date/Description/Amount/Dr-Cr/Balance CSV."
            )
    if a.get("amount") is not None:
        ai, di = a["amount"], a["drcr"]
        amount_hdr = low[ai] if ai is not None and ai < n else ""
        drcr_hdr = low[di] if di is not None and di < n else ""
        if "amount" not in amount_hdr or not any(t in drcr_hdr for t in _DRCR_HEADER_TOKENS):
            raise StatementParseError(
                "Unsupported bank statement format — could not identify the amount "
                "and Dr/Cr columns. Supported: HDFC, SBI, ICICI, Axis, a generic "
                "Date/Description/Debit/Credit/Balance CSV, or a generic "
                "Date/Description/Amount/Dr-Cr/Balance CSV."
            )
        return
    di, ci = a["debit"], a["credit"]
    debit_hdr = low[di] if di is not None and di < n else ""
    credit_hdr = low[ci] if ci is not None and ci < n else ""
    if not any(t in debit_hdr for t in _DEBIT_TOKENS) or not any(t in credit_hdr for t in _CREDIT_TOKENS):
        raise StatementParseError(
            "Unsupported bank statement format — could not identify the debit and "
            "credit columns. Supported: HDFC, SBI, ICICI, Axis, a generic "
            "Date/Description/Debit/Credit/Balance CSV, or a generic "
            "Date/Description/Amount/Dr-Cr/Balance CSV."
        )


# ── value parsers ─────────────────────────────────────────────────────────────

_MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _to_iso_date(val) -> Optional[str]:
    """Normalise a date cell to ISO YYYY-MM-DD, or None if unrecognised."""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.date().isoformat() if isinstance(val, datetime) else val.isoformat()
    s = str(val).strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{2})[/\-](\d{2})[/\-](\d{4})", s)       # DD/MM/YYYY or DD-MM-YYYY
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):                      # already ISO
        return s
    m = re.fullmatch(r"(\d{2})[ \-]([A-Za-z]{3})[ \-](\d{4})", s)  # DD MMM YYYY
    if m:
        mon = _MONTHS.get(m.group(2).lower())
        if mon:
            return f"{m.group(3)}-{mon}-{m.group(1)}"
    return None


_DRCR_SUFFIX_RE = re.compile(r"(dr|cr)$", re.IGNORECASE)


def _to_paise(val) -> int:
    """Parse a money cell to integer paise. Empty / '-' → 0. Never uses float.

    R2.11: a trailing Dr/Cr suffix is common across Indian bank exports in ANY
    case ('Dr', 'DR', 'dr', 'Cr', 'CR', 'cr') — the previous `.rstrip("DrCr")`
    stripped individual CHARACTERS 'D','r','C' (case-sensitive, so it happened
    to handle mixed-case "Dr"/"Cr" but silently zeroed every other case
    variant, since e.g. "150.00DR" has no matching trailing chars to strip and
    Decimal("150.00DR") then raises, caught below, returning 0). Fixed via a
    case-insensitive regex match on the two-letter suffix itself.

    The suffix also carries sign information a bank statement's BALANCE column
    relies on: "Dr" denotes an overdrawn (negative) balance, "Cr" a normal
    (positive) one — previously discarded entirely (both suffixes were just
    stripped, so a "Dr" balance was stored as if it were positive/"Cr"). The
    debit_paise/credit_paise columns wrap this in abs() at the call site, so
    applying the sign here is harmless for them and only matters for balance.
    """
    if val is None:
        return 0
    if isinstance(val, (int,)):
        return int(val) * 100
    if isinstance(val, float):
        return int((Decimal(str(val)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    s = str(val).strip()
    if s in ("", "-"):
        return 0
    s = re.sub(r"[₹,\s]", "", s)
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    m = _DRCR_SUFFIX_RE.search(s)
    drcr = None
    if m:
        drcr = m.group(1).lower()
        s = s[:m.start()]
    if not s:
        return 0
    try:
        paise = int((Decimal(s) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return 0
    if drcr == "dr":
        neg = True
    elif drcr == "cr":
        neg = False
    return -paise if neg else paise


def _looks_like_header(cells: list[str]) -> bool:
    low = " ".join(str(c).lower() for c in cells)
    return "date" in low and ("debit" in low or "amount" in low or "withdrawal" in low or "credit" in low)


_INDICATOR_DEBIT_TOKENS = ("d", "dr", "debit", "withdrawal")
_INDICATOR_CREDIT_TOKENS = ("c", "cr", "credit", "deposit")


def _rows_to_txns(rows: list[list], header_idx: int) -> list[NormalizedTxn]:
    headers = [str(c) for c in rows[header_idx]]
    fmt = detect_format(headers)
    _validate_adapter(fmt, headers)
    a = _ADAPTERS[fmt]
    amount_mode = a.get("amount") is not None
    out: list[NormalizedTxn] = []
    for cells in rows[header_idx + 1:]:
        if not cells or len([c for c in cells if str(c).strip()]) < 3:
            continue

        def col(key: str):
            i = a.get(key)
            if i is None or i >= len(cells):
                return None
            return cells[i]

        iso = _to_iso_date(col("date"))
        desc = (str(col("desc")).strip() if col("desc") is not None else "")
        if not iso or not desc:
            continue  # skip non-transaction rows (totals, blanks, sub-headers)
        ref = col("ref")

        if amount_mode:
            # R2.11: single signed-amount + separate Dr/Cr indicator column —
            # classify by the indicator rather than by column position, since
            # there is no separate debit/credit column to read.
            amount = abs(_to_paise(col("amount")))
            indicator = str(col("drcr") or "").strip().lower()
            is_debit = indicator in _INDICATOR_DEBIT_TOKENS
            is_credit = indicator in _INDICATOR_CREDIT_TOKENS
            if amount == 0 or (not is_debit and not is_credit):
                continue  # can't classify this row's direction — skip rather than guess
            debit_paise = amount if is_debit else 0
            credit_paise = amount if is_credit else 0
        else:
            debit_paise = abs(_to_paise(col("debit")))
            credit_paise = abs(_to_paise(col("credit")))

        out.append(NormalizedTxn(
            transaction_date=iso,
            description=desc,
            reference_no=(str(ref).strip() or None) if ref is not None else None,
            debit_paise=debit_paise,
            credit_paise=credit_paise,
            balance_paise=_to_paise(col("balance")),
        ))
    return out


def _find_header_idx(rows: list[list]) -> int:
    for i, cells in enumerate(rows[:10]):
        if _looks_like_header([str(c) for c in cells]):
            return i
    return 0


def parse_csv(text: str) -> list[NormalizedTxn]:
    text = text.lstrip("﻿")  # strip BOM
    reader = list(csv.reader(io.StringIO(text)))
    rows = [r for r in reader if any(str(c).strip() for c in r)]
    if len(rows) < 2:
        raise StatementParseError("File has no data rows.")
    txns = _rows_to_txns(rows, _find_header_idx(rows))
    if not txns:
        raise StatementParseError("No transactions found — check the file format/columns.")
    return txns


def parse_xlsx(content: bytes) -> list[NormalizedTxn]:
    try:
        from openpyxl import load_workbook  # lazy — only needed for XLSX
    except ImportError as e:  # pragma: no cover
        raise StatementParseError("XLSX support is unavailable on the server.") from e
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:
        raise StatementParseError("File is not a valid XLSX workbook.") from e
    ws = wb.active
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    rows = [r for r in rows if any(c is not None and str(c).strip() for c in r)]
    if len(rows) < 2:
        raise StatementParseError("Workbook has no data rows.")
    txns = _rows_to_txns(rows, _find_header_idx(rows))
    if not txns:
        raise StatementParseError("No transactions found — check the file format/columns.")
    return txns


def parse_statement(filename: str, content: bytes) -> list[NormalizedTxn]:
    """Dispatch by extension. Raises StatementParseError on unsupported/malformed."""
    name = (filename or "").lower().strip()
    if name.endswith(".csv"):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")
        return parse_csv(text)
    if name.endswith(".xlsx"):
        return parse_xlsx(content)
    raise StatementParseError("Unsupported file type — upload a .csv or .xlsx bank statement.")
