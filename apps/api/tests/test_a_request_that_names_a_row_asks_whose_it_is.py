"""A request that names a row of a client-owned table asks whose it is, found from the request models and not from a list (POST-A-350).

WHAT WAS WRONG
    POST-A-338 closed the doors it knew of, and the independent review of that change found five it had not named: a hand-written list of
    doors ends that way. `test_a_document_names_only_rows_of_its_own_client.py` keeps the doors it lists honest and cannot find a new one.
    Run over the request models this rule found eleven more, and each was a real hole: a recurring invoice or purchase-bill template
    naming another client's customer or vendor (every run then invoices or bills that party under the wrong client), an e-way bill naming
    another client's invoice (it is listed on that invoice's own hub), a receipt or a vendor payment naming another client's bank account
    (the posting reads the account by firm alone and the ledger trigger refused it later, as a 500), and the linked bill or invoice of the
    four note kinds, which was stored as sent and refused only when the note was issued.

WHAT IS ASSERTED
    * THE RULE. Every POST, PUT, PATCH or DELETE route takes a request model with a field that names a row of a client-owned table
      (`*vendor_id`, `*customer_id`, `*purchase_bill_id`, `*sales_invoice_id`, `*bank_account_id`, `*order_id`, `*quotation_id`). For each
      such field the route, or something it calls up to five calls down (imports and methods followed), must ask whose that row is: a
      `*_is_the_clients` function, the purchase and sales cycles' own `order_of_client` / `row_of_client`, the bank reconciliation's
      `_validate_bank_account`, a read of the named table filtered by `client_id`, or a read that is compared with the client's id. A door
      that does none is listed below with the reason it is safe, and that list only shrinks: an entry whose door has since been checked is
      a failure that says to delete it.
    * WHAT THE SECOND READING ADDED (POST-A-353). The names are wider (`original_invoice_id`, `linked_bill_id` and a bare `invoice_id` or
      `bill_id` are rows of the same tables), a model that CARRIES another model (a receipt's allocations, a payment's bills) names that
      model's rows too, a QUERY or FORM parameter that names a row counts like a body field (a path parameter does not: it is the row the
      route is about), and a body taken as a plain dict is its own kind, `dict_body`, because the AST cannot know its keys, so every such
      door is on the reviewed list with what the dict carries. The first run of it found one real gap, the statement inspector, which
      looked a saved column layout up by a bank account id and the firm alone: another client's account answered with that client's
      layout. It asks whose the account is now, before it reads the file.
    * THE SECOND FAMILY (POST-A-353, the stored-file half). Seven more kinds: a stored file (`*document_id`), a ledger entry
      (`*journal_entry_id`), a payroll employee, a vendor payment and the three stock places (godown, batch, cost centre). The run found
      three real doors that stored another client's row under this one: the 26AS upload named any client's stored file, and the ITR
      workspace's deduction claim and disallowance named any client's evidence file (the disallowance also any client's ledger entry).
      The payroll, stock and ledger doors the survey listed were already asked, by helpers the rule now knows by name.
    * THE THIRD FAMILY (POST-A-361, part 2): a MEMBER of the firm. A request that names a person (`assigned_to`, `assignee_id`, `reviewer_id`,
      `approver_id`, `preparer_id`, `partner_id`, `user_id`) names a row of `users`, which is the FIRM's and not a client's. Nine doors
      took the id as typed: the recurring-task configuration (a bare uuid column, so nothing anywhere refused a stranger), a fee engagement's
      assignee (also bare) with its reviewer and partner, a lead's assignee, a compliance obligation's preparer, reviewer and approver, and
      the recipient of a notification (a stranger of another firm would have been sent this firm's title, text and link). Where the column
      is keyed, migration 566 refuses a member of another firm, in a failure nobody can read; the door now says it in a sentence, before
      anything is written, and answers a stranger, a deleted member and an invented id in the same words. This family is asked by its own
      scan and not by the call graph's reach: the graph guesses a callee by its bare name, and an audit write ends in the MFA reset's
      lookup of a user, so "something below it looks a user up" is true of nearly every route. A lookup counts only when it is made ON the
      value the request carried (its text names the field, or the parameter the value was handed on as), up to three calls down.
    * ONE FIELD THE SCAN FOUND IS DELETED AND NOT LISTED. `RenewalIn.assigned_to` was accepted by `POST /api/lifecycle/renewals` and never
      stored (the table has no such column and the handler's row names none): a field nothing stores is removed, so the door asks about
      nothing instead of being put on the reviewed list with an apology.
    * TWO MODELS OF ONE NAME ARE NOT ONE MODEL. `routers/engagements.py` and `routers/engagement_letters.py` each define an
      `EngagementUpdate`; the scan matched an annotation by the bare class name and gave the letters door the fee engagement's assignee
      fields. Models are keyed by (module, class) now and a route sees the one its own module defines or imports.
    * THE SCAN IS NOT BLIND. It finds more than forty doors and all seven kinds, it flags a synthetic route that writes without asking, it
      accepts one that asks in the route and one that asks two calls down, and it flags one whose check sits in a function nothing calls.
    * EACH DOOR THE RULE FOUND. A sibling client's row named under this client is answered in the words a missing row gets and nothing is
      written, and the same request with the client's own row is not stopped by the question (the control: the refusal is the client).
"""
from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.compliance_ops as compliance_ops_router
import routers.credit_notes as credit_notes_router
import routers.debit_notes as debit_notes_router
import routers.engagements as engagements_router
import routers.eway_bill as eway_router
import routers.form_26as as form26as_router
import routers.itr_workspace as itr_router
import routers.lifecycle as lifecycle_router
import routers.notifications as notifications_router
import routers.purchase_credit_notes as pcn_router
import routers.purchase_payments as pp_router
import routers.receipts as receipts_router
import routers.recurring_invoices as ri_router
import routers.task_recurring as task_recurring_router
import routers.recurring_purchase_bills as rpb_router
import routers.sales_debit_notes as sdn_router
import routers.sales_invoices as sales_router
import services.recurring_invoice_service as ri_service
import services.recurring_purchase_bill_service as rpb_service
from core.auth import get_current_user
from tests._call_graph import CallGraph, called_name, chain_of
from tests.e2e_harness import FakeDB, wire_e2e

API = Path(__file__).resolve().parent.parent

# field name -> (kind, functions that ask, tables whose client-filtered read counts)
KINDS: dict[str, tuple[re.Pattern, set[str], set[str]]] = {
    "vendor": (re.compile(r"(^|_)vendor_id$"), {"vendor_is_the_clients"}, {"vendors"}),
    "customer": (re.compile(r"(^|_)customer_id$"), {"customer_is_the_clients"}, {"customers"}),
    "bill": (re.compile(r"(^|_)(purchase_)?bill_id$"), {"purchase_bill_is_the_clients"}, {"purchase_bills"}),
    "invoice": (re.compile(r"(^|_)(sales_)?invoice_id$"), {"sales_invoice_is_the_clients"}, {"client_sales_invoices"}),
    "bank": (re.compile(r"(^|_)bank_account_id$"), {"bank_account_is_the_clients", "_validate_bank_account"}, {"bank_accounts"}),
    "order": (re.compile(r"(^|_)order_id$"), {"order_of_client", "row_of_client"}, {"purchase_orders", "sales_orders"}),
    "quotation": (re.compile(r"(^|_)quotation_id$"), {"row_of_client"}, {"sales_quotations"}),
    # THE SECOND FAMILY (POST-A-353): a stored file, a ledger entry, a payroll employee and the three stock places.
    "document": (re.compile(r"(^|_)document_id$"), {"client_document_is_the_clients", "_assert_document_in_firm"}, {"client_documents"}),
    "journal": (re.compile(r"(^|_)journal_entry_id$"), {"journal_entry_is_the_clients"}, {"journal_entries"}),
    "employee": (re.compile(r"(^|_)employee_id$"), {"_employee_of_client"}, {"payroll_employees"}),
    "vendor_payment": (re.compile(r"(^|_)purchase_payment_id$"), set(), {"purchase_payments"}),
    "godown": (re.compile(r"(^|_)godown_id$"), set(), {"godowns"}),
    "batch": (re.compile(r"(^|_)batch_id$"), set(), {"inventory_batches"}),
    "cost_centre": (re.compile(r"(^|_)cost_centre_id$"), set(), {"cost_centres"}),
    # THE THIRD FAMILY (POST-A-361, part 2): a MEMBER of the firm named by a request (an assignee, a reviewer, a capacity row's person).
    # A member is the FIRM's and not a client's, and a call graph that guesses a callee by its bare name reaches a user lookup from almost
    # any route (an audit write ends in the MFA reset's lookup), so this kind is not asked through `_own_kinds`: `_Tree.asks_member`
    # needs the lookup to be made on the value the request carried.
    "member": (re.compile(r"(^|_)(assigned_to|assignee_id|assignee|reviewer_id|approver_id|preparer_id|partner_id|user_id)$"), set(), set()),
}
MEMBER_ASKING_FUNCTIONS = {"member_is_the_firms", "member_auth_id_is_the_firms"}
# A call that looks one member up under the firm although it is not the function above: the user repository's own lookup (scoped by firm).
MEMBER_ASKING_CALLS = {("user_repo", "find_by_id")}
MEMBER_DEPTH = 3
DICT_BODY = re.compile(r"(Optional\[)?(dict|Dict)(\[[^\]]*\])?\]?")
SCAN_DIRS = ("services", "domain", "repositories", "routers", "models", "core")      # not jobs: nothing a route calls lives there
WRITING_VERBS = ("post", "put", "patch", "delete")
DEPTH = 5

