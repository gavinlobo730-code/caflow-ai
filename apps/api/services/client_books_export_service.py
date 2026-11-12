"""A Partner's export of ONE client's books as a ZIP of CSV files with a manifest (POST-A-205, slice 1).

WHAT IT IS, AND WHAT IT IS NOT
    "What happens if you shut down?" is the question a firm asks before it moves its practice here, and the honest answer used to be "take the per-report PDFs".
    This is the first part of a real answer: the client's chart of accounts, customers and vendors, every journal entry and line, the sales and purchase
    documents with their lines, the receipts and vendor payments with their allocations and the TDS register, as plain CSV, with a manifest that names every
    file, its row count and its SHA-256, and a trial balance computed FROM THE FILES so the person who receives them can check the books add up without us.
    It is NOT the whole client. Payroll, the bank, document bytes, the audit log, GST return JSON, fixed assets, stock, PDFs and the whole-firm scope are not
    in it, and `manifest.json` and `README.txt` say so in words, because an export that looks complete and is not is worse than none.

WHY THE SHAPE
    * ONE PAGE IN MEMORY. A ledger of 12,836 entries and 32,936 lines is the largest client measured. Every table is read through `core.db_paging.iter_pages`
      (keyset pages of one request) and written to the ZIP as it comes; the ZIP is a spooled temporary file. A table is never held whole. The children of a document
      (its lines, a receipt's allocations) are read in a second pass over the parent ids, 150 parents at a time and page by page, because a ZIP can have only one
      member open for writing at a time. The deadline is checked between requests, so one slow request can run past it by its own length.
    * NOT A SNAPSHOT. The reads are many requests, not one transaction. Each file's rows are counted before it is read and compared with the rows written, and a
      difference is named in the manifest and in the response, never smoothed over: it means either that a row was added or removed while the export ran or that a
      read was cut short, and the person can tell which only by running it again.
    * BOUNDED, IN WORDS. A client with more entries than `MAX_JOURNAL_ENTRIES` (or more rows in all than `MAX_ROWS`) is REFUSED before anything is read, and a build
      still running at `DEADLINE_SECONDS` is stopped: the gunicorn timeout is 120 seconds on one worker, and a request killed there is silence, which is the one
      thing an export may not be. Both are 422/503 with a sentence and nothing is downloaded. An asynchronous job is the next slice.
    * EVERY ROW, WHATEVER ITS STATE. Drafts, reversed and soft-deleted rows are exported with the columns that say so (`is_posted`, `deleted_at`, `status`), so
      the trial balance can be recomputed by the recipient's own rule. The derived trial balance counts posted, non-deleted entries only, as the report does.
    * PAISE, FAITHFULLY. Money columns are the integers the database holds. A TEXT cell that begins with `=`, `+`, `-` or `@` (a narration is typed by a stranger)
      gets a leading apostrophe so a spreadsheet does not run it as a formula; numbers are never touched, and the manifest counts the cells it prefixed.

Pure with respect to the request: it takes a database client, a firm and a client, and returns bytes and a manifest, so the asynchronous job can wrap it.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Iterable, Optional

from core.db_paging import IN_CHUNK, iter_pages
from core.ist_clock import ist_now
from domain.money_sentence import rupee_text
from domain.reporting.export_document import ExportRefused

_logger = logging.getLogger("caflow.data_export")

SCHEMA = "practicesync-books-export/1"

#: Refused above this many journal entries (the largest client measured has 12,836) or this many rows in all.
MAX_JOURNAL_ENTRIES = 25_000
MAX_ROWS = 400_000
#: Stopped here: the web server's own timeout is 120 seconds on one worker, and a request killed by it says nothing.
DEADLINE_SECONDS = 90



class ExportStopped(ExportRefused):
    """The build ran out of time. A 503: nothing is wrong with the request, and the person can try again."""


@dataclass(frozen=True)
class Child:
    """The rows that hang from a parent by a foreign key and carry no firm or client of their own."""
    file: str
    fk: str
    read: Callable[[Any], Any]   # db -> a builder with the table and the projection `*` and nothing else


@dataclass(frozen=True)
class Section:
    """One parent table, read with the firm and the client on every request. `reads` is more than one only where a file is the union of two scopes."""
    file: str
    reads: tuple[Callable[..., Any], ...]   # (db, firm_id, client_id, columns, **select_kwargs) -> builder
    children: tuple[Child, ...] = ()
    #: Columns read but not written: a column that holds another kind of data than the file is named for. Named in the manifest.
    drop: frozenset = frozenset()


# One literal chain per table, written out, so the firm-scope reader can see each one carries the firm and the client.
_SECTIONS: tuple[Section, ...] = (
    Section("chart_of_accounts.csv", (
        lambda db, f, c, cols, **kw: db.table("chart_of_accounts").select(cols, **kw).eq("firm_id", f).eq("client_id", c),
        # An account with no client is the firm's own and may sit on any of the firm's entries, so the books are not readable without it.
        lambda db, f, c, cols, **kw: db.table("chart_of_accounts").select(cols, **kw).eq("firm_id", f).is_("client_id", "null"),
    )),
    Section("customers.csv", (
        lambda db, f, c, cols, **kw: db.table("customers").select(cols, **kw).eq("firm_id", f).eq("client_id", c),)),
    Section("vendors.csv", (
        lambda db, f, c, cols, **kw: db.table("vendors").select(cols, **kw).eq("firm_id", f).eq("client_id", c),)),
    Section("journal_entries.csv", (
        lambda db, f, c, cols, **kw: db.table("journal_entries").select(cols, **kw).eq("firm_id", f).eq("client_id", c),),
        (Child("journal_lines.csv", "journal_entry_id", lambda db: db.table("journal_lines").select("*")),)),
    Section("sales_invoices.csv", (
        lambda db, f, c, cols, **kw: db.table("client_sales_invoices").select(cols, **kw).eq("firm_id", f).eq("client_id", c),),
        (Child("sales_invoice_lines.csv", "sales_invoice_id", lambda db: db.table("client_sales_invoice_lines").select("*")),)),
    Section("purchase_bills.csv", (
        lambda db, f, c, cols, **kw: db.table("purchase_bills").select(cols, **kw).eq("firm_id", f).eq("client_id", c),),
        (Child("purchase_bill_lines.csv", "bill_id", lambda db: db.table("purchase_bill_lines").select("*")),)),
    Section("credit_notes.csv", (
        lambda db, f, c, cols, **kw: db.table("credit_notes").select(cols, **kw).eq("firm_id", f).eq("client_id", c),),
        (Child("credit_note_lines.csv", "credit_note_id", lambda db: db.table("credit_note_lines").select("*")),)),
    Section("debit_notes.csv", (
        lambda db, f, c, cols, **kw: db.table("debit_notes").select(cols, **kw).eq("firm_id", f).eq("client_id", c),),
        (Child("debit_note_lines.csv", "debit_note_id", lambda db: db.table("debit_note_lines").select("*")),)),
    Section("sales_debit_notes.csv", (
        lambda db, f, c, cols, **kw: db.table("sales_debit_notes").select(cols, **kw).eq("firm_id", f).eq("client_id", c),),
        (Child("sales_debit_note_lines.csv", "debit_note_id", lambda db: db.table("sales_debit_note_lines").select("*")),)),
    Section("purchase_credit_notes.csv", (
        lambda db, f, c, cols, **kw: db.table("purchase_credit_notes").select(cols, **kw).eq("firm_id", f).eq("client_id", c),),
        (Child("purchase_credit_note_lines.csv", "credit_note_id", lambda db: db.table("purchase_credit_note_lines").select("*")),)),
    Section("receipts.csv", (
        lambda db, f, c, cols, **kw: db.table("receipts").select(cols, **kw).eq("firm_id", f).eq("client_id", c),),
        (Child("receipt_allocations.csv", "receipt_id", lambda db: db.table("receipt_allocations").select("*")),)),
    Section("purchase_payments.csv", (
        lambda db, f, c, cols, **kw: db.table("purchase_payments").select(cols, **kw).eq("firm_id", f).eq("client_id", c),),
        (Child("purchase_payment_allocations.csv", "purchase_payment_id", lambda db: db.table("purchase_payment_allocations").select("*")),)),
    Section("tds_deductions.csv", (
        lambda db, f, c, cols, **kw: db.table("tds_deductions").select(cols, **kw).eq("firm_id", f).eq("client_id", c),)),
    Section("tds_challans.csv", (
        lambda db, f, c, cols, **kw: db.table("tds_challans").select(cols, **kw).eq("firm_id", f).eq("client_id", c),)),
    # `fvu_json` is the statement's body, and on a 24Q it names every employee with their PAN and gross pay: payroll data, which this export does not carry.
    Section("tds_returns.csv", (
        lambda db, f, c, cols, **kw: db.table("tds_returns").select(cols, **kw).eq("firm_id", f).eq("client_id", c),),
        drop=frozenset({"fvu_json"})),
)

#: What this export does not hold, said in the manifest and the README. Kept as data so a test can hold the list against the claim in the screen.
NOT_INCLUDED: tuple[str, ...] = (
    "Only the files listed in manifest.json are here. Any other record in the product is not, whether or not it is named below.",
    "Payroll: runs, slips, employees, statutory remittances and returns (the most sensitive data in the product; a separate, deliberate export). "
    "The body of a saved TDS statement (tds_returns.fvu_json) is left out for the same reason: on a 24Q it names every employee with PAN and gross pay. "
    "A TDS register row under section 192 (salary), if one exists, is in tds_deductions.csv as it was recorded.",
    "The bank: accounts, statements, lines, reconciliations.",
    "Uploaded documents themselves (the files); only the books' own records are here.",
    "The audit log (it is the firm's, not the client's, and holds no client column).",
    "GST returns and their JSON, e-invoice and e-way bill records, and the GSTR-2B reconciliation.",
    "Income tax: computations, ITR filings, tax audit, losses and advance tax.",
    "Fixed assets, stock and stock movements, fixed-asset registers and the depreciation schedule.",
    "Statements and reports as PDF or Excel (use the report exports for those).",
    "Other clients, and the firm's own settings (this is one client's books).",
    "Records that sit beside the books and are not in these files: customer and vendor advances and credits, loans, deposits and related-party loans, "
    "foreign-currency revaluations, cost centres, the service catalogue, recurring templates, orders, quotations and delivery challans.",
)

#: Columns in the exported files that point at a table this export does not carry, so a recipient is not left holding an id that leads nowhere.
REFERENCES_NOT_EXPORTED: tuple[str, ...] = (
    "journal_lines.cost_centre_id (cost centres)",
    "client_sales_invoice_lines.service_catalogue_id, purchase_bill_lines.service_catalogue_id and the other lines' service_catalogue_id (the service catalogue)",
    "purchase_bill_lines.expense_account_id and purchase_order_line_id (the first is a chart_of_accounts id and is here; the second is an order line and is not)",
)

_PLAIN_NUMBER = re.compile(r"[-+]?[0-9]+(\.[0-9]+)?", re.ASCII)
_RISKY_FIRST = ("=", "+", "-", "@", "\t", "\r")


class _Counting(io.RawIOBase):
    """A writable that hashes and counts what passes through to a ZIP member, so the manifest's SHA-256 is of exactly the bytes in the file."""

    def __init__(self, member):
        super().__init__()
        self._member = member
        self.sha = hashlib.sha256()
        self.bytes = 0

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:           # type: ignore[override]
        view = bytes(data)
        self.sha.update(view)
        self.bytes += len(view)
        self._member.write(view)
        return len(view)


