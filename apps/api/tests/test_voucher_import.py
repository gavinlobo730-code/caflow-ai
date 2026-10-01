"""
accounting-17 — a spreadsheet of journals, payments, receipts and contras becomes
vouchers, one by one, through the one posting kernel.

WHAT WAS MISSING
    Bulk import existed for invoices, receipts, bills, notes, the catalogue and
    payroll, and not for the vouchers a bookkeeper most often HAS in a
    spreadsheet. Many small clients send the CA an Excel of payments and journals;
    every line was typed again.

WHAT THESE PIN
    * every voucher is judged before any is posted, and a bad voucher comes back
      under its NUMBER with ALL its problems at once — "short by ₹250", the row of
      the ledger that does not exist, the date that cannot be read;
    * the good vouchers still post: by named voucher, not all or nothing;
    * UPLOADING THE SAME FILE AGAIN POSTS NOTHING — the voucher number is the
      entry's reference_no, which the kernel dedupes on with the date, and the
      plan recognises a voucher already on the books by date, type and total; the
      same number on anything else is refused and says what it clashes with,
      because the kernel would otherwise collapse a same-date entry into the old
      one without a word (a REVERSED voucher still holds its number);
    * ledgers resolve by CODE or by name, this client's own and the firm's shared
      ones, never another client's, never fuzzily, never when two share a name;
    * a date is read day-first and a two-digit year refused;
    * Sales, Purchase and Opening are refused by name — they are documents;
    * the posted-period lock is asked for a POSTED import and never for a draft,
      exactly as `manual_journal_service.create` does;
    * `status` has no default;
    * EVERY posting goes through `manual_journal_service.create`, which reaches
      `_create_journal`; this module writes to no ledger table of its own.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

from domain.accounting import voucher_import as vi
from services import voucher_import_service as svc

API_ROOT = Path(__file__).resolve().parents[1]

CHART = [
    {"id": "A-BANK", "account_code": "1001", "account_name": "HDFC Bank", "is_active": True, "client_id": "K1"},
    {"id": "A-CASH", "account_code": "1002", "account_name": "Cash in Hand", "is_active": True, "client_id": None},
    {"id": "A-RENT", "account_code": "5100", "account_name": "Rent Expense", "is_active": True, "client_id": "K1"},
    {"id": "A-VEND", "account_code": "2001", "account_name": "Trade Payables", "is_active": True, "client_id": None},
    {"id": "A-OLD", "account_code": "5999", "account_name": "Old Suspense", "is_active": False, "client_id": "K1"},
    {"id": "A-DUP1", "account_code": "6001", "account_name": "Misc Expense", "is_active": True, "client_id": "K1"},
    {"id": "A-DUP2", "account_code": "6002", "account_name": "misc  expense", "is_active": True, "client_id": None},
]


def L(row, vno="V1", date="05-04-2026", vtype="Journal", account="Rent Expense",
      debit=0, credit=0, narration="", line=""):
    return vi.Leg(row=row, voucher_no=vno, date=date, voucher_type=vtype, account=account,
                  debit_paise=debit, credit_paise=credit,
                  narration=narration or None, line_narration=line or None)


def voucher(vno="V1", amount=500_000, **kw):
    """A balanced two-leg payment."""
    return [L(1, vno, account="Rent Expense", debit=amount, vtype="Payment", **kw),
            L(2, vno, account="HDFC Bank", credit=amount, vtype="Payment", **kw)]


def plan(legs, existing=None, period=None):
    return vi.plan(legs, CHART, existing or {}, period_problem=period)


# ── a good voucher ───────────────────────────────────────────────────────────

def test_a_balanced_voucher_is_new_and_carries_resolved_lines():
    [v] = plan(voucher(narration="April rent"))
    assert v.status == vi.NEW and not v.problems
    assert v.entry_date == "2026-04-05" and v.entry_type == "Payment"
    assert v.narration == "April rent" and v.total_paise == 500_000
    assert [(l["account_id"], l["debit_paise"], l["credit_paise"]) for l in v.lines] == [
        ("A-RENT", 500_000, 0), ("A-BANK", 0, 500_000)]


def test_the_legs_of_one_voucher_need_not_be_adjacent_and_one_may_name_the_type():
    legs = [L(1, "J1", vtype="Journal", account="Rent Expense", debit=100),
            L(2, "J2", vtype="Receipt", account="HDFC Bank", debit=50),
            L(3, "J1", vtype="", account="HDFC Bank", credit=100),
            L(4, "J2", vtype="Receipt", account="Trade Payables", credit=50)]
    a, b = plan(legs)
    assert a.voucher_no == "J1" and a.rows == (1, 3) and a.entry_type == "Journal"
    assert b.voucher_no == "J2" and b.rows == (2, 4)
    assert a.status == b.status == vi.NEW


def test_a_type_is_read_without_case():
    [v] = plan([dataclass_leg for dataclass_leg in voucher() if True][:0] +
               [L(1, vtype="PAYMENT", debit=10), L(2, vtype="payment", account="HDFC Bank", credit=10)])
    assert v.entry_type == "Payment"


# ── ledgers ──────────────────────────────────────────────────────────────────

def test_a_ledger_is_found_by_code_or_by_name_and_the_firms_shared_ones_count():
    [v] = plan([L(1, account="5100", debit=10), L(2, account="cash IN hand", credit=10)])
    assert [l["account_id"] for l in v.lines] == ["A-RENT", "A-CASH"]


def test_a_name_two_accounts_share_is_reported_and_never_picked():
    [v] = plan([L(1, account="Misc Expense", debit=10), L(2, account="HDFC Bank", credit=10)])
    assert v.status == vi.REJECTED and "2 accounts" in v.sentence and "code" in v.sentence
    [ok] = plan([L(1, account="6002", debit=10), L(2, account="HDFC Bank", credit=10)])
    assert ok.status == vi.NEW and ok.lines[0]["account_id"] == "A-DUP2"


def test_a_ledger_that_is_not_in_this_clients_chart_is_refused_by_row():
    [v] = plan([L(1, account="Bank of Elsewhere", debit=10), L(2, account="HDFC Bank", credit=10)])
    assert v.status == vi.REJECTED
    assert "Row 1" in v.sentence and "not an account of this client's chart" in v.sentence


def test_an_inactive_ledger_cannot_be_posted_to():
    [v] = plan([L(1, account="Old Suspense", debit=10), L(2, account="HDFC Bank", credit=10)])
    assert v.status == vi.REJECTED and "inactive" in v.sentence


def test_a_name_is_never_matched_fuzzily():
    [v] = plan([L(1, account="Rent", debit=10), L(2, account="HDFC Bank", credit=10)])
    assert v.status == vi.REJECTED, "'Rent' is not 'Rent Expense'"


# ── legs and balance ─────────────────────────────────────────────────────────

def test_an_unbalanced_voucher_says_which_side_is_short_and_by_how_much():
    [v] = plan([L(1, account="Rent Expense", debit=1_000_00),
                L(2, account="HDFC Bank", credit=750_00)])
    assert v.status == vi.REJECTED
    assert "debits ₹1,000.00, credits ₹750.00" in v.sentence
    assert "credits are short by ₹250.00" in v.sentence
    [w] = plan([L(1, account="Rent Expense", debit=100_00),
                L(2, account="HDFC Bank", credit=400_00)])
    assert "debits are short by ₹300.00" in w.sentence


def test_a_single_line_is_not_a_voucher():
    [v] = plan([L(1, debit=100)])
    assert v.status == vi.REJECTED and "at least two lines" in v.sentence


@pytest.mark.parametrize("debit,credit,fragment", [
    (10, 10, "a debit or a credit, not both"),
    (0, 0, "no amount"),
    (None, 0, "the debit is not an amount"),
    (0, None, "the credit is not an amount"),
    (-5, 0, "cannot be negative"),
])
def test_a_line_is_one_side_and_an_amount(debit, credit, fragment):
    [v] = plan([L(1, debit=debit, credit=credit), L(2, account="HDFC Bank", credit=10)])
    assert v.status == vi.REJECTED and fragment in v.sentence, v.sentence


# ── dates, types, numbers ────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["2026-04-05", "05-04-2026", "5/4/2026", "05.04.2026", "05-Apr-2026"])
def test_a_date_is_read_day_first(text):
    [v] = plan(voucher(date=text))
    assert v.entry_date == "2026-04-05"


@pytest.mark.parametrize("text", ["4/5/26", "31-02-2026", "", "tomorrow"])
def test_a_date_that_cannot_be_read_with_certainty_is_refused_by_row(text):
    [v] = plan(voucher(date=text))
    assert v.status == vi.REJECTED and "Row 1" in v.sentence
    if text:
        assert "two-digit year" in v.sentence


def test_a_voucher_is_dated_once():
    legs = [L(1, "V9", date="05-04-2026", account="Rent Expense", debit=10),
            L(2, "V9", date="06-04-2026", account="HDFC Bank", credit=10)]
    [v] = plan(legs)
    assert v.status == vi.REJECTED and "different dates" in v.sentence


@pytest.mark.parametrize("vtype,fragment", [
    ("Sales", "document"), ("Purchase", "document"), ("Opening", "Opening Balances"),
    ("Banana", "Journal, Payment, Receipt or Contra"),
])
def test_what_a_spreadsheet_may_not_hand_make_is_refused_with_where_it_belongs(vtype, fragment):
    [v] = plan([L(1, vtype=vtype, debit=10), L(2, vtype=vtype, account="HDFC Bank", credit=10)])
    assert v.status == vi.REJECTED and fragment in v.sentence, v.sentence


def test_a_voucher_with_no_type_anywhere_is_refused():
    [v] = plan([L(1, vtype="", debit=10), L(2, vtype="", account="HDFC Bank", credit=10)])
    assert v.status == vi.REJECTED and "type is blank" in v.sentence


def test_a_voucher_whose_lines_disagree_about_the_type_is_refused():
    [v] = plan([L(1, vtype="Payment", debit=10), L(2, vtype="Receipt", account="HDFC Bank", credit=10)])
    assert v.status == vi.REJECTED and "different types" in v.sentence


def test_a_blank_voucher_number_is_refused_because_it_is_the_key():
    [v] = plan(voucher(vno=""))
    assert v.status == vi.REJECTED and "voucher number is blank" in v.sentence


def test_a_bad_voucher_lists_every_problem_at_once():
    """A file corrected one error at a time is a file uploaded nineteen times."""
    [v] = plan([L(1, "V7", date="soon", vtype="Sales", account="Nowhere", debit=100),
                L(2, "V7", date="soon", vtype="Sales", account="HDFC Bank", credit=40)])
    for fragment in ("Row 1: the date", "Row 1: Sales entry", "not an account of this client",
                     "does not balance"):
        assert fragment in v.sentence or fragment.replace("Sales entry", "A sales entry") in v.sentence, (
            fragment, v.sentence)


def test_a_one_row_voucher_reports_its_bad_cell_once_and_names_one_row():
    """A "Dr, Cr, amount" sheet is expanded to two legs on the SAME row, so a bad
    date on it is found twice — and said once, against one row number."""
    legs = [L(3, "P3", date="", vtype="Sales", account="Rent Expense", debit=100),
            L(3, "P3", date="", vtype="Sales", account="HDFC Bank", credit=100)]
    [v] = plan(legs)
    assert v.status == vi.REJECTED
    assert v.rows == (3,)
    assert len(v.problems) == len(set(v.problems))
    assert v.sentence.count("the date is blank") == 1
    assert v.sentence.count("Sales entry") == 1 or v.sentence.count("sales entry") == 1


def test_an_unreadable_amount_on_a_one_row_voucher_is_refused_by_that_row():
    legs = [L(9, "P9", vtype="Payment", account="Rent Expense", debit=None),
            L(9, "P9", vtype="Payment", account="HDFC Bank", credit=None)]
    [v] = plan(legs)
    assert v.status == vi.REJECTED and v.rows == (9,)
    assert "Row 9: the debit is not an amount." in v.problems
    assert "Row 9: the credit is not an amount." in v.problems


# ── periods ──────────────────────────────────────────────────────────────────

def test_a_closed_period_refuses_the_voucher_naming_the_date_and_the_reason():
    [v] = plan(voucher(), period=lambda d: "GSTR-3B for 04/2026 was filed on 20 May 2026.")
    assert v.status == vi.REJECTED
    assert "2026-04-05 is in a closed period" in v.sentence and "GSTR-3B" in v.sentence


def test_an_open_period_asks_once_per_distinct_date_by_being_called_with_it():
    asked = []
    legs = voucher("V1") + voucher("V2") + voucher("V3", date="06-04-2026")
    plan(legs, period=lambda d: asked.append(d))
    assert sorted(set(asked)) == ["2026-04-05", "2026-04-06"]


def test_a_draft_import_asks_nothing_about_the_period():
    [v] = plan(voucher(), period=None)
    assert v.status == vi.NEW


# ── a re-upload ──────────────────────────────────────────────────────────────

def _on_books(**over):
    return {"V1": [{"id": "E1", "entry_date": "2026-04-05", "entry_type": "Payment",
                    "is_reversed": False, "total_paise": 500_000, **over}]}


def test_the_same_voucher_again_is_already_recorded_not_an_error():
    [v] = plan(voucher(), existing=_on_books())
    assert v.status == vi.ALREADY_RECORDED and v.existing_id == "E1" and not v.problems


@pytest.mark.parametrize("over,fragment", [
    ({"entry_date": "2026-04-06"}, "dated 2026-04-06"),
    ({"total_paise": 400_000}, "₹4,000.00"),
    ({"entry_type": "Journal"}, "(Journal"),
])
def test_the_same_number_on_anything_else_is_refused_and_says_what_it_clashes_with(over, fragment):
    [v] = plan(voucher(), existing=_on_books(**over))
    assert v.status == vi.REJECTED
    assert fragment in v.sentence and "different voucher number" in v.sentence


def test_a_reversed_voucher_still_holds_its_number():
    [v] = plan(voucher(), existing=_on_books(is_reversed=True))
    assert v.status == vi.REJECTED and "reversed" in v.sentence and "new number" in v.sentence


# ── the service ──────────────────────────────────────────────────────────────

class _Q:
    def __init__(self, db, table):
        self._db, self._table = db, table
        self._rows = list(db.store.get(table, []))

    def select(self, *a, **k): return self
    def eq(self, c, v): self._rows = [r for r in self._rows if r.get(c) == v]; return self
    def is_(self, c, _n): self._rows = [r for r in self._rows if r.get(c) is None]; return self
    def in_(self, c, vs): self._rows = [r for r in self._rows if r.get(c) in list(vs)]; return self
    def gt(self, c, v): self._rows = [r for r in self._rows if str(r.get(c)) > str(v)]; return self
    def order(self, c, **k): self._rows.sort(key=lambda r: str(r.get(c))); return self
    def limit(self, n): self._rows = self._rows[:n]; return self
    def execute(self): return type("R", (), {"data": self._rows})()


class _DB:
    def __init__(self, chart=None):
        self.store = {"chart_of_accounts": [dict(c, firm_id="F1") for c in (chart or CHART)]
                      + [{"id": "A-OTHER", "firm_id": "F1", "client_id": "K2",
                          "account_code": "9999", "account_name": "Rent Expense",
                          "is_active": True}],
                      "journal_entries": [], "journal_lines": []}

    def table(self, name): return _Q(self, name)


class Kernel:
    """Stands in for `_create_journal` and records what reached it."""
    def __init__(self, db, refuse=None):
        self.db, self.calls, self.refuse = db, [], refuse

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.refuse and self.refuse(kw):
            raise ValueError("the kernel refused this one")
        total = sum(l["debit_paise"] for l in kw["lines"])
        assert total == sum(l["credit_paise"] for l in kw["lines"]), "the kernel asserts balance"
        eid = f"E{len(self.db.store['journal_entries']) + 1}"
        self.db.store["journal_entries"].append({
            "id": eid, "firm_id": kw["firm_id"], "client_id": kw["client_id"],
            "reference_no": kw["reference_no"], "entry_date": kw["entry_date"],
            "entry_type": kw["entry_type"], "is_reversed": False, "status": "posted"})
        for i, l in enumerate(kw["lines"]):
            self.db.store["journal_lines"].append({
                "id": f"{eid}-L{i}", "journal_entry_id": eid,
                "debit_paise": l["debit_paise"], "credit_paise": l["credit_paise"]})
        return eid


@pytest.fixture
def world(monkeypatch):
    """A fake database, the REAL manual-journal service in front of a recording
    kernel, and the period locks open."""
    from services import manual_journal_service as mjs
    db = _DB()
    kernel = Kernel(db)
    monkeypatch.setattr(mjs.phase2_journal_service, "_create_journal", kernel)
    asked = {"lock_reason": [], "fy": []}
    # ONE seam for the client's own lock: `assert_open` is `lock_reason` raising its
    # answer, so patching the answer leaves the real `assert_open` in both the plan's
    # asker and `manual_journal_service.create` — which is what lets a test make the
    # period CLOSED and watch both refuse.
    monkeypatch.setattr(svc.period_lock_service, "lock_reason",
                        lambda db_, f, c, d, cache=None: asked["lock_reason"].append(d))
    monkeypatch.setattr(mjs.period_validation_service, "validate_posting_date",
                        lambda f, d: asked["fy"].append(d))
    monkeypatch.setattr(svc.period_validation_service, "validate_posting_date_cached",
                        lambda f, d, cache=None: asked["fy"].append(d))
    return db, kernel, asked


def _file(n=200):
    """n vouchers of two legs, three of them bad."""
    legs = []
    for i in range(1, n + 1):
        vno = f"PV-{i:04d}"
        base = (i - 1) * 2
        amt = 1_000_00 + i * 100
        legs += [L(base + 1, vno, vtype="Payment", account="Rent Expense", debit=amt),
                 L(base + 2, vno, vtype="Payment", account="HDFC Bank", credit=amt)]
    legs[18] = L(19, "PV-0010", vtype="Payment", account="Rent Expense", debit=5)         # unbalanced
    legs[100] = L(101, "PV-0051", vtype="Payment", account="No Such Ledger", debit=1_050_00)
    legs[198] = L(199, "PV-0100", date="4/4/26", vtype="Payment", account="Rent Expense", debit=1_100_00)
    return legs


def _run(db, legs, *, size=20, **kw):
    """What the import screen does: vouchers in batches of `size`, each request
    small enough to finish well inside the browser's 45-second patience, the
    answers added up. A voucher's legs always travel together."""
    order: list[str] = []
    by: dict[str, list] = {}
    for leg in legs:
        key = (leg.voucher_no or "").strip()
        if key not in by:
            order.append(key)
        by.setdefault(key, []).append(leg)
    total = {"vouchers": 0, "created": 0, "would_create": 0, "already_recorded": 0,
             "rejected": 0, "created_paise": 0, "results": []}
    for i in range(0, len(order), size):
        batch = [leg for key in order[i:i + size] for leg in by[key]]
        out = svc.import_vouchers(db, "F1", "K1", legs=batch, **kw)
        for k in ("vouchers", "created", "would_create", "already_recorded", "rejected",
                  "created_paise"):
            total[k] += out[k]
        total["results"] += out["results"]
    return total


