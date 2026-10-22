"""The trial-balance import's account resolver and the bank layout save run against the real schema (ledger POST-A-313, POST-A-300).

WHY A DATABASE
    The mock-mode halves are `test_a_trial_balance_import_does_not_collide_with_another_clients_ledger.py` and
    `test_a_corrected_bank_layout_does_not_overwrite_another_accounts.py`. Both rest on facts about the real tables that a double
    only imitates: `chart_of_accounts` is unique on (firm_id, account_code) and on (firm_id, account_name) whichever client owns
    the account, and `bank_statement_column_mappings` is unique per (bank_account_id, header_fingerprint). So the real functions
    run here against the migration-built schema, through the signed-in double of `tests/_signed_in_postgrest.py`.

WHAT IS HELD
    * the two firm-wide unique keys exist and refuse a firm-level account that repeats a code or a name another client's ledger
      holds (the premise of POST-A-313);
    * `_resolve_or_create_accounts` numbers past a code another client's ledger holds, explicit or slugged, and creates the
      account without a 23505; a name another client's ledger holds refuses the import in words and creates nothing;
    * a corrected layout saved for one bank account leaves the other account's row byte-for-byte as it was and records one for
      its own, a second save updates that row and adds no third, as a Partner signed in with their own token and as the API's
      privileged client (POST-A-300).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

from domain.accounting.trial_balance import TrialBalanceError, TrialBalanceRow
from domain.banking.normalizer import header_fingerprint
from services import bank_column_mapping_service as mappings
from services import trial_balance_import_service as tbi
from tests._signed_in_postgrest import SignedInDb

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the real-schema proof requires HARNESS_PG + psql",
)

FIRM = "31300000-0000-0000-0000-000000000001"
CLIENT_A = "31300000-0000-0000-0000-0000000000a1"
CLIENT_B = "31300000-0000-0000-0000-0000000000b2"
PARTNER = {"id": "31300000-0000-0000-0000-00000000000a", "auth_user_id": "31300000-1111-0000-0000-000000000001"}
ACCOUNT_A = "31300000-0000-0000-0000-0000000000c1"
ACCOUNT_B = "31300000-0000-0000-0000-0000000000c2"
B_LEDGER_NAME, B_LEDGER_CODE = "HDFC Bank - 7890", "1101"
HEADERS = ["Value Date", "Details", "Paid Out", "Paid In", "Running Total"]
A_MAPPING = {"date": 0, "desc": 1, "debit": 2, "credit": 3, "balance": 4}
B_MAPPING = {"date": 0, "desc": 1, "debit": 3, "credit": 2, "balance": 4}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


@pytest.fixture()
def world(pg_template):
    admin = _ADMIN.strip()
    name = f"e313_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER["auth_user_id"]}', 'partner@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type)
                 VALUES ('{CLIENT_A}', '{FIRM}', 'A', 'Proprietorship'), ('{CLIENT_B}', '{FIRM}', 'B', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{PARTNER["id"]}', '{FIRM}', '{PARTNER["auth_user_id"]}', 'partner@t.in', 'P', 'Partner', true);
            INSERT INTO bank_accounts (id, firm_id, client_id, bank_name, account_no)
                 VALUES ('{ACCOUNT_A}', '{FIRM}', '{CLIENT_A}', 'HDFC', '1111'), ('{ACCOUNT_B}', '{FIRM}', '{CLIENT_B}', 'HDFC', '2222');
            -- client B's own ledgers, as routers/banking._ensure_bank_ledger creates them (a client id, codes from 1101 up)
            INSERT INTO chart_of_accounts (firm_id, client_id, account_name, account_code, account_type)
                 VALUES ('{FIRM}', '{CLIENT_B}', '{B_LEDGER_NAME}', '{B_LEDGER_CODE}', 'Asset'),
                        ('{FIRM}', '{CLIENT_B}', 'Petty Cash', 'TB-PETTY-CASH', 'Asset');
        """)
        assert seed.returncode == 0, seed.stderr

        class World:
            pass

        w = World()
        w.dsn = dsn
        w.service_db = SignedInDb(dsn, role="service_role")
        w.partner_db = SignedInDb(dsn, auth_user_id=PARTNER["auth_user_id"])
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _chart(w) -> list[list[str]]:
    return _rows(w.dsn, f"SELECT account_name, account_code, coalesce(client_id::text, '') FROM chart_of_accounts "
                        f"WHERE firm_id = '{FIRM}' ORDER BY account_code")


def tb(name, code=None):
    return TrialBalanceRow(account_name=name, account_type="Asset", debit_paise=100, credit_paise=0, account_code=code)


# ── POST-A-313 ───────────────────────────────────────────────────────────────────