# A door the rule flags that is safe, and why. Shrink-only: each key must still be flagged.
REVIEWED: dict[tuple[str, str, str], str] = {
    ("assignments", "remove_assignment", "member"):
        "a DELETE: it stores no person. The row it removes is matched on the firm, the client AND the person together, so a `user_id` that is "
        "another firm's, or invented, matches nothing and the answer is 'Assignment not found'. (Counted as asked until the first review of the "
        "member scan found that `.execute()` was resolved to the MFA reset's function, whose own lookup of a `user_id` it did not make.)",
    ("purchase_bills", "probe_near_duplicates", "vendor"):
        "a read-only probe (POST only because an invoice number does not belong in a URL): it lists the bills of THIS client that carry the "
        "vendor id, so a vendor of another client matches no bill of this one and the answer is the empty list a missing vendor gets.",
    # THE SHAPES THE FIRST RULE COULD NOT SEE (POST-A-353). A body taken as a plain dict is the kind "dict_body": the AST cannot know its
    # keys, so every such door is listed with what the dict carries, and a new one is a red test.
    ("fx_revaluation", "preview_revaluation", "dict_body"):
        "the payload is a period end and a map of currency to closing rate and names no row of any table; the client is a query "
        "parameter that the route asserts for the caller with assert_client_access before it reads anything. It writes nothing.",
    ("fx_revaluation", "run_revaluation", "dict_body"):
        "the payload is a period end and a map of currency to closing rate and names no row of any table; the client is a query "
        "parameter that the route asserts for the caller with assert_client_access before the revaluation is planned or posted.",
    ("memory_intelligence", "update_anomaly_status", "dict_body"):
        "the body carries a status word and nothing else; the row it acts on is the anomaly in the path, and the route reads that "
        "anomaly and asks the caller's access to its client (_assert_anomaly_scope) before the update, answering a missing one's words.",
    ("workflow_builder", "manually_trigger", "dict_body"):
        "the payload's client_id is asserted for the caller before the run starts and the run is created for that client; the other keys "
        "are the trigger's data, compared with the template's conditions and stored on the run. The one step that reads a client takes the "
        "instance's asserted client before the payload's, and checks it belongs to the firm.",
    # THE SECOND FAMILY (POST-A-353).
    ("banking", "remove_transaction_attachment", "document"):
        "the id only selects an entry to take out of the attachment list of THIS bank line (a comparison in domain/banking/attachments), and "
        "no row is written that names the document; adding an attachment, which does name one, asks the document under the line's client.",
    ("payroll", "put_leave_balance", "employee"):
        "the body names no client at all; the employee is resolved by the firm and the caller's assignment to the employee's OWN client is "
        "asked (_assert_employee_scope) before anything is read or written, a stranger answering in the words a missing employee gets.",
    # A NAMED ROW THE REQUEST CARRIES OUTSIDE THE BODY MODEL.
    ("payments", "create_payment_link", "invoice"):
        "the request names no client; the service reads the invoice by firm and asks can_access_client of the invoice's OWN client before "
        "anything is created, so an invoice of a client outside the caller's reach answers as a missing invoice.",
    ("purchase_bills", "preview_purchase_bill_tds", "bill"):
        "the id only drops one row from the list of THIS vendor's bills that the year's aggregate is summed over (a comparison of ids in "
        "services/vendor_tds), so a bill of another client matches nothing in it; the preview computes and writes nothing.",
}


# ── the scanner ────────────────────────────────────────────────────────────────────────────────────────────────────────────
class _Tree(CallGraph):
    """The shared call graph, plus the request models that carry a named field and what a function asks."""

    def __init__(self, root: Path):
        super().__init__(root, SCAN_DIRS)
        self.homes = self._model_homes()
        self.models = self._models_with_named_fields()

    def _model_homes(self) -> dict[str, set[str]]:
        """{class name: modules that define a class of that name}. Two routers define their own `EngagementUpdate`, and a scan that
        matches an annotation, and the fields of a class, by the bare name gave one router the other's fields."""
        homes: dict[str, set[str]] = {}
        for mod, tree in self.mods.items():
            if mod.startswith("models.") or mod.startswith("routers."):
                for c in ast.walk(tree):
                    if isinstance(c, ast.ClassDef):
                        homes.setdefault(c.name, set()).add(mod)
        return homes

    def model_is_visible_to(self, router_mod: str, model: tuple[str, str]) -> bool:
        """Is the class `model` = (defining module, name), as written in a route of `router_mod`, the class that name means there: the one
        the module defines, the only one of its name, or the one it imports by name."""
        home, name = model
        if home == router_mod or self.homes.get(name, set()) <= {home}:
            return True
        imported = self.imports.get(router_mod, {}).get(name)
        return bool(imported and imported[0] == "sym" and imported[1] == home)

    def _models_with_named_fields(self) -> dict[tuple[str, str], dict[str, set[str]]]:
        found: dict[tuple[str, str], dict[str, set[str]]] = {}
        annotated: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for mod, tree in self.mods.items():
            if not (mod.startswith("models.") or mod.startswith("routers.")):
                continue
            for c in ast.walk(tree):
                if isinstance(c, ast.ClassDef):
                    for n in c.body:
                        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                            annotated.setdefault((mod, c.name), []).append((n.target.id, ast.unparse(n.annotation)))
                            for kind, (rx, _, _) in KINDS.items():
                                if rx.search(n.target.id):
                                    found.setdefault((mod, c.name), {}).setdefault(kind, set()).add(n.target.id)
        # A model that CARRIES another model (a receipt's allocations, a payment's bills) names that model's rows too: the route
        # takes the outer model, so the scan has to read through it. Followed to a fixed point, so a list of lists is read.
        grew = True
        while grew:
            grew = False
            for outer, fields in annotated.items():
                for field, annotation in fields:
                    for inner, by_kind in list(found.items()):
                        if inner == outer or not re.search(rf"\b{inner[1]}\b", annotation) or not self.model_is_visible_to(outer[0], inner):
                            continue
                        for kind, names in by_kind.items():
                            have = found.setdefault(outer, {}).setdefault(kind, set())
                            for name in names:
                                if f"{field}.{name}" not in have:
                                    have.add(f"{field}.{name}")
                                    grew = True
        return found

    @staticmethod
    def _tables(fn) -> set[str]:
        return {c.args[0].value for c in ast.walk(fn)
                if isinstance(c, ast.Call) and called_name(c) == "table" and c.args and isinstance(c.args[0], ast.Constant)}

    @staticmethod
    def _compares_a_clients_id(fn) -> bool:
        for n in ast.walk(fn):
            if isinstance(n, ast.Compare):
                dumped = ast.dump(n)
                if "client_id" in dumped and ("Subscript" in dumped or "'get'" in dumped):
                    return True
        return False

    def _own_kinds(self, fn) -> set[str]:
        asked: set[str] = set()
        for c in ast.walk(fn):
            if not isinstance(c, ast.Call):
                continue
            name = called_name(c) or ""
            for kind, (_, asking, _) in KINDS.items():
                if name in asking:
                    asked.add(kind)
            table, filtered = None, False
            for method, link in chain_of(c):
                if method == "table" and link.args and isinstance(link.args[0], ast.Constant):
                    table = link.args[0].value
                if method in ("eq", "in_") and link.args and isinstance(link.args[0], ast.Constant) and link.args[0].value == "client_id":
                    filtered = True
            if filtered:
                for kind, (_, _, tables) in KINDS.items():
                    if table in tables:
                        asked.add(kind)
        return asked

    def asks(self, key: tuple[str, str], depth: int = DEPTH, seen: frozenset = frozenset()) -> set[str]:
        fn = self.funcs[key]
        asked = self._own_kinds(fn)
        callees = [t for _call, targets in self.calls_of(key) for t in targets]
        if self._compares_a_clients_id(fn):
            tables = set(self._tables(fn))
            for k in callees:
                tables |= self._tables(self.funcs[k])
            for kind, (_, _, kind_tables) in KINDS.items():
                if tables & kind_tables:
                    asked.add(kind)
        if depth > 0:
            for k in callees:
                if k not in seen:
                    asked |= self.asks(k, depth - 1, seen | {k})
        return asked