class _CsvMember:
    """One CSV file inside the ZIP, written row by row. Its header is the first row's columns, and a later row with a column the header does not have is counted."""

    def __init__(self, zf: zipfile.ZipFile, name: str):
        self.name = name
        self._zip_member = zf.open(name, "w", force_zip64=True)
        self._count = _Counting(self._zip_member)
        self._text = io.TextIOWrapper(self._count, encoding="utf-8-sig", newline="", write_through=False)
        self._writer: Optional[csv.writer] = None
        self.columns: list[str] = []
        self.rows = 0
        self.prefixed = 0
        self.stray_columns = 0
        self.sha256 = ""
        self.size = 0
        self._closed = False

    def _cell(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float, Decimal)):
            return str(value)
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        text = str(value)
        if text.startswith(_RISKY_FIRST) and not _PLAIN_NUMBER.fullmatch(text):
            self.prefixed += 1
            return "'" + text
        return text

    def write_rows(self, rows: Iterable[dict]) -> None:
        for row in rows:
            if self._writer is None:
                self.columns = list(row.keys())
                self._writer = csv.writer(self._text, lineterminator="\r\n")
                self._writer.writerow(self.columns)
            elif set(row.keys()) - set(self.columns):
                self.stray_columns += 1
            self._writer.writerow([self._cell(row.get(c)) for c in self.columns])
            self.rows += 1

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._text.flush()
        self._text.detach()                  # the text layer must not close the ZIP member under us
        self._zip_member.close()
        self.sha256 = self._count.sha.hexdigest()
        self.size = self._count.bytes


