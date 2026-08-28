"""
The GL side of the GSTR-3B books-vs-ledger reconciliation must actually find the
GST control accounts.

WHAT WAS WRONG
    gst_return_service._gl_gst_movements resolved the control accounts with

        .eq("firm_id", firm_id).eq("client_id", client_id)
        ... system_account_key in ("gst_cgst", "gst_sgst", "gst_igst") / "gst_input"

    Two independent assumptions, and a live firm broke both:

      * ITS ACCOUNTS ARE FIRM-WIDE (client_id NULL). That is how migration 011
        seeds them and how services/coa_seed_service.py creates them. The
        client-only filter matched none of them.
      * ITS ACCOUNTS ARE NOT KEYED. system_account_key is stamped by migrations
        092/098 on the accounts those migrations seeded; a chart built by
        coa_seed_service carries the same accounts with the key NULL.

    Either alone empties out_ids and in_ids, so every journal line falls through
    both branches and the function returns zero output tax and zero ITC. Nothing
    errors. gstr3b_from_books then reports books-vs-ledger as differing by the
    full value of the return — on a GSTR-3B a CA is about to file (CGST §39).

    The live firm: `1301 GST Input Tax Credit` and `2002 GST Output Tax Payable`,
    both firm-wide, both NULL-keyed, with 1,045 and 6,220 posted lines behind
    them.

WHY THE FAKE IMPLEMENTS or_ FOR REAL
    The fix turns the client filter into "this client OR firm-wide". A fake that
    treated .or_() as a passthrough would return every account regardless, and
    "a firm-wide account is found" would pass against a double that cannot tell
    scopes apart — proving nothing, and hiding a leak of another client's
    accounts. The first assertion below is that the fake itself discriminates.
"""
import pytest

import services.gst_return_service as svc

FIRM = "firm-1"
CLIENT = "client-1"
OTHER = "client-2"


# ── a fake that discriminates ────────────────────────────────────────────────

class _Q:
    def __init__(self, rows):
        self.rows = list(rows)

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def gte(self, col, val):
        self.rows = [r for r in self.rows if str(r.get(col)) >= str(val)]
        return self

    def lte(self, col, val):
        self.rows = [r for r in self.rows if str(r.get(col)) <= str(val)]
        return self

    def in_(self, col, vals):
        self.rows = [r for r in self.rows if r.get(col) in set(vals)]
        return self

    def or_(self, expr):
        """PostgREST's `col.eq.value,col.is.null` — the only form used here."""
        preds = []
        for clause in expr.split(","):
            col, op, val = clause.split(".", 2)
            if op == "eq":
                preds.append(lambda r, c=col, v=val: r.get(c) == v)
            elif op == "is" and val == "null":
                preds.append(lambda r, c=col: r.get(c) is None)
            else:                                    # pragma: no cover
                raise AssertionError(f"the fake does not implement or_ op {op!r}")
        self.rows = [r for r in self.rows if any(p(r) for p in preds)]
        return self

    def execute(self):
        return type("R", (), {"data": list(self.rows)})()


class FakeDB:
    def __init__(self, store): self.store = store
    def table(self, name): return _Q(self.store.get(name, []))


def _acct(id_, name, type_, key=None, client_id=None):
    return {"id": id_, "firm_id": FIRM, "client_id": client_id,
            "account_name": name, "account_type": type_, "system_account_key": key}


def _db(accounts, lines):
    """One posted entry in the period, carrying `lines`."""
    return FakeDB({
        "chart_of_accounts": accounts,
        "journal_entries": [{"id": "je1", "firm_id": FIRM, "client_id": CLIENT,
                             "entry_date": "2026-04-10", "is_posted": True}],
        "journal_lines": [dict(id=f"l{i}", journal_entry_id="je1", **l)
                          for i, l in enumerate(lines)],
    })


def _move(db):
    return svc._gl_gst_movements(db, FIRM, CLIENT, "2026-04-01", "2026-04-30")


# ── the fake itself ──────────────────────────────────────────────────────────

def test_the_fake_or_actually_discriminates():
    """If it did not, every scope assertion below would pass vacuously."""
    q = _Q([{"id": "a", "client_id": CLIENT}, {"id": "b", "client_id": None},
            {"id": "c", "client_id": OTHER}])
    got = {r["id"] for r in q.or_(f"client_id.eq.{CLIENT},client_id.is.null").execute().data}
    assert got == {"a", "b"}, f"the fake's or_ is not filtering: {got}"


# ── the production shape: firm-wide, NULL-keyed, one account per side ────────

COMBINED = [
    _acct("acc-in", "GST Input Tax Credit", "Asset"),
    _acct("acc-out", "GST Output Tax Payable", "Liability"),
    _acct("acc-bank", "Bank Account", "Asset"),
]


def test_firm_wide_null_keyed_accounts_are_found():
    db = _db(COMBINED, [
        {"account_id": "acc-out", "debit_paise": 0, "credit_paise": 18000},
        {"account_id": "acc-in", "debit_paise": 9000, "credit_paise": 0},
        {"account_id": "acc-bank", "debit_paise": 0, "credit_paise": 9000},
    ])
    gl = _move(db)
    assert gl["output_paise"] == 18000, (
        "output tax read as zero — the reconciliation would report the books "
        "differing from the ledger by the whole return")
    assert gl["itc_paise"] == 9000


