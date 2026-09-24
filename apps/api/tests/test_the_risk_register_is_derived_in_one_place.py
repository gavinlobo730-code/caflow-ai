"""THE RISK REGISTER IS DERIVED IN `apps/api`, AND THE BROWSER RENDERS IT.

`apps/web/app/risks/page.tsx` was 856 lines that made six PostgREST reads of
its own and derived NINE kinds of statutory risk in the browser — which filings
are overdue and how badly, which TDS statements are in default, which GSTINs
are wrong, which clients have gone quiet, which advance-tax instalments were
missed, which DSCs lapse soon, which loans are overdue, which deposits mature,
and which clients have no PAN — citing CGST §47, IT §200A, §201(1A), §234B/C,
§139A and §194A while doing it.

Three consequences, and none of them is abstract:

  * **`rbac()` RAN ON NONE OF THE SIX READS**, and neither did `core.authz`'s
    assignment scope, so an Executive who cannot see a client still read that
    client's compliance calendar, loans and fixed deposits.
  * **THE ADVANCE-TAX DATES WERE FOUR HARDCODED STRINGS** against
    `compliance_engine.advance_tax_due_dates`, which CLAUDE.md names as the
    single source for every due date in this product.
  * **A STATUTORY FIGURE WAS STATED THAT NOTHING CAN ESTABLISH** — see the
    domain module: §194A(3)(i) has three limbs and the registry holds one.

`domain/risk/register.py` is the rule and reads nothing;
`services/risk_register_service.py` fetches, scopes and pages;
`GET /api/risks/register` serves.

**THE GUARD IS ON THE PYTHON SIDE** — the Schedule III caption lesson. One
written in `apps/web` would assert the browser against a copy of itself.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date

import pytest

from domain.risk import register as rule

API = pathlib.Path(__file__).resolve().parent.parent
WEB = API.parent / "web"
PAGE = WEB / "app" / "risks" / "page.tsx"


# ── The browser derives nothing ────────────────────────────────────────────

def test_the_page_makes_no_database_read_of_its_own():
    src = PAGE.read_text(encoding="utf-8")
    code = "\n".join(line.split("//", 1)[0] for line in src.splitlines())
    for forbidden in ('.from("', "getSupabaseClient", "selectAll("):
        assert forbidden not in code, (
            f"app/risks/page.tsx reaches the database directly ({forbidden!r}). "
            "rbac() and core.authz's assignment scope both run on the endpoint "
            "and on neither of these."
        )


def test_the_page_asks_the_register_endpoint():
    src = PAGE.read_text(encoding="utf-8")
    assert "api.risks.register()" in src
    api_client = (WEB / "lib" / "api" / "index.ts").read_text(encoding="utf-8")
    assert '"/api/risks/register"' in api_client


def test_the_page_holds_no_statutory_rule():
    """No section citation and no threshold may be composed in the browser: the
    server supplies the whole `action` sentence. A section named in a COMMENT
    explaining the move is fine, which is why comments are stripped."""
    src = PAGE.read_text(encoding="utf-8")
    code = "\n".join(line.split("//", 1)[0] for line in src.splitlines())
    # The block comment at the head of the file explains the finding and names
    # several sections; drop it the same way.
    if "*/" in code:
        code = code.split("*/", 1)[1]
    for marker in ("§", "Section 47", "Section 200A", "194A", "234B", "139A"):
        assert marker not in code, (
            f"app/risks/page.tsx composes statutory text ({marker!r}). The "
            "`action` sentence is the server's."
        )


def test_the_page_keeps_no_category_vocabulary_it_filters_on():
    """`CATEGORY_ORDER` is a display ORDER, not a vocabulary — a kind the server
    sends that it does not name must still render. The old page's filter
    offered a hardcoded list of nine, which is how a screen comes to omit a
    category the engine emits."""
    src = PAGE.read_text(encoding="utf-8")
    assert "CATEGORY_ORDER" in src
    assert "const unnamed" in src, "the page must render kinds CATEGORY_ORDER does not name"
    assert "new Set(rows.map((r) => r.risk_type))" in src, (
        "the category filter must be built from what arrived, not from a list "
        "kept in the browser"
    )


# ── The rule is a rule: it reads nothing ───────────────────────────────────

def test_the_domain_module_touches_no_database():
    tree = ast.parse((API / "domain" / "risk" / "register.py").read_text(encoding="utf-8"))
    imported = {
        n.module or ""
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
    }
    for mod in imported:
        assert "supabase" not in mod and "repositor" not in mod, (
            f"domain/risk/register imports {mod} — it must decide, not fetch"
        )
    src = (API / "domain" / "risk" / "register.py").read_text(encoding="utf-8")
    assert ".table(" not in src


def test_the_service_pages_every_read():
    """PostgREST caps a response at ~1000 rows and says nothing when it does.
    `compliance_calendar` carries a row per obligation per client per period, so
    a fifty-client book passes that inside a year — and a register short by an
    unknown amount reads exactly like a clean one."""
    src = (API / "services" / "risk_register_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    table_reads = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "table"
    )
    paged = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "fetch_all"
    )
    assert table_reads >= 5, f"only {table_reads} table reads found — the probe is broken"
    assert paged == table_reads, (
        f"{table_reads} table reads but only {paged} go through fetch_all"
    )


def test_the_service_derives_the_advance_tax_dates():
    """Not four literals. CLAUDE.md makes compliance_engine the single source
    for every due date in this product, so a CBDT extension moves one thing."""
    src = (API / "services" / "risk_register_service.py").read_text(encoding="utf-8")
    assert "advance_tax_due_dates" in src
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    for literal in ("-06-15", "-09-15", "-12-15", "-03-15"):
        assert literal not in code, f"the §208 dates are derived, not written ({literal})"


# ── The rule itself ────────────────────────────────────────────────────────

_AS_AT = date(2026, 9, 24)


def _reg(**over):
    args = dict(
        calendar=[], clients=[], client_ids_with_recent_entries=set(),
        advance_tax_installments=[], advance_tax_tracked_client_ids=set(),
        advance_tax_filed_keys=set(), dsc_rows=[], loans=[], deposits=[],
        as_at=_AS_AT,
    )
    args.update(over)
    return rule.build(**args)


def test_a_tds_statement_is_never_graded_on_the_ordinary_ladder():
    """§234E charges ₹200 a DAY from the due date and is payable before the
    statement can be delivered, so a one-day-late statement is already a real
    exposure. The ordinary ladder would call it `low`."""
    cal = [{"client_id": "c", "compliance_type": "TDS26Q",
            "due_date": "2026-09-23", "filing_status": "pending"}]
    rows = _reg(calendar=cal, clients=[{"id": "c", "client_name": "X", "pan": "AABCU9603R"}]).rows
    tds = [r for r in rows if r.risk_type == "TDS Default"]
    assert len(tds) == 1 and tds[0].severity == "high"
    assert rule.overdue_severity(1) == "low", "the premise: the ordinary ladder would say low"


def test_a_tds_statement_is_not_also_an_ordinary_overdue_filing():
    """ONE list, read twice. Two copies is how 27Q lands in both buckets."""
    cal = [{"client_id": "c", "compliance_type": "TDS27Q",
            "due_date": "2026-01-31", "filing_status": "pending"}]
    rows = _reg(calendar=cal, clients=[{"id": "c", "client_name": "X", "pan": "AABCU9603R"}]).rows
    assert [r.risk_type for r in rows if "Filing" in r.risk_type or "TDS" in r.risk_type] \
        == ["TDS Default"]


def test_27eq_is_not_in_the_statement_list():
    """TCS under §206C, which this product records as reference data it does not
    implement — so nothing here generates one to be late with."""
    assert "TDS27EQ" not in rule.TDS_STATEMENT_TYPES
    assert set(rule.TDS_STATEMENT_TYPES) == {"TDS24Q", "TDS26Q", "TDS27Q"}


def test_a_gstin_is_tested_against_the_check_digit():
    """The browser's copy was a shape regex, which accepts every transposition
    inside the PAN — the commonest wrong GSTIN, and the only kind this section
    exists to find."""
    good = "27AAPFU0939F1ZV"
    transposed = "27AAPFU0399F1ZV"  # two PAN characters swapped; same shape
    clients = [
        {"id": "a", "client_name": "Good", "gstin": good, "pan": "AABCU9603R"},
        {"id": "b", "client_name": "Bad", "gstin": transposed, "pan": "AABCU9603R"},
    ]
    rows = [r for r in _reg(clients=clients).rows if r.risk_type == "GSTIN Mismatch"]
    assert [r.client_name for r in rows] == ["Bad"]
    assert "check digit" in rows[0].description


def test_an_unregistered_client_is_not_a_gstin_mismatch():
    clients = [{"id": "a", "client_name": "No GST", "gstin": "", "pan": "AABCU9603R"}]
    assert not [r for r in _reg(clients=clients).rows if r.risk_type == "GSTIN Mismatch"]


def test_a_dsc_carries_no_client_because_the_table_holds_none():
    dsc = [{"id": "d", "holder_name": "R Sharma", "expiry_date": "2026-10-01"}]
    rows = [r for r in _reg(dsc_rows=dsc).rows if r.risk_type == "DSC Expiry"]
    assert rows and rows[0].client_id == "" and rows[0].client_name == "Firm-wide"
    assert rows[0].severity == "high", "7 days out is inside the urgent window"


def test_a_dsc_beyond_the_notice_window_is_not_raised():
    far = [{"id": "d", "holder_name": "R Sharma", "expiry_date": "2027-06-01"}]
    assert not [r for r in _reg(dsc_rows=far).rows if r.risk_type == "DSC Expiry"]


def test_no_figure_is_quoted_for_section_194a():
    """§194A(3)(i) sets one limit for a banking company, another as the general
    rule and another for a senior citizen; `section_rates` holds only the
    general one. The browser stated ₹40,000 — the bank limb as it stood before
    the Finance Act 2025. The section is named and no number is given."""
    fd = [{"id": "f", "client_id": "c", "bank_name": "SBI",
           "maturity_date": "2026-10-01", "maturity_amount_paise": 500000}]
    rows = [r for r in _reg(deposits=fd).rows if r.risk_type == "FD Maturing Soon"]
    assert rows
    action = rows[0].action
    assert "194A" in action
    for figure in ("40,000", "10,000", "50,000", "1,00,000"):
        assert figure not in action, (
            f"the FD advice quotes {figure}, and no module here can establish "
            "which §194A limb applies"
        )


def test_the_domain_module_states_no_194a_threshold_at_all():
    """On the SOURCE as well as the answer — a threshold held as a constant is
    one refactor away from being quoted."""
    src = (API / "domain" / "risk" / "register.py").read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    if '"""' in code:
        parts = code.split('"""')
        code = "".join(parts[::2])  # drop docstrings
    assert "section_rates" not in code, (
        "the register must not read the §194A threshold; see the module docstring"
    )


