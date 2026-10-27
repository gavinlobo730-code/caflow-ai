"""The two Schedule III fixed-asset lines tie to the fixed-asset register once an intangible asset's amortisation is in its own ledger
(POST-A-345, stage 3), driven through the real routes and journals against a real database, as the roles production uses.

THE DEFECT, ON THE DATABASE (the first test asserts it, so the fix is shown against something and not against nothing)
    The standard chart books the depreciation of every category in ONE ledger, Accumulated Depreciation, which Schedule III presents
    on the tangible line. A licence amortised there leaves the tangible line short, and the intangible line over, by the licence's
    whole accumulated amortisation, while the register (which keeps each asset's own figure) says otherwise.

WHAT IS HELD
    * before: the ledger's two lines differ from the register's two net blocks, each by exactly the amortisation of the licence;
    * after a Partner's reclassification the two lines EQUAL the register's net blocks, and the totals of the two ledgers are the same
      as before it (the move is between two ledgers, so no cash-flow figure and no total changes);
    * a month posted after the move credits the new ledger, and the lines still tie;
    * a disposal clears the ledger the asset points at and leaves a debit balance in neither;
    * an asset created after the change is born in its own ledger and ties without any reclassification;
    * the undo puts everything back as it was, the journal-reversal route refuses these entries, and a closed year refuses the move;
    * with months posted AFTER the stated date, the lines tie at every financial year end from it, and a date between is off by exactly
      the months not yet moved (the preview says so; this proves the sentence is true);
    * a second client of the same firm is neither read nor disturbed, and the depreciation an asset brought over sits in the ledger the
      Partner names and nowhere else.

HOW. `tests/_signed_in_postgrest.SignedInDb` runs each call in a real database as `service_role` (the API's privileged client, which is
what the fixed-asset routes and the ledger doors use) or as an authenticated Partner (the request's own client, which the posting
kernel reads with). Nothing under test is replaced except which client the two providers hand out, the audit writer and the
client-belongs-to-firm lookup.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest
from fastapi import HTTPException

from domain.reporting.year_end_lines import schedule_line_for_account
from services.coa_seed_service import STANDARD_COA
from tests._signed_in_postgrest import SignedInDb

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the live-database proof requires HARNESS_PG + psql",
)

FIRM = "54501000-0000-0000-0000-000000000001"
CLIENT = "54501000-0000-0000-0000-0000000000a1"
PARTNER = {"id": "54501000-0000-0000-0000-00000000000a", "auth_user_id": "54501000-1111-0000-0000-000000000001",
           "role": "Partner", "firm_id": FIRM, "email": "partner@t.in"}
AS_AT = "2025-09-30"
CLIENT2 = "54501000-0000-0000-0000-0000000000a2"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


@pytest.fixture()
def world(pg_template, monkeypatch):
    admin = _ADMIN.strip()
    name = f"e545_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        chart = "\n".join(
            "INSERT INTO chart_of_accounts (firm_id, client_id, account_code, account_name, account_type, account_subtype, is_active) "
            f"VALUES ('{FIRM}', NULL, '{code}', '{n.replace(chr(39), chr(39) * 2)}', '{t}', "
            f"{'NULL' if sub is None else chr(39) + sub + chr(39)}, TRUE);"
            for code, n, t, sub in STANDARD_COA)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER["auth_user_id"]}', 'partner@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT2}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{PARTNER["id"]}', '{FIRM}', '{PARTNER["auth_user_id"]}', 'partner@t.in', 'P', 'Partner', true);
            {chart}
        """)
        assert seed.returncode == 0, seed.stderr

        class World:
            pass

        w = World()
        w.dsn = dsn
        w.partner_db = SignedInDb(dsn, auth_user_id=PARTNER["auth_user_id"])
        w.service_db = SignedInDb(dsn, role="service_role")

        import core.authz
        import core.db_provider
        import core.supabase_client
        import routers.accounting
        import routers.fixed_assets
        import services.amortisation_reclass_service
        import services.phase2_journal_service

        monkeypatch.setenv("SUPABASE_URL", "test://db")
        monkeypatch.setattr(core.supabase_client, "get_supabase", lambda *a, **k: w.partner_db)
        monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: w.service_db)
        monkeypatch.setattr(routers.fixed_assets, "_db", lambda: w.service_db)
        monkeypatch.setattr(services.phase2_journal_service, "_USE_MOCK", False)
        monkeypatch.setattr(core.authz, "_USE_MOCK", False)
        monkeypatch.setattr(core.authz, "_client_belongs_to_firm", lambda client_id, firm_id: True)
        monkeypatch.setattr(routers.fixed_assets, "log_event", lambda *a, **k: None)
        monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None)
        monkeypatch.setattr(routers.fixed_assets.timeline_service, "log", lambda *a, **k: None)
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── what the database says ──────────────────────────────────────────────────