def test_a_200_voucher_file_posts_the_good_ones_and_names_the_bad_ones(world):
    db, kernel, _ = world
    out = _run(db, _file(), status="posted", actor_id="u1")
    assert out["vouchers"] == 200 and out["created"] == 197 and out["rejected"] == 3
    bad = {r["voucher_no"]: r for r in out["results"] if r["status"] == vi.REJECTED}
    assert sorted(bad) == ["PV-0010", "PV-0051", "PV-0100"]
    assert "does not balance" in " ".join(bad["PV-0010"]["problems"])
    assert "not an account of this client" in " ".join(bad["PV-0051"]["problems"])
    assert "two-digit year" in " ".join(bad["PV-0100"]["problems"])
    assert bad["PV-0010"]["rows"] == [19, 20]
    assert len(kernel.calls) == 197
    assert len(db.store["journal_entries"]) == 197


def test_uploading_the_same_file_again_posts_nothing_twice(world):
    db, kernel, _ = world
    first = _run(db, _file(), status="posted")
    entries = len(db.store["journal_entries"])
    again = _run(db, _file(), status="posted")
    assert first["created"] == 197
    assert again["created"] == 0 and again["already_recorded"] == 197 and again["rejected"] == 3
    assert len(kernel.calls) == 197, "the kernel was asked to post a voucher it already had"
    assert len(db.store["journal_entries"]) == entries


