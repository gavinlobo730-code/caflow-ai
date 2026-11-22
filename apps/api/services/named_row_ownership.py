"""A document may only name a row of its own client (POST-A-338).

THE GAP
    Several documents carry the id of another row in their body: a Bill of Entry names a vendor and a purchase bill, a fixed asset
    names the bill it was bought on, a delivery challan names an order, a customer, a vendor and an invoice, a purchase order or
    a sales order names the party. The API reads and writes through the privileged client by firm and id, and the foreign key on
    each of those columns is not client-aware, so an id that belongs to a SIBLING client of the same firm was accepted and stored.
    The worst case was a Bill of Entry of client A naming client B's purchase bill: the carry-over then attached A's customs duty
    to B's bill, and so to B's stock cost.

WHAT THIS DOES
    One read per named row, under the firm AND the client, BEFORE anything is written. A row that is not there (another client's,
    another firm's, deleted or invented) is a 404 in the same words a missing row gets, so the answer does not say which it was.
    It asks nothing when no id is named or when there is no database (mock mode).

A MEMBER OF THE FIRM IS THE SAME QUESTION ONE LEVEL UP (POST-A-361, part 2)
    A request that names a person (an assignee, a reviewer, a capacity row's person) names a row of `users`, which belongs to the FIRM
    and not to a client. Where the column has a foreign key to `users` and a `firm_id` on its own table the database refuses a stranger
    since migration 566, in a failure the person cannot read; where the column is a bare uuid (`task_recurring_configs.assignee_id`,
    `fee_engagements.assigned_to`) nothing refused it at all. `member_is_the_firms` asks before anything is written and answers a
    stranger, a deleted member and an invented id in the same words. **ONE COLUMN IS KEYED TO THE OTHER ID.** Every person column above holds a
    `users.id`, except `leads.assigned_to`, whose foreign key is to `auth.users(id)` (migration 059; the production snapshot of 13-09-2026
    agrees): the value it can hold is a member's AUTH id, and a `users.id` there is refused by the database as a 500. A lead's assignee is asked
    with `member_auth_id_is_the_firms`, which reads `users.auth_user_id`; asking the first function there made every value unusable (an auth
    id answered 404, a `users.id` passed the check and failed the key).

WHAT IT DOES NOT DO
    It is the API's answer only. A writer that does not come through these routes (an import that builds rows itself, a SQL
    function) is not asked. Each table is spelled out in its own function and not read through a variable, because the column
    check in `tests/test_backend_columns_exist_pg.py` resolves no name and a read it cannot see is a read it cannot check.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from core.db_provider import privileged_for


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"That {what} was not found.")


def _named(row_id) -> Optional[str]:
    text = str(row_id).strip() if row_id is not None else ""
    return text or None


def _find(query) -> list:
    """The rows of one ownership lookup. A string that is not an id of the column's type (a UUID) makes PostgREST answer with a type error
    (SQLSTATE 22P02), which the route used to turn into a 500; a row that could never exist is a row that is not there, so it answers
    the way a missing row does. The check is made on the database's own answer and not in the helper's first line because the test
    suites use readable ids that are not UUIDs, and the production column's type is the only authority on what an id is."""
    try:
        return query.execute().data or []
    except Exception as exc:
        if _is_a_malformed_id(exc):
            return []
        raise


def rows_of(query) -> list:
    """The rows of a read that names a row by id, or `[]` when the id is not an id at all (see `_find`). For a caller that needs the ROW and not only the answer
    (`bank_payee_service` wants the party's name), so a malformed id is a missing row there too and not a 500."""
    return _find(query)


