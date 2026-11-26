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
    checked the firm first — true of the identity router, false of the approval
    engine's user-activation and role-change handlers (retired on 19-10-2026,
    POST-A-240), which updated `p["user_id"]` straight off a request payload. So `firm_id` is a
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
    `find_linked_member` is the other, keyed on the caller's own verified sign-in:
    accept-invite asks it whether that sign-in already belongs to a practice.

THE INVITATION'S TOKEN NEVER LEAVES THIS MODULE BUT THROUGH `find_by_invite_token`
    (POST-A-445.) Every other read and write returns the row WITHOUT
    `invite_token` and with `invite_outstanding` (whether one is set) in its place,
    which is all `domain/firm/member_state` needs. The team list served it whole to
    anyone who may read the team, and a role change, an activation and a forced
    sign-out each echoed it back; since the join page turns a token into a sign-in,
    a token on a response was a sign-in for somebody else's address. The column also
    holds a hash now (`domain/firm/invite_token`), so a stored value that leaks some
    other way opens nothing either.
"""
import os
from typing import Optional
from repositories.base import BaseRepository
from core.exceptions import NotFoundError
from core import db_provider
from domain.firm.invite_token import lookup_values

_USE_MOCK = not os.environ.get("SUPABASE_URL")

if _USE_MOCK:
    from mock_data import MOCK_TEAM_MEMBERS


_get_db = db_provider.service_db


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


def _without_token(row: Optional[dict]) -> Optional[dict]:
    """The row as every method but `find_by_invite_token` returns it: no token, and whether one is set."""
    if not row:
        return row
    out = {k: v for k, v in row.items() if k != "invite_token"}
    out["invite_outstanding"] = bool(row.get("invite_token"))
    return out


def _invitation_columns(previous: dict, now: str) -> dict:
    """The two invitation columns a restore writes back, named: a restore puts back an invitation and nothing else,
    whatever else the dict it is handed carries. The database path writes the same three names as a literal, so the
    column check can read every name it writes."""
    return {"invite_token": previous.get("invite_token"), "invite_expires_at": previous.get("invite_expires_at"),
            "updated_at": now}


class UserRepository(BaseRepository[dict]):

    def find_by_id(self, id: str, *, firm_id: str) -> Optional[dict]:
        _require_firm(firm_id, "find_by_id")
        if _USE_MOCK:
            return _without_token(self._mock_row(id, firm_id))
        result = (_get_db().table("users").select("*")
                  .eq("id", id).eq("firm_id", firm_id)
                  .is_("deleted_at", None).maybe_single().execute())
        return _without_token(result.data)

    @staticmethod
    def _mock_row(id: str, firm_id: str) -> Optional[dict]:
        return next((u for u in MOCK_TEAM_MEMBERS if u["id"] == id and _mock_in_firm(u, firm_id)), None)

    def find_all(self, firm_id: Optional[str] = None, role: Optional[str] = None, **filters) -> list[dict]:
        if _USE_MOCK:
            users = list(MOCK_TEAM_MEMBERS)
            if firm_id:
                users = [u for u in users if _mock_in_firm(u, firm_id)]
            if role:
                users = [u for u in users if u.get("role") == role]
            return [_without_token(u) for u in users]
        _require_firm(firm_id, "find_all")
        query = (_get_db().table("users").select("*")
                 .eq("firm_id", firm_id).is_("deleted_at", None))
        if role:
            query = query.eq("role", role)
        result = query.order("full_name").execute()
        return [_without_token(u) for u in (result.data or [])]

    def find_by_email(self, email: str, *, firm_id: str) -> Optional[dict]:
        _require_firm(firm_id, "find_by_email")
        if _USE_MOCK:
            return _without_token(next((u for u in MOCK_TEAM_MEMBERS
                                        if u["email"] == email and _mock_in_firm(u, firm_id)), None))
        result = (_get_db().table("users").select("*")
                  .eq("email", email).eq("firm_id", firm_id)
                  .is_("deleted_at", None).maybe_single().execute())
        return _without_token(result.data)

    def find_by_auth_user_id(self, auth_user_id: str, *, firm_id: str) -> Optional[dict]:
        _require_firm(firm_id, "find_by_auth_user_id")
        if _USE_MOCK:
            return None
        result = (_get_db().table("users").select("*")
                  .eq("auth_user_id", auth_user_id).eq("firm_id", firm_id)
                  .maybe_single().execute())
        return _without_token(result.data)

    def find_linked_member(self, auth_user_id: str) -> Optional[dict]:
        """The member row a sign-in is already linked to, in ANY practice, or None (POST-A-445).

        Deliberately NOT firm-scoped, and keyed on the caller's own verified sign-in: accept-invite asks it before
        linking, because a sign-in linked to two `users` rows locks its owner out of both (`core/auth` reads that
        link with `maybe_single`, which a second row turns into a 503 on every request)."""
        if not auth_user_id:
            return None
        if _USE_MOCK:
            return _without_token(next((u for u in MOCK_TEAM_MEMBERS
                                        if u.get("auth_user_id") == auth_user_id), None))
        result = (_get_db().table("users").select("id, firm_id")
                  .eq("auth_user_id", auth_user_id).limit(1).execute())
        rows = result.data or []
        return rows[0] if rows else None

    def invite_columns(self, id: str, *, firm_id: str) -> Optional[dict]:
        """A member's stored invitation (`invite_token`, a hash or the pre-POST-A-445 secret, and
        `invite_expires_at`), read only so a resend whose mail did not go can put it back. Never served."""
        _require_firm(firm_id, "invite_columns")
        if _USE_MOCK:
            row = self._mock_row(id, firm_id)
        else:
            row = (_get_db().table("users").select("invite_token, invite_expires_at")
                   .eq("id", id).eq("firm_id", firm_id).maybe_single().execute()).data
        if not row:
            return None
        return {"invite_token": row.get("invite_token"), "invite_expires_at": row.get("invite_expires_at")}

    def restore_invitation(self, id: str, previous: dict, *, replacing: str, firm_id: str) -> Optional[dict]:
        """Write `previous` (an invitation's stored columns) back over the member's row, but ONLY while the row still
        holds the invitation `replacing` (its stored form), has no sign-in and is switched on. A resend whose mail did
        not go puts the earlier invitation back this way, so a withdraw, an acceptance or another resend that landed
        while the mail was being sent is never undone (POST-A-445). None when nothing was written."""
        _require_firm(firm_id, "restore_invitation")
        if _USE_MOCK:
            row = self._mock_row(id, firm_id)
            if (not row or row.get("invite_token") != replacing or row.get("auth_user_id")
                    or row.get("is_active") is False):
                return None
            row.update(_invitation_columns(previous, self.now_iso()))
            return _without_token(row)
        result = (_get_db().table("users")
                  .update({"invite_token": previous.get("invite_token"),
                           "invite_expires_at": previous.get("invite_expires_at"),
                           "updated_at": self.now_iso()})
                  .eq("id", id).eq("firm_id", firm_id).eq("invite_token", replacing)
                  .is_("auth_user_id", None).eq("is_active", True).execute())
        return _without_token(result.data[0]) if result.data else None

    def find_by_invite_token(self, token: str) -> Optional[dict]:
        """A row awaiting invite acceptance (F21 fix) — never matches an
        already-linked row, since auth_user_id must still be NULL.

        Deliberately NOT firm-scoped: the invitee belongs to no firm the
        request can name yet, and the 256-bit token is the scope (see the
        module docstring). The ONE read that returns the stored token (a hash
        since POST-A-445, `domain/firm/invite_token`), because the caller asks
        which form it is in before it opens a sign-in."""
        values = lookup_values(token)
        if not values:
            return None
        if _USE_MOCK:
            return next((u for u in MOCK_TEAM_MEMBERS
                         if u.get("invite_token") in values and not u.get("auth_user_id")), None)
        result = (_get_db().table("users").select("*")
                  .in_("invite_token", values).is_("auth_user_id", None)
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
            return _without_token(record)
        result = _get_db().table("users").insert({**data, "created_at": self.now_iso(), "updated_at": self.now_iso()}).execute()
        return _without_token(result.data[0])

    def update(self, id: str, data: dict, *, firm_id: str) -> Optional[dict]:
        """Update one member of `firm_id`. A user id belonging to another firm
        matches no row and answers None — the same answer as an unknown id."""
        _require_firm(firm_id, "update")
        if "firm_id" in data and data["firm_id"] != firm_id:
            # Moving a person between tenants is not an update anybody asks for.
            raise ValueError("user_repo.update cannot move a user to another firm")
        if _USE_MOCK:
            user = self._mock_row(id, firm_id)
            if not user:
                return None
            user.update({**data, "updated_at": self.now_iso()})
            return _without_token(user)
        result = (_get_db().table("users")
                  .update({**data, "updated_at": self.now_iso()})
                  .eq("id", id).eq("firm_id", firm_id).execute())
        return _without_token(result.data[0]) if result.data else None


user_repo = UserRepository()
