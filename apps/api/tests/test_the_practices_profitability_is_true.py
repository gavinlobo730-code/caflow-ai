"""A client's profit is the fee billed less what the time cost, and it is not shown where either is not known (POST-B-321).

WHAT WAS WRONG, measured on the code this replaced (each is a test below; the negative control is in the commit message):

  * revenue summed every fee invoice in the window, a Draft and a Cancelled one included;
  * `/revenue-vs-effort` summed `total_paise`, which carries the 18% GST, and only the statuses 'Issued' and 'Paid', so
    an issued invoice that fell overdue dropped out and every other one was overstated by the tax;
  * the client list was built from the clients that HAD revenue, so the client with ten hours recorded and nothing billed
    never appeared and the firm's cost left out its time;
  * cost was `minutes x time_entries.hourly_rate_paise`, the rate the hour BILLS at, which is NULL on every entry the
    timer started: those hours cost nothing, and profit equalled revenue and was printed as a margin;
  * `users.cost_rate_paise` was captured and read by nothing;
  * every time and invoice read was one unpaged request, so past about a thousand rows the answer was silently short;
  * the member view summed every entry of the firm for a caller assigned to one client.

THE RULES THESE TESTS HOLD:

  * revenue is the fee before GST on invoices that were issued (Issued, Sent, Paid, Overdue);
  * cost is the member's cost rate times the hours, floored once per entry, and a member with no rate is UNKNOWN: the hours
    are counted and named, the profit and margin are None, and 0 is a rate only when somebody stated it;
  * a client billed with no time recorded has no known cost, and a client with time and no invoice has a margin that is
    undefined, not 0%;
  * every row of every read is counted, not the first thousand.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.practice import profitability as rule

API = Path(__file__).resolve().parents[1]
MIGRATIONS = API / "migrations"


# ═════════════════════════════════════════════════════════════════════════════
# the rule
# ═════════════════════════════════════════════════════════════════════════════

def _check_statuses() -> set[str]:
    text = (MIGRATIONS / "123_fee_invoices_status_issued.sql").read_text(encoding="utf-8")
    block = re.search(r"ADD CONSTRAINT fee_invoices_status_check CHECK \(status IN \((.*?)\)\)", text, re.S)
    assert block, "migration 123 no longer declares the fee invoice status check"
    return set(re.findall(r"'([A-Za-z]+)'", block.group(1)))


def test_every_status_the_table_allows_is_counted_or_not_counted_and_never_neither():
    """A status added to the table is a decision about revenue, not a silent omission from it."""
    counted, not_counted = set(rule.COUNTED_STATUSES), set(rule.NOT_COUNTED_STATUSES)
    assert not counted & not_counted
    assert counted | not_counted == _check_statuses()


def test_migration_123_is_the_only_one_that_declares_the_status_check():
    """The vocabulary above is read from migration 123, so a later migration that widens it must be noticed here."""
    declaring = sorted(p.name for p in MIGRATIONS.glob("*.sql")
                       if "ADD CONSTRAINT fee_invoices_status_check" in p.read_text(encoding="utf-8"))
    assert declaring == ["123_fee_invoices_status_issued.sql"]


def _invoice(client, status="Issued", amount=100_000, **extra):
    return {"client_id": client, "status": status, "amount_paise": amount,
            "gst_paise": amount * 18 // 100, "total_paise": amount + amount * 18 // 100, **extra}


def test_a_draft_and_a_cancelled_invoice_are_not_revenue():
    out = rule.revenue_by_client([
        _invoice("A", "Issued", 100_000), _invoice("A", "Draft", 900_000), _invoice("A", "Cancelled", 700_000),
    ])
    assert out == {"A": 100_000}


def test_a_client_whose_only_invoice_is_a_draft_is_not_billed_at_all():
    assert rule.revenue_by_client([_invoice("A", "Draft", 900_000)]) == {}


@pytest.mark.parametrize("status", ["Issued", "Sent", "Paid", "Overdue"])
def test_an_issued_invoice_is_revenue_whatever_became_of_it(status):
    assert rule.revenue_by_client([_invoice("A", status, 50_000)]) == {"A": 50_000}


def test_revenue_is_the_fee_before_gst_not_the_total():
    """`total_paise` is the fee plus the 18% GST, which is the government's. The rule reads `amount_paise`."""
    inv = _invoice("A", amount=100_000)
    assert inv["total_paise"] == 118_000
    assert rule.revenue_paise(inv) == 100_000
    assert rule.revenue_by_client([inv]) == {"A": 100_000}


def test_revenue_by_engagement_counts_and_skips_an_invoice_with_no_engagement():
    out = rule.revenue_by_engagement([
        _invoice("A", engagement_id="e1", amount=10_000), _invoice("A", "Paid", engagement_id="e1", amount=5_000),
        _invoice("A", "Draft", engagement_id="e1", amount=99_000), _invoice("A", amount=1_000),
    ])
    assert out == {"e1": {"engagement_id": "e1", "client_id": "A", "revenue_paise": 15_000, "invoice_count": 2}}