def test_an_advance_tax_instalment_is_only_raised_for_a_tracked_client():
    """A client with no advance-tax obligation recorded has no instalment to
    miss, and inventing one for every client would bury the real ones."""
    clients = [{"id": "c", "client_name": "X", "pan": "AABCU9603R"},
               {"id": "d", "client_name": "Y", "pan": "AABCU9603R"}]
    inst = [{"due_date": "2026-06-15", "installment": "15% by 15 Jun 2026"}]
    rows = [r for r in _reg(
        clients=clients, advance_tax_installments=inst,
        advance_tax_tracked_client_ids={"c"},
    ).rows if r.risk_type == "Advance Tax Default"]
    assert [r.client_id for r in rows] == ["c"]


def test_a_filed_instalment_is_not_a_default():
    clients = [{"id": "c", "client_name": "X", "pan": "AABCU9603R"}]
    inst = [{"due_date": "2026-06-15", "installment": "15% by 15 Jun 2026"}]
    rows = [r for r in _reg(
        clients=clients, advance_tax_installments=inst,
        advance_tax_tracked_client_ids={"c"},
        advance_tax_filed_keys={"c|2026-06-15"},
    ).rows if r.risk_type == "Advance Tax Default"]
    assert not rows


@pytest.mark.parametrize("days,expected", [
    (31, "high"), (30, "medium"), (15, "medium"), (14, "low"), (1, "low"),
])
def test_the_overdue_ladder_is_exact(days: int, expected: str):
    assert rule.overdue_severity(days) == expected


