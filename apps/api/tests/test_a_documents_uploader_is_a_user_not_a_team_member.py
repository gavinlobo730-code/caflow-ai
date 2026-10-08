"""PRE-A-012 — the document upload stamps the INTERNAL user id.

THE BUG THIS PINS
    `documents.uploaded_by` and `documents.reviewed_by` referenced `team_members(id)`
    (migration 001), a staff table the product stopped writing when `users` replaced
    it, so the table is empty in production. POST /api/documents/upload wrote the
    caller's Supabase AUTH id into `uploaded_by`, and the foreign key refused every
    upload (SQLSTATE 23503): no document has ever been stored, and the bank entry
    modal's "attach a receipt" has never worked.

    Migration 479 repoints both columns at `public.users(id)`; the route writes
    `current_user["id"]`, the internal id, like every other created_by column.

THIS FILE IS THE MOCK-MODE HALF (no database). The foreign key itself and a row
going through it are in `test_a_documents_uploader_is_a_user_pg.py`.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = API_ROOT / "migrations"
MIGRATION = MIGRATIONS / "479_a_documents_uploader_and_reviewer_are_users_not_team_members.sql"

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
CLIENT = "11111111-2222-3333-4444-555555555555"
# The internal id and the auth id are DIFFERENT strings on purpose: a test whose
# two ids were equal could not tell which one the route wrote.
USER = {"firm_id": "F1", "id": "internal-user-id", "auth_user_id": "supabase-auth-id",
        "email": "ca@f.test", "role": "Partner"}


def _file() -> UploadFile:
    return UploadFile(filename="receipt.pdf", file=io.BytesIO(PDF))


class _Bucket:
    def upload(self, path=None, file=None, file_options=None, **kw):
        return {"path": path}

    def create_signed_url(self, *a, **k):
        return {"signedURL": "https://signed.example/x"}


class _Supabase:
    class storage:  # noqa: N801 - mirrors the client's attribute
        @staticmethod
        def from_(_bucket):
            return _Bucket()


def _route(monkeypatch, *, mock: bool):
    import core.supabase_client as sc
    import routers.documents as docs

    monkeypatch.setattr(sc, "get_supabase", lambda: _Supabase())
    monkeypatch.setattr(docs, "_USE_MOCK", mock)
    monkeypatch.setattr(docs, "assert_partner_for_internal_id", lambda *a, **k: None)
    monkeypatch.setattr(docs, "assert_client_access", lambda *a, **k: None)
    repo = MagicMock()
    repo.create.side_effect = lambda row: {"id": "doc-1", **row}
    monkeypatch.setattr(docs, "document_repo", repo)
    events: list[tuple] = []
    monkeypatch.setattr(docs, "log_event", lambda *a, **k: events.append((a, k)))
    monkeypatch.setattr(docs, "log_activity", lambda *a, **k: None)
    return docs, repo, events


@pytest.mark.parametrize("mock", [True, False], ids=["mock path", "database path"])
def test_the_row_names_the_internal_user_not_the_auth_id(monkeypatch, mock):
    docs, repo, _ = _route(monkeypatch, mock=mock)
    docs.upload_document(file=_file(), document_type="OTHER", client_id=CLIENT, current_user=USER)
    row = repo.create.call_args.args[0]
    assert row["uploaded_by"] == USER["id"]
    assert row["uploaded_by"] != USER["auth_user_id"]


@pytest.mark.parametrize("mock", [True, False], ids=["mock path", "database path"])
def test_the_audit_log_still_names_the_auth_id(monkeypatch, mock):
    """`audit_log.actor_id` takes the AUTH id (no foreign key; migration 111's
    trigger writes it that way). Moving `uploaded_by` must not drag it along."""
    docs, _, events = _route(monkeypatch, mock=mock)
    docs.upload_document(file=_file(), document_type="OTHER", client_id=CLIENT, current_user=USER)
    [(_, kwargs)] = events
    assert kwargs["actor_id"] == USER["auth_user_id"]


def test_the_route_never_writes_the_auth_id_into_uploaded_by():
    """The rule, not a spelling of today's call: nothing in the router builds a
    `documents` row whose uploaded_by or reviewed_by is the AUTH id."""
    src = (API_ROOT / "routers" / "documents.py").read_text()
    for m in re.finditer(r'"(uploaded_by|reviewed_by)"\s*:\s*([^\n]+)', src):
        assert "auth_user_id" not in m.group(2), m.group(0)


def test_the_migration_points_both_columns_at_users():
    sql = MIGRATION.read_text()
    for col in ("uploaded_by", "reviewed_by"):
        assert re.search(
            rf"ADD CONSTRAINT documents_{col}_fkey\s+FOREIGN KEY \({col}\) REFERENCES public\.users\(id\)",
            sql), col
    # the premise: 001 declared team_members, which is what made every upload fail
    first = (MIGRATIONS / "001_initial_schema.sql").read_text()
    assert re.search(r"uploaded_by UUID REFERENCES team_members\(id\)", first)
    assert re.search(r"reviewed_by UUID REFERENCES team_members\(id\)", first)


def test_no_other_migration_redefines_the_two_constraints_after_479():
    """Derive the last definer by NUMBER (CLAUDE.md, "Migrations"): a later file
    that put `team_members` back would silently reopen the defect."""
    later = []
    for p in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        if p.name.endswith("_rollback.sql") or int(p.name[:3]) <= 479:
            continue
        if re.search(r"documents_(uploaded|reviewed)_by_fkey", p.read_text()):
            later.append(p.name)
    assert later == [], later
