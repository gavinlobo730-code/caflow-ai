"""POST-A-272 (the live re-check) — a challan or remittance tied to an entry that still stands but no longer debits the tax-payable account says so.

WHAT WAS WRONG
    A challan (`tds_challans.journal_entry_id`) and an ESI or professional-tax remittance (`statutory_remittances.journal_entry_id`) are tied to the
    ledger entry that paid them, and the CHALLAN's link door refuses an entry that does not debit the liability account the payment clears (the
    remittance's door asks only that the entry is the client's own and live). After the link nothing asked again. A manual journal can be edited in place while its period is open (migration 266), so the entry that was tied
    because it debited "TDS Payable" could be rewritten to debit something else, and the register went on saying "Tied to an entry": a false
    statement about the ledger, on a statutory register, with the entry live and nothing to tell it from a good link.

WHAT THIS PINS
    STATE     a tied challan whose entry is live reads `not_debiting` when no line of the entry DEBITS the account its section clears ("TDS
              Payable - Salary" for section 192, "TDS Payable" for the rest), whether the line now debits another account, was moved to the
              credit side or was deleted; an entry that still debits it stays `live`;
    WORDS     the label names the account, the note says the entry is still in the books, that the document stays because the payment was made,
              and what to do (take the link back and tie the entry that records it); the remittance side says the same of its own account;
    CANNOT    a challan or a remittance in a chart that holds no ACTIVE account of that name (never added, renamed, or made inactive after the
              link; a remittance's door never asked, a challan's asked only at the time) is UNKNOWN, "not checked", with the reason and no
              take-back, never a link that looks checked;
    FAILED    when the lines cannot be read the live rows are UNKNOWN, never live, and an entry that is not live keeps the state it already had;
    NEVER     reading changes nothing: the link is not cleared and nothing is posted.
"""
import uuid

import pytest

from services import statutory_remittance_service as rem
from services import tds_challan_ledger_service as svc
from tests.e2e_harness import FakeDB

FIRM = "11111111-1111-1111-1111-111111111111"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ACC_TDS, ACC_SAL, ACC_BANK, ACC_OTHER = "acc-tds", "acc-tds-salary", "acc-bank", "acc-other"


def _id(n: int) -> str:
    return str(uuid.UUID(int=n))


GOOD, MOVED, CREDITED, NO_LINE, REVERSED = (_id(i) for i in (1, 2, 3, 4, 5))


def _entry(db, je, debit_account, *, side="debit", reversed_=False):
    db.seed("journal_entries", {"id": je, "firm_id": FIRM, "client_id": A, "entry_date": "2026-07-07", "reference_no": f"R-{je[-2:]}",
                                "narration": "TDS paid", "is_posted": True, "is_reversed": reversed_, "reversal_of": None, "deleted_at": None})
    if debit_account:
        db.seed("journal_lines", {"journal_entry_id": je, "account_id": debit_account,
                                  "debit_paise": 100_000_00 if side == "debit" else 0, "credit_paise": 0 if side == "debit" else 100_000_00})
    db.seed("journal_lines", {"journal_entry_id": je, "account_id": ACC_BANK, "debit_paise": 0, "credit_paise": 100_000_00})


def _challan(db, n, link, *, section="194C"):
    return db.seed("tds_challans", {"id": _id(100 + n), "firm_id": FIRM, "client_id": A, "section": section, "total_paise": 100_000_00,
                                    "payment_date": "2026-07-07", "challan_no": f"CH-{n}", "journal_entry_id": link,
                                    "financial_year": "2026-27", "quarter": "Q2"})


@pytest.fixture
def world():
    db = FakeDB()
    for aid, name in ((ACC_TDS, "TDS Payable"), (ACC_SAL, "TDS Payable - Salary"), (ACC_BANK, "Bank"), (ACC_OTHER, "Office Expenses")):
        db.seed("chart_of_accounts", {"id": aid, "firm_id": FIRM, "client_id": A, "account_name": name, "is_active": True})
    _entry(db, GOOD, ACC_TDS)                       # still debits TDS Payable
    _entry(db, MOVED, ACC_OTHER)                    # edited in place to debit something else
    _entry(db, CREDITED, ACC_TDS, side="credit")    # TDS Payable moved to the credit side
    _entry(db, NO_LINE, None)                       # the TDS line was deleted: only the bank leg is left
    _entry(db, REVERSED, ACC_TDS, reversed_=True)
    return db


def annotated(db, *links, section="194C"):
    rows = [_challan(db, n, link, section=section) for n, link in enumerate(links)]
    svc.annotate_links(db, firm_id=FIRM, client_id=A, rows=rows)
    return rows