def _balances(w, client: str = CLIENT, upto: str | None = None) -> dict[str, int]:
    """{account code: debit minus credit} for the client, from the monthly rows the database's own triggers keep. `upto` is a date: the
    balances as at it (a month's row is dated its first day, so a month ending on or before `upto` is in)."""
    until = f"AND b.period_month <= '{upto}'" if upto else ""
    rows = _rows(w.dsn, f"""
        SELECT c.account_code, COALESCE(SUM(b.debit_paise - b.credit_paise), 0)
          FROM chart_of_accounts c LEFT JOIN account_period_balances b ON b.account_id = c.id AND b.client_id = '{client}' {until}
         WHERE c.firm_id = '{FIRM}' GROUP BY c.account_code""")
    return {code: int(v) for code, v in rows}


def _lines(w, client: str = CLIENT, upto: str | None = None) -> dict[str, int]:
    """The ledger's two fixed-asset lines on the balance sheet, as the Schedule III classifier places each account, debit positive."""
    accounts = _rows(w.dsn, f"SELECT account_code, account_type, COALESCE(account_subtype, ''), COALESCE(schedule_iii_mapping, '') "
                            f"FROM chart_of_accounts WHERE firm_id = '{FIRM}'")
    bal = _balances(w, client, upto)
    out = {"tangible_assets": 0, "intangible_assets": 0}
    for code, atype, subtype, mapping in accounts:
        line = schedule_line_for_account(atype, subtype or None, mapping or None)
        if line in out:
            out[line] += bal.get(code, 0)
    return out


def _register(w, client: str = CLIENT) -> dict[str, int]:
    """The register's net block per kind: cost less accumulated depreciation, live undisposed assets."""
    rows = _rows(w.dsn, f"SELECT asset_category, purchase_cost_paise - accumulated_depreciation_paise FROM fixed_assets "
                        f"WHERE client_id = '{client}' AND deleted_at IS NULL AND NOT is_disposed")
    out = {"tangible_assets": 0, "intangible_assets": 0}
    for category, net in rows:
        out["intangible_assets" if category == "Intangibles" else "tangible_assets"] += int(net)
    return out


def _cash_flow(w):
    """The cash-flow statement's figures for the year. A COUNT of entries read is dropped: the reclassification is one more entry, and
    that is a fact about the ledger and not a figure on the statement."""
    import json
    raw = json.loads(_rows(w.dsn, f"SELECT public.cash_flow_report('{FIRM}', '{CLIENT}', '2025-04-01', '2026-03-31')::text")[0][0])

    def figures(node):
        if isinstance(node, dict):
            return {k: figures(v) for k, v in node.items() if not k.endswith("_count")}
        if isinstance(node, list):
            return [figures(v) for v in node]
        return node
    return figures(raw)


# ── what a CA does ──────────────────────────────────────────────────────────

def _create(w, name, category, cost, life, method="SL", client: str = CLIENT):
    import routers.fixed_assets as fa
    from models.accounting import FixedAssetIn
    res = fa.create_asset(FixedAssetIn(
        client_id=client, asset_name=name, asset_category=category, purchase_date="2025-04-05", purchase_cost_paise=cost,
        depreciation_method=method, useful_life_years=life, acquisition_mode="paid"), PARTNER)
    assert res["success"] is True, res
    return res["data"]


def _depreciate(w, asset_id, months):
    import routers.fixed_assets as fa
    from models.accounting import DepreciationIn
    for period in months:
        assert fa.post_depreciation(asset_id, DepreciationIn(period=period), PARTNER)["success"]


def _make_it_a_legacy_asset(w, asset_id):
    """Every intangible asset in production today has no pointer: the stage that creates one did not exist."""
    assert _psql(w.dsn, f"UPDATE fixed_assets SET accumulated_account_id = NULL WHERE id = '{asset_id}';").returncode == 0


def _legacy_books(w, licence_months=("2025-04", "2025-05", "2025-06"), client: str = CLIENT):
    plant = _create(w, "Lathe", "Plant & Machinery", 2_40_000_00, 15, "WDV", client=client)
    licence = _create(w, "Licence", "Intangibles", 1_20_000_00, 5, client=client)
    _make_it_a_legacy_asset(w, licence["id"])
    _depreciate(w, plant["id"], ("2025-04", "2025-05", "2025-06"))
    _depreciate(w, licence["id"], licence_months)
    return plant, licence