def _mentions(text: str, names: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(n)}\b", text) for n in names)


def _simple(names: set[str]) -> set[str]:
    return {n.split(".")[-1] for n in names}


def _member_lookup(call: ast.Call) -> bool:
    """Is this call a lookup of one member under the firm: the ownership function, the user repository's own, or a read of `users` by id AND firm."""
    if (called_name(call) or "") in MEMBER_ASKING_FUNCTIONS:
        return True
    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) \
            and (call.func.value.id, call.func.attr) in MEMBER_ASKING_CALLS:
        return True
    table, columns = None, set()
    for method, link in chain_of(call):
        if method == "table" and link.args and isinstance(link.args[0], ast.Constant):
            table = link.args[0].value
        if method in ("eq", "in_") and link.args and isinstance(link.args[0], ast.Constant):
            columns.add(link.args[0].value)
    # By the member's own id, or by the auth id (a lead's assignee is keyed to auth.users), and in both cases under the firm.
    return table == "users" and "firm_id" in columns and bool({"id", "auth_user_id"} & columns)


def _asks_member(self, key, names: set[str], depth: int = MEMBER_DEPTH, seen: frozenset = frozenset()) -> bool:
    """Does this function, or one it passes the named value to (up to MEMBER_DEPTH calls down), look the named member up under the firm?
    A lookup counts only when it is made ON the value the request carried (its text mentions the field, or the parameter the value was
    passed in as), so a lookup of the caller's own row, or of the firm's roster, asks nothing about the person who was named."""
    fn = self.funcs[key]
    names = _simple(names)
    for c in ast.walk(fn):
        if isinstance(c, ast.Call) and _member_lookup(c) and _mentions(ast.unparse(c), names):
            return True
    if depth <= 0:
        return False
    for call, targets in self.calls_of(key):
        handed = [ast.unparse(a) for a in call.args] + [ast.unparse(k.value) for k in call.keywords]
        if not any(_mentions(text, names) for text in handed):
            # The value is not handed on: nothing the callee does is about this member. Judged on the ARGUMENTS and not on the whole call's
            # text, because a fluent chain (`db.table("t").insert({"user_id": body.user_id}).execute()`) carries the field in its receiver, and
            # `.execute()` is resolved by its bare name to the one function of that name in the tree (the MFA reset's), whose own lookup of a
            # `user_id` then counted for a door that asked nothing (found by the review of the first version, 1-11-2026).
            continue
        for target in targets:
            if target in seen:
                continue
            callee = self.funcs[target]
            params = [a.arg for a in callee.args.args if a.arg not in ("self", "cls")]
            passed = set(names)
            for i, arg in enumerate(call.args):
                if i < len(params) and _mentions(ast.unparse(arg), names):
                    passed.add(params[i])
            for kw in call.keywords:
                if kw.arg and _mentions(ast.unparse(kw.value), names):
                    passed.add(kw.arg)
            if _asks_member(self, target, passed, depth - 1, seen | {target}):
                return True
    return False


_Tree.asks_member = _asks_member


def doors(root: Path) -> list[tuple[str, str, set[str], set[str]]]:
    """(router, handler, kinds the request names, kinds nothing reached asks) for every writing route whose request names a row."""
    tree = _Tree(root)
    found = []
    for mod, module in sorted(tree.mods.items()):
        if not mod.startswith("routers."):
            continue
        for fn in ast.walk(module):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            verbs = [d.func.attr for d in fn.decorator_list
                     if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and getattr(d.func.value, "id", "") == "router"]
            if not verbs or verbs[0] not in WRITING_VERBS:
                continue
            named: dict[str, set[str]] = {}
            route_path = next((d.args[0].value for d in fn.decorator_list
                               if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant)), "")
            defaults = dict(zip(reversed(fn.args.args), reversed(fn.args.defaults), strict=False))      # defaults are the TAIL of the arguments
            defaults.update({a: d for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True) if d is not None})
            for arg in fn.args.args + fn.args.kwonlyargs:
                if "Depends" in ast.unparse(defaults[arg]) if arg in defaults else False:
                    continue                                    # the caller's own identity, not something the caller named
                annotation = ast.unparse(arg.annotation) if arg.annotation else ""
                for model, by_kind in tree.models.items():
                    if re.search(rf"\b{model[1]}\b", annotation) and tree.model_is_visible_to(mod, model):
                        for kind, fields in by_kind.items():
                            named.setdefault(kind, set()).update(fields)
                if "{" + arg.arg + "}" in route_path:
                    continue                                    # a path parameter is the row the route is about, not a second row it names
                for kind, (rx, _, _) in KINDS.items():
                    if rx.search(arg.arg):                      # a query or form parameter that names a row (the body is not the only door)
                        named.setdefault(kind, set()).add(arg.arg)
                if DICT_BODY.fullmatch(annotation):             # a body taken as a plain dict: the AST cannot know its keys
                    named.setdefault("dict_body", set()).add(arg.arg)
            if not named or (mod, fn.name) not in tree.funcs:
                continue
            asked = tree.asks((mod, fn.name))
            if "member" in named and tree.asks_member((mod, fn.name), named["member"]):
                asked = asked | {"member"}
            found.append((mod.split(".")[-1], fn.name, set(named), set(named) - asked))
    return found


@pytest.fixture(scope="module")
def real():
    return doors(API)


# ── the rule ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_every_route_that_names_a_row_asks_whose_it_is_or_says_why_not(real):
    unasked = {(r, h, k) for r, h, _named, missing in real for k in missing}
    new = sorted(unasked - set(REVIEWED))
    assert not new, (
        "these routes take a request that names a row of a client-owned table and nothing they call asks whether the row is the client's. "
        "Call the matching function in services/named_row_ownership before the first write (it answers 404 in the words a missing row "
        "gets), or add the route to REVIEWED with the reason it is safe:\n  " + "\n  ".join(map(str, new)))


def test_a_reviewed_door_is_still_unasked_and_still_gives_its_reason(real):
    unasked = {(r, h, k) for r, h, _named, missing in real for k in missing}
    for key, reason in REVIEWED.items():
        assert key in unasked, f"{key} is now checked (or gone): delete it from REVIEWED, the list only shrinks"
        assert len(reason) > 80, f"{key} needs a reason"


def test_the_scan_sees_the_doors_it_is_meant_to(real):
    assert len(real) >= 40, f"only {len(real)} routes found: the scan has gone blind"
    seen_kinds = set().union(*(named for _r, _h, named, _m in real)) - {"dict_body"}
    assert seen_kinds == set(KINDS), f"kinds never seen: {set(KINDS) - seen_kinds}"
    handlers = {(r, h) for r, h, _n, _m in real}
    for expected in (("receipts", "create_receipt"), ("purchase_payments", "create_purchase_payment"), ("eway_bill", "create_eway_bill"),
                     ("recurring_invoices", "create_recurring"), ("recurring_purchase_bills", "create_recurring_bill"),
                     ("debit_notes", "create_debit_note"), ("fixed_assets", "create_asset"), ("bills_of_entry", "create_bill_of_entry"),
                     ("form_26as", "create_upload"), ("itr_workspace", "create_disallowance"), ("itr_workspace", "create_deduction"),
                     ("payroll", "put_attendance"), ("inventory", "transfer_stock"),
                     ("task_recurring", "create_recurring"), ("engagements", "create_engagement"), ("lifecycle", "update_lead"),
                     ("compliance_ops", "assign_obligation"), ("notifications", "create_notification"), ("tasks", "create_task")):
        assert expected in handlers, f"{expected} is no longer found as a door"