def _is_a_malformed_id(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or (exc.args[0].get("code") if exc.args and isinstance(exc.args[0], dict) else None)
    return str(code) == "22P02" or "invalid input syntax for type uuid" in str(exc)


def member_is_the_firms(db, firm_id: str, member_id) -> None:
    """404 "That team member was not found." unless `member_id` is a `users.id` of this firm that has not been deleted. Nothing named, nothing asked.

    Membership, not activity: a suspended member can still be named, as the task door has always allowed, because whether somebody may be
    assigned work is a staffing decision and not a tenancy one. A DELETED member (`users.deleted_at`) is not named: the task door's own
    lookup (`user_repo.find_by_id`) leaves them out, and a person who has been removed is not somebody to hand work to. The read is made with
    the privileged client and filtered by the id AND the firm, the same reasoning as the bank account below: the filter is the assertion."""
    named = _named(member_id)
    if db is None or named is None:
        return
    rows = _find(privileged_for(db).table("users").select("id").eq("id", named).eq("firm_id", firm_id)
                 .is_("deleted_at", None).limit(1))
    if not rows:
        raise _not_found("team member")


#: What a door says when the person it names cannot open the client the row belongs to (POST-A-451). The person exists and is in
#: the firm, so this is not the 404 of a stranger: it is a refusal the caller can act on, and only a Partner can act on it.
NOT_ASSIGNED_TO_THE_CLIENT = (
    "That team member is not assigned to this client, so they could not open the work or read what they would be sent "
    "about it. A Partner can assign them to the client under Team, Assignments, and then they can be named here."
)


def member_reaches_client(db, firm_id: str, member_id, client_id) -> None:
    """The question after `member_is_the_firms`, for a row that belongs to a client (POST-A-451): 422 unless the member named can
    open that client (a Partner, or a member assigned to it). An obligation's preparer, reviewer and approver, a task's assignee
    and an engagement's people are told about the client by name in the nightly mails, and they do the work inside it; naming
    somebody the firm's own assignments keep out of the client handed them both a notice they should not read and work they could
    not open. Asks nothing when no person or no client is named, or when there is no database (mock mode), like the others here.
    A deleted member, a stranger or an invented id is the 404 `member_is_the_firms` gives, in its words."""
    from core.authz import member_reaches_client as _reaches   # core.authz imports the database provider; kept out of import time
    named = _named(member_id)
    if db is None or named is None or not _named(client_id):
        return
    rows = _find(privileged_for(db).table("users").select("id, role").eq("id", named).eq("firm_id", firm_id)
                 .is_("deleted_at", None).limit(1))
    if not rows:
        raise _not_found("team member")
    if not _reaches({"id": named, "role": rows[0].get("role")}, str(client_id), firm_id):
        raise HTTPException(status_code=422, detail=NOT_ASSIGNED_TO_THE_CLIENT)


def member_auth_id_is_the_firms(db, firm_id: str, auth_user_id) -> None:
    """The same question for a column keyed to `auth.users(id)` (a lead's assignee): 404 unless `auth_user_id` is the auth id of a member of this
    firm who has not been deleted. Nothing named, nothing asked. A `users.id` is NOT an answer here: it is not an auth id, and the database
    would refuse it."""
    named = _named(auth_user_id)
    if db is None or named is None:
        return
    rows = _find(privileged_for(db).table("users").select("id").eq("auth_user_id", named).eq("firm_id", firm_id)
                 .is_("deleted_at", None).limit(1))
    if not rows:
        raise _not_found("team member")


def vendor_is_the_clients(db, firm_id: str, client_id: str, vendor_id) -> None:
    """404 "That vendor was not found." unless `vendor_id` is a vendor of this firm and this client. Nothing named, nothing asked."""
    named = _named(vendor_id)
    if db is None or named is None:
        return
    rows = _find(db.table("vendors").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("vendor")


def customer_is_the_clients(db, firm_id: str, client_id: str, customer_id) -> None:
    """404 "That customer was not found." unless `customer_id` is a customer of this firm and this client."""
    named = _named(customer_id)
    if db is None or named is None:
        return
    rows = _find(db.table("customers").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("customer")


def purchase_bill_is_the_clients(db, firm_id: str, client_id: str, bill_id) -> None:
    """404 "That bill was not found." (the words `purchase_cycle_service.bill_of_client` uses) unless the bill is this client's."""
    named = _named(bill_id)
    if db is None or named is None:
        return
    rows = _find(db.table("purchase_bills").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("bill")


def bank_account_is_the_clients(db, firm_id: str, client_id: str, bank_account_id) -> None:
    """404 "That bank account was not found." unless the bank account is this client's."""
    named = _named(bank_account_id)
    if db is None or named is None:
        return
    # A bank table is read with the privileged client, after the caller's firm and client are asserted (POST-A-339); the filter below
    # is that assertion, so the account has to be this firm's and this client's whoever is asking.
    rows = _find(privileged_for(db).table("bank_accounts").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("bank account")


def sales_invoice_is_the_clients(db, firm_id: str, client_id: str, invoice_id) -> None:
    """404 "That invoice was not found." unless the sales invoice is this client's."""
    named = _named(invoice_id)
    if db is None or named is None:
        return
    rows = _find(db.table("client_sales_invoices").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("invoice")


#: What a note's route answers when the document it names belongs to ANOTHER customer or supplier of the same client (POST-A-553).
ANOTHER_CUSTOMERS_INVOICE = ("That invoice was issued to another customer. A credit or debit note is raised against an invoice of the "
                             "customer it is for: choose one of this customer's invoices, or none.")
ANOTHER_SUPPLIERS_BILL = ("That bill is from another supplier. A debit or credit note is raised against a bill of the supplier it is for: "
                          "choose one of this supplier's bills, or none.")


def _link_left_behind(data: dict, stored: Optional[dict], party_key: str, link_key: str, cleared: bool) -> Optional[str]:
    """The id of the document a DRAFT note still points at after its party was changed by a request that names no document, or None.

    A document belongs to one party, so a draft whose party changes cannot keep the old party's document. The screens empty the box
    and say so; a request that does not is answered here. Nothing is left behind when the note is not a draft (its party cannot
    change), when the request names a document or clears it itself, or when the party sent is the party stored."""
    if stored is None or cleared or link_key in data or stored.get("status") != "draft":
        return None
    party = _named(data.get(party_key))
    if party is None or party == str(stored.get(party_key) or ""):
        return None
    return _named(stored.get(link_key))


def note_invoice_is_its_customers(db, firm_id: str, client_id: str, data: dict, stored: Optional[dict] = None, *, cleared: bool = False) -> None:
    """A sales credit or debit note is raised against an invoice of ITS OWN customer (POST-A-553).

    `sales_invoice_is_the_clients` asked only whose CLIENT the invoice is, so a note for customer A could name customer B's invoice
    of the same client. Issuing it allocates the note against that invoice: B's invoice has less open because of A's note, and both
    statements, the ageing and the note tables of GSTR-1 carry a note against a recipient it was not issued to (CGST s.34 speaks of
    the recipient of the original supply). The screens offer only the chosen customer's invoices; this is the API's answer.

      * the request NAMES an invoice (a create, or an edit that sends one): 404 "That invoice was not found." unless it is this
        client's, as before, and 422 in one sentence unless it is the note's customer's (the customer in the request, else the one
        stored);
      * an edit of a DRAFT changes the customer and names no invoice: the stored link is the old customer's, so it is written as
        NULL with the same request (`data` is changed in place), unless that invoice is in fact the new customer's;
      * anything else asks nothing. `cleared` says the request itself takes the link away (`models.clearable.draft_only_clears`).

    One read, under the firm and the client. Nothing is asked in mock mode (no database)."""
    if db is None:
        return
    named = _named(data.get("sales_invoice_id"))
    asked = named or _link_left_behind(data, stored, "customer_id", "sales_invoice_id", cleared)
    if asked is None:
        return
    party = _named(data.get("customer_id")) or _named((stored or {}).get("customer_id"))
    rows = _find(db.table("client_sales_invoices").select("id, customer_id").eq("id", asked)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    theirs = bool(rows) and (party is None or str(rows[0].get("customer_id") or "") == party)
    if named is None:
        if not theirs:
            data["sales_invoice_id"] = None
        return
    if not rows:
        raise _not_found("invoice")
    if not theirs:
        raise HTTPException(status_code=422, detail=ANOTHER_CUSTOMERS_INVOICE)


def note_bill_is_its_suppliers(db, firm_id: str, client_id: str, data: dict, stored: Optional[dict] = None, *, cleared: bool = False) -> None:
    """A purchase debit or credit note is raised against a bill of ITS OWN supplier: `note_invoice_is_its_customers`, on the purchase
    side, in the same three cases and the same order (POST-A-553)."""
    if db is None:
        return
    named = _named(data.get("purchase_bill_id"))
    asked = named or _link_left_behind(data, stored, "vendor_id", "purchase_bill_id", cleared)
    if asked is None:
        return
    party = _named(data.get("vendor_id")) or _named((stored or {}).get("vendor_id"))
    rows = _find(db.table("purchase_bills").select("id, vendor_id").eq("id", asked)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    theirs = bool(rows) and (party is None or str(rows[0].get("vendor_id") or "") == party)
    if named is None:
        if not theirs:
            data["purchase_bill_id"] = None
        return
    if not rows:
        raise _not_found("bill")
    if not theirs:
        raise HTTPException(status_code=422, detail=ANOTHER_SUPPLIERS_BILL)


def client_document_is_the_clients(db, firm_id: str, client_id: str, document_id) -> None:
    """404 "That document was not found." unless the stored file (`client_documents`) is this client's."""
    named = _named(document_id)
    if db is None or named is None:
        return
    # The document tables are read with the privileged client, after the caller's firm and client are asserted (POST-A-339, the same
    # reasoning as the bank account above): the filter is the assertion.
    rows = _find(privileged_for(db).table("client_documents").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("document")


def journal_entry_is_the_clients(db, firm_id: str, client_id: str, journal_entry_id) -> None:
    """404 "That journal entry was not found." unless the ledger entry is this client's."""
    named = _named(journal_entry_id)
    if db is None or named is None:
        return
    rows = _find(db.table("journal_entries").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("journal entry")


def mca_company_is_the_clients(db, firm_id: str, client_id: str, company_id) -> None:
    """404 "That company was not found." unless the MCA company (`mca_companies`) is this client's.

    A director and a filing each name a company by a plain foreign key, which any company in the database satisfies: a director of client
    A stored under client B's company then shows in B's company view, which lists directors by company and firm (POST-A-353)."""
    named = _named(company_id)
    if db is None or named is None:
        return
    rows = _find(db.table("mca_companies").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("company")


def task_is_the_clients(db, firm_id: str, client_id: str, task_id) -> None:
    """404 "That task was not found." unless the task (not deleted) is this client's."""
    named = _named(task_id)
    if db is None or named is None:
        return
    rows = _find(db.table("tasks").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).is_("deleted_at", "null").limit(1))
    if not rows:
        raise _not_found("task")


def task_of_the_firm(db, firm_id: str, task_id) -> Optional[dict]:
    """The task (`id`, `client_id`) when it is this firm's and not deleted, else 404 "That task was not found."; None when nothing is named or
    there is no database. For a request that names a task and no client: the CALLER's reach of the task's own client is then the question
    (see `routers/time_tracking._the_task_is_the_callers`)."""
    named = _named(task_id)
    if db is None or named is None:
        return None
    rows = _find(db.table("tasks").select("id, client_id").eq("id", named).eq("firm_id", firm_id).is_("deleted_at", "null").limit(1))
    if not rows:
        raise _not_found("task")
    return rows[0]


def lead_is_the_firms(db, firm_id: str, lead_id) -> None:
    """404 "That lead was not found." unless the lead is this firm's. A lead belongs to the FIRM (it has no client yet), so the question is
    asked of the firm alone; the foreign key on a proposal's `lead_id` is satisfied by any firm's lead."""
    named = _named(lead_id)
    if db is None or named is None:
        return
    rows = _find(db.table("leads").select("id").eq("id", named).eq("firm_id", firm_id).limit(1))
    if not rows:
        raise _not_found("lead")


def year_end_engagement_is_the_clients(db, firm_id: str, client_id: str, engagement_id) -> None:
    """404 "That year-end engagement was not found." unless the year-end engagement is this client's."""
    named = _named(engagement_id)
    if db is None or named is None:
        return
    rows = _find(db.table("year_end_engagements").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("year-end engagement")


def payroll_run_is_the_clients(db, firm_id: str, client_id: str, run_id) -> None:
    """404 "That payroll run was not found." unless the payroll run is this client's."""
    named = _named(run_id)
    if db is None or named is None:
        return
    # A payroll table is read with the privileged client, after the caller's firm and client are asserted (POST-A-339); the filter below is
    # that assertion, so the run has to be this firm's and this client's whoever is asking.
    rows = _find(privileged_for(db).table("payroll_runs").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("payroll run")


def itr_filing_is_the_clients(db, firm_id: str, client_id: str, filing_id) -> None:
    """404 "That filing was not found." unless the income-tax filing (`itr_filings`) is this client's. A revised or updated return copies
    the earlier return's acknowledgement number and filing date from the filing it names, so a sibling client's filing would have had its
    receipt copied into this client's return (POST-A-353)."""
    named = _named(filing_id)
    if db is None or named is None:
        return
    rows = _find(db.table("itr_filings").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", client_id).limit(1))
    if not rows:
        raise _not_found("filing")


def service_is_the_practices(db, firm_id: str, service_id) -> None:
    """404 "That service was not found." unless the service (`service_catalogue`) is one of the practice's own, which is the firm's
    INTERNAL client's (a retainer is billed out of the practice's catalogue, not out of the client being billed)."""
    named = _named(service_id)
    if db is None or named is None:
        return
    from services.internal_client_service import get_internal_client_id
    internal = get_internal_client_id(firm_id)
    if not internal:
        # No practice client yet, so there is no catalogue to name a service of: the sentence `billing_service.generate_for_schedule` gives.
        raise HTTPException(status_code=409, detail="Provision the firm's practice (internal client) before billing.")
    rows = _find(db.table("service_catalogue").select("id").eq("id", named)
            .eq("firm_id", firm_id).eq("client_id", internal).limit(1))
    if not rows:
        raise _not_found("service")