@dataclass
class ExportResult:
    content: bytes
    filename: str
    manifest: dict
    problems: list[str] = field(default_factory=list)


class _Clock:
    """The deadline, with the clock a test can replace."""

    def __init__(self, seconds: float, now: Callable[[], float]):
        self._now = now
        self._until = now() + seconds
        self.seconds = seconds

    def check(self, where: str) -> None:
        if self._now() > self._until:
            raise ExportStopped(
                f"The export could not finish within {int(self.seconds)} seconds, so nothing was downloaded (it stopped while reading {where}). "
                "Try again in a quiet moment; a client this large needs the background export, which is not built yet.")


def _count(db, section: Section, firm_id: str, client_id: str) -> Optional[int]:
    """How many rows the section will read, asked of the database before it is read, or None when the database does not say."""
    total = 0
    for read in section.reads:
        res = read(db, firm_id, client_id, "id", count="exact").limit(1).execute()
        n = getattr(res, "count", None)
        if n is None:
            return None
        total += int(n)
    return total


def _slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return out[:40] or "client"


def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


class _Run:
    """One export in progress: the archive, the files written so far, what has been found wrong, and the figures the derived trial balance is made of."""

    def __init__(self, db, firm_id: str, client_id: str, clock: _Clock, spool):
        self.db, self.firm_id, self.client_id, self.clock = db, firm_id, client_id, clock
        self.zf = zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED)
        self.members: list[_CsvMember] = []
        self.files: list[dict] = []
        self.problems: list[str] = []
        self.expected: dict[str, Optional[int]] = {}
        self.accounts: dict[str, dict] = {}
        self.live_entries: set[str] = set()
        self.entries_with_lines: set[str] = set()
        self.tally: dict[str, list[int]] = {}
        self.dropped: dict[str, list[str]] = {}

    # ── one file ────────────────────────────────────────────────────────────────────────────────────────────
    def _open(self, name: str) -> _CsvMember:
        self.clock.check(name)
        member = _CsvMember(self.zf, name)
        self.members.append(member)
        return member

    def _finish(self, member: _CsvMember, *, expected_rows: Optional[int], kind: str, parent: Optional[str] = None) -> None:
        member.close()
        entry = {"name": member.name, "kind": kind, "rows": member.rows, "bytes": member.size, "sha256": member.sha256,
                 "columns": member.columns, "database_rows_at_start": expected_rows, "text_cells_prefixed": member.prefixed}
        if parent:
            entry["rows_of"] = parent
        if self.dropped.get(member.name):
            entry["columns_not_exported"] = self.dropped[member.name]
        if expected_rows is not None:
            entry["matches_database_count"] = expected_rows == member.rows
            if expected_rows != member.rows:
                self.problems.append(
                    f"{member.name}: {member.rows:,} rows were written but the database counted {expected_rows:,} when the export began. A row may have been "
                    "added or removed while the export ran, or a read was cut short; run the export again before relying on this file.")
        if member.stray_columns:
            entry["columns_consistent"] = False
            self.problems.append(f"{member.name}: {member.stray_columns:,} rows carried a column the file's header does not have, so that column is missing from them.")
        self.files.append(entry)

    # ── the parents, then their children ────────────────────────────────────────────────────────────────────
    def write_section(self, section: Section) -> None:
        member = self._open(section.file)
        if section.drop:
            self.dropped[section.file] = sorted(section.drop)
        parent_ids: list[str] = []
        for read in section.reads:
            for page in iter_pages(lambda read=read: read(self.db, self.firm_id, self.client_id, "*"), "id", label=section.file):
                self.clock.check(section.file)
                parent_ids.extend(str(r["id"]) for r in page)
                self._remember(section.file, page)
                member.write_rows([{k: v for k, v in r.items() if k not in section.drop} for r in page] if section.drop else page)
        self._finish(member, expected_rows=self.expected.get(section.file), kind="rows")
        for child in section.children:
            self._write_child(child, section.file, parent_ids)

    def _remember(self, file: str, page: list[dict]) -> None:
        """What the derived trial balance needs from the parents: the chart (for names) and which entries count."""
        if file == "chart_of_accounts.csv":
            for r in page:
                self.accounts[str(r["id"])] = r
        elif file == "journal_entries.csv":
            for r in page:
                if r.get("is_posted") and not r.get("deleted_at"):
                    self.live_entries.add(str(r["id"]))

    def _write_child(self, child: Child, parent_file: str, parent_ids: list[str]) -> None:
        member = self._open(child.file)
        for chunk in _chunks(parent_ids, IN_CHUNK):
            for page in iter_pages(lambda chunk=chunk: child.read(self.db).in_(child.fk, chunk), "id", label=child.file):
                self.clock.check(child.file)
                member.write_rows(page)
                if child.file == "journal_lines.csv":
                    self._tally(page)
        self._finish(member, expected_rows=None, kind="child rows", parent=parent_file)

    def _tally(self, lines: list[dict]) -> None:
        for r in lines:
            self.entries_with_lines.add(str(r.get("journal_entry_id")))
            if str(r.get("journal_entry_id")) in self.live_entries:
                acc = self.tally.setdefault(str(r.get("account_id")), [0, 0])
                acc[0] += int(r.get("debit_paise") or 0)
                acc[1] += int(r.get("credit_paise") or 0)

    # ── what is derived, and what is said ───────────────────────────────────────────────────────────────────
    def write_trial_balance(self) -> tuple[int, int]:
        """The trial balance the recipient can recompute: posted, non-deleted entries' lines summed per account. Returns the posted debit and credit totals."""
        tb = self._open("trial_balance_from_the_ledger_files.csv")
        rows = []
        for account_id in sorted(self.tally, key=lambda a: (str(self.accounts.get(a, {}).get("account_code") or "~"), a)):
            dr, cr = self.tally[account_id]
            acc = self.accounts.get(account_id, {})
            rows.append({"account_id": account_id, "account_code": acc.get("account_code"), "account_name": acc.get("account_name"),
                         "account_type": acc.get("account_type"), "debit_paise": dr, "credit_paise": cr, "net_debit_paise": dr - cr})
        tb.write_rows(rows)
        self._finish(tb, expected_rows=None, kind="derived")
        bare = self.live_entries - self.entries_with_lines
        if bare:
            self.problems.append(f"{len(bare):,} posted entries have no line in journal_lines.csv. A posted entry always has lines, so either the books are damaged or a "
                                 "read of the lines was cut short; the trial balance made from these files is not to be relied on until that is explained.")
        unknown = [a for a in self.tally if a not in self.accounts]
        if unknown:
            self.problems.append(f"{len(unknown)} accounts used by the entries are not in chart_of_accounts.csv, so their code and name are blank in the trial balance "
                                 "(their ids are there).")
        return sum(v[0] for v in self.tally.values()), sum(v[1] for v in self.tally.values())

    def manifest(self, *, client: dict, firm_id: str, exported_by: Optional[str], started_at, debit: int, credit: int) -> dict:
        counted = sum(1 for n in self.expected.values() if n is not None)
        if counted < len(self.expected):
            self.problems.append(f"The database did not report a row count for {len(self.expected) - counted} of the {len(self.expected)} main files, so those were not "
                                 "checked against it.")
        if debit != credit:
            self.problems.append(f"The posted lines do not balance: debits {rupee_text(debit)}, credits {rupee_text(credit)}. The books themselves are out of balance, "
                                 "or the lines were not all read; the export has not hidden it.")
        return {
            "schema": SCHEMA,
            "generated_at_ist": started_at.isoformat(timespec="seconds"),
            "firm_id": firm_id,
            "client": {"id": self.client_id, "name": client.get("legal_name") or client.get("client_name"), "pan": client.get("pan"), "gstin": client.get("gstin")},
            "exported_by": exported_by,
            "scope": ("One client's books, every period. Drafts, reversed and soft-deleted rows are included; their own columns (is_posted, deleted_at, status) say "
                      "which they are. Money columns are integer paise."),
            "not_a_snapshot": ("The files were read one request at a time, not in one transaction. Each file's rows were counted before it was read; "
                               "matches_database_count says whether the same number was written."),
            "files": self.files,
            "checks": {
                "posted_lines_debit_paise": debit,
                "posted_lines_credit_paise": credit,
                "posted_lines_balance": debit == credit,
                "main_files_counted_by_the_database": f"{counted} of {len(self.expected)}",
                "every_counted_file_matches_the_database": all(f.get("matches_database_count", True) for f in self.files),
                "posted_entries_without_a_line": len(self.live_entries - self.entries_with_lines),
                "every_file_has_one_set_of_columns": all(f.get("columns_consistent", True) for f in self.files),
            },
            "problems": self.problems,
            "not_included": list(NOT_INCLUDED),
            "ids_that_lead_to_tables_not_in_the_export": list(REFERENCES_NOT_EXPORTED),
            "how_to_check": ("Add debit_paise and credit_paise of journal_lines.csv per account_id for the lines whose journal_entry_id belongs to an entry in "
                             "journal_entries.csv with is_posted = true and an empty deleted_at: that is trial_balance_from_the_ledger_files.csv."),
        }

    def abort(self) -> None:
        """Close whatever is open so the archive can close without raising over the real error."""
        for m in self.members:
            try:
                m.close()
            except Exception:                         # noqa: BLE001
                _logger.warning("books export: closing %s while stopping failed", m.name, exc_info=True)
        try:
            self.zf.close()
        except Exception:                             # noqa: BLE001
            _logger.warning("books export: closing the archive while stopping failed", exc_info=True)


