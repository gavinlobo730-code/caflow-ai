"""
Every field a document is CREATED with is either editable or deliberately not.

WHAT WAS WRONG (PAY-12)
    models/payroll.EmployeeUpdateIn listed date_of_birth and not joining_date.
    components/payroll/AddEmployeeModal.tsx has always sent joining_date on the
    edit path, and PYDANTIC IGNORES UNKNOWN KEYS BY DEFAULT, so it was dropped
    in silence:

        EmployeeUpdateIn(name="A", joining_date="2026-10-01")
            .model_dump(exclude_none=True)      ->  {"name": "A"}

    routers/payroll.update_employee then wrote whatever survived and reported
    success. A wrong joining date could never be corrected.

    That is not cosmetic. The joining date decides gratuity's five years of
    continuous service (Payment of Gratuity Act s.4(1)), the EPS eligibility
    test on first joining, and how much of the year a leaver is paid for.

    apps/web/scripts/employee-form-captures-what-filing-needs.test.ts asserts
    joining_date is on the FORM, and passed throughout — the form had it and
    the model threw it away.

WHY THIS TEST IS A SCAN AND NOT A LINE ABOUT joining_date
    PAY-12 was one of eleven create/update pairs, and every one of them drops
    something. Most of those drops are RIGHT — a document cannot move client,
    an account number is the account's identity — but "right" and "forgotten"
    look identical from outside, which is exactly how joining_date survived.

    So the rule is: a field on the create model is either on the update model,
    or named below with a reason. Nothing is left to be inferred from absence.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

import models


# ── Fields that are deliberately NOT editable, and why ──────────────────────
#
# Every entry here is a decision. Removing a field from this map without adding
# it to the update model fails the test below, which is the point.
IMMUTABLE_ON_UPDATE: dict[tuple[str, str], str] = {
    # A document cannot move between clients. The client is the accounting
    # entity the document belongs to; changing it would move a posted figure
    # out of one set of books and into another, and every derived row —
    # journals, returns, ageing — would still point at the old one.
    ("AccountUpdateIn", "client_id"): "a ledger belongs to one set of books",
    ("JournalEntryUpdateIn", "client_id"): "an entry belongs to one set of books",
    ("BankAccountUpdateIn", "client_id"): "an account belongs to one client",
    ("MatchingRuleUpdateIn", "client_id"): "a rule belongs to one client",
    ("PurchaseBillUpdateIn", "client_id"): "a bill belongs to one set of books",
    ("SalesInvoiceUpdateIn", "client_id"): "an invoice belongs to one set of books",
    ("CustomerUpdateIn", "client_id"): "a customer belongs to one client",
    ("VendorUpdateIn", "client_id"): "a vendor belongs to one client",
    ("EmployeeUpdateIn", "client_id"): "an employee belongs to one client",
    ("ServiceCatalogueUpdateIn", "client_id"): "a catalogue entry belongs to one client",
    ("FirmHsnLibraryUpdateIn", "client_id"): "a library entry belongs to one client",

    # Identity. Changing one of these does not correct the record, it makes it
    # a different record — and the row it would collide with may already exist.
    ("BankAccountUpdateIn", "account_no"): "the account number IS the account",
    ("FirmHsnLibraryUpdateIn", "hsn_code"): "the code IS the entry",

    # Type, once anything has been posted against it.
    ("AccountUpdateIn", "account_type"): (
        "an account's type decides which side of the trial balance it falls "
        "on; changing it after a posting silently restates every report"),
    ("FirmHsnLibraryUpdateIn", "hsn_type"): "goods against services — see hsn_code",
    ("FirmHsnLibraryUpdateIn", "source"): (
        "provenance: whether the row was typed or came from an import. It "
        "records HOW the entry arrived, so editing it would falsify the "
        "record rather than correct the entry"),
    ("ServiceCatalogueUpdateIn", "kind"): (
        "good against service decides whether a line moves stock "
        "(migrations 184/188/189); flipping it after use strands the movements"),

    # State that moves through its own endpoint, never a silent PATCH.
    ("JournalEntryUpdateIn", "status"): "posting and reversal have their own routes",

    # Currency and the rate frozen with it. A document's currency is fixed at
    # creation because every settlement against it is measured in that
    # currency; re-denominating it afterwards would restate the settlements.
    ("BankAccountUpdateIn", "currency"): "the account's currency is fixed at opening",
    ("PurchaseBillUpdateIn", "currency"): "settlements are measured in the document's currency",
    ("PurchaseBillUpdateIn", "exchange_rate"): "frozen with the currency at creation",
    ("SalesInvoiceUpdateIn", "currency"): "settlements are measured in the document's currency",
    ("SalesInvoiceUpdateIn", "exchange_rate"): "frozen with the currency at creation",

    # The counterparty. CGST s.34 makes a credit or debit note the way to
    # correct a document already issued to somebody; re-pointing it at a
    # different party is not a correction, it is a different supply.
    ("PurchaseBillUpdateIn", "vendor_id"): "s.34 — issue a debit note, do not re-point the bill",

    # Display overrides that are snapshots of the party at creation. The
    # customer record is what to edit; these are copies of it.
    ("SalesInvoiceUpdateIn", "customer_name"): "a snapshot of the customer at issue",
    ("SalesInvoiceUpdateIn", "customer_gstin"): "a snapshot of the customer at issue",
    ("SalesInvoiceUpdateIn", "place_of_supply"): (
        "the same field as supply_state_code, which IS updatable — one name "
        "reaches the column and the other is the create path's alias"),

    # Attachments are added through their own endpoint.
    ("JournalEntryUpdateIn", "attachments"): "attachments have their own route",

    # The COA hierarchy. Not editable TODAY and that is a gap rather than a
    # decision — ACC-09: nothing writes parent_id, nothing reads it, and there
    # is no screen to set it. Named here so it is a known hole with an owner
    # instead of an omission, and so removing it from this map is what the fix
    # will do.
    ("AccountUpdateIn", "parent_id"): (
        "ACC-09 — the chart of accounts is flat: nothing writes parent_id and "
        "no screen sets it. A gap, not a decision"),
}


def _pairs() -> list[tuple[str, type, type]]:
    """Every (module, CreateModel, UpdateModel) triple in models/."""
    out = []
    for m in pkgutil.iter_modules(models.__path__):
        mod = importlib.import_module(f"models.{m.name}")
        classes = {n: o for n, o in vars(mod).items()
                   if inspect.isclass(o) and hasattr(o, "model_fields")}
        for name, cls in sorted(classes.items()):
            if not name.endswith("UpdateIn"):
                continue
            base = classes.get(name[: -len("UpdateIn")] + "In")
            if base is not None:
                out.append((m.name, base, cls))
    return out


def test_the_scan_finds_the_models_it_is_about():
    """Vacuity guard. A rename that stops this matching would leave the test
    green and checking nothing."""
    names = {u.__name__ for _, _, u in _pairs()}
    assert len(names) >= 10, names
    assert "EmployeeUpdateIn" in names
    assert "SalesInvoiceUpdateIn" in names


@pytest.mark.parametrize("mod,create,update",
                         _pairs(), ids=lambda x: getattr(x, "__name__", str(x)))
def test_every_creatable_field_is_editable_or_named_immutable(mod, create, update):
    unaccounted = sorted(
        f for f in create.model_fields
        if f not in update.model_fields
        and (update.__name__, f) not in IMMUTABLE_ON_UPDATE
    )
    assert not unaccounted, (
        f"{create.__name__} accepts {unaccounted} and {update.__name__} does "
        f"not, with no reason recorded. Pydantic IGNORES unknown keys, so a "
        f"caller sending one of these gets no error and no effect — the field "
        f"is simply uncorrectable. Either add it to {update.__name__}, or add "
        f"it to IMMUTABLE_ON_UPDATE with the reason.")


def test_the_immutable_map_has_no_stale_entries():
    """An entry that names a field the update model now HAS is a reason nobody
    is applying, and it would hide the next real omission behind it."""
    by_update = {u.__name__: u for _, _, u in _pairs()}
    stale = [
        (u, f) for (u, f) in IMMUTABLE_ON_UPDATE
        if u in by_update and f in by_update[u].model_fields
    ]
    assert not stale, f"these are editable now and still listed as immutable: {stale}"


def test_every_reason_is_a_reason():
    for key, why in IMMUTABLE_ON_UPDATE.items():
        assert len(why) > 12, f"{key} needs a reason, not a label: {why!r}"


# ── The three this change actually fixed ────────────────────────────────────

def test_a_joining_date_can_be_corrected():
    """PAY-12. It decides gratuity's five years (Payment of Gratuity Act
    s.4(1)), the EPS eligibility test, and a leaver's proportion of the year."""
    from models.payroll import EmployeeUpdateIn
    out = EmployeeUpdateIn(name="A", joining_date="2026-10-01").model_dump(exclude_none=True)
    assert out == {"name": "A", "joining_date": "2026-10-01"}