def test_the_ladder_says_it_is_a_convention():
    """No section grades a delay, so the register must not present the ladder as
    though one did."""
    assert "convention" in rule.OVERDUE_LADDER_NOTE
    reg = _reg()
    assert rule.OVERDUE_LADDER_NOTE in reg.notes


def test_every_row_carries_particulars_the_browser_can_render():
    """The screen holds no per-kind knowledge, so a kind that supplies no
    particulars renders as a client name and a severity and nothing else."""
    cal = [{"client_id": "c", "compliance_type": "GSTR3B",
            "due_date": "2026-07-20", "filing_status": "pending"}]
    reg = _reg(
        calendar=cal,
        clients=[{"id": "c", "client_name": "X", "gstin": "", "pan": ""}],
        dsc_rows=[{"id": "d", "holder_name": "R", "expiry_date": "2026-10-01"}],
        loans=[{"id": "l", "client_id": "c", "lender_name": "HDFC",
                "loan_type": "Term", "outstanding_paise": 100000}],
    )
    assert reg.rows
    for row in reg.rows:
        assert isinstance(row.particulars, dict)
        assert row.particulars, f"{row.risk_type} supplies no particulars"


def test_the_counts_agree_with_the_rows():
    cal = [{"client_id": "c", "compliance_type": "GSTR3B",
            "due_date": "2026-07-20", "filing_status": "pending"}]
    reg = _reg(calendar=cal, clients=[{"id": "c", "client_name": "X", "pan": ""}])
    counts = reg.counts
    assert counts["total"] == len(reg.rows)
    assert sum(counts[s] for s in rule.SEVERITIES) == counts["total"]


def test_a_severity_outside_the_vocabulary_is_refused():
    with pytest.raises(AssertionError):
        rule.RiskRow(client_id="c", client_name="X", risk_type="T",
                     description="d", severity="urgent", action="a")