def _entry(user, client, minutes, **extra):
    return {"user_id": user, "client_id": client, "duration_minutes": minutes, "is_billable": True, **extra}


def test_cost_is_the_members_cost_rate_times_the_hours_not_the_rate_the_hour_bills_at():
    # the entry's own billing rates are enormous and are ignored; the member's cost rate is ₹300 an hour
    entry = _entry("u1", "A", 120, hourly_rate_paise=999_999, billable_rate_paise=888_888)
    effort = rule.fold_effort([entry], rule.clean_cost_rates({"u1": 30_000}), "client_id")
    assert effort["A"].cost_paise == 60_000
    assert effort["A"].cost_is_known


def test_a_member_with_no_cost_rate_is_unknown_and_never_zero():
    rates = rule.clean_cost_rates({"u1": 30_000, "u2": None})
    entries = [_entry("u1", "A", 120), _entry("u2", "A", 60)]
    effort = rule.fold_effort(entries, rates, "client_id")["A"]
    assert (effort.minutes, effort.unrated_minutes, effort.cost_paise) == (180, 60, 60_000)
    assert not effort.cost_is_known

    (position,) = rule.positions({"A": 500_000}, {"A": effort})
    assert position.profit_paise is None and position.margin_pct is None
    assert position.status == rule.STATUS_UNPRICED
    # the cost of the hours that DO have a rate is still said
    assert position.cost_paise == 60_000


def test_a_member_who_is_not_in_the_rate_list_at_all_is_unknown_too():
    effort = rule.fold_effort([_entry("ghost", "A", 60), _entry(None, "A", 30)], {}, "client_id")["A"]
    assert effort.unrated_minutes == 90 and effort.cost_paise == 0 and not effort.cost_is_known


def test_a_stated_cost_rate_of_zero_is_a_rate():
    """A retainer partner whose hours are a favour has a cost rate of 0, said on purpose: those hours are priced at
    nothing and are NOT on the unknown list. `if rate:` is how the code this replaces confused the two."""
    effort = rule.fold_effort([_entry("u1", "A", 600)], rule.clean_cost_rates({"u1": 0}), "client_id")["A"]
    assert (effort.cost_paise, effort.unrated_minutes) == (0, 0)
    assert effort.cost_is_known


@pytest.mark.parametrize("bad", [-5, 12.5, True, "abc", "12.5", "-1", None, ""])
def test_a_cost_rate_that_is_not_a_whole_non_negative_number_is_unknown(bad):
    assert rule.clean_cost_rates({"u1": bad}) == {"u1": None}


def test_a_cost_rate_that_arrives_as_text_is_read_when_it_is_digits():
    """PostgREST can hand a bigint back as a string."""
    assert rule.clean_cost_rates({"u1": "45000"}) == {"u1": 45_000}


def test_a_client_with_time_and_no_invoice_is_on_the_list_with_a_loss_and_no_margin():
    rates = rule.clean_cost_rates({"u1": 30_000})
    effort = rule.fold_effort([_entry("u1", "C", 600)], rates, "client_id")      # ten hours
    rows = rule.positions({}, effort)
    assert [r.key for r in rows] == ["C"]
    c = rows[0]
    assert (c.revenue_paise, c.cost_paise, c.profit_paise) == (0, 300_000, -300_000)
    assert c.margin_pct is None, "a margin on no revenue is undefined, and 0% would rank it above a client billed at a loss"
    assert c.status == rule.STATUS_NOT_BILLED


def test_a_client_billed_with_no_time_recorded_has_no_known_cost():
    """The old footnote said "that is an absence of data, not a margin" under a column that drew it as 100%."""
    (b,) = rule.positions({"B": 50_000}, {})
    assert b.profit_paise is None and b.margin_pct is None
    assert b.status == rule.STATUS_NO_TIME


def test_the_margin_and_its_band_follow_the_profit():
    rates = rule.clean_cost_rates({"u1": 60_000})
    effort = {k: rule.fold_effort([_entry("u1", k, minutes)], rates, "client_id")[k]
              for k, minutes in {"good": 30, "mid": 80, "bad": 100}.items()}   # ₹300, ₹800, ₹1,000 of cost
    rows = {r.key: r for r in rule.positions({"good": 100_000, "mid": 100_000, "bad": 100_000}, effort)}
    assert (rows["good"].margin_pct, rows["good"].status) == (70.0, rule.STATUS_HEALTHY)
    assert (rows["mid"].margin_pct, rows["mid"].status) == (20.0, rule.STATUS_FAIR)
    assert (rows["bad"].margin_pct, rows["bad"].status) == (0.0, rule.STATUS_AT_RISK)