def _reclassify(w, asset_id, as_at=AS_AT, client: str = CLIENT, carried: str | None = None):
    import routers.fixed_assets as fa
    pre = fa.amortisation_reclassification_preview(client, as_at, carried, PARTNER)["data"]
    assert pre["ready"] is True, pre["refusals"]
    body = fa.AmortisationReclassIn(client_id=client, as_at=as_at, asset_ids=[asset_id], expected_total_paise=pre["total_to_move_paise"],
                                    carried_over_from_account_id=carried)
    return fa.amortisation_reclassification_post(body, PARTNER)["data"]


# ── the proof ───────────────────────────────────────────────────────────────

def test_before_the_move_the_ledgers_two_lines_are_off_the_register_by_the_amortisation_and_after_it_they_tie(world):
    w = world
    plant, licence = _legacy_books(w)
    register_before, lines_before = _register(w), _lines(w)
    amortised = int(_rows(w.dsn, f"SELECT accumulated_depreciation_paise FROM fixed_assets WHERE id = '{licence['id']}'")[0][0])
    assert amortised > 0

    # THE DEFECT: the tangible line is short, and the intangible line over, by exactly what the licence has been amortised.
    assert lines_before["tangible_assets"] == register_before["tangible_assets"] - amortised
    assert lines_before["intangible_assets"] == register_before["intangible_assets"] + amortised
    cash_before = _cash_flow(w)

    moved = _reclassify(w, licence["id"])
    assert moved["failed"] == [] and moved["skipped"] == [] and moved["total_moved_paise"] == amortised

    # THE FIX: each line equals the register's net block of its kind. Nothing else moved.
    assert _lines(w) == _register(w) == register_before
    bal = _balances(w)
    assert bal["1591"] == -amortised, "the Accumulated Amortisation ledger holds exactly the licence's amortisation, as a credit"
    assert _cash_flow(w) == cash_before, "a move between two fixed-asset ledgers changes no cash-flow figure"
    assert sum(bal.values()) == 0, "the books still balance"


def test_a_month_posted_after_the_move_credits_the_new_ledger_and_the_lines_still_tie(world):
    w = world
    plant, licence = _legacy_books(w)
    _reclassify(w, licence["id"])
    _depreciate(w, licence["id"], ("2025-07",))
    bal = _balances(w)
    register_amortisation = int(_rows(w.dsn, f"SELECT accumulated_depreciation_paise FROM fixed_assets WHERE id = '{licence['id']}'")[0][0])
    assert bal["1591"] == -register_amortisation
    assert _lines(w) == _register(w)


def test_a_disposal_clears_the_ledger_the_asset_points_at_and_leaves_a_debit_balance_in_neither(world):
    w = world
    plant, licence = _legacy_books(w)
    _depreciate(w, licence["id"], ("2025-07", "2025-08", "2025-09"))     # a disposal needs every month through its own posted
    _reclassify(w, licence["id"])
    import routers.fixed_assets as fa
    from models.accounting import DisposalIn
    early = DisposalIn(disposal_date="2025-06-30", sale_proceeds_paise=50_000_00, disposal_type="Sale")
    with pytest.raises(HTTPException) as refused:
        fa.dispose_asset(licence["id"], early, PARTNER)
    assert refused.value.status_code == 422 and "before it was credited" in refused.value.detail, \
        "a disposal dated before the move would debit the new ledger on a day it held nothing"
    out = fa.dispose_asset(licence["id"], DisposalIn(disposal_date="2025-09-30", sale_proceeds_paise=50_000_00, disposal_type="Sale"), PARTNER)
    assert out["success"] is True, out
    bal = _balances(w)
    assert bal["1591"] == 0, "the new ledger is cleared by the disposal"
    assert bal["1590"] <= 0, "the shared ledger still credits the plant's depreciation and never goes to a debit balance"
    assert _lines(w) == _register(w)