def test_every_voucher_reaches_the_kernel_through_the_manual_journal_service(world):
    db, kernel, _ = world
    svc.import_vouchers(db, "F1", "K1", legs=voucher("PV-1", narration="April rent"),
                        status="posted", actor_id="u-internal")
    [call] = kernel.calls
    assert call["reference_no"] == "PV-1" and call["entry_type"] == "Payment"
    assert call["entry_date"] == "2026-04-05" and call["narration"] == "April rent"
    assert call["is_posted"] is True and call["source_type"] == "manual"
    assert call["created_by"] == "u-internal"
    assert call["firm_id"] == "F1" and call["client_id"] == "K1"
    assert [(l["account_id"], l["debit_paise"], l["credit_paise"]) for l in call["lines"]] == [
        ("A-RENT", 500_000, 0), ("A-BANK", 0, 500_000)]


def test_a_ledger_of_another_client_is_never_matched(world):
    db, kernel, _ = world
    svc.import_vouchers(db, "F1", "K1", legs=voucher("PV-1"), status="posted")
    ids = [l["account_id"] for l in kernel.calls[0]["lines"]]
    assert "A-OTHER" not in ids and ids[0] == "A-RENT"


def test_a_posted_import_asks_both_period_questions_and_a_draft_asks_neither(world):
    db, kernel, asked = world
    svc.import_vouchers(db, "F1", "K1", legs=voucher("PV-1"), status="posted")
    # The client's lock is asked twice for the one date — once by the plan, before
    # anything is posted, and once by manual_journal_service.create — and the FY
    # check by both as well. Neither is skipped because the other happened.
    assert asked["lock_reason"] == ["2026-04-05", "2026-04-05"], asked
    assert len(asked["fy"]) == 2, asked
    asked.update(lock_reason=[], fy=[])
    svc.import_vouchers(db, "F1", "K1", legs=voucher("PV-2"), status="draft")
    assert asked == {"lock_reason": [], "fy": []}, (
        "a draft is off-books and is checked when it is approved")
    assert kernel.calls[-1]["is_posted"] is False


