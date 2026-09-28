"""
The staff `users` table — read and written as the SERVICE ROLE, scoped by firm
in every query that is not addressed by a bearer secret.

WHY THE SERVICE CLIENT
    This repository used `get_supabase()`, which under USE_USER_JWT is the
    caller's own `authenticated` client. On `public.users` that role holds
    SELECT through `users_own_row_select` (auth_user_id = auth.uid(), so it
    sees exactly ONE row, its own), a column-level UPDATE on `full_name` only,
    and no INSERT at all (migration 153 revoked the browser's write paths, and
    rightly). Every staff-identity act in `routers/identity.py` is a write the
    browser was deliberately stripped of and the API was meant to do instead:

      * PATCH /me sends `updated_at` beside `full_name` → 42501 on the column
        grant, so nobody could rename themselves;
      * POST /users (invite) is an INSERT → 42501;
      * the Team list, role change, suspend, reactivate and force-logout all
        start from a read of ANOTHER member's row, which the SELECT policy
        hides → an empty list and a 404 for everyone but the caller;
      * accept-invite reads an UNLINKED row (auth_user_id IS NULL), which the
        SELECT policy can never see → "Invalid or expired invite" for every
        invitee, and the task router's C4 assignee check answered "Assignee not
        found in this firm" for any assignee but the caller.

    All invisible in a firm of one. Each endpoint that reaches this module runs
    `rbac()` (accept-invite runs `get_jwt_user`, by design: the caller has no
    users row yet), so the app layer is the access control here and RLS was
    only ever refusing the legitimate act.

WHY EVERY QUERY NOW CARRIES firm_id
    The service role bypasses RLS, so the `.eq("firm_id", …)` filter IS the
    tenant boundary (CLAUDE.md "Tenancy and access"). Before this, `find_by_id`
    and `update` addressed a row by id alone and trusted each caller to have
    checked the firm first — true of the identity router, false of
    `services/approval_service._h_user_activation` / `_h_role_change`, which
    updated `p["user_id"]` straight off a request payload. So `firm_id` is a
    REQUIRED keyword on every method addressed by an id or an email: a caller
    that forgets it fails with a TypeError at its first call rather than
    reading or writing another firm's staff.

    `find_all` keeps its optional signature for the mock-mode scheduler, and
    REFUSES a missing firm in live mode — "every staff member of every firm"
    is never a question an endpoint asks.

    The ONE unscoped read is `find_by_invite_token`: the invitee does not yet
    belong to a firm the request could name, and the token — a 256-bit secret
    sent only to the invited mailbox, matched only on a row not yet linked —
    is the scope. Its caller checks expiry and the mailbox as well.
"""
import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_TEAM_MEMBERS


def _get_db():
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


def _require_firm(firm_id: Optional[str], method: str) -> str:
    if not firm_id:
        raise ValueError(
            f"user_repo.{method} needs a firm_id — this repository reads as the "
            "service role, so the firm filter is the tenant boundary."
        )
    return firm_id


def _mock_in_firm(u: dict, firm_id: str) -> bool:
    # The seeded mock member carries no firm_id; a row created in mock mode
    # does, and must not answer for another firm.
    return u.get("firm_id") in (None, firm_id)


class UserRepository(BaseRepository[dict]):

    def find_by_id(self, id: str, *, firm_id: str) -> Optional[dict]:
        _require_firm(firm_id, "find_by_id")
        if _USE_MOCK:
            return next((u for u in MOCK_TEAM_MEMBERS
                         if u["id"] == id and _mock_in_firm(u, firm_id)), None)
        result = (_get_db().table("users").select("*")
                  .eq("id", id).eq("firm_id", firm_id)
                  .is_("deleted_at", None).maybe_single().execute())
        return result.data

    def find_all(self, firm_id: Optional[str] = None, role: Optional[str] = None, **filters) -> list[dict]:
        if _USE_MOCK:
            users = list(MOCK_TEAM_MEMBERS)
            if firm_id:
                users = [u for u in users if _mock_in_firm(u, firm_id)]
            if role:
                users = [u for u in users if u.get("role") == role]
            return users
        _require_firm(firm_id, "find_all")
        query = (_get_db().table("users").select("*")
                 .eq("firm_id", firm_id).is_("deleted_at", None))
        if role:
            query = query.eq("role", role)
        result = query.order("full_name").execute()
        return result.data or []

    def find_by_email(self, email: str, *, firm_id: str) -> Optional[dict]:
        _require_firm(firm_id, "find_by_email")
        if _USE_MOCK:
            return next((u for u in MOCK_TEAM_MEMBERS
                         if u["email"] == email and _mock_in_firm(u, firm_id)), None)
        result = (_get_db().table("users").select("*")
                  .eq("email", email).eq("firm_id", firm_id)
                  .is_("deleted_at", None).maybe_single().execute())
        return result.data

    def find_by_auth_user_id(self, auth_user_id: str, *, firm_id: str) -> Optional[dict]:
        _require_firm(firm_id, "find_by_auth_user_id")
        if _USE_MOCK:
            return None
        result = (_get_db().table("users").select("*")
                  .eq("auth_user_id", auth_user_id).eq("firm_id", firm_id)
                  .maybe_single().execute())
        return result.data

    def find_by_invite_token(self, token: str) -> Optional[dict]:
        """A row awaiting invite acceptance (F21 fix) — never matches an
        already-linked row, since auth_user_id must still be NULL.

        Deliberately NOT firm-scoped: the invitee belongs to no firm the
        request can name yet, and the 256-bit token is the scope (see the
        module docstring)."""
        if not token:
            return None
        if _USE_MOCK:
            return next((u for u in MOCK_TEAM_MEMBERS
                         if u.get("invite_token") == token and not u.get("auth_user_id")), None)
        result = (_get_db().table("users").select("*")
                  .eq("invite_token", token).is_("auth_user_id", None)
                  .maybe_single().execute())
        return result.data

    def get_or_raise(self, id: str, *, firm_id: str) -> dict:
        user = self.find_by_id(id, firm_id=firm_id)
        if not user:
            raise NotFoundError("User", id)
        return user

    def create(self, data: dict) -> dict:
        # The row's own firm_id is the scope of an INSERT; one without it would
        # be a staff member of no firm, which no caller means.
        _require_firm(data.get("firm_id"), "create")
        if _USE_MOCK:
            import uuid
            record = {"id": str(uuid.uuid4()), **data, "created_at": self.now_iso()}
            MOCK_TEAM_MEMBERS.append(record)
            return record
        result = _get_db().table("users").insert({**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}).execute()
        return result.data[0]

    def update(self, id: str, data: dict, *, firm_id: str) -> Optional[dict]:
        """Update one member of `firm_id`. A user id belonging to another firm
        matches no row and answers None — the same answer as an unknown id."""
        _require_firm(firm_id, "update")
        if "firm_id" in data and data["firm_id"] != firm_id:
            # Moving a person between tenants is not an update anybody asks for.
            raise ValueError("user_repo.update cannot move a user to another firm")
        if _USE_MOCK:
            user = self.find_by_id(id, firm_id=firm_id)
            if not user:
                return None
            user.update({**data, "updated_at": self.now_iso()})
            return user
        result = (_get_db().table("users")
                  .update({**data, "updated_at": self.now_iso()})
                  .eq("id", id).eq("firm_id", firm_id).execute())
        return result.data[0] if result.data else None


user_repo = UserRepository()