def test_a_draft_bill_can_have_its_reverse_charge_flag_corrected():
    """Editable on a draft SALES invoice and, until now, on no purchase bill at
    all — with no reason stated anywhere."""
    from models.invoices import PurchaseBillUpdateIn
    assert PurchaseBillUpdateIn(is_reverse_charge=True).is_reverse_charge is True


def test_the_form_15ca_and_15cb_references_can_be_recorded_after_receipt():
    """They come into existence AFTER the bill — the same shape as an export's
    shipping bill. Form 15CB's UDIN is generated when the CA signs the
    certificate; Form 15CA's acknowledgement only exists once the declaration
    has been filed. Locked at receipt, there would be no moment at which either
    could be recorded."""
    from models.invoices import PurchaseBillUpdateIn
    from routers.purchase_bills import _SOFT_BILL_UPDATE_FIELDS
    for f in ("form_15ca_ack_no", "form_15ca_filed_on", "form_15cb_udin"):
        assert f in PurchaseBillUpdateIn.model_fields
        assert f in _SOFT_BILL_UPDATE_FIELDS, (
            f"{f} must survive receipt, or it can never be recorded at all")


def test_the_bill_is_otherwise_still_frozen_at_receipt():
    """The exception is exactly those three wide. Any wider and it is a hole in
    CGST s.34 rather than an accommodation of when the paperwork arrives."""
    from routers.purchase_bills import _SOFT_BILL_UPDATE_FIELDS
    for locked in ("bill_no", "bill_date", "lines", "is_inter_state",
                   "vendor_id", "is_reverse_charge"):
        assert locked not in _SOFT_BILL_UPDATE_FIELDS