def test_a_closed_period_refuses_the_voucher_before_the_kernel_is_asked(world, monkeypatch):
    db, kernel, _ = world
    monkeypatch.setattr(svc.period_lock_service, "lock_reason",
                        lambda *a, **k: "The financial year is locked.")
    out = svc.import_vouchers(db, "F1", "K1", legs=voucher("PV-1"), status="posted")
    assert out["created"] == 0 and out["rejected"] == 1 and kernel.calls == []
    assert "closed period" in out["results"][0]["problems"][0]


def test_a_voucher_the_kernel_refuses_is_named_and_its_neighbours_still_post(world, monkeypatch):
    db, kernel, _ = world
    kernel.refuse = lambda kw: kw["reference_no"] == "PV-2"
    out = svc.import_vouchers(db, "F1", "K1", status="posted",
                              legs=voucher("PV-1") + [dict_leg for dict_leg in []]
                              + [L(3, "PV-2", vtype="Payment", account="Rent Expense", debit=10),
                                 L(4, "PV-2", vtype="Payment", account="HDFC Bank", credit=10)]
                              + [L(5, "PV-3", vtype="Payment", account="Rent Expense", debit=10),
                                 L(6, "PV-3", vtype="Payment", account="HDFC Bank", credit=10)])
    assert out["created"] == 2 and out["rejected"] == 1
    [bad] = [r for r in out["results"] if r["status"] == vi.REJECTED]
    assert bad["voucher_no"] == "PV-2" and "the kernel refused" in bad["problems"][0]
    assert out["created_paise"] == 500_000 + 10, "the refused voucher's amount is not counted"