def _refuse_if_too_large(expected: dict[str, Optional[int]], max_entries: int, max_rows: int) -> None:
    entries = expected.get("journal_entries.csv")
    if entries is not None and entries > max_entries:
        raise ExportRefused(
            f"This client has {entries:,} journal entries, more than the {max_entries:,} the export reads in one request, so nothing was read. "
            "The background export, which has no such limit, is not built yet; the report exports (ledger, trial balance, day book) cover the same books in the meantime.")
    known = sum(n for n in expected.values() if n is not None)
    if known > max_rows:
        raise ExportRefused(
            f"This client's books hold {known:,} rows across the exported tables, more than the {max_rows:,} the export reads in one request, so nothing was read. "
            "The background export, which has no such limit, is not built yet.")


def build(db, firm_id: str, client_id: str, *, exported_by: Optional[str] = None,
          now: Callable[[], float] = time.monotonic, deadline_seconds: float = DEADLINE_SECONDS,
          max_entries: int = MAX_JOURNAL_ENTRIES, max_rows: int = MAX_ROWS) -> ExportResult:
    """The ZIP for one client's books. Raises `ExportRefused` (422) for a client over the ceilings and `ExportStopped` (503) when it runs out of time.

    `db` is the privileged client; every request here names the firm and the client (the line and allocation tables have neither, and are read by the ids of
    parents that did). The caller has already established who may ask (`rbac`, the client scope, MFA) and written the audit row."""
    clock = _Clock(deadline_seconds, now)
    started_at = ist_now()
    client_rows = (db.table("clients").select("id, client_name, legal_name, pan, gstin")
                   .eq("firm_id", firm_id).eq("id", client_id).limit(1).execute().data) or []
    if not client_rows:
        raise ExportRefused("That client was not found for this firm.")
    client = client_rows[0]

    expected: dict[str, Optional[int]] = {}
    for section in _SECTIONS:
        expected[section.file] = _count(db, section, firm_id, client_id)
        clock.check("the row counts")
    _refuse_if_too_large(expected, max_entries, max_rows)

    spool = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    run = _Run(db, firm_id, client_id, clock, spool)
    run.expected = expected
    try:
        for section in _SECTIONS:
            run.write_section(section)
        debit, credit = run.write_trial_balance()
        clock.check("the manifest")
        manifest = run.manifest(client=client, firm_id=firm_id, exported_by=exported_by, started_at=started_at, debit=debit, credit=credit)
        run.zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        run.zf.writestr("README.txt", _readme(manifest).encode("utf-8"))
        run.zf.close()
    except BaseException:
        run.abort()
        spool.close()
        raise
    spool.seek(0)
    content = spool.read()
    spool.close()
    filename = f"books-{_slug(client.get('client_name') or client.get('legal_name') or '')}-{started_at.date().isoformat()}.zip"
    return ExportResult(content=content, filename=filename, manifest=manifest, problems=run.problems)