# ── the scan against code written for the purpose ──────────────────────────────────────────────────────────────────────────
_MODEL = '''
from pydantic import BaseModel
class ThingIn(BaseModel):
    client_id: str
    vendor_id: str
'''


def _tree_with(tmp_path: Path, router_body: str, service_body: str = "def noop():\n    return None\n") -> Path:
    for d in ("models", "routers", "services"):
        (tmp_path / d).mkdir(exist_ok=True)
    (tmp_path / "models" / "m.py").write_text(_MODEL)
    (tmp_path / "services" / "s.py").write_text(textwrap.dedent(service_body))
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent(router_body))
    return tmp_path


_ROUTER = '''
from fastapi import APIRouter
from models.m import ThingIn
from services import s
router = APIRouter()
@router.post("/x")
def make(data: ThingIn):
{body}
'''


def _verdict(tmp_path, body: str, service: str = "def noop():\n    return None\n"):
    out = doors(_tree_with(tmp_path, _ROUTER.replace("{body}", textwrap.indent(textwrap.dedent(body), "    ")), service))
    assert len(out) == 1, out
    return out[0][3]


def test_a_route_that_writes_without_asking_is_flagged(tmp_path):
    assert _verdict(tmp_path, 'db.table("things").insert({"vendor_id": data.vendor_id}).execute()') == {"vendor"}


def test_a_route_that_asks_in_its_own_body_is_not(tmp_path):
    assert _verdict(tmp_path, '''
        named_row_ownership.vendor_is_the_clients(db, "f", data.client_id, data.vendor_id)
        db.table("things").insert({"vendor_id": data.vendor_id}).execute()''') == set()


def test_a_route_whose_service_asks_two_calls_down_is_not(tmp_path):
    service = '''
        def first(db, data):
            return second(db, data)
        def second(db, data):
            named_row_ownership.vendor_is_the_clients(db, "f", data.client_id, data.vendor_id)
    '''
    assert _verdict(tmp_path, "s.first(db, data)", service) == set()


def test_a_route_whose_service_reads_the_vendor_under_the_client_is_not(tmp_path):
    service = '''
        def first(db, data):
            return db.table("vendors").select("id").eq("id", data.vendor_id).eq("client_id", data.client_id).execute()
    '''
    assert _verdict(tmp_path, "s.first(db, data)", service) == set()


def test_a_read_that_is_compared_with_the_clients_id_counts(tmp_path):
    service = '''
        def first(db, data):
            row = db.table("vendors").select("*").eq("id", data.vendor_id).execute().data[0]
            if row["client_id"] != data.client_id:
                raise ValueError("no")
    '''
    assert _verdict(tmp_path, "s.first(db, data)", service) == set()


def test_a_check_in_a_function_nothing_calls_does_not_count(tmp_path):
    service = '''
        def first(db, data):
            db.table("things").insert({"vendor_id": data.vendor_id}).execute()
        def never_called(db, data):
            named_row_ownership.vendor_is_the_clients(db, "f", data.client_id, data.vendor_id)
    '''
    assert _verdict(tmp_path, "s.first(db, data)", service) == {"vendor"}


def test_a_read_of_the_table_by_id_alone_does_not_count(tmp_path):
    service = '''
        def first(db, data):
            return db.table("vendors").select("id").eq("id", data.vendor_id).eq("firm_id", "f").execute()
    '''
    assert _verdict(tmp_path, "s.first(db, data)", service) == {"vendor"}


def test_a_route_that_asks_about_a_different_kind_is_still_flagged(tmp_path):
    assert _verdict(tmp_path, 'named_row_ownership.customer_is_the_clients(db, "f", data.client_id, "c")') == {"vendor"}


def test_a_dict_body_is_flagged_until_it_is_reviewed(tmp_path):
    (tmp_path / "models").mkdir(); (tmp_path / "routers").mkdir(); (tmp_path / "services").mkdir()
    (tmp_path / "models" / "m.py").write_text("x = 1\n")
    (tmp_path / "services" / "s.py").write_text("def noop():\n    return None\n")
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent('''
        from typing import Any
        from fastapi import APIRouter, Depends
        router = APIRouter()
        @router.post("/x")
        def make(payload: dict, current_user: dict = Depends(lambda: {})):
            return payload
        @router.post("/y/{thing_id}")
        def other(thing_id: str, payload: dict[str, Any]):
            return payload
    '''))
    out = doors(tmp_path)
    assert sorted((h, sorted(named), sorted(missing)) for _r, h, named, missing in out) == [
        ("make", ["dict_body"], ["dict_body"]), ("other", ["dict_body"], ["dict_body"])]


def test_a_query_parameter_that_names_a_row_is_a_door_and_a_path_parameter_is_not(tmp_path):
    (tmp_path / "models").mkdir(); (tmp_path / "routers").mkdir(); (tmp_path / "services").mkdir()
    (tmp_path / "models" / "m.py").write_text("x = 1\n")
    (tmp_path / "services" / "s.py").write_text("def noop():\n    return None\n")
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent('''
        from fastapi import APIRouter, Query
        router = APIRouter()
        @router.post("/a")
        def by_query(vendor_id: str = Query(...)):
            return vendor_id
        @router.post("/b/{vendor_id}")
        def by_path(vendor_id: str):
            return vendor_id
    '''))
    assert [(h, sorted(missing)) for _r, h, _n, missing in doors(tmp_path)] == [("by_query", ["vendor"])]


def test_a_model_that_carries_another_model_names_that_models_rows(tmp_path):
    (tmp_path / "models").mkdir(); (tmp_path / "routers").mkdir(); (tmp_path / "services").mkdir()
    (tmp_path / "models" / "m.py").write_text(textwrap.dedent('''
        from pydantic import BaseModel
        class LineIn(BaseModel):
            linked_bill_id: str
        class PayIn(BaseModel):
            client_id: str
            lines: list[LineIn]
    '''))
    (tmp_path / "services" / "s.py").write_text("def noop():\n    return None\n")
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent('''
        from fastapi import APIRouter
        from models.m import PayIn
        router = APIRouter()
        @router.post("/p")
        def pay(data: PayIn):
            return data
    '''))
    assert [(h, sorted(missing)) for _r, h, _n, missing in doors(tmp_path)] == [("pay", ["bill"])]


def test_the_names_that_the_ledger_listed_are_recognised():
    for name, kind in (("original_invoice_id", "invoice"), ("linked_bill_id", "bill"), ("sales_invoice_id", "invoice"),
                       ("purchase_bill_id", "bill"), ("exclude_bill_id", "bill")):
        assert KINDS[kind][0].search(name), name
    assert not KINDS["invoice"][0].search("fee_invoice_number")
    for name, kind in (("evidence_document_id", "document"), ("journal_entry_id", "journal"), ("employee_id", "employee"),
                       ("from_godown_id", "godown"), ("batch_id", "batch"), ("cost_centre_id", "cost_centre"),
                       ("purchase_payment_id", "vendor_payment")):
        assert KINDS[kind][0].search(name), name


# ── the member scan against code written for the purpose ───────────────────────────────────────────────────────────────────
def _member_tree(tmp_path: Path, router_body: str, service_body: str = "def noop():\n    return None\n") -> Path:
    for d in ("models", "routers", "services"):
        (tmp_path / d).mkdir(exist_ok=True)
    (tmp_path / "models" / "m.py").write_text(textwrap.dedent('''
        from typing import Optional
        from pydantic import BaseModel
        class AssignIn(BaseModel):
            title: str
            assignee_id: Optional[str] = None
    '''))
    (tmp_path / "services" / "s.py").write_text(textwrap.dedent(service_body))
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent(_ROUTER.replace("ThingIn", "AssignIn").replace(
        "{body}", textwrap.indent(textwrap.dedent(router_body), "    "))))
    return tmp_path


def _member_verdict(tmp_path, body: str, service: str = "def noop():\n    return None\n"):
    out = doors(_member_tree(tmp_path, body, service))
    assert len(out) == 1, out
    return out[0][3]