def test_a_dry_run_posts_nothing_and_asks_the_kernel_nothing(world):
    db, kernel, _ = world
    out = _run(db, _file(), status="posted", dry_run=True)
    assert kernel.calls == [] and db.store["journal_entries"] == []
    assert out["created"] == 0 and out["would_create"] > 0
    assert {r["status"] for r in out["results"]} <= {"would_create", vi.REJECTED}


def test_the_request_is_bounded_and_status_is_explicit(world):
    db, _, _ = world
    with pytest.raises(HTTPException) as e1:
        svc.import_vouchers(db, "F1", "K1", legs=[], status="posted")
    with pytest.raises(HTTPException) as e2:
        svc.import_vouchers(db, "F1", "K1", legs=voucher(), status="maybe")
    big = [L(i, f"V{i // 2}", account="Rent Expense", debit=1) for i in range(vi.MAX_LEGS + 1)]
    with pytest.raises(HTTPException) as e3:
        svc.import_vouchers(db, "F1", "K1", legs=big, status="posted")
    many = []
    for i in range(vi.MAX_VOUCHERS + 1):
        many += voucher(f"V{i}")
    with pytest.raises(HTTPException) as e4:
        svc.import_vouchers(db, "F1", "K1", legs=many, status="draft")
    assert all(e.value.status_code == 422 for e in (e1, e2, e3, e4))
    assert "smaller batches" in e4.value.detail