def _readme(manifest: dict) -> str:
    lines = [
        "PRACTICESYNC - BOOKS EXPORT (CSV)",
        "",
        f"Client: {manifest['client'].get('name')}",
        f"Made: {manifest['generated_at_ist']} (India time)",
        "",
        "WHAT THIS IS",
        "One client's books as plain CSV files. manifest.json lists every file with its row count and SHA-256.",
        "Money columns are whole paise (1 rupee = 100 paise). Dates are ISO (YYYY-MM-DD). Text is UTF-8 with a byte-order mark so a spreadsheet reads the rupee sign and Indian-language names.",
        "Drafts, reversed and deleted rows are included; read is_posted, deleted_at and status before adding anything up.",
        "A text cell that begins with = + - or @ has a leading apostrophe so a spreadsheet does not run it; remove it if you need the original.",
        "",
        "HOW TO CHECK THE BOOKS ADD UP",
        manifest["how_to_check"],
        "",
        "WHAT IS NOT HERE",
    ]
    lines += [f"- {item}" for item in manifest["not_included"]]
    lines += ["", "IDS IN THESE FILES THAT LEAD TO TABLES THAT ARE NOT HERE"] + [f"- {item}" for item in manifest["ids_that_lead_to_tables_not_in_the_export"]]
    if manifest["problems"]:
        lines += ["", "PROBLEMS THE EXPORT FOUND IN ITSELF"] + [f"- {p}" for p in manifest["problems"]]
    lines += ["", "The files were read one request at a time, not in one transaction (see not_a_snapshot in manifest.json)."]
    return "\r\n".join(lines) + "\r\n"