def test_the_chart_is_unique_per_firm_on_code_and_on_name_whichever_client_owns_the_account(world):
    code = _psql(world.dsn, f"INSERT INTO chart_of_accounts (firm_id, account_name, account_code, account_type) "
                            f"VALUES ('{FIRM}', 'Another name', '{B_LEDGER_CODE}', 'Asset');")
    assert code.returncode != 0 and "chart_of_accounts_firm_code_unique" in code.stderr, code.stderr
    name = _psql(world.dsn, f"INSERT INTO chart_of_accounts (firm_id, account_name, account_code, account_type) "
                            f"VALUES ('{FIRM}', '{B_LEDGER_NAME}', 'ANOTHER-CODE', 'Asset');")
    assert name.returncode != 0 and "chart_of_accounts_firm_name_unique" in name.stderr, name.stderr


def test_an_explicit_code_another_clients_ledger_holds_is_numbered_past_and_the_account_is_created(world):
    resolved = tbi._resolve_or_create_accounts(world.service_db, FIRM, CLIENT_A, [tb("Cash at bank", B_LEDGER_CODE)])
    assert set(resolved) == {"Cash at bank"}
    created = [r for r in _chart(world) if r[0] == "Cash at bank"]
    assert created == [["Cash at bank", f"{B_LEDGER_CODE}-2", ""]], created      # firm-level, past the code B's ledger holds


def test_a_slugged_code_another_clients_ledger_holds_is_numbered_past(world):
    # 'Petty Cash' belongs to client B, so for client A this is a different name that slugs to the same code
    resolved = tbi._resolve_or_create_accounts(world.service_db, FIRM, CLIENT_A, [tb("Petty cash (A)"), tb("Petty-Cash!")])
    assert len(resolved) == 2
    codes = {r[0]: r[1] for r in _chart(world)}
    assert codes["Petty cash (A)"] == "TB-PETTY-CASH-A"
    assert codes["Petty-Cash!"] == "TB-PETTY-CASH-2", "the code client B's ledger holds was chosen again"
    assert len({r[1] for r in _chart(world)}) == len(_chart(world))


def test_a_name_another_clients_ledger_holds_refuses_the_import_in_words_and_creates_nothing(world):
    before = _chart(world)
    with pytest.raises(TrialBalanceError, match="another client's ledger"):
        tbi._resolve_or_create_accounts(world.service_db, FIRM, CLIENT_A, [tb("Brand new account"), tb(B_LEDGER_NAME)])
    assert _chart(world) == before, "the import created an account before it refused the row"


def test_the_client_that_owns_the_ledger_still_matches_its_own_account_by_name(world):
    resolved = tbi._resolve_or_create_accounts(world.service_db, FIRM, CLIENT_B, [tb(B_LEDGER_NAME.upper())])
    own = _rows(world.dsn, f"SELECT id FROM chart_of_accounts WHERE firm_id = '{FIRM}' AND account_name = '{B_LEDGER_NAME}'")[0][0]
    assert resolved == {B_LEDGER_NAME.upper(): own}
    assert len(_chart(world)) == 2


# ── POST-A-300 ───────────────────────────────────────────────────────────────────

def _layouts(w) -> list[list[str]]:
    return _rows(w.dsn, "SELECT bank_account_id, client_id, mapping::text, created_by::text, updated_at::text "
                        "FROM bank_statement_column_mappings ORDER BY bank_account_id")


@pytest.mark.parametrize("who", ["partner", "service"])
def test_a_correction_for_one_account_leaves_the_other_accounts_layout_untouched(world, who):
    db = world.partner_db if who == "partner" else world.service_db
    mappings.save_mapping(db, FIRM, CLIENT_A, ACCOUNT_A, HEADERS, A_MAPPING, actor_id=PARTNER["id"])
    (first,) = _layouts(world)
    assert mappings.find_mapping(db, FIRM, ACCOUNT_B, header_fingerprint(HEADERS))["match_scope"] == "firm"

    mappings.save_mapping(db, FIRM, CLIENT_B, ACCOUNT_B, HEADERS, B_MAPPING, actor_id=PARTNER["id"])
    rows = _layouts(world)
    assert len(rows) == 2, rows
    assert rows[0] == first, "account A's saved layout was changed by a correction made for account B"
    assert rows[1][0] == ACCOUNT_B and rows[1][1] == CLIENT_B and '"debit": 3' in rows[1][2]

    # a second correction for B updates B's own row and adds no third
    mappings.save_mapping(db, FIRM, CLIENT_B, ACCOUNT_B, HEADERS, {**B_MAPPING, "debit": 2, "credit": 3}, actor_id=PARTNER["id"])
    again = _layouts(world)
    assert len(again) == 2 and again[0] == first and '"debit": 2' in again[1][2], again