# ── the rule, not the call sites ─────────────────────────────────────────────

def test_the_service_writes_to_no_table_of_its_own():
    """ONE posting kernel, no alternative path (CLAUDE.md). Every write goes
    through `manual_journal_service.create`; this file reads and nothing more."""
    tree = ast.parse((API_ROOT / "services" / "voucher_import_service.py").read_text())
    writes = [n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr in {"insert", "update", "upsert", "delete", "rpc"}]
    assert writes == [], f"the importer writes by itself: {writes}"
    src = (API_ROOT / "services" / "voucher_import_service.py").read_text()
    assert "manual_journal_service.create(" in src
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_create_journal" not in names, (
        "reach the kernel THROUGH manual_journal_service, never around it")
    assert "phase2_journal_service" not in names


def test_the_domain_module_holds_no_database_handle_and_no_clock():
    src = (API_ROOT / "domain" / "accounting" / "voucher_import.py").read_text()
    for forbidden in ("supabase", "db.table", "datetime.now", "date.today"):
        assert forbidden not in src


# ── the door ─────────────────────────────────────────────────────────────────

def _app(role="Partner"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routers.accounting as ra
    from core.auth import get_current_user
    app = FastAPI()
    app.include_router(ra.router)
    user = {"id": "u1", "firm_id": "F1", "role": role, "email": "p@f1.test",
            "auth_user_id": "auth-1"}
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False), ra