def test_the_list_puts_known_profits_first_the_best_at_the_top():
    rates = rule.clean_cost_rates({"u1": 60_000, "u2": None})
    effort = {
        "rich": rule.fold_effort([_entry("u1", "rich", 30)], rates, "client_id")["rich"],
        "thin": rule.fold_effort([_entry("u1", "thin", 90)], rates, "client_id")["thin"],
        "murky": rule.fold_effort([_entry("u2", "murky", 60)], rates, "client_id")["murky"],
    }
    rows = rule.positions({"rich": 100_000, "thin": 100_000, "murky": 900_000, "unbilled": 0}, effort)
    assert [r.key for r in rows[:2]] == ["rich", "thin"]
    assert rows[2].key == "murky", "the unpriced rows follow the known ones, not interleave with them"


def test_the_firm_total_is_not_a_profit_while_any_clients_cost_is_unknown():
    rates = rule.clean_cost_rates({"u1": 60_000})
    effort = {"A": rule.fold_effort([_entry("u1", "A", 60)], rates, "client_id")["A"]}     # ₹600 on ₹1,000
    tot = rule.totals(rule.positions({"A": 100_000, "B": 50_000}, effort))                  # B has no time recorded
    assert tot.revenue_paise == 150_000 and tot.cost_paise == 60_000
    assert tot.profit_paise is None and tot.margin_pct is None
    assert tot.avg_profit_per_billed_client_paise is None
    assert (tot.clients_with_cost, tot.clients_without_cost) == (1, 1)
    # the figure that can be said, with its scope: the one client whose cost is known
    assert tot.profit_on_known_paise == 40_000


def test_the_firm_total_is_a_profit_when_every_cost_is_known():
    rates = rule.clean_cost_rates({"u1": 60_000})
    effort = {k: rule.fold_effort([_entry("u1", k, 60)], rates, "client_id")[k] for k in ("A", "B", "C")}
    tot = rule.totals(rule.positions({"A": 100_000, "B": 200_000}, effort))                 # C is time with no invoice
    assert (tot.revenue_paise, tot.cost_paise) == (300_000, 180_000)
    assert tot.profit_paise == 120_000 and tot.margin_pct == 40.0
    assert (tot.clients_billed, tot.clients_not_billed) == (2, 1)
    assert tot.avg_profit_per_billed_client_paise == 60_000


def test_time_recorded_against_no_client_is_a_group_of_its_own_and_not_a_client():
    effort = rule.fold_effort([_entry("u1", None, 45), _entry("u1", "A", 15)], rule.clean_cost_rates({"u1": 60_000}), "client_id")
    assert effort[None].minutes == 45
    assert [p.key for p in rule.positions({}, effort)] == ["A"]


def test_an_entry_with_no_minutes_adds_nothing_and_a_running_timer_is_not_the_rules_to_judge():
    effort = rule.fold_effort([_entry("u1", "A", None), _entry("u1", "A", 0), _entry("u1", "A", 30)],
                              rule.clean_cost_rates({"u1": 60_000}), "client_id")
    assert effort["A"].minutes == 30


def test_the_people_with_unpriced_hours_are_named_with_how_many_the_most_first():
    rates = rule.clean_cost_rates({"u1": 30_000, "u2": None, "u3": None})
    entries = [_entry("u2", "A", 60), _entry("u3", "B", 120), _entry("u2", "B", 30), _entry("u1", "A", 600), _entry(None, "A", 10)]
    assert rule.unrated_people(entries, rates) == [("u3", 120), ("u2", 90), (None, 10)]


def test_the_people_named_are_the_ones_whose_missing_rate_leaves_a_clients_cost_short():
    """The headline hours (`unrated_minutes`, summed over the clients) and the names beside them are one population. Time
    with no client is in no client's cost whatever the member's rate, so it is not what the notice names."""
    rates = rule.clean_cost_rates({"u1": 30_000, "u2": None})
    entries = [_entry("u2", "A", 300), _entry("u2", None, 180), _entry("u1", None, 60)]
    effort = rule.fold_effort(entries, rates, "client_id")
    headline = sum(e.unrated_minutes for k, e in effort.items() if k is not None)
    named = rule.unrated_people(entries, rates)
    assert headline == 300 and named == [("u2", 300)]
    assert sum(minutes for _, minutes in named) == headline
    # a member whose only unrated time has no client is not named at all
    assert rule.unrated_people([_entry("u2", None, 180)], rates) == []


def test_a_key_with_nothing_billed_and_no_time_is_not_a_row():
    """A ₹0 invoice for a client nobody spent a minute on would otherwise be "time recorded, nothing billed" and would take
    the firm's profit away."""
    assert rule.positions({"A": 0}, {}) == []
    rows = rule.positions({"A": 0, "B": 50_000}, {})
    assert [r.key for r in rows] == ["B"]