# ── the challan ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_entry_that_still_debits_the_account_stays_live(world):
    row, = annotated(world, GOOD)
    assert row["ledger_link"] == {"state": "live", "label": "Tied to an entry", "note": None}


@pytest.mark.parametrize("entry", [MOVED, CREDITED, NO_LINE])
def test_an_entry_that_no_longer_debits_the_account_says_so_whatever_became_of_the_line(world, entry):
    row, = annotated(world, entry)
    link = row["ledger_link"]
    assert link["state"] == "not_debiting"
    assert link["label"] == 'Tied to an entry that no longer debits "TDS Payable"'
    assert "still in the books" in link["note"] and "The challan stays: the tax was deposited." in link["note"] and "Take the link back" in link["note"]
    assert row["journal_entry_id"] == entry, "reading the link does not clear it"


def test_a_salary_challan_is_judged_against_the_salary_account_and_not_the_other_one(world):
    # GOOD debits "TDS Payable"; a section 192 challan clears "TDS Payable - Salary", so the same entry is not its payment.
    row, = annotated(world, GOOD, section="192")
    assert row["ledger_link"]["state"] == "not_debiting"
    assert row["ledger_link"]["label"] == 'Tied to an entry that no longer debits "TDS Payable - Salary"'
    _entry(world, _id(50), ACC_SAL)
    row2, = annotated(world, _id(50), section="192")
    assert row2["ledger_link"]["state"] == "live"


def test_an_entry_that_is_not_live_keeps_the_state_it_already_had(world):
    row, = annotated(world, REVERSED)
    assert row["ledger_link"]["state"] == "reversed"


def test_a_challan_in_a_chart_without_its_account_is_not_checked_and_never_passed_as_checked():
    db = FakeDB()
    _entry(db, GOOD, ACC_TDS)
    row, = annotated(db, GOOD)
    link = row["ledger_link"]
    assert link["state"] == "unknown" and link["label"] == "Tied to an entry (not checked)"
    assert "no active TDS Payable account" in link["note"] and "The challan stays: the tax was deposited." in link["note"]
    assert "make it active again" in link["note"] and "could not be read" not in link["note"], "a missing account is not a failed read"


@pytest.mark.parametrize("after_the_link", ["renamed", "made inactive"])
def test_an_account_renamed_or_made_inactive_after_the_link_leaves_the_challan_not_checked(world, after_the_link):
    """The door asked for the account at the time of the link; nothing stops the chart changing after it."""
    change = {"account_name": "Statutory dues"} if after_the_link == "renamed" else {"is_active": False}
    world.table("chart_of_accounts").update(change).eq("id", ACC_TDS).execute()
    row, = annotated(world, MOVED)           # an entry that does not debit TDS Payable, which a working check would have caught
    assert row["ledger_link"]["state"] == "unknown", after_the_link
    assert row["journal_entry_id"] == MOVED, "reading the link does not clear it"


def test_a_failed_read_of_the_lines_marks_the_live_rows_unknown_and_leaves_the_others(world, monkeypatch):
    import core.observability as obs
    seen = []
    monkeypatch.setattr(rem, "entries_debiting", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **k: seen.append(k.get("operation")))
    live, gone = annotated(world, GOOD, REVERSED)
    assert live["ledger_link"]["state"] == "unknown" and "not checked just now" in live["ledger_link"]["label"]
    assert gone["ledger_link"]["state"] == "reversed"
    assert seen == ["tds_challan_ledger_service.annotate_links.debits"]


def test_the_lines_of_every_tied_entry_are_read_in_one_request_and_an_untied_challan_reads_none(world, monkeypatch):
    calls = []
    real = rem.entries_debiting
    monkeypatch.setattr(rem, "entries_debiting", lambda db, **k: (calls.append(k), real(db, **k))[1])
    annotated(world, GOOD, MOVED, CREDITED, None)
    assert len(calls) == 1 and sorted(calls[0]["entry_ids"]) == sorted([GOOD, MOVED, CREDITED])
    calls.clear()
    annotated(world, None, None)
    assert calls == []


def test_more_entries_than_one_request_holds_are_all_judged(world):
    ids = [_id(1000 + i) for i in range(230)]
    for i, je in enumerate(ids):
        _entry(world, je, ACC_TDS if i % 2 == 0 else ACC_OTHER)
    rows = annotated(world, *ids)
    states = [r["ledger_link"]["state"] for r in rows]
    assert states[::2] == ["live"] * 115 and states[1::2] == ["not_debiting"] * 115