_BODY = {"client_id": "K1", "status": "posted", "legs": [
    {"row": 1, "voucher_no": "PV-1", "date": "05-04-2026", "voucher_type": "Payment",
     "account": "Rent Expense", "debit_paise": 500000, "credit_paise": 0},
    {"row": 2, "voucher_no": "PV-1", "date": "05-04-2026", "voucher_type": "Payment",
     "account": "HDFC Bank", "debit_paise": 0, "credit_paise": 500000}]}


def test_status_is_required_by_the_door_so_nothing_posts_by_omission():
    http, _ra = _app()
    body = {k: v for k, v in _BODY.items() if k != "status"}
    assert http.post("/api/accounting/vouchers/import", json=body).status_code == 422
    assert http.post("/api/accounting/vouchers/import",
                     json=dict(_BODY, status="whenever")).status_code == 422


def test_a_role_that_cannot_write_accounting_cannot_import():
    http, _ra = _app(role="Reviewer")
    assert http.post("/api/accounting/vouchers/import", json=_BODY).status_code == 403


def test_the_door_posts_audits_once_and_a_re_upload_audits_nothing(world, monkeypatch):
    db, kernel, _ = world
    http, ra = _app()
    monkeypatch.setattr(ra, "_prod_db", lambda: db)
    events = []
    monkeypatch.setattr(ra, "log_event", lambda *a, **k: events.append((a, k)))
    res = http.post("/api/accounting/vouchers/import", json=_BODY)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["created"] == 1 and data["created_paise"] == 500_000
    assert len(events) == 1
    (args, kwargs) = events[0]
    assert args[3] == "voucher_import" and kwargs["actor_id"] == "auth-1"
    assert kernel.calls[0]["created_by"] == "u1", "created_by is the INTERNAL id"

    again = http.post("/api/accounting/vouchers/import", json=_BODY).json()["data"]
    assert again["created"] == 0 and again["already_recorded"] == 1
    assert len(events) == 1 and len(kernel.calls) == 1


def test_a_failed_audit_write_is_not_a_failed_post(world, monkeypatch):
    db, kernel, _ = world
    http, ra = _app()
    monkeypatch.setattr(ra, "_prod_db", lambda: db)
    monkeypatch.setattr(ra, "log_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))
    res = http.post("/api/accounting/vouchers/import", json=_BODY)
    assert res.status_code == 200 and res.json()["data"]["created"] == 1