def test_a_route_that_stores_a_named_person_without_asking_is_flagged(tmp_path):
    assert _member_verdict(tmp_path, 'db.table("things").insert({"assignee_id": data.assignee_id}).execute()') == {"member"}


def test_a_route_that_asks_whether_the_person_is_the_firms_is_not(tmp_path):
    assert _member_verdict(tmp_path, '''
        named_row_ownership.member_is_the_firms(db, "f", data.assignee_id)
        db.table("things").insert({"assignee_id": data.assignee_id}).execute()''') == set()


def test_the_user_repositorys_own_lookup_on_the_named_value_counts(tmp_path):
    assert _member_verdict(tmp_path, '''
        user_repo.find_by_id(data.assignee_id, firm_id="f")
        db.table("things").insert({"assignee_id": data.assignee_id}).execute()''') == set()


def test_a_read_of_users_by_id_and_firm_on_the_named_value_counts(tmp_path):
    assert _member_verdict(tmp_path, '''
        db.table("users").select("id").eq("id", data.assignee_id).eq("firm_id", "f").execute()
        db.table("things").insert({"assignee_id": data.assignee_id}).execute()''') == set()


def test_a_service_two_calls_down_that_is_handed_the_value_and_asks_is_not_flagged(tmp_path):
    service = '''
        def first(db, who):
            return second(db, who)
        def second(db, other):
            named_row_ownership.member_is_the_firms(db, "f", other)
    '''
    assert _member_verdict(tmp_path, "s.first(db, data.assignee_id)", service) == set()


def test_a_lookup_of_somebody_else_does_not_count(tmp_path):
    """The caller's own row, looked up under the firm, says nothing about the person who was named."""
    assert _member_verdict(tmp_path, '''
        user_repo.find_by_id(current_user["id"], firm_id="f")
        db.table("things").insert({"assignee_id": data.assignee_id}).execute()''') == {"member"}


def test_a_roster_read_by_firm_alone_does_not_count(tmp_path):
    assert _member_verdict(tmp_path, '''
        db.table("users").select("id").eq("firm_id", "f").execute()
        db.table("things").insert({"assignee_id": data.assignee_id}).execute()''') == {"member"}


def test_a_check_in_a_function_that_is_not_handed_the_value_does_not_count(tmp_path):
    service = '''
        def first(db):
            named_row_ownership.member_is_the_firms(db, "f", "somebody")
    '''
    assert _member_verdict(tmp_path, '''
        s.first(db)
        db.table("things").insert({"assignee_id": data.assignee_id}).execute()''', service) == {"member"}


def test_a_field_called_user_id_is_not_asked_because_the_one_function_called_execute_looks_a_user_up(tmp_path):
    """The review of the first version: `.execute()` ends every Supabase write, the call graph resolves it by its bare name to the one function
    called `execute` in the tree, and when that function (the MFA reset's) looks a `user_id` up, a door that stored a `user_id` and asked nothing
    was read as asked. Only a field literally called `user_id` was masked, because only that text matched the lookup inside."""
    for d in ("models", "routers", "services"):
        (tmp_path / d).mkdir(exist_ok=True)
    (tmp_path / "models" / "m.py").write_text(textwrap.dedent('''
        from typing import Optional
        from pydantic import BaseModel
        class PersonIn(BaseModel):
            user_id: Optional[str] = None
    '''))
    (tmp_path / "services" / "mfa.py").write_text(textwrap.dedent('''
        def execute(payload):
            return _member("f", payload.get("user_id"))
        def _member(firm_id, user_id):
            return user_repo.find_by_id(user_id, firm_id=firm_id)
    '''))
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent('''
        from fastapi import APIRouter
        from models.m import PersonIn
        router = APIRouter()
        @router.post("/x")
        def make(data: PersonIn):
            db.table("things").insert({"user_id": data.user_id}).execute()
        @router.post("/y")
        def make_through_a_variable(data: PersonIn):
            query = db.table("things").insert({"user_id": data.user_id})
            query.execute()
    '''))
    assert sorted((h, sorted(missing)) for _r, h, _n, missing in doors(tmp_path)) == [("make", ["member"]), ("make_through_a_variable", ["member"])]


def test_a_lookup_of_the_auth_id_under_the_firm_counts_and_so_does_its_own_function(tmp_path):
    assert _member_verdict(tmp_path, '''
        named_row_ownership.member_auth_id_is_the_firms(db, "f", data.assignee_id)
        db.table("things").insert({"assignee_id": data.assignee_id}).execute()''') == set()
    assert _member_verdict(tmp_path, '''
        db.table("users").select("id").eq("auth_user_id", data.assignee_id).eq("firm_id", "f").execute()
        db.table("things").insert({"assignee_id": data.assignee_id}).execute()''') == set()
    # By the auth id alone, with no firm, it is a lookup of anybody's row.
    assert _member_verdict(tmp_path, '''
        db.table("users").select("id").eq("auth_user_id", data.assignee_id).execute()
        db.table("things").insert({"assignee_id": data.assignee_id}).execute()''') == {"member"}


def test_two_models_of_one_name_are_not_mixed(tmp_path):
    """A router whose own `AssignIn` names nobody is not a door because ANOTHER module's `AssignIn` names a person."""
    for d in ("models", "routers", "services"):
        (tmp_path / d).mkdir(exist_ok=True)
    (tmp_path / "services" / "s.py").write_text("def noop():\n    return None\n")
    (tmp_path / "models" / "m.py").write_text(textwrap.dedent('''
        from typing import Optional
        from pydantic import BaseModel
        class AssignIn(BaseModel):
            assignee_id: Optional[str] = None
    '''))
    (tmp_path / "routers" / "other.py").write_text(textwrap.dedent('''
        from pydantic import BaseModel
        from fastapi import APIRouter
        router = APIRouter()
        class AssignIn(BaseModel):
            title: str
        @router.post("/o")
        def make(data: AssignIn):
            return data
    '''))
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent('''
        from fastapi import APIRouter
        from models.m import AssignIn
        router = APIRouter()
        @router.post("/x")
        def make(data: AssignIn):
            return data
    '''))
    assert sorted((r, h, sorted(missing)) for r, h, _n, missing in doors(tmp_path)) == [("r", "make", ["member"])]


def test_the_member_names_are_recognised_and_a_path_parameter_is_not_a_door():
    for name in ("assigned_to", "assignee_id", "reviewer_id", "approver_id", "preparer_id", "partner_id", "user_id", "task_assignee_id"):
        assert KINDS["member"][0].search(name), name
    assert not KINDS["member"][0].search("created_by")
    assert not KINDS["member"][0].search("client_id")


# ── each door the rule found ───────────────────────────────────────────────────────────────────────────────────────────────
FIRM = "11111111-1111-1111-1111-111111111111"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}
LINE = {"service_catalogue_id": "svc-a", "description": "Service", "quantity": 1, "rate_paise": 100_000, "gst_rate_percent": 18}


def _world() -> FakeDB:
    db = FakeDB()
    for client, tag in ((A, "a"), (B, "b")):
        db.seed("clients", {"id": client, "firm_id": FIRM, "financial_year_start": "2025-04-01"})
        db.seed("vendors", {"id": f"vendor-{tag}", "firm_id": FIRM, "client_id": client, "is_active": True, "name": f"Vendor {tag}"})
        db.seed("customers", {"id": f"customer-{tag}", "firm_id": FIRM, "client_id": client, "is_active": True, "name": f"Customer {tag}"})
        db.seed("purchase_bills", {"id": f"bill-{tag}", "firm_id": FIRM, "client_id": client, "vendor_id": f"vendor-{tag}",
                                   "bill_no": f"B-{tag}", "status": "received", "deleted_at": None})
        db.seed("client_sales_invoices", {"id": f"invoice-{tag}", "firm_id": FIRM, "client_id": client, "customer_id": f"customer-{tag}",
                                          "invoice_no": f"INV-{tag}", "status": "issued", "deleted_at": None, "invoice_date": "2026-04-10"})
        db.seed("service_catalogue", {"id": f"svc-{tag}", "firm_id": FIRM, "client_id": client, "name": f"Item {tag}"})
        db.seed("bank_accounts", {"id": f"bank-{tag}", "firm_id": FIRM, "client_id": client, "bank_name": f"Bank {tag}"})
    return db


