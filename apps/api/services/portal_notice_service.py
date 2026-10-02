"""Tell both sides when the client portal moves (practice_management-02).

A document request and a portal message used to be a row and nothing else: the
client was never told their accountant had asked for something, and the staff
member was never told the client had written back. The reply sat unseen until
somebody happened to open that client's portal tab.

THREE THINGS, AND EACH IS A DIFFERENT AUDIENCE

  (a) the CLIENT'S PORTAL CONTACT is mailed when the firm creates a document
      request or sends a message. That is the practice writing to its own
      client, so it goes out under the practice's name with a Reply-To that
      reaches the practice (practice_management-04) — and it is NEVER an
      invoice-type mail, so it never names, copies or reaches a client's
      customer. Only an ACTIVE contact with an address is mailed: an invited
      contact has no account to sign in to, and a client with no contact at all
      is told to the CA in the answer ("nobody was emailed, because…") rather
      than being quietly skipped.
  (b) the STAFF assigned to the client — and the firm's Partners where nobody is
      assigned, so a message never lands on nobody — get an in-app notification
      and a mail when the client posts a message.
  (c) a FIRM-WIDE unread count, so staff do not have to open each client's tab to
      find out who has written.

WHAT IS DELIBERATELY NOT HERE

  * No message BODY travels by mail, in either direction. A message is the
    client's own business, mail is not a secure channel, and the words are one
    sign-in away.
  * No "client uploaded a document" notice, because a client CANNOT upload: the
    portal's upload is deliberately not built (routers/portal_data.
    portal_document_requests says why). The notice belongs to that door when it
    exists; writing it now would be a branch nothing reaches.
  * No client-side preference. A client has no screen for one and a request a
    person asked for is not something to default off.

SERVICE ROLE, EVERYWHERE, with the firm filter on every query. Request (b) runs
under a portal CLIENT's own JWT, which has no `users` row — so under it the
assignment table, `users`, `clients` and `notifications` all read as empty or
refuse the write, and the notice would silently go to nobody.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from core.db_paging import fetch_all
from core.ist_clock import ist_today
from core.urls import portal_login_url
from domain import practice_notices as rules
from services import email_service, practice_mail_service as mail
from services.practice_mail_service import Ref
from core import db_provider

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.portal_notice")

_EXCERPT = 140


_db = db_provider.service_db


# ── (a) the client's own contacts ────────────────────────────────────────────

def _active_contacts(firm_id: str, client_id: str) -> list[dict]:
    """Portal contacts who can actually SIGN IN and have somewhere to be mailed."""
    from services import portal_access_service
    try:
        rows = portal_access_service.list_contacts(firm_id, client_id, db=None if _USE_MOCK else _db())
    except Exception:                                           # noqa: BLE001
        _logger.warning("caflow.portal_notice: could not list contacts for client %s",
                        client_id, exc_info=True)
        return []
    seen: set[str] = set()
    out = []
    for c in rows:
        email = str(c.get("email") or "").strip()
        if c.get("status") != "active" or not email or email.lower() in seen:
            continue
        seen.add(email.lower())
        out.append({"email": email, "name": c.get("name")})
    return out


def _notify_contacts(firm_id: str, client_id: str, event_type: str, ref: Ref, sender) -> dict:
    """Mail every active contact; return what happened, for the CA to be told.

    `sender(contact, practice_name, reply_to)` returns whether the provider took
    the mail. The answer carries a REASON when nobody was mailed, because "the
    request was created" and "the client was told" are two facts and the CA is
    entitled to the second.
    """
    contacts = _active_contacts(firm_id, client_id)
    if not mail.mail_enabled():
        # The switch is the reason, whether or not there is anyone to mail: it
        # is the fact that does not change when a contact is invited, and the
        # sentence below would send the CA to invite one for nothing.
        return {"contacts": len(contacts), "emailed": 0,
                "reason": "Email notices are switched off for this deployment, so nobody was "
                          "emailed. The request is saved and visible on the client's portal."}
    if not contacts:
        return {"contacts": 0, "emailed": 0,
                "reason": "The client has no active portal contact, so nobody was emailed. "
                          "Invite one from the client's portal contacts."}
    practice_name, practice_email = mail.practice_sender(firm_id)
    firm_name = practice_name or "Your Chartered Accountant"
    emailed = 0
    for contact in contacts:
        status = mail.deliver(
            firm_id, event_type, contact, [ref],
            lambda _r, c=contact: sender(c, firm_name, practice_name, practice_email),
            day=ist_today(), kind="client_contact")
        if status in ("sent", "queued"):
            emailed += 1
    reason = None
    if emailed == 0:
        reason = ("The email could not be delivered right now. The request is saved and "
                  "visible on the client's portal.")
    return {"contacts": len(contacts), "emailed": emailed, "reason": reason}


def document_requested(firm_id: str, client_id: str, request: dict) -> dict:
    """Mail the client's portal contacts about a new document request."""
    try:
        def send(contact, firm_name, practice_name, practice_email) -> bool:
            return email_service.send_document_request_notice(
                contact["email"], contact.get("name") or "", firm_name,
                request.get("title") or "A document", bool(request.get("is_urgent")),
                mail.pretty_date(request["due_date"]) if request.get("due_date") else None,
                portal_login_url(), sender_name=practice_name, reply_to=practice_email)
        return _notify_contacts(firm_id, client_id, "document_request_notice",
                                Ref("document_request", str(request.get("id"))), send)
    except Exception:                                           # noqa: BLE001
        _logger.warning("caflow.portal_notice: document-request notice failed", exc_info=True)
        return {"contacts": 0, "emailed": 0, "reason": "The client could not be notified right now."}