def test_a_sum_of_hours_none_of_which_has_a_rate_is_not_a_cost_of_zero():
    none_rated = rule.fold_effort([_entry("u2", "A", 120)], rule.clean_cost_rates({"u2": None}), "client_id")["A"]
    assert none_rated.priced_cost_paise is None and none_rated.rated_minutes == 0
    some_rated = rule.fold_effort([_entry("u1", "A", 120), _entry("u2", "A", 60)],
                                  rule.clean_cost_rates({"u1": 30_000, "u2": None}), "client_id")["A"]
    assert some_rated.priced_cost_paise == 60_000, "the part that is priced is still said"
    stated_zero = rule.fold_effort([_entry("u1", "A", 120)], rule.clean_cost_rates({"u1": 0}), "client_id")["A"]
    assert stated_zero.priced_cost_paise == 0, "a stated rate of 0 prices the hours at nothing: that is a cost of 0"
    tot = rule.totals(rule.positions({"A": 100_000}, {"A": none_rated}))
    assert tot.priced_cost_paise is None


def test_the_cost_of_an_entry_is_floored_not_rounded():
    """7 minutes at ₹250.01 an hour is 2,916.78 paise: 2,916, the floor `domain/billing/time_rate.value_paise` takes, so
    cost and the value of unbilled work round the same way. Every other example here is a multiple of 60."""
    effort = rule.fold_effort([_entry("u1", "A", 7)], rule.clean_cost_rates({"u1": 25_001}), "client_id")["A"]
    assert effort.cost_paise == 2_916


def test_a_margin_of_exactly_the_band_edge_is_in_the_better_band():
    rates = rule.clean_cost_rates({"u1": 60_000})
    at_25 = rule.positions({"A": 100_000}, {"A": rule.fold_effort([_entry("u1", "A", 75)], rates, "client_id")["A"]})[0]
    at_15 = rule.positions({"A": 100_000}, {"A": rule.fold_effort([_entry("u1", "A", 85)], rates, "client_id")["A"]})[0]
    assert (at_25.margin_pct, at_25.status) == (25.0, rule.STATUS_HEALTHY)
    assert (at_15.margin_pct, at_15.status) == (15.0, rule.STATUS_FAIR)


def test_a_margin_is_rounded_to_two_places():
    rates = rule.clean_cost_rates({"u1": 60_000})
    row = rule.positions({"A": 300_000}, {"A": rule.fold_effort([_entry("u1", "A", 1)], rates, "client_id")["A"]})[0]
    assert row.cost_paise == 1_000 and row.margin_pct == 99.67


# ═════════════════════════════════════════════════════════════════════════════
# the three endpoints, over the real repositories and a database that has the row cap
# ═════════════════════════════════════════════════════════════════════════════

import routers.analytics as an  # noqa: E402
from tests._capped_postgrest import DB_MAX_ROWS, CappedDB  # noqa: E402

FIRM = "firm-profit"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}
A, B, C, D = "client-a", "client-b", "client-c", "client-d"
NAMES = {A: "A Ltd", B: "B Ltd", C: "C Ltd", D: "D Ltd"}


def _window() -> tuple[str, str]:
    date_from, date_to, _ = an._period_range("month")
    return date_from, date_to


