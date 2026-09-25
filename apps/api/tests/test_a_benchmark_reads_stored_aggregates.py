"""A cross-client benchmark reads stored rows, and an absent figure is not nil.

WHAT THIS IS FOR (STUCK.md §1; D30; migration 417)

    A client's effective tax rate is derived from that client's whole ledger,
    so computing it for every client to compare one against them is CLAUDE.md's
    reporting rule broken twice over. The answer is a table the nightly sweep
    fills and the benchmark reads.

    The rule this guards is the one that makes the table honest: in a
    DISTRIBUTION, a figure nobody could derive read as zero moves every median
    it is counted in AND makes the client it belongs to read as the firm's best
    performer on a ratio nobody computed for them. So `None` is excluded, `0`
    is counted, and the two are told apart on whether a SOURCE ROW was found
    rather than on whether the total came to zero.

    The vocabulary half is the Schedule III caption lesson: the twelve figures
    are named once, and the migration, the service and the router are asserted
    against that one list rather than against each other.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from domain.practice import client_metrics as rule
from services import client_metrics_service as svc

API = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = API / "migrations" / "417_a_benchmark_reads_stored_aggregates_not_every_ledger.sql"


def _row(name: str, **figures) -> rule.ClientPeriod:
    return rule.ClientPeriod(
        client_id=name, client_name=name, financial_year="2026-27",
        figures={f: figures.get(f) for f in rule.FIGURES},
    )


# ── NULL IS NOT NIL ──────────────────────────────────────────────────────────

def test_a_client_with_no_figure_is_left_out_of_the_median_not_counted_as_nil():
    rows = [
        _row("a", turnover_paise=1_000_000),
        _row("b", turnover_paise=3_000_000),
        _row("c"),                                   # never derived
    ]
    d = rule.distribution("turnover_paise", rows, lambda r: r.get("turnover_paise"))
    assert d.n == 2, "the client with no turnover was counted"
    assert d.median == 2_000_000
    assert d.lowest == 1_000_000
    assert d.not_measured == ("c",)


def test_a_real_nil_is_counted_because_it_is_an_answer():
    rows = [_row("a", turnover_paise=0), _row("b", turnover_paise=2_000_000)]
    d = rule.distribution("turnover_paise", rows, lambda r: r.get("turnover_paise"))
    assert d.n == 2 and d.lowest == 0 and d.median == 1_000_000


def test_negative_control_counting_none_as_zero_moves_the_median():
    # The defect this guard exists to catch, run deliberately: if `None` were
    # read as 0 the median would halve and the silent client would rank lowest.
    rows = [_row("a", turnover_paise=1_000_000), _row("b", turnover_paise=3_000_000), _row("c")]
    honest = rule.distribution("t", rows, lambda r: r.get("turnover_paise"))
    wrong = rule.distribution("t", rows, lambda r: r.get("turnover_paise") or 0)
    assert honest.median != wrong.median
    assert wrong.median == 1_000_000 and honest.median == 2_000_000


def test_the_exclusion_is_per_key_not_per_row():
    # A client missing payroll still counts towards the GST distribution.
    rows = [
        _row("a", turnover_paise=100, payroll_cost_paise=10),
        _row("b", turnover_paise=300),
    ]
    assert rule.distribution("t", rows, lambda r: r.get("turnover_paise")).n == 2
    assert rule.distribution("p", rows, lambda r: r.get("payroll_cost_paise")).n == 1


# ── A RATIO REFUSES RATHER THAN ANSWERING ZERO ───────────────────────────────

@pytest.mark.parametrize("num,den", [(None, 100), (100, None), (100, 0), (100, -50)])
def test_a_ratio_refuses_where_it_cannot_be_computed(num, den):
    assert rule.ratio_bps(num, den) is None


def test_a_negative_denominator_is_refused_for_its_own_reason():
    # Profit before tax can legitimately be a LOSS, and "tax as 40% of a loss"
    # is not a rate a reader can use in either direction.
    assert rule.ratio_bps(50_000, -200_000) is None


def test_a_ratio_is_basis_points_and_an_integer():
    assert rule.ratio_bps(2_500, 10_000) == 2500
    assert isinstance(rule.ratio_bps(1, 3), int)


# ── POSITION ─────────────────────────────────────────────────────────────────

def test_rank_one_is_the_lowest_and_a_silent_client_has_no_rank():
    p = rule.position("k", 200, [100, 200, 300])
    assert (p.rank, p.of) == (2, 3)
    assert rule.position("k", None, [100, 200]).rank is None


def test_the_benchmark_ranks_and_never_judges():
    src = (API / "domain" / "practice" / "client_metrics.py").read_text()
    body = "\n".join(
        l for l in src.splitlines() if not l.strip().startswith(("#", "*"))
    )
    # No verdict vocabulary in the code. An effective tax rate above the firm's
    # median is a fact; "high" is an opinion about a client's affairs.
    for word in ("healthy", "unhealthy", "too high", "too low", "warning"):
        assert word not in body.lower(), f"the benchmark judges: {word!r}"


# ── ONE VOCABULARY, THREE READERS ────────────────────────────────────────────

def test_the_migration_declares_exactly_the_figures_the_module_names():
    sql = MIGRATION.read_text()
    declared = set(re.findall(r"^\s{4}(\w+_paise|employee_count)\s+(?:BIGINT|INTEGER)",
                              sql, re.M))
    assert declared == set(rule.FIGURES), (
        "migration 417 and domain/practice/client_metrics.FIGURES disagree about "
        "which figures exist — the column list is fixed once (D30) because a "
        "column added later cannot be back-filled for a locked period"
    )


def test_every_column_is_nullable_with_no_default():
    # The load-bearing half of migration 417: `DEFAULT 0` would make "had none"
    # and "nobody could derive it" the same row.
    sql = MIGRATION.read_text()
    for f in rule.FIGURES:
        line = next(l for l in sql.splitlines() if re.match(rf"^\s{{4}}{f}\s", l))
        assert "NOT NULL" not in line and "DEFAULT" not in line, \
            f"{f} is not nullable-with-no-default: {line.strip()!r}"


def test_the_service_answers_every_figure_or_names_a_gap_for_it():
    c = svc._Collector()
    assert set(c.figures) == set(rule.FIGURES)
    assert all(v is None for v in c.figures.values()), \
        "a collector starts with an answer nobody computed"
    c.cannot("turnover_paise", "because")
    assert c.figures["turnover_paise"] is None
    assert [g.figure for g in c.gaps] == ["turnover_paise"]


def test_every_figure_has_a_meaning_a_ca_can_read():
    assert set(rule.FIGURE_MEANING) == set(rule.FIGURES)
    assert all(len(v) > 40 for v in rule.FIGURE_MEANING.values())


def test_employee_count_is_not_money():
    assert "employee_count" not in rule.MONEY_FIGURES
    assert set(rule.MONEY_FIGURES) == {f for f in rule.FIGURES if f.endswith("_paise")}


def test_every_ratio_names_figures_that_exist():
    for key, num, den in rule.RATIOS:
        assert num in rule.FIGURES and den in rule.FIGURES, key


# ── THE PERIOD KEYS ──────────────────────────────────────────────────────────

def test_a_financial_year_is_twelve_mmyyyy_periods_starting_in_april():
    p = svc._periods_in("2026-27")
    assert len(p) == 12
    assert p[0] == "042026" and p[-1] == "032027"


def test_the_periods_are_named_never_ranged():
    # MMYYYY is TEXT, so '042026' > '032027' — a gte/lte would drop the first
    # nine months of every year and keep three belonging to the next. GST-10's
    # trap, restated here because this module keys on the same column.
    p = svc._periods_in("2026-27")
    assert min(p) != p[0], "the fixture no longer demonstrates the trap"
    src = (API / "services" / "client_metrics_service.py").read_text()
    assert '.in_("period"' in src and '.gte("period"' not in src


def test_the_preceding_year_is_derived():
    assert svc.preceding_fy("2026-27") == "2025-26"
    assert svc.preceding_fy("2020-21") == "2019-20"
    assert svc.preceding_fy("2000-01") == "1999-00"


def test_the_sweep_covers_two_years_and_says_so():
    assert svc.YEARS_SWEPT == 2
    years = svc.years_to_sweep()
    assert len(years) == 2 and years[1] == svc.preceding_fy(years[0])


# ── WHAT THE SWEEP READS, AND HOW ────────────────────────────────────────────

def test_every_row_set_read_is_paged():
    """PostgREST caps a response at ~1000 rows and says nothing."""
    src = (API / "services" / "client_metrics_service.py").read_text()
    tree = ast.parse(src)
    tables = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "table" and node.args
                and isinstance(node.args[0], ast.Constant)):
            tables.add(node.args[0].value)
    # Every read but the upsert target goes through fetch_all.
    assert tables - {"client_period_metrics"}, "the fixture found no reads at all"
    assert src.count("fetch_all(") == len(tables - {"client_period_metrics"}), (
        "a read in client_metrics_service is not paged — see CLAUDE.md on "
        "core/db_paging.fetch_all"
    )


def test_payroll_counts_released_runs_only_and_asks_the_domain():
    # PAY-04. The tuple MOVED to domain/payroll/run_status so a service does
    # not have to import a router to reach it.
    from domain.payroll.run_status import PAYROLL_RELEASED, PAYROLL_UNRELEASED
    assert PAYROLL_RELEASED == ("finalized", "paid")
    assert PAYROLL_UNRELEASED == ("draft", "review")
    src = (API / "services" / "client_metrics_service.py").read_text()
    assert "from domain.payroll.run_status import PAYROLL_RELEASED" in src
    assert "routers" not in src, "a service imported a router"


def test_the_router_re_exports_the_moved_tuples_unchanged():
    import routers.payroll as pr
    assert pr._PAYROLL_RELEASED == ("finalized", "paid")
    assert pr._PAYROLL_UNRELEASED == ("draft", "review")


def test_payroll_cost_is_gross_plus_the_employer_side_not_net():
    from domain.payroll.department_cost import EMPLOYER_COST_FIELDS
    src = (API / "services" / "client_metrics_service.py").read_text()
    assert "EMPLOYER_COST_FIELDS" in src, \
        "the employer side is respelled rather than read from PAY-25's own list"
    assert "net_paise" not in src, "net pay is not cost"
    assert set(EMPLOYER_COST_FIELDS) == {
        "pf_employer_paise", "esi_employer_paise", "edli_paise", "pf_admin_paise"}


def test_tds_deducted_and_deposited_are_two_populations():
    src = (API / "services" / "client_metrics_service.py").read_text()
    assert '"tds_deductions"' in src and '"tds_challans"' in src, \
        "one of the two TDS sides is not read"
    # The challan's TAX figure, never its total: a total carries surcharge,
    # interest and penalty, and interest on a late deposit is not tax
    # deposited. Asserted on the PROJECTION rather than on the function body,
    # which legitimately names `total_paise` in the comment saying why not.
    tds = src.split("def _tds")[1].split("\ndef ")[0]
    assert 'db.table("tds_challans").select("id, tds_paise")' in tds
    assert "total_paise" not in tds.replace("`total_paise`", "")


def test_the_nightly_sweep_runs_it():
    src = (API / "jobs" / "scheduler.py").read_text()
    assert "client_metrics_service import refresh_firm" in src
    assert '_already_ran_today("client_period_metrics"' in src


def test_the_benchmark_endpoint_exists_and_is_read_scoped():
    import routers.analytics as a
    paths = {r.path for r in a.router.routes}
    assert "/api/analytics/benchmark" in paths
    src = (API / "routers" / "analytics.py").read_text()
    seg = src.split('@router.get("/benchmark")')[1]
    assert 'rbac("analytics", "read")' in seg
    assert "effective_client_ids" in seg, \
        "the benchmark is not assignment-scoped — an Executive would read the " \
        "turnover and profit of clients they are not on"


# ── THE PROJECTIONS ARE LITERALS, AND A TEST KEEPS THEM HONEST ──────────────
#
# `tests/test_backend_columns_exist_pg` checks every `.select()` in apps/api
# against the real schema AS A STRING, and `test_backend_inserts_supply_every_
# required_column_pg` reads an insert payload as a DICT LITERAL. Either reached
# through a NAME is invisible to its guard — and both guards' budgets are EXACT
# with no headroom, which is how this change first failed CI: a
# `", ".join(FIGURES)` and a `{**row, …}` cost two column references and one
# payload, and CLAUDE.md records that raising the budget there would buy an
# exemption where the coverage is recoverable.
#
# So the three sites are written out, and these assert each literal against the
# ONE list that owns it — so the join cannot come back and the literal cannot
# drift from `FIGURES` or from PAY-25's `EMPLOYER_COST_FIELDS`.


def _select_literal(path: str, table: str) -> str:
    """The `.select("…")` string this module passes for `table`, joined."""
    src = (API / path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "select"):
            continue
        inner = node.func.value
        if not (isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "table"
                and inner.args and isinstance(inner.args[0], ast.Constant)
                and inner.args[0].value == table):
            continue
        assert node.args and isinstance(node.args[0], ast.Constant), (
            f"{path}: the projection for {table} is not a literal — "
            "test_backend_columns_exist_pg cannot see it"
        )
        return node.args[0].value
    raise AssertionError(f"{path}: no select on {table}")


def test_the_stored_row_is_read_with_exactly_the_figures_the_module_names():
    cols = [c.strip() for c in
            _select_literal("routers/analytics.py", "client_period_metrics").split(",")]
    assert set(cols) - {"id", "client_id", "financial_year", "gaps"} == set(rule.FIGURES)


def test_the_payroll_projection_names_pay_25s_own_employer_fields():
    from domain.payroll.department_cost import EMPLOYER_COST_FIELDS
    cols = [c.strip() for c in
            _select_literal("services/client_metrics_service.py", "payroll_slips").split(",")]
    assert set(EMPLOYER_COST_FIELDS) <= set(cols), (
        "the projection and PAY-25's employer-cost list have drifted — the "
        "payroll figure would silently lose a contribution"
    )
    assert "gross_paise" in cols, "§17(1) gross is half the cost"
    assert "net_paise" not in cols, "net pay is not cost"


def test_the_upsert_names_every_column_rather_than_spreading_a_dict():
    src = (API / "services" / "client_metrics_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    payloads = [
        n.args[0] for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "upsert" and n.args
    ]
    assert len(payloads) == 1
    assert isinstance(payloads[0], ast.Dict), (
        "the upsert payload is not a dict literal — "
        "test_backend_inserts_supply_every_required_column_pg cannot read it"
    )
    keys = {k.value for k in payloads[0].keys if isinstance(k, ast.Constant)}
    assert set(rule.FIGURES) <= keys, "a figure is not written"
    assert {"firm_id", "client_id", "financial_year", "gaps"} <= keys
    assert not any(k is None for k in payloads[0].keys), "a `**spread` is still there"