def test_reading_posts_nothing_and_changes_no_challan(world):
    before = (world.rows("journal_entries"), world.rows("journal_lines"))
    annotated(world, MOVED)
    assert (world.rows("journal_entries"), world.rows("journal_lines")) == before
    assert {r["journal_entry_id"] for r in world.rows("tds_challans")} == {MOVED}


# ── the ESI and professional-tax remittances ─────────────────────────────────────────────────────────────────────────

ESI_ACC = "acc-esi"


@pytest.fixture
def esi():
    db = FakeDB()
    db.seed("clients", {"id": A, "firm_id": FIRM, "client_name": "Acme"})
    for aid, name in ((ESI_ACC, "ESI Payable"), (ACC_BANK, "Bank - Current"), (ACC_OTHER, "Office Expenses")):
        db.seed("chart_of_accounts", {"id": aid, "firm_id": FIRM, "client_id": A, "account_name": name, "account_type": "Liability", "is_active": True})
    return db


def _remittance(db, entry_id, *, month="2026-09"):
    r = rem.record(db, firm_id=FIRM, client_id=A, scheme=rem.ESIC, wage_month=month, submitted_on="2026-10-14", status=rem.PAID,
                   paid_on="2026-10-15", amount_paise=10_500_00)
    db.table("statutory_remittances").update({"journal_entry_id": entry_id}).eq("id", r["id"]).execute()
    return r


def _esi_entry(db, eid, account):
    db.seed("journal_entries", {"id": eid, "firm_id": FIRM, "client_id": A, "entry_date": "2026-10-15", "reference_no": eid, "narration": "ESI",
                                "is_posted": True, "is_reversed": False, "reversal_of": None, "deleted_at": None})
    db.seed("journal_lines", {"journal_entry_id": eid, "account_id": account, "debit_paise": 10_500_00, "credit_paise": 0})
    db.seed("journal_lines", {"journal_entry_id": eid, "account_id": ACC_BANK, "debit_paise": 0, "credit_paise": 10_500_00})


def test_a_remittance_whose_entry_still_debits_its_account_is_not_listed(esi):
    _esi_entry(esi, "JE-OK", ESI_ACC)
    _remittance(esi, "JE-OK")
    assert rem.stale_links(esi, firm_id=FIRM, client_id=A) == []


def test_a_remittance_whose_entry_no_longer_debits_its_account_is_listed_in_words(esi):
    _esi_entry(esi, "JE-MOVED", ACC_OTHER)
    _remittance(esi, "JE-MOVED")
    stale, = rem.stale_links(esi, firm_id=FIRM, client_id=A)
    link = stale["ledger_link"]
    assert link["state"] == "not_debiting" and link["can_take_back"] is True
    # The remittance's door does not ask that the entry debits the account, so the words claim no history: it "does not", not "no longer".
    assert link["label"] == "Tied to an entry that does not debit ESI Payable"
    assert "still in the books" in link["note"] and "may never have" in link["note"] and "The remittance stays: it was paid." in link["note"]
    assert "no longer" not in link["label"] + link["note"]
    assert stale["journal_entry_id"] == "JE-MOVED"