def test_an_asset_created_after_the_change_is_born_in_its_own_ledger_and_ties_with_no_reclassification(world):
    w = world
    licence = _create(w, "Licence", "Intangibles", 1_20_000_00, 5)
    pointer = _rows(w.dsn, f"SELECT accumulated_account_id FROM fixed_assets WHERE id = '{licence['id']}'")[0][0]
    own = _rows(w.dsn, f"SELECT id FROM chart_of_accounts WHERE firm_id = '{FIRM}' AND account_code = '1591'")[0][0]
    assert pointer == own
    _depreciate(w, licence["id"], ("2025-04", "2025-05"))
    assert _lines(w) == _register(w)
    assert _balances(w)["1590"] == 0, "nothing went to the shared ledger"


def test_the_undo_puts_the_ledgers_back_as_they_were_and_the_journal_reversal_route_refuses_these_entries(world):
    w = world
    plant, licence = _legacy_books(w)
    lines_before, balances_before = _lines(w), _balances(w)
    _reclassify(w, licence["id"])
    import routers.accounting as acct
    import routers.fixed_assets as fa
    from models.accounting import JournalReversalIn
    entry = _rows(w.dsn, f"SELECT id FROM journal_entries WHERE source_type = 'amortisation_reclass' AND source_id = '{licence['id']}'")[0][0]
    with pytest.raises(HTTPException) as refused:
        acct.reverse_journal_entry(entry, JournalReversalIn(reversal_date="2025-10-01"), PARTNER)
    assert refused.value.status_code == 422 and "Moved by a reclassification" in refused.value.detail

    undone = fa.amortisation_reclassification_undo(licence["id"], PARTNER)
    assert undone["success"] is True
    assert _balances(w) == balances_before and _lines(w) == lines_before
    assert _rows(w.dsn, f"SELECT accumulated_account_id IS NULL FROM fixed_assets WHERE id = '{licence['id']}'") == [["t"]]
    reversed_ = _rows(w.dsn, f"SELECT is_reversed FROM journal_entries WHERE id = '{entry}'")
    assert reversed_ == [["t"]], "the move itself is reversed, and by the route that also puts the pointer back"


def test_a_closed_year_refuses_the_move_and_nothing_is_written(world):
    w = world
    plant, licence = _legacy_books(w)
    assert _psql(w.dsn, f"INSERT INTO client_year_locks (firm_id, client_id, financial_year, reason) "
                        f"VALUES ('{FIRM}', '{CLIENT}', '2025-26', 'finalised');").returncode == 0
    import routers.fixed_assets as fa
    pre = fa.amortisation_reclassification_preview(CLIENT, AS_AT, None, PARTNER)["data"]
    assert pre["ready"] is False and pre["refusals"]
    entries = _rows(w.dsn, "SELECT count(*) FROM journal_entries")[0][0]
    body = fa.AmortisationReclassIn(client_id=CLIENT, as_at=AS_AT, asset_ids=[licence["id"]],
                                    expected_total_paise=pre["total_to_move_paise"])
    with pytest.raises(HTTPException):
        fa.amortisation_reclassification_post(body, PARTNER)
    assert _rows(w.dsn, "SELECT count(*) FROM journal_entries")[0][0] == entries


def test_with_months_posted_after_the_stated_date_the_lines_tie_at_every_year_end_from_it_and_a_date_between_is_off_by_exactly_those_months(world):
    """The claim the preview makes in words, proved on the database: entries are dated the stated date and each later financial year end,
    so a balance sheet cut at a year end is exact and one cut between is short by the months not yet moved."""
    w = world
    plant, licence = _legacy_books(w, licence_months=("2025-04", "2025-05", "2025-06", "2025-07", "2025-08"))
    moved = _reclassify(w, licence["id"], as_at="2025-05-31")
    assert moved["failed"] == [] and len(moved["moved"][0]["journal_entry_ids"]) == 2, "the first two months on 31 May, the rest in a second entry"
    dates = [d for (d,) in _rows(w.dsn, f"SELECT entry_date FROM journal_entries WHERE source_type = 'amortisation_reclass' "
                                        f"AND source_id = '{licence['id']}' ORDER BY entry_date")]
    assert dates == ["2025-05-31", "2026-03-31"]
    register = _register(w)

    def amortised(after: str, upto: str) -> int:
        """What the licence's own depreciation entries credited to the shared ledger between two dates, from the journals."""
        return int(_rows(w.dsn, f"""
            SELECT COALESCE(SUM(l.credit_paise - l.debit_paise), 0) FROM journal_lines l JOIN journal_entries e ON e.id = l.journal_entry_id
             WHERE e.source_type = 'depreciation' AND l.account_id = (SELECT id FROM chart_of_accounts WHERE firm_id = '{FIRM}' AND account_code = '1590')
               AND e.source_id = '{licence['id']}' AND e.entry_date > '{after}' AND e.entry_date <= '{upto}'""")[0][0])

    to_may, jun_to_aug = amortised("2000-01-01", "2025-05-31"), amortised("2025-05-31", "2025-08-31")
    assert to_may > 0 and jun_to_aug > 0
    # a year end after the second entry, and today: exact
    assert _lines(w, upto="2026-03-31") == register and _lines(w) == register
    # 31 May 2025 is the stated date: exact (only April and May exist by then, and both are moved that day)
    assert _lines(w, upto="2025-05-31")["intangible_assets"] == 1_20_000_00 - to_may
    # 31 August 2025 is between: June to August are still in the shared ledger on that day
    aug = _lines(w, upto="2025-08-31")
    assert aug["intangible_assets"] == register["intangible_assets"] + jun_to_aug
    assert aug["tangible_assets"] == register["tangible_assets"] - jun_to_aug