def ca_message_posted(firm_id: str, client_id: str) -> dict:
    """Mail the client's portal contacts that their accountant wrote to them.

    Once per contact per DAY: a CA sending five messages in an afternoon is one
    thing to read. The `Ref` is the client, not the message, for that reason.
    """
    try:
        def send(contact, firm_name, practice_name, practice_email) -> bool:
            return email_service.send_portal_message_notice(
                contact["email"], contact.get("name") or "", firm_name,
                portal_login_url(), sender_name=practice_name, reply_to=practice_email)
        return _notify_contacts(firm_id, client_id, "portal_message_notice",
                                Ref("client", str(client_id)), send)
    except Exception:                                           # noqa: BLE001
        _logger.warning("caflow.portal_notice: message notice failed", exc_info=True)
        return {"contacts": 0, "emailed": 0, "reason": "The client could not be notified right now."}


# ── (b) the staff ────────────────────────────────────────────────────────────

def _create_notification(row: dict) -> None:
    """In-app notification as the SERVICE role: a portal client's own JWT cannot
    write another user's notification (migration 084's recipient scope)."""
    from repositories.notifications_repository import notifications_repo
    notifications_repo.create(row, db=None if _USE_MOCK else _db())


def client_wrote(firm_id: str, client_id: str, message: dict,
                 writer_name: Optional[str] = None) -> dict:
    """The client posted a message: an in-app notification to each assigned
    member of staff, and a mail to each who wants one. Never raises — the
    client's message is already saved and must not fail over a notice."""
    result = {"notified": 0, "emailed": 0}
    try:
        client_name = mail.client_names(firm_id, [client_id]).get(str(client_id), "A client")
        people = mail.staff_for_client(firm_id, client_id)
        body = " ".join(str(message.get("body") or "").split())
        excerpt = body if len(body) <= _EXCERPT else body[:_EXCERPT - 1].rstrip() + "…"
        link = f"/client-portal?client={client_id}&tab=messages"
        for person in people:
            try:
                _create_notification({
                    "firm_id": firm_id,
                    "user_id": person["id"],
                    "client_id": client_id,
                    "type": rules.PORTAL_MESSAGE_NOTIFICATION_TYPE,
                    "title": f"New portal message from {client_name}",
                    "body": f"{writer_name or client_name}: {excerpt}" if excerpt
                            else f"{writer_name or client_name} sent a message.",
                    "severity": "medium",
                    "action_url": link,
                    "metadata": {"client_id": str(client_id),
                                 "message_id": str(message.get("id") or "")},
                    "is_read": False,
                    "is_archived": False,
                })
                result["notified"] += 1
            except Exception:                                   # noqa: BLE001
                _logger.warning("caflow.portal_notice: notification for user %s failed",
                                person.get("id"), exc_info=True)
            status = mail.deliver(
                firm_id, "portal_message", person, [Ref("client", str(client_id))],
                lambda _r, p=person: email_service.send_client_wrote_to_staff(
                    str(p.get("email")), p.get("full_name") or "", client_name,
                    mail.app_link(link)),
                day=ist_today())
            if status in ("sent", "queued"):
                result["emailed"] += 1
    except Exception:                                           # noqa: BLE001
        _logger.warning("caflow.portal_notice: client_wrote failed", exc_info=True)
    return result


# ── (c) the firm-wide unread count ───────────────────────────────────────────

def unread_summary(firm_id: str, allowed_client_ids: Optional[set]) -> dict:
    """How many client messages nobody at the firm has opened, per client.

    `allowed_client_ids` is `core.authz.effective_client_ids`: None means every
    client in the firm and an EMPTY set means none, never "no filter". The read
    is proportional to the unread messages — the partial index migration 450
    added — and not to the thread history.
    """
    if _USE_MOCK:
        import domain.portal_service as svc
        rows = [m for m in svc._MOCK_MESSAGES
                if m.get("firm_id") == firm_id and not m.get("from_ca")
                and not m.get("is_read")]
    else:
        rows = fetch_all(
            lambda: _db().table("portal_messages")
            .select("id, client_id, created_at")
            .eq("firm_id", firm_id).eq("sender_type", "client").eq("is_read", False),
            label="portal_notice_service.unread")
    if allowed_client_ids is not None:
        rows = [r for r in rows if str(r.get("client_id")) in allowed_client_ids]
    per: dict[str, dict] = {}
    for r in rows:
        slot = per.setdefault(str(r["client_id"]), {"client_id": str(r["client_id"]),
                                                    "unread": 0, "latest_at": None})
        slot["unread"] += 1
        created = str(r.get("created_at") or "")
        if created and (slot["latest_at"] is None or created > slot["latest_at"]):
            slot["latest_at"] = created
    names = mail.client_names(firm_id, per.keys())
    clients = sorted(
        ({**s, "client_name": names.get(s["client_id"])} for s in per.values()),
        key=lambda s: s["latest_at"] or "", reverse=True)
    return {"unread_total": sum(s["unread"] for s in clients), "clients": clients}


def mark_thread_read(firm_id: str, client_id: str) -> int:
    """The firm has opened this client's thread: every message the CLIENT sent
    is read. Messages the firm sent are the client's to read and are untouched.
    Returns how many were marked."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    if _USE_MOCK:
        import domain.portal_service as svc
        n = 0
        for m in svc._MOCK_MESSAGES:
            if (m.get("firm_id") == firm_id and m.get("client_id") == client_id
                    and not m.get("from_ca") and not m.get("is_read")):
                m["is_read"] = True
                m["read_at"] = now
                n += 1
        return n
    res = (_db().table("portal_messages")
           .update({"is_read": True, "read_at": now})
           .eq("firm_id", firm_id).eq("client_id", client_id)
           .eq("sender_type", "client").eq("is_read", False).execute())
    return len(res.data or [])
