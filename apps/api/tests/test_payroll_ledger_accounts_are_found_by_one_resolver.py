"""The payroll ledger accounts have one vocabulary and one client-scoped resolver, for every writer and reader (POST-A-083).

The accrual, the settlement and the disbursement found their accounts by ILIKE; the 24Q tie-out and the salary challan
register by the exact name; the ESI and PT remittance register by another ILIKE. A renamed account was then found by one of
them and missed by another. These tests hold the rule: the choice (`domain/payroll/ledger_accounts.choose`), the resolver that
reads the chart for it, that every reader now asks it, that no payroll account is spelled anywhere else, and that the seed and
migration 640 speak the same vocabulary.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from domain.payroll import ledger_accounts as L
from services import payroll_ledger_accounts as R

_API = pathlib.Path(__file__).resolve().parents[1]
FIRM, CLIENT, OTHER = "f-1", "c-1", "c-2"


def row(i, name, *, client=None, key=None, active=True):
    return {"id": i, "client_id": client, "account_name": name, "system_account_key": key, "is_active": active}


# ── the choice ───────────────────────────────────────────────────────────────

def test_a_keyed_account_is_found_after_a_rename():
    keyed = row("a1", "Provident Fund Dues", key=L.PF_PAYABLE.key)
    got = L.choose(L.PF_PAYABLE, key_rows=[keyed], name_rows=[row("a2", "PF Payable (old)")], client_id=CLIENT)
    assert (got.id, got.via) == ("a1", "key")


def test_the_clients_own_row_wins_over_the_firms_at_the_same_step():
    got = L.choose(L.PF_PAYABLE, key_rows=[row("firm", "PF Payable", key=L.PF_PAYABLE.key),
                                           row("own", "PF Payable - Unit 2", client=CLIENT, key=L.PF_PAYABLE.key)],
                   name_rows=[], client_id=CLIENT)
    assert got.id == "own"


def test_another_clients_row_is_never_a_candidate():
    assert L.choose(L.PF_PAYABLE, key_rows=[row("x", "PF Payable", client=OTHER, key=L.PF_PAYABLE.key)],
                    name_rows=[row("y", "PF Payable", client=OTHER)], client_id=CLIENT) is None


def test_an_unkeyed_chart_is_still_found_by_the_postings_own_pattern():
    got = L.choose(L.TDS_PAYABLE_SALARY, key_rows=[], name_rows=[row("t", "TDS Payable - Salary")], client_id=CLIENT)
    assert (got.id, got.via) == ("t", "name")


def test_two_name_matches_take_the_exact_canonical_name_and_otherwise_refuse():
    rows = [row("a", "PF Payable"), row("b", "EPF Payable")]
    assert L.choose(L.PF_PAYABLE, key_rows=[], name_rows=rows, client_id=CLIENT).id == "a"
    with pytest.raises(L.PayrollLedgerAmbiguous) as exc:
        L.choose(L.PF_PAYABLE, key_rows=[], name_rows=[row("b", "EPF Payable"), row("c", "PF Payable - Old")], client_id=CLIENT)
    assert '"EPF Payable"' in exc.value.sentence and '"PF Payable - Old"' in exc.value.sentence


def test_an_inactive_row_is_not_found():
    assert L.choose(L.ESI_PAYABLE, key_rows=[row("k", "ESI Payable", key=L.ESI_PAYABLE.key, active=False)],
                    name_rows=[row("n", "ESI Payable", active=False)], client_id=CLIENT) is None


def test_the_tds_payable_pattern_of_the_salary_ledger_does_not_find_the_194_account():
    assert L.choose(L.TDS_PAYABLE_SALARY, key_rows=[], name_rows=[row("s", "TDS Payable")], client_id=CLIENT) is None


# ── the resolver over a chart ──────────────────────────────────────────────────

class _Q:
    def __init__(self, rows):
        self.rows, self.preds = rows, []

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.preds.append(lambda r: r.get(col) == val)
        return self

    def or_(self, expr):
        m = re.fullmatch(r"client_id\.eq\.(.+),client_id\.is\.null", expr)
        cid = m.group(1)
        self.preds.append(lambda r: r.get("client_id") in (cid, None))
        return self

    def is_(self, col, val):
        self.preds.append(lambda r: r.get(col) is None)
        return self

    def ilike(self, col, pattern):
        self.preds.append(lambda r: L._matches(str(r.get(col) or ""), pattern))
        return self

    def execute(self):
        return type("R", (), {"data": [r for r in self.rows if all(p(r) for p in self.preds)]})()


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "chart_of_accounts"
        return _Q(self.rows)


def _chart(*rows):
    return _DB([{**r, "firm_id": FIRM} for r in rows] + [{**row("elsewhere", "PF Payable", key=L.PF_PAYABLE.key),
                                                          "firm_id": "f-2"}])


def test_the_resolver_reads_the_firms_chart_and_raises_when_a_posting_needs_what_is_missing():
    db = _chart(row("p", "Provident Fund Dues", key=L.PF_PAYABLE.key))
    assert R.resolve_id(db, firm_id=FIRM, client_id=CLIENT, ledger=L.PF_PAYABLE) == "p"
    with pytest.raises(L.PayrollLedgerMissing):
        R.resolve(db, firm_id=FIRM, client_id=CLIENT, ledger=L.ESI_PAYABLE)
    assert R.resolve(db, firm_id=FIRM, client_id=CLIENT, ledger=L.ESI_PAYABLE, required=False) is None


def test_the_accrual_and_its_three_readers_land_on_the_same_renamed_account():
    """The point of the item: with the salary TDS account renamed, the 24Q tie-out, the challan register and the accrual
    agree, and the ESI and PT remittance register agrees with the accrual about ESI."""
    from services import statutory_remittance_service as rem
    from services import tds_challan_ledger_service as ch
    from services import tds_return_service as tr
    db = _chart(row("tds", "Salary TDS Payable", key=L.TDS_PAYABLE_SALARY.key),
                row("tds194", "TDS Payable"),
                row("esi", "ESIC Dues", key=L.ESI_PAYABLE.key))
    posted = R.resolve_id(db, firm_id=FIRM, client_id=CLIENT, ledger=L.TDS_PAYABLE_SALARY)
    assert posted == "tds"
    assert tr._salary_tds_account(db, FIRM, CLIENT) == ("tds", "Salary TDS Payable", None)
    assert ch.liability_account_id(db, firm_id=FIRM, client_id=CLIENT, section="192") == "tds"
    assert rem._liability_account_id(db, firm_id=FIRM, client_id=CLIENT, scheme=rem.ESIC) == "esi"


def test_the_24q_tie_out_names_an_ambiguity_instead_of_tying_to_a_guess():
    from services import tds_return_service as tr
    db = _chart(row("a", "TDS Payable - Salary (old)"), row("b", "TDS Payable - Salary FY24"))
    tid, name, note = tr._salary_tds_account(db, FIRM, CLIENT)
    assert tid is None and name is None and "will not choose" in note


# ── one vocabulary, everywhere ─────────────────────────────────────────────────

def _docstring_ids(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


#: Files that may spell a payroll account, and why. The vocabulary itself; the seed, whose names are held equal to it
#: below; and the year-end tab grouping, which lists lowercase substrings to GROUP accounts on a screen (it picks no account
#: and the keys it reads first are the vocabulary's).
_ALLOWED = {"domain/payroll/ledger_accounts.py", "services/coa_seed_service.py", "domain/reporting/year_end_lines.py"}


def test_no_payroll_account_is_named_outside_the_vocabulary():
    found = []
    for top in ("services", "routers", "domain", "jobs", "core", "models", "scripts"):
        for path in (_API / top).rglob("*.py"):
            rel = path.relative_to(_API).as_posix()
            if rel in _ALLOWED:
                continue
            tree = ast.parse(path.read_text())
            skip = _docstring_ids(tree)
            for n in ast.walk(tree):
                if not (isinstance(n, ast.Constant) and isinstance(n.value, str)) or id(n) in skip:
                    continue
                v = n.value.strip().lower()
                for ledger in L.ALL:
                    if v == ledger.name.lower() or (v.startswith("%") and ledger.pattern.strip("%").lower() in v):
                        found.append(f"{rel}:{n.lineno} {n.value!r}")
    assert found == [], "name the account through domain/payroll/ledger_accounts and find it with " \
                        "services/payroll_ledger_accounts.resolve:\n" + "\n".join(found)


def test_the_guard_sees_the_spellings_it_replaced():
    """Negative control on the rule itself: the four spellings the readers used before are caught."""
    for literal in ('"%PF Payable%"', '"TDS Payable - Salary"', '"%ESI Payable%"', '"%Salaries Expense%"'):
        n = ast.parse(f"x = {literal}").body[0].value
        v = n.value.strip().lower()
        assert any(v == l.name.lower() or (v.startswith("%") and l.pattern.strip("%").lower() in v) for l in L.ALL)


def test_the_standard_chart_carries_every_payroll_ledger_under_its_canonical_name_and_seeds_its_key():
    from services.coa_seed_service import STANDARD_COA, standard_key
    by_code = {code: name for code, name, _t, _s in STANDARD_COA}
    for ledger in L.ALL:
        assert by_code.get(ledger.code) == ledger.name, ledger
        assert standard_key(ledger.code, ledger.name) == ledger.key
    assert [c for c, n, _t, _s in STANDARD_COA if standard_key(c, n)] and \
        all(standard_key(c, n) in L.BY_KEY for c, n, _t, _s in STANDARD_COA if standard_key(c, n))


def test_the_migrations_list_is_the_vocabulary():
    sql = (_API / "migrations" / "640_payroll_ledger_accounts_carry_a_key.sql").read_text()
    pairs = set(re.findall(r"\('(payroll_[a-z_]+)',\s*'([^']+)'\)", sql))
    assert pairs == {(l.key, l.pattern) for l in L.ALL}


def test_every_payroll_key_is_on_the_year_end_statutory_tab_or_is_an_expense_or_asset():
    from domain.reporting import year_end_lines as y
    for ledger in (L.NET_SALARY_PAYABLE, L.PF_PAYABLE, L.ESI_PAYABLE, L.PT_PAYABLE, L.TDS_PAYABLE_SALARY):
        assert y.statutory_schedule_bucket(ledger.key, "Renamed Account") == "tds"
    for ledger in (L.SALARIES_EXPENSE, L.EMPLOYER_CONTRIBUTION, L.EMPLOYEE_LOANS):
        assert y.statutory_schedule_bucket(ledger.key, ledger.name) is None