@pytest.fixture()
def world(monkeypatch):
    db = _world()
    wire_e2e(monkeypatch, db, [ri_router, ri_service, rpb_router, rpb_service, eway_router, receipts_router, pp_router,
                               debit_notes_router, pcn_router, sdn_router, credit_notes_router, sales_router])
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    for module in (ri_service, rpb_service):
        monkeypatch.setattr(module, "_db", lambda db=db: db, raising=False)
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)
    return db


def _client(*routers) -> TestClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def _refused(res, words: str):
    assert res.status_code == 404 and res.json()["detail"] == words, (res.status_code, res.text)


def test_a_recurring_invoice_template_names_a_customer_of_its_own_client_only(world):
    body = {"client_id": A, "title": "Retainer", "frequency": "monthly", "start_date": "2026-05-01", "lines": [
        {"service_catalogue_id": "svc-a", "description": "Retainer", "rate_paise": 100_000}]}
    client = _client(ri_router)
    _refused(client.post("/api/recurring-invoices", json={**body, "customer_id": "customer-b"}), "That customer was not found.")
    assert world.rows("recurring_invoice_templates") == [], "nothing was stored for the sibling's customer"
    own = client.post("/api/recurring-invoices", json={**body, "customer_id": "customer-a"})
    assert own.json().get("detail") != "That customer was not found.", own.text


def test_a_recurring_purchase_bill_template_names_a_vendor_of_its_own_client_only(world):
    line = {"service_catalogue_id": "svc-a", "description": "Rent", "rate_paise": 100_000}
    body = {"client_id": A, "title": "Rent", "frequency": "monthly", "start_date": "2026-05-01", "lines": [line]}
    client = _client(rpb_router)
    _refused(client.post("/api/recurring-purchase-bills", json={**body, "vendor_id": "vendor-b"}), "That vendor was not found.")
    assert world.rows("recurring_purchase_bill_templates") == []
    own = client.post("/api/recurring-purchase-bills", json={**body, "vendor_id": "vendor-a"})
    assert own.json().get("detail") != "That vendor was not found.", own.text


def test_a_recurring_purchase_bill_template_cannot_be_re_pointed_at_a_sibling_clients_vendor(world):
    world.seed("recurring_purchase_bill_templates", {"id": "tpl-1", "firm_id": FIRM, "client_id": A, "vendor_id": "vendor-a", "title": "Rent",
                                                     "frequency": "monthly", "start_date": "2026-05-01", "next_run_date": "2026-05-01",
                                                     "status": "active"})
    client = _client(rpb_router)
    _refused(client.put("/api/recurring-purchase-bills/tpl-1", json={"vendor_id": "vendor-b"}), "That vendor was not found.")
    assert world.rows("recurring_purchase_bill_templates")[0]["vendor_id"] == "vendor-a"
    own = client.put("/api/recurring-purchase-bills/tpl-1", json={"vendor_id": "vendor-a"})
    assert own.status_code == 200, own.text


def test_an_eway_bill_names_an_invoice_of_its_own_client_only(world):
    body = {"client_id": A, "invoice_number": "A/1", "dispatch_from": "Pune", "ship_to": "Mumbai", "goods_description": "Goods",
            "taxable_value_paise": 100_000}
    client = _client(eway_router)
    _refused(client.post("/api/eway-bill/records", json={**body, "sales_invoice_id": "invoice-b"}), "That invoice was not found.")
    assert world.rows("eway_bill_records") == []
    own = client.post("/api/eway-bill/records", json={**body, "sales_invoice_id": "invoice-a"})
    assert own.json().get("detail") != "That invoice was not found.", own.text


def test_a_receipt_names_a_bank_account_of_its_own_client_only(world):
    body = {"client_id": A, "customer_id": "customer-a", "receipt_date": "2026-05-02", "amount_paise": 50_000, "payment_mode": "bank"}
    client = _client(receipts_router)
    res = client.post("/api/receipts", json={**body, "bank_account_id": "bank-b"})
    _refused(res, "That bank account was not found.")
    assert world.rows("receipts") == [] and world.rows("journal_entries") == []
    own = client.post("/api/receipts", json={**body, "bank_account_id": "bank-a"})
    assert "That bank account was not found." not in own.text, own.text


def test_a_vendor_payment_names_a_bank_account_of_its_own_client_only(world):
    body = {"client_id": A, "vendor_id": "vendor-a", "payment_date": "2026-05-02", "amount_paise": 10_000, "payment_mode": "bank"}
    client = _client(pp_router)
    res = client.post("/api/purchase-payments", json={**body, "bank_account_id": "bank-b"})
    _refused(res, "That bank account was not found.")
    assert world.rows("purchase_payments") == [] and world.rows("journal_entries") == []
    own = client.post("/api/purchase-payments", json={**body, "bank_account_id": "bank-a"})
    assert "That bank account was not found." not in own.text, own.text


NOTE_CASES = [
    # (id, router, create path, create body without the link, link field, sibling id, own id, words, table, update path prefix)
    ("debit note", debit_notes_router, "/api/debit-notes",
     {"vendor_id": "vendor-a", "debit_note_date": "2026-05-02"}, "purchase_bill_id", "bill-b", "bill-a",
     "That bill was not found.", "debit_notes"),
    ("purchase credit note", pcn_router, "/api/purchase-credit-notes",
     {"vendor_id": "vendor-a", "credit_note_date": "2026-05-02"}, "purchase_bill_id", "bill-b", "bill-a",
     "That bill was not found.", "purchase_credit_notes"),
    ("sales debit note", sdn_router, "/api/sales-debit-notes",
     {"customer_id": "customer-a", "debit_note_date": "2026-05-02"}, "sales_invoice_id", "invoice-b", "invoice-a",
     "That invoice was not found.", "sales_debit_notes"),
]


@pytest.mark.parametrize("name,router,path,base,field,sibling,own,words,table", NOTE_CASES, ids=[c[0] for c in NOTE_CASES])
def test_a_note_names_the_bill_or_invoice_it_amends_only_if_it_is_the_clients(world, name, router, path, base, field, sibling, own, words, table):
    client = _client(router)
    body = {"client_id": A, "lines": [LINE], **base}
    _refused(client.post(path, json={**body, field: sibling}), words)
    assert world.rows(table) == [], "the sibling's document was stored as the note's link"
    created = client.post(path, json={**body, field: own})
    assert created.status_code == 200, created.text
    note_id = created.json()["data"]["id"]
    _refused(client.patch(f"{path}/{note_id}", json={field: sibling}), words)
    assert world.rows(table)[0][field] == own, "the correction re-pointed the note at the sibling's document"
    assert client.patch(f"{path}/{note_id}", json={field: own}).status_code == 200


def test_a_sales_credit_note_cannot_be_re_pointed_at_a_sibling_clients_invoice(world):
    client = _client(credit_notes_router)
    body = {"client_id": A, "customer_id": "customer-a", "credit_note_date": "2026-05-02", "lines": [LINE]}
    created = client.post("/api/credit-notes", json={**body, "sales_invoice_id": "invoice-a"})
    assert created.status_code == 200, created.text
    note_id = created.json()["data"]["id"]
    _refused(client.patch(f"/api/credit-notes/{note_id}", json={"sales_invoice_id": "invoice-b"}), "That invoice was not found.")
    assert world.rows("credit_notes")[0]["sales_invoice_id"] == "invoice-a"


def test_the_statement_inspector_names_a_bank_account_of_its_own_client_only(world, monkeypatch):
    """The gap the second reading found: a saved column layout was looked up by the account id and the firm, so another client's
    account answered with that client's layout."""
    import io
    import routers.banking as banking
    from fastapi import HTTPException
    from starlette.datastructures import UploadFile
    monkeypatch.setattr(banking, "_db", lambda: world)
    looked_up: list = []
    monkeypatch.setattr(banking.column_mappings, "find_mapping",
                        lambda db, firm, account, fingerprint: looked_up.append(account) or {"id": "m", "mapping": {"x": 1}, "match_scope": "account"})
    csv = b"Date,Narration,Withdrawal,Deposit,Balance\n01/04/2026,Opening,0,0,100\n"

    def call(account):
        return banking.inspect_statement_file(file=UploadFile(file=io.BytesIO(csv), filename="s.csv"), client_id=A,
                                              bank_account_id=account, pdf_password=None, current_user=PARTNER)

    with pytest.raises(HTTPException) as refused:
        call("bank-b")
    assert refused.value.status_code == 404 and refused.value.detail == "That bank account was not found."
    assert looked_up == [], "the sibling's saved layout was looked up before the account was asked about"
    own = call("bank-a")
    assert own["success"] is True and looked_up == ["bank-a"], own


