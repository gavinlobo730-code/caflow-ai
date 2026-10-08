"""PRE-A-012 / migration 479 — a document's uploader is a row of `users`.

WHAT IS ASSERTED, AND WHY IT IS A DATABASE FACT
    * the route's own row (`routers.documents.upload_document`, UNMODIFIED, with
      its repository pointed at a real INSERT) is stored, and `uploaded_by` is the
      internal user id: the end-to-end proof that an upload can succeed, which it
      never could while the column referenced the empty `team_members`;
    * the same insert with the Supabase AUTH id (what the route wrote before) or
      with any other uuid is refused by the foreign key, SQLSTATE 23503 — the
      negative control that makes the first assertion mean something;
    * `reviewed_by` follows the same rule, and NULL is still allowed for both;
    * the constraints are the ones 479 names, they reference `users`, and 479 is
      idempotent;
    * 479's own rollback puts the `team_members` references back, and the proof
      fails again — the hole is real and the migration is what closes it.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = API_ROOT / "migrations" / "479_a_documents_uploader_and_reviewer_are_users_not_team_members.sql"
ROLLBACK = API_ROOT / "migrations" / "479_a_documents_uploader_and_reviewer_are_users_not_team_members_rollback.sql"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the documents foreign-key proofs require HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000479"
CLIENT = "cccccccc-0000-0000-0000-000000000479"
USER_ID = "bbbbbbbb-0000-0000-0000-000000000479"
AUTH_ID = "11111111-0000-0000-0000-000000000479"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-tA", "-f", "-"],
                          input=sql, capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"docs_m479_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        _ok(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{AUTH_ID}', 'u@m479.test');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'M479 Firm', 'm479@test.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
              VALUES ('{USER_ID}', '{FIRM}', '{AUTH_ID}', 'u@m479.test', 'Uploader', 'Partner', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type)
              VALUES ('{CLIENT}', '{FIRM}', 'Client', 'Private Limited');
        """)
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