def test_a_remittance_whose_lines_cannot_be_read_is_listed_unknown_and_never_clean(esi, monkeypatch):
    _esi_entry(esi, "JE-OK", ESI_ACC)
    _remittance(esi, "JE-OK")
    monkeypatch.setattr(rem, "entries_debiting", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    stale, = rem.stale_links(esi, firm_id=FIRM, client_id=A)
    assert stale["ledger_link"]["state"] == "unknown" and stale["ledger_link"]["can_take_back"] is False


def test_a_remittance_in_a_chart_without_its_account_is_listed_not_checked_and_never_passed_as_checked(esi):
    """The remittance door does not ask that the account exists, so the link can be made in such a chart. Leaving the row out of the list would
    show it as a link that was checked."""
    esi.table("chart_of_accounts").delete().eq("id", ESI_ACC).execute()
    _esi_entry(esi, "JE-X", ACC_OTHER)
    _remittance(esi, "JE-X")
    stale, = rem.stale_links(esi, firm_id=FIRM, client_id=A)
    link = stale["ledger_link"]
    assert link["state"] == "unknown" and link["label"] == "Tied to an entry (not checked)"
    assert link["can_take_back"] is False, "with the account gone the screen lists no entry to tie instead, so taking the link back would lose it"
    assert "no active ESI Payable account" in link["note"] and "could not be checked" in link["note"]
    assert "Add the account, or make it active again" in link["note"]
    assert "could not be read" not in link["note"], "a missing account is not a failed read"


def test_a_remittance_whose_account_was_made_inactive_is_told_the_account_is_not_active_and_not_that_it_is_missing(esi):
    esi.table("chart_of_accounts").update({"is_active": False}).eq("id", ESI_ACC).execute()
    _esi_entry(esi, "JE-Y", ACC_OTHER)
    _remittance(esi, "JE-Y")
    stale, = rem.stale_links(esi, firm_id=FIRM, client_id=A)
    assert stale["ledger_link"]["state"] == "unknown"
    assert "no active ESI Payable account" in stale["ledger_link"]["note"] and "make it active again" in stale["ledger_link"]["note"]


def test_the_challan_words_keep_no_longer_because_its_door_does_refuse_an_entry_with_no_debit(world):
    row, = annotated(world, MOVED)
    assert row["ledger_link"]["label"] == 'Tied to an entry that no longer debits "TDS Payable"'
    assert "may never have" not in row["ledger_link"]["note"]


def test_one_account_lookup_per_scheme_however_many_remittances_are_tied(esi, monkeypatch):
    for n in range(5):
        _esi_entry(esi, f"JE-{n}", ESI_ACC)
        _remittance(esi, f"JE-{n}", month=f"2026-0{n + 1}")
    calls = []
    real = rem._liability_account_id
    monkeypatch.setattr(rem, "_liability_account_id", lambda db, **k: (calls.append(k["scheme"]), real(db, **k))[1])
    assert rem.stale_links(esi, firm_id=FIRM, client_id=A) == []
    assert calls == [rem.ESIC], f"the account was looked up {len(calls)} times for one scheme: {calls}"


class _CappedLines:
    """`journal_lines` behind PostgREST's 1,000-row cap: it answers at most 1,000 rows to one request and says nothing when it cuts one short.
    It supports the filters the paged debit read uses (`in_`, `gt` on two columns, `order`, `limit`) and counts its requests."""

    CAP = 1000

    def __init__(self, rows):
        self._rows, self.requests = rows, 0

    def table(self, name):
        assert name == "journal_lines"
        outer = self

        class Q:
            def __init__(self):
                self._in, self._gt, self._order, self._limit = [], [], None, None
            def select(self, *_a, **_k): return self
            def in_(self, col, vals): self._in.append((col, set(vals))); return self
            def gt(self, col, v): self._gt.append((col, v)); return self
            def order(self, col, desc=False): self._order = col; return self
            def limit(self, n): self._limit = n; return self
            def execute(self):
                outer.requests += 1
                rows = [r for r in outer._rows if all(r[c] in vs for c, vs in self._in) and all(r[c] > v for c, v in self._gt)]
                if self._order:
                    rows.sort(key=lambda r: r[self._order])
                class R:
                    pass
                out = R()
                out.data = rows[:min(self._limit or _CappedLines.CAP, _CappedLines.CAP)]
                return out
        return Q()


def test_a_hundred_entries_with_twelve_debit_lines_each_are_all_judged_past_the_row_cap():
    """1,200 debit lines for one chunk of 100 entries: one unpaged request would have returned 1,000 and flagged the last 17 entries' good links."""
    rows, n = [], 0
    for e in range(100):
        for _ in range(12):
            n += 1
            rows.append({"id": f"{n:06d}", "journal_entry_id": f"JE{e:03d}", "account_id": "ACC", "debit_paise": 100})
        n += 1
        rows.append({"id": f"{n:06d}", "journal_entry_id": f"JE{e:03d}", "account_id": "BANK", "debit_paise": 0})   # not a debit
    db = _CappedLines(rows)
    found = rem.entries_debiting(db, entry_ids=[f"JE{e:03d}" for e in range(100)], account_ids=["ACC", "BANK"])
    assert found == {(f"JE{e:03d}", "ACC") for e in range(100)}, f"{100 - len(found)} good links would have read as not debiting"
    assert db.requests >= 2, "one request cannot have read 1,200 rows past a 1,000-row cap"


def test_the_reader_judges_only_debits_and_only_the_accounts_asked(esi):
    _esi_entry(esi, "JE-1", ESI_ACC)
    got = rem.entries_debiting(esi, entry_ids=["JE-1", None, ""], account_ids=[ESI_ACC, None])
    assert got == {("JE-1", ESI_ACC)}, "the bank's credit line is not a debit and was not asked for"
    assert rem.entries_debiting(esi, entry_ids=[], account_ids=[ESI_ACC]) == set()
    assert rem.entries_debiting(esi, entry_ids=["JE-1"], account_ids=[]) == set()