# ── the second family: each door the rule found ────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def filed(world, monkeypatch):
    """The world, with a stored file and a ledger entry for each client, and the three workspaces' mock stores emptied."""
    import domain.income_tax.computation_workspace as workspace
    import domain.income_tax.form26as_service as form26as
    for client, tag in ((A, "a"), (B, "b")):
        world.seed("client_documents", {"id": f"doc-{tag}", "firm_id": FIRM, "client_id": client, "file_name": f"{tag}.pdf"})
        world.seed("journal_entries", {"id": f"je-{tag}", "firm_id": FIRM, "client_id": client, "entry_date": "2026-05-01"})
    for store in ("_MOCK_UPLOADS", "_MOCK_RECORDS"):
        monkeypatch.setattr(form26as, store, {})
    for store in ("_MOCK_DISALLOWANCES", "_MOCK_DEDUCTIONS"):
        monkeypatch.setattr(workspace, store, {})
    return world


def test_a_26as_upload_names_a_stored_file_of_its_own_client_only(filed):
    import domain.income_tax.form26as_service as form26as
    client = _client(form26as_router)
    body = {"client_id": A, "financial_year": "2025-26"}
    _refused(client.post("/api/form-26as/uploads", json={**body, "document_id": "doc-b"}), "That document was not found.")
    assert form26as._MOCK_UPLOADS == {}, "the sibling's file was stored as the upload's"
    own = client.post("/api/form-26as/uploads", json={**body, "document_id": "doc-a"})
    assert own.status_code == 200 and own.json()["data"]["document_id"] == "doc-a", own.text
    nothing_named = client.post("/api/form-26as/uploads", json=body)
    assert nothing_named.status_code == 200, "an upload that names no file is not stopped by the question"


def test_a_deduction_claim_names_an_evidence_file_of_its_own_client_only(filed):
    import domain.income_tax.computation_workspace as workspace
    client = _client(itr_router)
    body = {"client_id": A, "financial_year": "2025-26", "section": "80C", "claimed_amount_paise": 150_000_00}
    _refused(client.post("/api/itr/deductions", json={**body, "evidence_document_id": "doc-b"}), "That document was not found.")
    assert workspace._MOCK_DEDUCTIONS == {}
    own = client.post("/api/itr/deductions", json={**body, "evidence_document_id": "doc-a"})
    assert own.status_code == 200 and own.json()["data"]["evidence_document_id"] == "doc-a", own.text


@pytest.mark.parametrize("field,sibling,words", [
    ("evidence_document_id", "doc-b", "That document was not found."),
    ("journal_entry_id", "je-b", "That journal entry was not found."),
])
def test_a_disallowance_names_an_evidence_file_and_a_ledger_entry_of_its_own_client_only(filed, field, sibling, words):
    import domain.income_tax.computation_workspace as workspace
    client = _client(itr_router)
    body = {"client_id": A, "financial_year": "2025-26", "section": "40A(3)", "description": "Cash payment", "amount_paise": 20_000_00}
    own_ids = {"evidence_document_id": "doc-a", "journal_entry_id": "je-a"}
    _refused(client.post("/api/itr/disallowances", json={**body, **own_ids, field: sibling}), words)
    assert workspace._MOCK_DISALLOWANCES == {}, "the sibling's row was stored on the disallowance"
    own = client.post("/api/itr/disallowances", json={**body, **own_ids})
    assert own.status_code == 200, own.text
    assert (own.json()["data"]["evidence_document_id"], own.json()["data"]["journal_entry_id"]) == ("doc-a", "je-a")


# ── THE THIRD FAMILY: each door that names a person (POST-A-361, part 2) ──────────────────────────────────────────────────────
OTHER_FIRM = "99999999-9999-9999-9999-999999999999"
STRANGER_WORDS = "That team member was not found."


@pytest.fixture()
def staff(monkeypatch):
    """A firm with one member, another firm with one, and the request's database pointed at them."""
    db = FakeDB()
    db.seed("users", {"id": "member-own", "auth_user_id": "auth-own", "firm_id": FIRM, "full_name": "Asha Rao"})
    db.seed("users", {"id": "member-other-firm", "auth_user_id": "auth-other-firm", "firm_id": OTHER_FIRM, "full_name": "Stranger"})
    db.seed("users", {"id": "member-gone", "auth_user_id": "auth-gone", "firm_id": FIRM, "full_name": "Left the firm",
                      "deleted_at": "2026-09-01T00:00:00+00:00"})
    wire_e2e(monkeypatch, db, [])
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)
    return db


STRANGERS = ["member-other-firm", "no-such-member", "member-gone"]        # another firm's, invented, and one of this firm's who was deleted


def test_the_ownership_function_answers_a_stranger_a_missing_member_and_an_invented_one_alike(staff):
    from services import named_row_ownership as nro
    assert nro.member_is_the_firms(staff, FIRM, "member-own") is None
    for named in STRANGERS:
        with pytest.raises(Exception) as e:
            nro.member_is_the_firms(staff, FIRM, named)
        assert (e.value.status_code, e.value.detail) == (404, STRANGER_WORDS), named
    # The same member asked about under the OTHER firm is the stranger.
    with pytest.raises(Exception) as e:
        nro.member_is_the_firms(staff, OTHER_FIRM, "member-own")
    assert e.value.detail == STRANGER_WORDS


def test_a_suspended_member_can_be_named_and_a_deleted_one_cannot(staff):
    """The task door has always allowed a member who is only suspended, and its own lookup leaves out a member who was deleted."""
    from services import named_row_ownership as nro
    staff.seed("users", {"id": "member-suspended", "firm_id": FIRM, "full_name": "On leave", "is_active": False})
    assert nro.member_is_the_firms(staff, FIRM, "member-suspended") is None
    with pytest.raises(Exception) as e:
        nro.member_is_the_firms(staff, FIRM, "member-gone")
    assert (e.value.status_code, e.value.detail) == (404, STRANGER_WORDS)


def test_the_auth_id_function_answers_for_a_column_keyed_to_auth_users(staff):
    """A lead's assignee is keyed to auth.users(id): the value is a member's AUTH id, and a `users.id` is not an answer."""
    from fastapi import HTTPException
    from services import named_row_ownership as nro
    assert nro.member_auth_id_is_the_firms(staff, FIRM, "auth-own") is None
    for named in ("auth-other-firm", "no-such-member", "auth-gone", "member-own"):
        with pytest.raises(Exception) as e:
            nro.member_auth_id_is_the_firms(staff, FIRM, named)
        assert (e.value.status_code, e.value.detail) == (404, STRANGER_WORDS), named
    with pytest.raises(HTTPException) as other_firm:
        nro.member_auth_id_is_the_firms(staff, OTHER_FIRM, "auth-own")
    assert other_firm.value.detail == STRANGER_WORDS
    for named in (None, "", "   "):
        assert nro.member_auth_id_is_the_firms(staff, FIRM, named) is None
    assert nro.member_auth_id_is_the_firms(None, FIRM, "auth-other-firm") is None


def test_nothing_named_and_no_database_ask_nothing(staff):
    from services import named_row_ownership as nro
    for named in (None, "", "   "):
        assert nro.member_is_the_firms(staff, FIRM, named) is None
    assert nro.member_is_the_firms(None, FIRM, "member-other-firm") is None


def test_a_recurring_configuration_names_a_member_of_its_own_firm_only(staff, monkeypatch):
    monkeypatch.setattr(task_recurring_router, "_get_db", lambda: staff)
    client = _client(task_recurring_router)
    body = {"title": "Monthly close", "frequency": "monthly", "next_due_date": "2026-12-01"}
    for named in STRANGERS:
        _refused(client.post("/api/task-recurring", json={**body, "assignee_id": named}), STRANGER_WORDS)
    assert staff.rows("task_recurring_configs") == [], "nothing was stored for a person of another firm"
    own = client.post("/api/task-recurring", json={**body, "assignee_id": "member-own"})
    assert own.status_code == 200, own.text
    assert [r["assignee_id"] for r in staff.rows("task_recurring_configs")] == ["member-own"]
    assert client.post("/api/task-recurring", json=body).status_code == 200, "no assignee is still allowed"