def _fee_row(i, client, status, amount, **extra):
    date_from, _ = _window()
    return {"id": f"inv{i:05d}", "firm_id": FIRM, "client_id": client, "engagement_id": extra.pop("engagement_id", None),
            "status": status, "invoice_date": date_from, "is_deleted": False, "amount_paise": amount,
            "gst_paise": amount * 18 // 100, "total_paise": amount + amount * 18 // 100, **extra}


def _time_row(i, user, client, minutes, **extra):
    date_from, _ = _window()
    return {"id": f"te{i:05d}", "firm_id": FIRM, "user_id": user, "client_id": client,
            "engagement_id": extra.pop("engagement_id", None), "duration_minutes": minutes, "is_billable": True,
            "started_at": f"{date_from}T10:00:00+05:30", "ended_at": f"{date_from}T11:00:00+05:30",
            "hourly_rate_paise": 999_999, **extra}


@pytest.fixture
def book(monkeypatch):
    """A firm whose three tables are served by a database with the row cap, read by the REAL repositories."""
    import core.authz as authz
    import core.db_provider as provider
    import repositories.client_repository as cr
    import repositories.engagement_repository as er
    import repositories.invoice_repository as ir
    import repositories.time_tracking_analytics_repository as tta
    import repositories.user_repository as ur
    import services.billing_service as bs

    def install(invoices=(), entries=(), users=(("u1", 30_000),), engagements=()):
        db = CappedDB({
            "fee_invoices": list(invoices),
            "time_entries": list(entries),
            "users": [{"id": uid, "firm_id": FIRM, "cost_rate_paise": rate} for uid, rate in users],
        })
        monkeypatch.setattr(ir, "_USE_MOCK", False)
        monkeypatch.setattr(ir, "_get_db", lambda: db)
        monkeypatch.setattr(tta, "_USE_MOCK", False)
        monkeypatch.setattr(tta, "_get_db", lambda: db)
        monkeypatch.setattr(bs, "_USE_MOCK", False)
        monkeypatch.setattr(provider, "service_db", lambda: db)
        monkeypatch.setattr(authz, "effective_client_ids", lambda user: None)
        monkeypatch.setattr(cr.client_repo, "find_all",
                            lambda **kw: [{"id": c, "client_name": n} for c, n in NAMES.items()])
        monkeypatch.setattr(ur.user_repo, "find_all",
                            lambda **kw: [{"id": uid, "full_name": f"Member {uid}"} for uid, _ in users])
        monkeypatch.setattr(er.engagement_repo, "find_all", lambda **kw: engagements)
        monkeypatch.setattr(an, "_get_db", lambda: db)
        return db

    return install


def _profit(**kw):
    return an.profitability_analytics(period="month", current_user=USER, **kw)["data"]


def test_a_draft_and_a_cancelled_invoice_add_nothing_to_a_clients_revenue(book):
    book(invoices=[_fee_row(1, A, "Issued", 100_000), _fee_row(2, A, "Draft", 900_000), _fee_row(3, A, "Cancelled", 700_000),
                   _fee_row(4, B, "Overdue", 50_000, is_deleted=True)],
         entries=[_time_row(1, "u1", A, 60)])
    data = _profit()
    rows = {c["client_id"]: c for c in data["by_client"]}
    assert rows[A]["revenue_paise"] == 100_000
    assert B not in rows, "a deleted invoice is not revenue either"
    assert data["firm_metrics"]["total_revenue_paise"] == 100_000


def test_a_client_with_ten_hours_and_no_invoice_shows_a_loss_and_no_margin(book):
    book(invoices=[_fee_row(1, A, "Issued", 100_000)],
         entries=[_time_row(1, "u1", A, 60), _time_row(2, "u1", C, 600)])
    data = _profit()
    c = next(r for r in data["by_client"] if r["client_id"] == C)
    assert c["client_name"] == "C Ltd"
    assert (c["revenue_paise"], c["cost_paise"], c["profit_paise"]) == (0, 300_000, -300_000)
    assert c["profit_margin_pct"] is None and c["status"] == "not_billed"
    m = data["firm_metrics"]
    assert m["num_clients_billed"] == 1 and m["num_clients_not_billed"] == 1
    assert m["total_cost_paise"] == 30_000 + 300_000, "the firm's cost includes the time on the client nobody billed"


def test_fifteen_hundred_time_entries_are_all_counted_not_the_first_thousand(book):
    entries = [_time_row(i, "u1", D, 60) for i in range(1, 1501)]
    assert len(entries) > DB_MAX_ROWS
    db = book(invoices=[_fee_row(1, D, "Issued", 9_000_000)], entries=entries, users=(("u1", 10_000),))
    d = next(r for r in _profit()["by_client"] if r["client_id"] == D)
    assert d["effort_minutes"] == 1500 * 60
    assert d["cost_paise"] == 1500 * 10_000, "an unpaged read counted a thousand of them"
    assert len(db.requests["time_entries"]) >= 2, "the entries were read in more than one request"


def test_fifteen_hundred_invoices_are_all_counted_not_the_first_thousand(book):
    invoices = [_fee_row(i, A, "Issued", 1_000) for i in range(1, 1501)]
    book(invoices=invoices, entries=[_time_row(1, "u1", A, 60)])
    assert _profit()["firm_metrics"]["total_revenue_paise"] == 1500 * 1_000


def test_cost_uses_the_members_cost_rate_whatever_the_entry_says_it_bills_at(book):
    book(invoices=[_fee_row(1, A, "Issued", 100_000)],
         entries=[_time_row(1, "u1", A, 120, billable_rate_paise=777_777)], users=(("u1", 45_000),))
    a = next(r for r in _profit()["by_client"] if r["client_id"] == A)
    assert a["cost_paise"] == 90_000 and a["profit_paise"] == 10_000 and a["profit_margin_pct"] == 10.0
    assert a["status"] == "at_risk"


def test_a_member_with_no_cost_rate_makes_the_clients_profit_unknown_and_is_named(book):
    book(invoices=[_fee_row(1, A, "Issued", 100_000), _fee_row(2, B, "Issued", 200_000)],
         entries=[_time_row(1, "u1", A, 60), _time_row(2, "u2", A, 120), _time_row(3, "u1", B, 60)],
         users=(("u1", 30_000), ("u2", None)))
    data = _profit()
    a = next(r for r in data["by_client"] if r["client_id"] == A)
    assert a["unrated_minutes"] == 120 and a["cost_is_complete"] is False
    assert a["profit_paise"] is None and a["profit_margin_pct"] is None and a["status"] == "unpriced"
    b = next(r for r in data["by_client"] if r["client_id"] == B)
    assert (b["profit_paise"], b["profit_margin_pct"]) == (170_000, 85.0)

    m = data["firm_metrics"]
    assert m["profit_paise"] is None and m["profit_margin_pct"] is None and m["cost_is_complete"] is False
    assert m["unrated_minutes"] == 120 and m["profit_on_known_paise"] == 170_000
    assert data["cost_rates_missing"] == [{"user_id": "u2", "user_name": "Member u2", "minutes": 120}]


def test_a_client_billed_with_no_time_says_so_and_has_no_profit(book):
    book(invoices=[_fee_row(1, A, "Issued", 100_000)], entries=[])
    data = _profit()
    (a,) = data["by_client"]
    assert a["status"] == "no_time" and a["profit_paise"] is None
    assert data["firm_metrics"]["clients_without_cost"] == 1 and data["firm_metrics"]["profit_paise"] is None


def test_the_statements_of_what_is_not_measured_travel_with_the_figures(book):
    book()
    assert _profit()["not_measured"] == list(rule.NOT_MEASURED)


def test_the_engagement_view_lists_an_engagement_with_effort_and_no_invoice(book):
    engagements = [{"id": "e1", "client_id": A, "service_type": "GST"}, {"id": "e2", "client_id": A, "service_type": "Audit"}]
    book(invoices=[_fee_row(1, A, "Issued", 100_000, engagement_id="e1")],
         entries=[_time_row(1, "u1", A, 60, engagement_id="e1"), _time_row(2, "u1", A, 300, engagement_id="e2")],
         engagements=engagements)
    rows = {r["engagement_id"]: r for r in _profit(include_by_engagement=True)["by_engagement"]}
    assert rows["e1"]["profit_paise"] == 100_000 - 30_000 and rows["e1"]["service_type"] == "GST"
    assert (rows["e2"]["revenue_paise"], rows["e2"]["profit_paise"], rows["e2"]["profit_margin_pct"]) == (0, -150_000, None)


def test_the_member_view_gives_a_member_with_no_rate_an_unknown_cost_not_zero(book):
    book(entries=[_time_row(1, "u1", A, 60), _time_row(2, "u2", A, 90)], users=(("u1", 30_000), ("u2", None)))
    team = {m["user_id"]: m for m in _profit(include_by_team=True)["by_team_member"]}
    assert team["u1"]["cost_paise"] == 30_000 and team["u1"]["profit_paise"] == -30_000
    assert team["u2"]["cost_paise"] is None and team["u2"]["profit_paise"] is None
    assert team["u2"]["effort_minutes"] == 90


def test_realization_counts_the_fee_before_gst_and_an_overdue_invoice(book):
    """`/revenue-vs-effort` read `total_paise` (the fee plus GST) and only 'Issued' and 'Paid'."""
    engagements = [{"id": "e1", "client_id": A, "service_type": "GST"}]
    book(invoices=[_fee_row(1, A, "Issued", 100_000, engagement_id="e1"), _fee_row(2, A, "Overdue", 50_000, engagement_id="e1"),
                   _fee_row(3, A, "Draft", 900_000, engagement_id="e1")],
         entries=[_time_row(1, "u1", A, 60, engagement_id="e1")], engagements=engagements)
    data = an.revenue_vs_effort(period="month", current_user=USER)["data"]
    assert data["total_revenue_paise"] == 150_000, "the fee before GST, Draft excluded, the overdue invoice included"
    assert data["by_engagement"][0]["revenue_paise"] == 150_000


def test_the_concentration_margin_is_unknown_where_the_cost_is(book):
    book(invoices=[_fee_row(1, A, "Issued", 100_000), _fee_row(2, B, "Issued", 100_000)],
         entries=[_time_row(1, "u1", A, 60)])                    # B was billed and no time was recorded on it
    out = an.fee_concentration(period="month", current_user=USER)["data"]
    shares = {s["client_id"]: s for s in out["shares"]}
    assert shares[A]["profit_paise"] == 70_000 and shares[A]["margin_bps"] == 7000
    assert shares[B]["profit_paise"] is None and shares[B]["margin_bps"] is None
    assert out["median_margin_bps"] == 7000, "the median is over the clients whose margin is known"


def test_the_in_memory_twin_returns_the_same_rows_the_database_would(monkeypatch):
    """Mock mode and a local run read `MOCK_INVOICES`: the same window, the same firm, the same statuses, the same six
    columns, so a screen demonstrated without a database shows what it would show with one."""
    import repositories.invoice_repository as ir
    date_from, date_to = _window()
    rows = [
        _fee_row(1, A, "Issued", 100_000), _fee_row(2, A, "Draft", 900_000), _fee_row(3, A, "Cancelled", 700_000),
        _fee_row(4, B, "Paid", 40_000, is_deleted=True), _fee_row(5, B, "Overdue", 50_000, firm_id="another-firm"),
        _fee_row(6, B, "Sent", 30_000, invoice_date="2000-01-01"),
    ]
    monkeypatch.setattr(ir, "_USE_MOCK", True)
    monkeypatch.setattr(ir, "MOCK_INVOICES", rows, raising=False)
    got = ir.InvoiceRepository().fee_revenue_rows(FIRM, date_from, date_to)
    assert [r["id"] for r in got] == ["inv00001"]
    assert set(got[0]) == set(ir.InvoiceRepository.REVENUE_COLUMNS) == set(
        ir.InvoiceRepository.REVENUE_COLUMNS) & set(", ".join(ir.InvoiceRepository.REVENUE_COLUMNS).split(", "))


def test_the_revenue_read_asks_the_database_for_issued_live_invoices_of_this_firm_only(book):
    db = book(invoices=[_fee_row(1, A, "Issued", 100_000)])
    _profit()
    ops = [op for request in db.requests["fee_invoices"] for op in request]
    assert ("eq", "firm_id", FIRM) in ops and ("eq", "is_deleted", False) in ops
    assert ("in", "status", list(rule.COUNTED_STATUSES)) in ops
    import repositories.invoice_repository as ir
    import repositories.time_tracking_analytics_repository as tta
    assert db.selects["fee_invoices"][0] == ", ".join(ir.InvoiceRepository.REVENUE_COLUMNS), \
        "the revenue read takes six columns, not every column of every invoice, and the literal is the constant"
    assert db.selects["time_entries"][0] == tta.TimeTrackingAnalyticsRepository.COST_COLUMNS
    assert db.selects["users"][0] == "id, cost_rate_paise"
    # and both bounds of the invoice date are asked of the database
    assert ("gte", "invoice_date", _window()[0]) in ops and ("lte", "invoice_date", _window()[1]) in ops


# ═════════════════════════════════════════════════════════════════════════════
# the browser's copy of the vocabulary and the payload, held from the side that owns them
# ═════════════════════════════════════════════════════════════════════════════

WEB_API_TS = API.parent / "web" / "lib" / "api" / "index.ts"


def _ts_block(text: str, opening: str, closing: str) -> str:
    m = re.search(re.escape(opening) + r"(.*?)" + closing, text, re.S)
    assert m, f"{opening!r} is no longer declared in lib/api/index.ts"
    return m.group(1)


def _ts_keys(block: str, indent: int) -> set[str]:
    return set(re.findall(rf"^ {{{indent}}}(\w+)\??:", block, re.M))


def test_the_browsers_statuses_are_the_rules():
    declared = set(re.findall(r'"(\w+)"', _ts_block(WEB_API_TS.read_text(encoding="utf-8"),
                                                    "export type ProfitabilityStatus =", r";")))
    held = {v for k, v in vars(rule).items() if k.startswith("STATUS_") and isinstance(v, str)}
    assert declared == held


def test_the_browsers_payload_names_the_keys_the_endpoint_answers(book):
    """A key the server adds or renames and the type does not know is a screen reading `undefined`."""
    ts = WEB_API_TS.read_text(encoding="utf-8")
    interface = _ts_block(ts, "export interface ProfitabilityPayload {", r"\n\}\n")
    book(invoices=[_fee_row(1, A, "Issued", 100_000)], entries=[_time_row(1, "u1", A, 60)])
    data = _profit()
    assert _ts_keys(interface, 2) == set(data)
    assert _ts_keys(_ts_block(interface, "firm_metrics: {", r"\n  \};"), 4) == set(data["firm_metrics"])
    assert _ts_keys(_ts_block(interface, "by_client?: {", r"\n  \}\[\];"), 4) == set(data["by_client"][0])
    book(invoices=[_fee_row(1, A, "Issued", 100_000)], entries=[_time_row(1, "u9", A, 60)], users=(("u9", None),))
    missing = _profit()["cost_rates_missing"]
    assert missing and _ts_keys(_ts_block(interface, "cost_rates_missing: {", r"\n  \}\[\];"), 4) == set(missing[0])


# ═════════════════════════════════════════════════════════════════════════════
# what the independent reads of this change found
# ═════════════════════════════════════════════════════════════════════════════

def test_only_the_invoices_dated_in_the_window_are_revenue(book):
    """Three mutations that removed the lower bound, the upper bound or both of the invoice date passed every test."""
    date_from, date_to = _window()
    book(invoices=[_fee_row(1, A, "Issued", 100_000), _fee_row(2, A, "Issued", 10_000, invoice_date=date_to),
                   _fee_row(3, A, "Issued", 900_000, invoice_date="2000-01-01"),
                   _fee_row(4, A, "Issued", 700_000, invoice_date="2100-01-01")],
         entries=[_time_row(1, "u1", A, 60)])
    assert _profit()["firm_metrics"]["total_revenue_paise"] == 110_000


def test_the_concentration_of_an_assigned_caller_is_of_their_own_clients(book, monkeypatch):
    import core.authz as authz
    book(invoices=[_fee_row(1, A, "Issued", 100_000), _fee_row(2, B, "Issued", 900_000)],
         entries=[_time_row(1, "u1", A, 60), _time_row(2, "u1", B, 60)])
    monkeypatch.setattr(authz, "effective_client_ids", lambda user: {A})
    out = an.fee_concentration(period="month", current_user=USER)["data"]
    assert [s["client_id"] for s in out["shares"]] == [A]
    assert out["total_revenue_paise"] == 100_000 and out["largest_share_bps"] == 10_000


def test_the_member_view_lists_the_dearest_first_and_the_unpriced_last(book):
    book(entries=[_time_row(1, "u1", A, 60), _time_row(2, "u2", A, 180), _time_row(3, "u3", A, 30)],
         users=(("u1", 30_000), ("u2", 30_000), ("u3", None)))
    team = _profit(include_by_team=True)["by_team_member"]
    assert [m["user_id"] for m in team] == ["u2", "u1", "u3"]
    assert [m["cost_paise"] for m in team] == [90_000, 30_000, None]


def test_when_no_hour_has_a_cost_rate_the_cost_is_not_a_figure_at_all(book):
    """A sum of nothing was sent as 0, so the Cost tile read ₹0.00 on the first load of a firm that has set no rate."""
    book(invoices=[_fee_row(1, A, "Issued", 100_000)], entries=[_time_row(1, "u1", A, 60)], users=(("u1", None),))
    data = _profit()
    assert data["firm_metrics"]["total_cost_paise"] is None
    (a,) = data["by_client"]
    assert a["cost_paise"] is None and a["unrated_minutes"] == 60 and a["profit_paise"] is None
    # once there is a rate, there is a cost
    book(invoices=[_fee_row(1, A, "Issued", 100_000)], entries=[_time_row(1, "u1", A, 60)], users=(("u1", 30_000),))
    assert _profit()["firm_metrics"]["total_cost_paise"] == 30_000


def test_time_with_no_client_is_counted_for_a_firmwide_caller_and_unknown_to_an_assigned_one(book, monkeypatch):
    import core.authz as authz
    book(invoices=[_fee_row(1, A, "Issued", 100_000)],
         entries=[_time_row(1, "u1", A, 60), _time_row(2, "u1", None, 45)])
    assert _profit()["firm_metrics"]["minutes_without_client"] == 45
    monkeypatch.setattr(authz, "effective_client_ids", lambda user: {A})
    assert _profit()["firm_metrics"]["minutes_without_client"] is None, "0 would say there is none"


def test_the_headline_hours_and_the_names_beside_them_agree_at_the_endpoint(book):
    book(invoices=[_fee_row(1, A, "Issued", 100_000)],
         entries=[_time_row(1, "u2", A, 300), _time_row(2, "u2", None, 180)], users=(("u1", 30_000), ("u2", None)))
    data = _profit()
    assert data["firm_metrics"]["unrated_minutes"] == 300
    assert data["cost_rates_missing"] == [{"user_id": "u2", "user_name": "Member u2", "minutes": 300}]


def test_a_client_with_a_zero_invoice_and_no_time_is_not_on_the_list_and_does_not_take_the_profit_away(book):
    book(invoices=[_fee_row(1, A, "Issued", 100_000), _fee_row(2, B, "Issued", 0)], entries=[_time_row(1, "u1", A, 60)])
    data = _profit()
    assert [r["client_id"] for r in data["by_client"]] == [A]
    assert data["firm_metrics"]["profit_paise"] == 70_000


def test_an_archived_client_keeps_its_name_beside_its_money(book, monkeypatch):
    import repositories.client_repository as cr
    book(invoices=[_fee_row(1, D, "Issued", 100_000)], entries=[_time_row(1, "u1", D, 60)])
    monkeypatch.setattr(cr.client_repo, "find_all", lambda **kw: (
        [{"id": D, "client_name": "D Ltd (archived)"}] if kw.get("include_archived") else []))
    assert _profit()["by_client"][0]["client_name"] == "D Ltd (archived)"
    out = an.fee_concentration(period="month", current_user=USER)["data"]
    assert out["shares"][0]["client_name"] == "D Ltd (archived)"


def test_realization_needs_no_database_handle_of_its_own(book, monkeypatch):
    """It opened `_get_db()` and never used it, so it was the one analytics endpoint that raised in mock mode."""
    book(invoices=[_fee_row(1, A, "Issued", 100_000, engagement_id="e1")], entries=[_time_row(1, "u1", A, 60, engagement_id="e1")],
         engagements=[{"id": "e1", "client_id": A, "service_type": "GST"}])

    def refuse():
        raise AssertionError("revenue_vs_effort opened a database handle it does not read")
    monkeypatch.setattr(an, "_get_db", refuse)
    assert an.revenue_vs_effort(period="month", current_user=USER)["success"] is True


def test_the_cost_rate_list_asks_the_permission_that_sets_a_rate():
    """A rate is derived from a person's pay and overheads: a member granted the fee figures to READ does not get every
    colleague's rate with them."""
    from main import app

    def names(method: str) -> set[str]:
        route = next(r for r in app.routes if getattr(r, "path", None) == "/api/billing/staff-cost-rates"
                     and method in getattr(r, "methods", ()))
        return {d.call.__name__ for d in route.dependant.dependencies}
    assert "rbac_billing_write" in names("GET") and "rbac_billing_read" not in names("GET")