def test_a_second_client_of_the_same_firm_is_neither_read_nor_disturbed(world):
    w = world
    plant1, licence1 = _legacy_books(w)
    plant2, licence2 = _legacy_books(w, licence_months=("2025-04", "2025-05"), client=CLIENT2)
    before2, lines2, register2 = _balances(w, CLIENT2), _lines(w, CLIENT2), _register(w, CLIENT2)
    assert lines2 != register2, "the second client has the same defect until its own Partner moves it"

    _reclassify(w, licence1["id"])
    assert _lines(w) == _register(w)
    assert _balances(w, CLIENT2) == before2, "the first client's move wrote nothing into the second client's books"
    assert _rows(w.dsn, f"SELECT accumulated_account_id IS NULL FROM fixed_assets WHERE id = '{licence2['id']}'") == [["t"]]

    _reclassify(w, licence2["id"], client=CLIENT2)
    assert _lines(w, CLIENT2) == _register(w, CLIENT2) and _lines(w) == _register(w)


def test_depreciation_brought_over_sits_in_the_ledger_the_partner_names_and_nowhere_else(world):
    w = world
    plant, licence = _legacy_books(w)
    carried = 10_000_00
    imported = "54501000-0000-0000-0000-0000000000c1"
    entry = "54501000-0000-0000-0000-0000000000e1"
    seeded = _psql(w.dsn, f"""
        INSERT INTO chart_of_accounts (id, firm_id, client_id, account_code, account_name, account_type, account_subtype, is_active)
          VALUES ('{imported}', '{FIRM}', '{CLIENT}', '1700', 'Accumulated Dep - Software (imported)', 'Asset', 'Fixed Asset', TRUE);
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status, source_type)
          VALUES ('{entry}', '{FIRM}', '{CLIENT}', '2025-04-01', 'TB-1', 'imported trial balance', 'Journal', true, 'posted', 'TrialBalance');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise) VALUES
          ('{entry}', '{imported}', 0, {carried}),
          ('{entry}', (SELECT id FROM chart_of_accounts WHERE firm_id = '{FIRM}' AND account_name = 'Cash in Hand' LIMIT 1), {carried}, 0);
        UPDATE fixed_assets SET accumulated_depreciation_paise = accumulated_depreciation_paise + {carried} WHERE id = '{licence['id']}';
    """)
    assert seeded.returncode == 0, seeded.stderr
    import routers.fixed_assets as fa
    blank = fa.amortisation_reclassification_preview(CLIENT, AS_AT, None, PARTNER)["data"]
    assert blank["ready"] is False and any("Choose the ledger it sits in" in r for r in blank["refusals"])
    assert [c["id"] for c in blank["carried_over_candidates"]] == [imported]
    shared = _rows(w.dsn, f"SELECT id FROM chart_of_accounts WHERE firm_id = '{FIRM}' AND account_code = '1590'")[0][0]
    on_purpose = fa.amortisation_reclassification_preview(CLIENT, AS_AT, shared, PARTNER)["data"]
    assert not any("Choose the ledger it sits in" in r for r in on_purpose["refusals"]), \
        "naming the shared ledger is an answer. (Whether it is the right one is the Partner's: the shared ledger also holds the tangible " \
        "assets' credit, so a sufficiency check cannot tell, and the screen says the choice is theirs.)"

    moved = _reclassify(w, licence["id"], carried=imported)
    assert moved["failed"] == [] and moved["skipped"] == []
    bal = _balances(w)
    register_amortisation = int(_rows(w.dsn, f"SELECT accumulated_depreciation_paise FROM fixed_assets WHERE id = '{licence['id']}'")[0][0])
    assert bal["1700"] == 0, "the imported ledger was emptied"
    assert bal["1591"] == -register_amortisation, "the new ledger holds the licence's whole accumulated amortisation"
    assert _lines(w) == _register(w)
    assert sum(bal.values()) == 0