class _InsertingRepo:
    """The `document_repo.create` the route calls, as a real INSERT. Only the
    transport differs from `DocumentRepository.create`; the row is the route's."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.rows: list[dict] = []

    def create(self, row: dict) -> dict:
        cols = ", ".join(row)
        vals = ", ".join("NULL" if v is None else "'" + str(v).replace("'", "''") + "'" for v in row.values())
        out = _ok(self.dsn, f"INSERT INTO documents ({cols}) VALUES ({vals}) RETURNING id;")
        self.rows.append({"id": out, **row})
        return self.rows[-1]


def _upload(monkeypatch, dsn: str, user: dict) -> _InsertingRepo:
    import core.supabase_client as sc
    import routers.documents as docs

    class _Bucket:
        def upload(self, path=None, file=None, file_options=None, **kw):
            return {"path": path}

        def create_signed_url(self, *a, **k):
            return {"signedURL": "https://signed.example/x"}

    class _Supabase:
        class storage:  # noqa: N801
            @staticmethod
            def from_(_b):
                return _Bucket()

    repo = _InsertingRepo(dsn)
    monkeypatch.setattr(sc, "get_supabase", lambda: _Supabase())
    monkeypatch.setattr(docs, "_USE_MOCK", False)
    monkeypatch.setattr(docs, "assert_partner_for_internal_id", lambda *a, **k: None)
    monkeypatch.setattr(docs, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(docs, "document_repo", repo)
    monkeypatch.setattr(docs, "log_event", MagicMock())
    monkeypatch.setattr(docs, "log_activity", MagicMock())
    docs.upload_document(file=UploadFile(filename="receipt.pdf", file=io.BytesIO(PDF)),
                         document_type="OTHER", client_id=CLIENT, current_user=user)
    return repo


USER = {"firm_id": FIRM, "id": USER_ID, "auth_user_id": AUTH_ID, "email": "u@m479.test", "role": "Partner"}


def test_an_upload_through_the_route_is_stored_with_the_internal_user(db, monkeypatch):
    repo = _upload(monkeypatch, db, USER)
    [row] = repo.rows
    stored = _ok(db, f"SELECT uploaded_by FROM documents WHERE id = '{row['id']}';")
    assert stored == USER_ID


def test_the_auth_id_the_route_used_to_write_is_refused(db):
    r = _psql(db, f"""INSERT INTO documents (firm_id, client_id, document_type, file_name, file_path, uploaded_by)
                      VALUES ('{FIRM}', '{CLIENT}', 'OTHER', 'a.pdf', 'p/a.pdf', '{AUTH_ID}');""")
    assert r.returncode != 0
    assert "documents_uploaded_by_fkey" in r.stderr and "23503" in r.stderr or "violates foreign key" in r.stderr


def test_an_unknown_uploader_or_reviewer_is_refused_and_null_is_allowed(db):
    stray = str(uuid.uuid4())
    for col in ("uploaded_by", "reviewed_by"):
        r = _psql(db, f"""INSERT INTO documents (firm_id, client_id, document_type, file_name, file_path, {col})
                          VALUES ('{FIRM}', '{CLIENT}', 'OTHER', 'a.pdf', 'p/a.pdf', '{stray}');""")
        assert r.returncode != 0 and "violates foreign key" in r.stderr, col
    _ok(db, f"""INSERT INTO documents (firm_id, client_id, document_type, file_name, file_path)
                VALUES ('{FIRM}', '{CLIENT}', 'OTHER', 'a.pdf', 'p/a.pdf');""")
    _ok(db, f"""INSERT INTO documents (firm_id, client_id, document_type, file_name, file_path, reviewed_by)
                VALUES ('{FIRM}', '{CLIENT}', 'OTHER', 'b.pdf', 'p/b.pdf', '{USER_ID}');""")


def test_both_constraints_reference_users(db):
    refs = _ok(db, """
        SELECT conname || '->' || confrelid::regclass::text
          FROM pg_constraint
         WHERE conrelid = 'public.documents'::regclass AND contype = 'f'
           AND conname IN ('documents_uploaded_by_fkey', 'documents_reviewed_by_fkey')
         ORDER BY conname;""").splitlines()
    assert refs == ["documents_reviewed_by_fkey->users", "documents_uploaded_by_fkey->users"]


def test_479_is_idempotent(db):
    _ok(db, MIGRATION.read_text())
    _ok(db, MIGRATION.read_text())
    assert _ok(db, "SELECT count(*) FROM pg_constraint WHERE conrelid = 'public.documents'::regclass "
                   "AND conname IN ('documents_uploaded_by_fkey', 'documents_reviewed_by_fkey');") == "2"


def test_a_row_that_pre_dates_479_does_not_fail_the_migration(db):
    """An older row cannot name a `users.id` (the old constraint admitted only
    `team_members`). Put the old constraints back, store such a row against a
    team_members id, and re-run 479: it must go through, the constraints must be
    the new ones, and the old row is left exactly as it was."""
    _ok(db, ROLLBACK.read_text())
    tm = str(uuid.uuid4())
    _ok(db, f"INSERT INTO team_members (id, name, email, role) VALUES ('{tm}', 'Old Staff', 'old@m479.test', 'staff');")
    _ok(db, f"""INSERT INTO documents (firm_id, client_id, document_type, file_name, file_path, uploaded_by)
                VALUES ('{FIRM}', '{CLIENT}', 'OTHER', 'old.pdf', 'p/old.pdf', '{tm}');""")
    _ok(db, MIGRATION.read_text())
    assert _ok(db, "SELECT uploaded_by FROM documents WHERE file_name = 'old.pdf';") == tm
    r = _psql(db, f"""INSERT INTO documents (firm_id, client_id, document_type, file_name, file_path, uploaded_by)
                      VALUES ('{FIRM}', '{CLIENT}', 'OTHER', 'new.pdf', 'p/new.pdf', '{tm}');""")
    assert r.returncode != 0, "a NEW row naming a team member must still be refused"


def test_the_rollback_restores_the_defect(db, monkeypatch):
    """The negative control: with 001's references back, the route's own row is
    refused, which is exactly what production did."""
    _ok(db, ROLLBACK.read_text())
    with pytest.raises(AssertionError) as err:
        _upload(monkeypatch, db, USER)
    assert "documents_uploaded_by_fkey" in str(err.value) or "violates foreign key" in str(err.value)