def test_a_recurring_configuration_cannot_be_re_pointed_at_a_member_of_another_firm(staff, monkeypatch):
    monkeypatch.setattr(task_recurring_router, "_get_db", lambda: staff)
    staff.seed("task_recurring_configs", {"id": "cfg-1", "firm_id": FIRM, "client_id": None, "assignee_id": "member-own", "title": "T"})
    client = _client(task_recurring_router)
    for named in STRANGERS:
        _refused(client.put("/api/task-recurring/cfg-1", json={"assignee_id": named}), STRANGER_WORDS)
    assert [r["assignee_id"] for r in staff.rows("task_recurring_configs")] == ["member-own"]
    ok = client.put("/api/task-recurring/cfg-1", json={"assignee_id": "member-own", "title": "Renamed"})
    assert ok.status_code == 200, ok.text


@pytest.fixture()
def engagement_repo_calls(monkeypatch, staff):
    calls = {"create": [], "update": []}
    monkeypatch.setattr(engagements_router.client_repo, "find_by_id", lambda *a, **k: {"id": A, "firm_id": FIRM})
    monkeypatch.setattr(engagements_router.engagement_repo, "find_by_id",
                        lambda *a, **k: {"id": "eng-1", "firm_id": FIRM, "client_id": A, "fee_paise": 1})
    monkeypatch.setattr(engagements_router.engagement_repo, "create", lambda row: calls["create"].append(row) or {"id": "eng-new", **row})
    monkeypatch.setattr(engagements_router.engagement_repo, "update", lambda i, row: calls["update"].append(row) or {"id": i, **row})
    return calls


@pytest.mark.parametrize("field", ["assigned_to", "reviewer_id", "partner_id"])
def test_a_fee_engagement_names_its_assignee_reviewer_and_partner_from_its_own_firm_only(engagement_repo_calls, field):
    client = _client(engagements_router)
    base = {"client_id": A, "service_type": "GST", "fee_paise": 100, "billing_cycle": "monthly", "start_date": "2026-04-01"}
    for named in STRANGERS:
        _refused(client.post("/api/engagements", json={**base, field: named}), STRANGER_WORDS)
        _refused(client.patch("/api/engagements/eng-1", json={field: named}), STRANGER_WORDS)
    assert engagement_repo_calls == {"create": [], "update": []}, "something was stored for a person of another firm"
    assert client.post("/api/engagements", json={**base, field: "member-own"}).status_code == 200
    assert client.patch("/api/engagements/eng-1", json={field: "member-own"}).status_code == 200
    assert [r[field] for r in engagement_repo_calls["create"]] == ["member-own"]


def test_a_lead_names_an_assignee_of_its_own_firm_only_by_the_auth_id_its_column_is_keyed_to(staff, monkeypatch):
    """`leads.assigned_to` is keyed to auth.users(id) (migration 059). The first version of this check asked for a `users.id`, so an auth id
    was refused and a `users.id` passed the check and failed the key as a 500: no value could be assigned. And create_lead stored None whatever
    it was given, so its check protected nothing."""
    monkeypatch.setattr(lifecycle_router, "_db", lambda: staff)
    monkeypatch.setattr(lifecycle_router, "timeline_service", type("T", (), {"log": staticmethod(lambda *a, **k: None)}))
    staff.seed("leads", {"id": "lead-1", "firm_id": FIRM, "company_name": "Acme", "stage": "Lead", "assigned_to": None})
    client = _client(lifecycle_router)
    # Another firm's, invented, deleted, and (the one the first version let through) a member's users.id, which is not an auth id.
    for named in ("auth-other-firm", "no-such-member", "auth-gone", "member-own"):
        _refused(client.post("/api/lifecycle/leads", json={"company_name": "Acme", "assigned_to": named}), STRANGER_WORDS)
        _refused(client.patch("/api/lifecycle/leads/lead-1", json={"assigned_to": named}), STRANGER_WORDS)
    assert [r["id"] for r in staff.rows("leads")] == ["lead-1"], "a lead was stored for a person who is not this firm's"
    assert staff.rows("leads")[0]["assigned_to"] is None
    own = client.post("/api/lifecycle/leads", json={"company_name": "Acme", "assigned_to": "auth-own"})
    assert own.status_code == 200, own.text
    assert sorted(r["assigned_to"] for r in staff.rows("leads") if r["id"] != "lead-1") == ["auth-own"], "the named assignee was dropped on create"
    moved = client.patch("/api/lifecycle/leads/lead-1", json={"assigned_to": "auth-own"})
    assert moved.status_code == 200, moved.text
    assert staff.rows("leads")[0]["assigned_to"] == "auth-own"
    assert client.post("/api/lifecycle/leads", json={"company_name": "No owner"}).status_code == 200, "no assignee is still allowed"


def test_an_assignment_rule_target_is_asked_about_when_the_rule_is_already_fixed_user(staff, monkeypatch):
    """A PATCH that changes only `target_value` of a rule that is already `fixed_user` names a person without saying `rule_type`; the check ran
    only when the request itself carried the type, so any value was stored (it did nothing when the rule was evaluated, but it was kept)."""
    monkeypatch.setattr(task_recurring_router, "_get_db", lambda: staff)
    monkeypatch.setattr(task_recurring_router, "_assert_config_scope", lambda *a, **k: None)
    staff.seed("assignment_rules", {"id": "rule-user", "firm_id": FIRM, "recurring_config_id": "cfg-1", "rule_type": "fixed_user", "target_value": "member-own"})
    staff.seed("assignment_rules", {"id": "rule-role", "firm_id": FIRM, "recurring_config_id": "cfg-1", "rule_type": "by_role", "target_value": "Manager"})
    client = _client(task_recurring_router)
    url = "/api/task-recurring/cfg-1/rules/{}"
    for named in ("member-other-firm", "no-such-member"):
        refused = client.patch(url.format("rule-user"), json={"target_value": named})
        assert refused.status_code == 400 and "Invalid user_id for fixed_user rule" in refused.text, refused.text
    assert staff.rows("assignment_rules")[0]["target_value"] == "member-own"
    assert client.patch(url.format("rule-user"), json={"target_value": "member-own"}).status_code == 200
    # A rule that is not fixed_user takes a role or a team as its target, which is not a person.
    assert client.patch(url.format("rule-role"), json={"target_value": "Executive"}).status_code == 200
    # Changing the type to fixed_user in the same request is still asked, as before.
    assert client.patch(url.format("rule-role"), json={"rule_type": "fixed_user", "target_value": "no-such-member"}).status_code == 400


def test_an_obligation_names_its_preparer_reviewer_and_approver_from_its_own_firm_only(staff, monkeypatch):
    saved = []
    monkeypatch.setattr(compliance_ops_router, "_assert_obligation_scope", lambda *a, **k: None)
    monkeypatch.setattr(compliance_ops_router.obligations, "assign", lambda *a, **k: saved.append(k) or {"id": "rec-1"})
    client = _client(compliance_ops_router)
    for field in ("preparer_id", "reviewer_id", "approver_id"):
        for named in STRANGERS:
            _refused(client.post("/api/compliance/obligations/rec-1/assign", json={field: named}), STRANGER_WORDS)
    assert saved == [], "an assignment was stored for a person of another firm"
    assert client.post("/api/compliance/obligations/rec-1/assign", json={"preparer_id": "member-own"}).status_code == 200
    assert len(saved) == 1


def test_a_notification_is_addressed_to_a_member_of_its_own_firm_only(staff, monkeypatch):
    created = []
    monkeypatch.setattr(notifications_router.notifications_repo, "create", lambda row: created.append(row) or {"id": "n-1", **row})
    client = _client(notifications_router)
    body = {"type": "info", "title": "Hello", "body": "This firm's text"}
    for named in STRANGERS:
        _refused(client.post("/api/notifications", json={**body, "user_id": named}), STRANGER_WORDS)
    assert created == [], "a stranger of another firm was sent this firm's notification"
    assert client.post("/api/notifications", json={**body, "user_id": "member-own"}).status_code == 200
    assert client.post("/api/notifications", json=body).status_code == 200, "a firm-level notification names nobody"
    assert [r["user_id"] for r in created] == ["member-own", None]