def test_a_debit_to_the_shared_ledger_two_months_after_the_entry_that_would_take_it_below_what_left_it_refuses_the_move(world):
    """Judged only on the entry's own day this passed, and left the tangible line's contra in debit from August on, today included."""
    w = world
    plant, licence = _legacy_books(w)
    import routers.fixed_assets as fa
    shared = _rows(w.dsn, f"SELECT id FROM chart_of_accounts WHERE firm_id = '{FIRM}' AND account_code = '1590'")[0][0]
    cash = _rows(w.dsn, f"SELECT id FROM chart_of_accounts WHERE firm_id = '{FIRM}' AND account_name = 'Cash in Hand' LIMIT 1")[0][0]
    held = -_balances(w)["1590"]
    amortised = int(_rows(w.dsn, f"SELECT accumulated_depreciation_paise FROM fixed_assets WHERE id = '{licence['id']}'")[0][0])
    assert fa.amortisation_reclassification_preview(CLIENT, "2025-06-30", None, PARTNER)["data"]["ready"] is True
    # a later debit (a tangible asset disposed of, say) that leaves the shared ledger holding less than the licence's share
    debit = held - amortised + 100
    entry = "54501000-0000-0000-0000-0000000000e2"
    seeded = _psql(w.dsn, f"""
        INSERT INTO journal_entries (id, firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status, source_type)
          VALUES ('{entry}', '{FIRM}', '{CLIENT}', '2025-08-31', 'LATER-DEBIT', 'a debit two months after', 'Journal', true, 'posted', 'manual');
        INSERT INTO journal_lines (journal_entry_id, account_id, debit_paise, credit_paise) VALUES
          ('{entry}', '{shared}', {debit}, 0), ('{entry}', '{cash}', 0, {debit});""")
    assert seeded.returncode == 0, seeded.stderr
    out = fa.amortisation_reclassification_preview(CLIENT, "2025-06-30", None, PARTNER)["data"]
    assert out["ready"] is False and any("31 Aug 2025" in r and "debit balance" in r for r in out["refusals"]), out["refusals"]
    entries = _rows(w.dsn, "SELECT count(*) FROM journal_entries")[0][0]
    body = fa.AmortisationReclassIn(client_id=CLIENT, as_at="2025-06-30", asset_ids=[licence["id"]], expected_total_paise=amortised)
    with pytest.raises(HTTPException):
        fa.amortisation_reclassification_post(body, PARTNER)
    assert _rows(w.dsn, "SELECT count(*) FROM journal_entries")[0][0] == entries


def test_an_asset_claimed_and_never_posted_is_refused_for_disposal_listed_for_undo_and_taken_back_cleanly(world):
    w = world
    plant, licence = _legacy_books(w)
    import routers.fixed_assets as fa
    from models.accounting import DisposalIn
    own = _rows(w.dsn, f"SELECT id FROM chart_of_accounts WHERE firm_id = '{FIRM}' AND account_code = '1591'")[0][0]
    assert _psql(w.dsn, f"UPDATE fixed_assets SET accumulated_account_id = '{own}' WHERE id = '{licence['id']}';").returncode == 0
    summary = fa.amortisation_reclassification_summary(CLIENT, PARTNER)["data"]
    assert [a["asset_id"] for a in summary["moved_assets"]] == [licence["id"]] and summary["moved_assets"][0]["unfinished"] is True
    preview = fa.amortisation_reclassification_preview(CLIENT, AS_AT, None, PARTNER)["data"]
    assert preview["ready"] is False and any("did not finish" in r for r in preview["refusals"])
    with pytest.raises(HTTPException) as refused:
        fa.dispose_asset(licence["id"], DisposalIn(disposal_date="2025-06-30", sale_proceeds_paise=1_000_00, disposal_type="Sale"), PARTNER)
    assert refused.value.status_code == 422 and "did not finish" in refused.value.detail
    assert fa.amortisation_reclassification_undo(licence["id"], PARTNER)["success"] is True
    assert _rows(w.dsn, f"SELECT accumulated_account_id IS NULL FROM fixed_assets WHERE id = '{licence['id']}'") == [["t"]]
    assert _reclassify(w, licence["id"])["failed"] == [] and _lines(w) == _register(w)