def test_a_combined_output_account_reports_under_its_own_head():
    """It cannot say CGST or SGST, so it must not claim to."""
    db = _db(COMBINED, [{"account_id": "acc-out", "debit_paise": 0, "credit_paise": 18000}])
    heads = _move(db)["by_head"]
    assert heads.get("output") == 18000
    assert heads.get("") is None, "an empty-string head is a bug, not a bucket"
    assert heads["cgst"] == 0 and heads["sgst"] == 0


# ── the keyed chart must be completely unaffected ────────────────────────────

KEYED = [
    _acct("k-cgst", "GST Output - CGST", "Liability", "gst_cgst"),
    _acct("k-sgst", "GST Output - SGST", "Liability", "gst_sgst"),
    _acct("k-in", "GST Input Credit - CGST", "Asset", "gst_input"),
]


def test_a_keyed_chart_still_resolves_by_key_and_splits_by_head():
    db = _db(KEYED, [
        {"account_id": "k-cgst", "debit_paise": 0, "credit_paise": 5000},
        {"account_id": "k-sgst", "debit_paise": 0, "credit_paise": 5000},
        {"account_id": "k-in", "debit_paise": 3000, "credit_paise": 0},
    ])
    gl = _move(db)
    assert gl["output_paise"] == 10000
    assert gl["itc_paise"] == 3000
    assert gl["by_head"]["cgst"] == 5000 and gl["by_head"]["sgst"] == 5000, (
        "a keyed chart must still report each head separately — the name "
        "fallback has swallowed the key lookup")


def test_the_name_fallback_fires_only_for_the_side_that_found_nothing():
    """Output keyed, input not. The keyed side must keep using keys."""
    db = _db([_acct("k-cgst", "GST Output - CGST", "Liability", "gst_cgst"),
              _acct("k-decoy", "GST Output Tax Payable", "Liability"),
              _acct("acc-in", "GST Input Tax Credit", "Asset")],
             [{"account_id": "k-cgst", "debit_paise": 0, "credit_paise": 5000},
              {"account_id": "k-decoy", "debit_paise": 0, "credit_paise": 7777},
              {"account_id": "acc-in", "debit_paise": 3000, "credit_paise": 0}])
    gl = _move(db)
    assert gl["output_paise"] == 5000, (
        "the unkeyed decoy was counted — with a keyed account present the "
        "output side must not fall back to names at all")
    assert gl["itc_paise"] == 3000, "the unkeyed input side must still fall back"


# ── the two sides must not bleed into each other ─────────────────────────────

def test_an_asset_named_like_output_is_not_counted_as_output_tax():
    """account_type is the separation migration 098 enforces by keying output
    heads on Liability accounts only. Counting an asset as tax owed would
    overstate the liability on a filed return."""
    db = _db([_acct("weird", "GST Output Recoverable", "Asset")],
             [{"account_id": "weird", "debit_paise": 0, "credit_paise": 9999}])
    assert _move(db)["output_paise"] == 0


def test_a_liability_named_like_input_is_not_counted_as_itc():
    db = _db([_acct("weird", "GST Input Payable", "Liability")],
             [{"account_id": "weird", "debit_paise": 9999, "credit_paise": 0}])
    assert _move(db)["itc_paise"] == 0


# ── scope still holds ────────────────────────────────────────────────────────

def test_another_clients_account_is_not_reachable():
    db = _db([_acct("theirs", "GST Output Tax Payable", "Liability", client_id=OTHER)],
             [{"account_id": "theirs", "debit_paise": 0, "credit_paise": 4444}])
    assert _move(db)["output_paise"] == 0, (
        "widening the client filter to include firm-wide accounts must not "
        "also pull in another client's")


def test_another_firms_account_is_not_reachable():
    a = _acct("other-firm", "GST Output Tax Payable", "Liability")
    a["firm_id"] = "firm-2"
    db = _db([a], [{"account_id": "other-firm", "debit_paise": 0, "credit_paise": 4444}])
    assert _move(db)["output_paise"] == 0


def test_this_clients_own_account_is_still_found():
    db = _db([_acct("mine", "GST Output Tax Payable", "Liability", client_id=CLIENT)],
             [{"account_id": "mine", "debit_paise": 0, "credit_paise": 4444}])
    assert _move(db)["output_paise"] == 4444


# ── direction ────────────────────────────────────────────────────────────────

def test_output_is_net_of_debits_and_itc_net_of_credits():
    """A credit note debits the output liability; an ITC reversal credits the
    input asset. Both must net, or a month with reversals overstates the return."""
    db = _db(COMBINED, [
        {"account_id": "acc-out", "debit_paise": 0, "credit_paise": 18000},
        {"account_id": "acc-out", "debit_paise": 3000, "credit_paise": 0},
        {"account_id": "acc-in", "debit_paise": 9000, "credit_paise": 0},
        {"account_id": "acc-in", "debit_paise": 0, "credit_paise": 1000},
    ])
    gl = _move(db)
    assert gl["output_paise"] == 15000
    assert gl["itc_paise"] == 8000
