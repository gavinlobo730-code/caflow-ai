#!/usr/bin/env python3
"""
Write the demo practice into a running deployment — through the API, never the
database.

    python3 scripts/seed_demo_firm.py --api-url http://localhost:8000 --token "$JWT"
    python3 scripts/seed_demo_firm.py --api-url ... --token "$JWT" --confirm

⚠️ **IT IS A DRY RUN UNTIL `--confirm`.** This repository applies migrations to
the LIVE Supabase project on every merge to `main` (`docs/deploy-migrations.md`),
so a script here that wrote on import, or on its default invocation, is one
mistyped command from putting a fictional practice into somebody's real books.
Without `--confirm` it prints the plan and the counts and touches nothing.

**IT DRIVES THE API, NOT THE DATABASE, AND THAT IS THE DESIGN.** Every posting
in this schema goes through `services/phase2_journal_service._create_journal`
and nothing else; a seeder writing rows straight into Postgres would produce
books this product's own Verify Books would refuse, and a demo whose trial
balance does not foot is worse than no demo. Going through the doors also means
`rbac()`, the validators, the invoice-series rule, the GSTIN check digit and the
posting kernel all run — so the data is, by construction, what the product
produces. It is slower. That is the whole point.

**IT ONLY ADDS.** Nothing here deletes, truncates or updates an existing row. A
firm that already has clients is refused unless `--add-to-existing` is passed,
because merging a fictional practice into a real book is the mistake that
cannot be undone from here.

The practice itself is `domain/demo/fixture.py` — pure data, no handle, tested.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from domain.demo import fixture  # noqa: E402


class ApiRefusal(SystemExit):
    """The server answered a write with an HTTP error. It IS a SystemExit, so every stage that lets it through stops the
    run exactly as before; `status` is what lets the one stage that carries on (the GST returns) tell a refusal that is
    a finding about the product (a 422) from one that means every later call will fail the same way (an expired token,
    a missing permission, a rate limit, a server that is down)."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class Api:
    """The smallest HTTP client that will do. No retries: a seeder that retries
    a POST can create the document twice, and this product's own invoice-series
    rule would then refuse the rest of the run in a way nobody could read."""

    def __init__(self, base: str, token: str, *, pause: float = 0.0):
        self.base = base.rstrip("/")
        self.token = token
        self.pause = pause
        self.calls = 0

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base}{path}", data=data, method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        self.calls += 1
        if self.pause:
            time.sleep(self.pause)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = (e.read() or b"").decode()[:400]
            raise ApiRefusal(
                f"\n{method} {path} → HTTP {e.code}\n{detail}\n"
                "Nothing further was written. Fix the cause and re-run; this "
                "script only ever ADDS, so the rows already created stay.",
                e.code,
            )

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def post(self, path: str, body: dict) -> dict:
        return self._write("POST", path, body)

    def put(self, path: str, body: dict) -> dict:
        """Two of the doors this seeder drives are PUTs — payroll enablement
        and attendance — and neither is a POST by accident: each REPLACES a
        stated position rather than appending an event. Same envelope check,
        because the refusal shape is the same."""
        return self._write("PUT", path, body)

    def patch(self, path: str, body: dict) -> dict:
        """The GST workspace moves a saved return through its statuses with a
        PATCH. Same envelope check as every other write: that router answers a
        refusal (a Manager-or-above check, a books-moved check) as HTTP 200
        with `{"success": false}`."""
        return self._write("PATCH", path, body)

    def _write(self, method: str, path: str, body: dict) -> dict:
        out = self._request(method, path, body)
        # THE ENVELOPE IS CHECKED, ALWAYS. Several routers in this product
        # answer a refusal as HTTP 200 with `{"success": false}` — the GST
        # workspace notably — so a seeder trusting the status code would
        # report a practice it had not written.
        if isinstance(out, dict) and out.get("success") is False:
            raise ApiRefusal(
                f"\n{method} {path} was refused: {out.get('error')}\n"
                "The HTTP status was 200; this product answers some refusals "
                "that way, which is why the envelope is checked.",
                200,
            )
        return out


#: How many open-invoice credits one client's statement carries. Enough that
#: the match queue is worth opening on any client, few enough that the CA can
#: see the operating lines underneath them.
_OPEN_CREDITS_PER_CLIENT = 5


def _id(resp: dict) -> str:
    """The id out of an `api_response` envelope, whatever the router named the
    object. Tried in order rather than guessed, and it RAISES rather than
    returning None — a seeder that carries an empty id forward writes a
    hundred rows pointing at nothing."""
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict):
        for key in ("id", "client_id", "customer_id", "vendor_id", "invoice_id",
                    "bill_id", "employee_id"):
            if data.get(key):
                return str(data[key])
        for value in data.values():
            if isinstance(value, dict) and value.get("id"):
                return str(value["id"])
    raise SystemExit(f"could not find an id in the response: {json.dumps(resp)[:300]}")


def _total_paise(resp: dict) -> int:
    """The document's own total, as the ENGINE computed it. Raises rather than
    defaulting to zero: a settlement of nil is indistinguishable from an unpaid
    document on every screen, so a silent zero here would quietly undo the one
    thing these receipts exist to demonstrate."""
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict) and isinstance(data.get("total_paise"), int):
        return data["total_paise"]
    raise SystemExit(
        f"no total_paise in the response — cannot settle it: {json.dumps(resp)[:300]}")


def _taxable_paise(resp: dict) -> int:
    """The document's taxable value as the ENGINE computed it, for the one
    thing that needs it: the cost a bill contributes to a project under
    construction. Raises rather than defaulting to nil, like `_total_paise`: a
    tranche of nil is refused by the door (`amount_paise` is positive) and a
    silent zero here would be a project with nothing in it."""
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict) and isinstance(data.get("taxable_amount_paise"), int):
        return data["taxable_amount_paise"]
    raise SystemExit(
        f"no taxable_amount_paise in the response — cannot cost the project: {json.dumps(resp)[:300]}")


def _paid_on(doc_date: str, days: int) -> str:
    from datetime import date, timedelta
    y, m, d = (int(x) for x in doc_date.split("-"))
    return (date(y, m, d) + timedelta(days=days)).isoformat()


def _settle(api: Api, client, doc, invoice: dict,
            client_id: str, customer_id: str,
            bank_account_id: Optional[str] = None) -> bool:
    """A customer receipt against one invoice, or nothing.

    `tds_paise` is the tax the CUSTOMER withheld, and the settlement is
    `amount + tds` — §198 deems the deducted tax to be income received and
    §199 gives the deductee credit for it, so a ₹1,00,000 invoice paid
    ₹90,000 net of ₹10,000 under §194J is discharged in full. The receipt is
    split the same way here, which is why the amount banked is the total LESS
    the withholding rather than the whole."""
    st = doc.settlement
    if st is None or st.paid_after_days is None:
        return False
    total = _total_paise(invoice)
    settled = total * st.fraction_bps // 10_000
    tds = settled * st.tds_bps // 10_000
    if settled <= 0:
        return False
    api.post("/api/receipts/", {
        "client_id": client_id,
        "customer_id": customer_id,
        "receipt_date": _paid_on(doc.doc_date, st.paid_after_days),
        "amount_paise": settled - tds,
        "tds_paise": tds,
        "payment_mode": "neft",
        # NAMED, not left to the fallback. `resolve_payment_account` has a
        # generic `%Bank%` branch for a document that names no account, and it
        # carries a real disclosure (`posting_account_notice`) that the CA is
        # meant to read — so a demo in which EVERY receipt carries it teaches
        # that the notice is noise. Naming the account also puts the money in
        # the client's own bank ledger, which is what the register, the Bank
        # Book and the reconciliation are all computed from.
        "bank_account_id": bank_account_id,
        "allocations": [{"sales_invoice_id": _id(invoice),
                         "allocated_paise": settled}],
    })
    return True


def _owed_paise(resp: dict) -> int:
    """What the client owes the vendor on a bill: `net_payable_paise`, which is
    the total LESS the tax withheld at the bill (`outstanding_paise` is
    generated from it, migration 278).

    The total is the bill's face value and is NOT what is open once any tax
    has been deducted: a payment of a fraction of the total against a bill
    whose net payable is smaller is refused ("Payment exceeds the bill's
    outstanding"). Falls back to the total only when the response carries no
    net figure, which is a bill nothing was withheld from. Raises, like
    `_total_paise`, rather than defaulting to nil."""
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict) and isinstance(data.get("net_payable_paise"), int):
        return data["net_payable_paise"]
    return _total_paise(resp)


def _pay(api: Api, doc, bill: dict, client_id: str, vendor_id: str,
         bank_account_id: Optional[str] = None) -> bool:
    """A vendor payment against one bill.

    NO `tds_paise` HERE and that is not an omission: on a purchase the client
    is the DEDUCTOR and the tax comes off at the bill, so the payment is
    already net — `PurchasePaymentIn` has no such field for exactly that
    reason. THE FRACTION IS OF WHAT IS OWED (`_owed_paise`), not of the face
    total, for the same reason. The bills left unpaid are what gives §43B(h)
    something to report: a screen that flags every purchase flags nothing."""
    st = doc.settlement
    if st is None or st.paid_after_days is None:
        return False
    settled = _owed_paise(bill) * st.fraction_bps // 10_000
    if settled <= 0:
        return False
    api.post("/api/purchase-payments", {
        "client_id": client_id,
        "vendor_id": vendor_id,
        "payment_date": _paid_on(doc.doc_date, st.paid_after_days),
        "amount_paise": settled,
        "purchase_bill_id": _id(bill),
        "payment_mode": "neft",
        "bank_account_id": bank_account_id,
    })
    return True


def _post_the_document(api: Api, path: str, transition: str, doc_id: str,
                       doc_date: str, last_month: str) -> bool:
    """Issue an invoice, or receive a bill — and say whether it was.

    ⚠️ EVERY DOCUMENT THIS SEEDER WROTE WAS A DRAFT, AND A DRAFT DOES NOTHING.
    `POST /api/sales-invoices/` and `POST /api/purchase-bills/` both insert
    with `status: "draft"`, and the journal is posted by the SEPARATE
    transition — `/{id}/issue` and `/{id}/receive`. Until this existed the
    demo had 315 invoices and 200 bills that posted no journal, so the trial
    balance, the profit and loss and the balance sheet were empty of both; no
    receivable or payable existed, so every ageing schedule was nil; no stock
    moved, because `apply_purchase_to_inventory` and `apply_sale_to_inventory`
    run at receive and issue; and NOTHING REACHED A RETURN, because only a
    posted document does — so GSTR-1 and GSTR-3B were structurally empty on a
    book of 515 documents. The counts looked right and every screen the demo
    exists for showed nothing.

    THE LAST MONTH IS LEFT IN DRAFT ON PURPOSE. A practice partway through the
    month after the year end has exactly that: eleven months posted and the
    twelfth still being entered. It is also the state the issue and receive
    buttons exist for, and a book where every document is already posted
    cannot show them.
    """
    if doc_date[:7] == last_month:
        return False
    # The transition is NAMED by the caller rather than sniffed out of the
    # path. "sales in the url means issue" is a spelling of the rule, and the
    # day a second sales-side document needs receiving it is a silent wrong
    # call rather than a 404.
    api.post(f"{path}/{doc_id}/{transition}", {})
    return True


def _banks(api: Api, c, client_id: str, fy_start: str, written: dict) -> list[str]:
    """The client's bank accounts, primary first.

    No `coa_account_id` is sent: `POST /accounts` creates a ledger for an
    unlinked account rather than leaving it unlinked, which is the behaviour
    that stopped two banks sharing code 1101 and rendering as one line. An
    opening balance carries its own DATE because `BankAccountIn` refuses one
    without it (BANK-27) — a balance with no as-at date makes every
    pre-opening line count twice.
    """
    ids = []
    for b in c.banks:
        ids.append(_id(api.post("/api/banking/accounts", {
            "client_id": client_id,
            "bank_name": b.bank_name,
            "account_no": b.account_no,
            "ifsc": b.ifsc,
            "account_type": b.account_type,
            # A CREDIT CARD's figure is the amount OWED, stated the way the
            # card states it; `account_kind.to_ledger_sign` negates it on the
            # way in so the ledger carries a credit balance. Sent as the
            # statement states it, which is what the model requires.
            "opening_balance_paise": b.opening_balance_paise,
            "opening_balance_date": fy_start if b.opening_balance_paise else None,
        })))
        written["bank_accounts"] += 1
    return ids


def _fixed_assets(api: Api, c, client_id: str, bank_id: Optional[str],
                  fy: str, written: dict) -> None:
    """The register, then ten months of the Companies Act charge.

    THE RUN STARTS AT THE FINANCIAL YEAR AND NOT AT THE OLDEST ASSET, and that
    is deliberate rather than a saving. Several assets here were acquired in
    earlier years — a demo whose every asset was bought this April has no
    opening gross block and no movement note worth reading — and FA-04's rule
    is that a first posting may begin at any month, because an asset brought
    over from Tally mid-life already carries its accumulated depreciation and
    its first charge in this product is whatever month the CA took over in.
    The run WARNS about the months that forecloses (`foreclosed_months`), and
    that warning on a migrated register is exactly what a CA should see.

    IT STOPS TWO MONTHS SHORT OF THE YEAR END so the depreciation screen has
    something to do. A register with nothing left to post shows a button that
    can only say "nothing to run".
    """
    if not c.assets:
        return
    for a in c.assets:
        api.post("/api/fixed-assets", {
            "client_id": client_id,
            "asset_name": a.name,
            "asset_category": a.category,
            "purchase_date": a.purchase_date,
            "purchase_cost_paise": a.cost_paise,
            "salvage_value_paise": a.salvage_value_paise,
            "depreciation_method": a.method,
            # The LIFE and the rate are left to the router, which resolves them
            # from Schedule II Part C and DERIVES the WDV rate from the life.
            # Sending either here would be a second statutory table.
            "acquisition_mode": "paid",
            "bank_account_id": bank_id,
            "payment_mode": "neft" if bank_id else None,
            "igst_paise": a.igst_paise,
            "cgst_paise": a.cgst_paise,
            "sgst_paise": a.sgst_paise,
            "itc_eligible": a.itc_eligible,
            "itc_blocked_reason": a.itc_blocked_reason,
            "location": a.location,
        })
        written["fixed_assets"] += 1

    start_year = int(fy[:4])
    body = {"client_id": client_id,
            "from_period": f"{start_year}-04",
            "to_period": f"{start_year + 1}-01"}
    # Chunked and resumable by design (DEPRECIATION_RUN_CHUNK) — the loop is
    # what the screen's "Run again" control does, and it terminates because
    # every asset's own depreciation_posted_through says where it stopped.
    for _ in range(12):
        out = api.post("/api/fixed-assets/run-depreciation", body).get("data") or {}
        written["depreciation_months"] += int(out.get("months_posted") or 0)
        if not int(out.get("remaining_months") or 0):
            break


def _cwip(api: Api, c, client_id: str, book, written: dict) -> None:
    """Assets under construction, built out of bills the books already hold.

    EACH TRANCHE IS `from_bill`: the cost was charged to Purchases when the bill
    was received and the tranche moves exactly that amount into the project
    (Dr Capital Work-in-Progress / Cr Purchases), touching neither the payable
    nor the bank -- so the receivables, payables and bank checks stay as they
    were. `credit` would credit Trade Payables with no purchase bill behind it,
    which Verify Books reports as a critical payables difference.

    THE AMOUNT IS THE ENGINE'S taxable value off the bill's own create response
    (`_taxable_paise`), never a second copy of the arithmetic, and the tranche
    is dated the bill's own date, so the move can never precede the debit it
    reclassifies. A bill that was left as a draft posted nothing and has
    nothing to reclassify: its tranche is skipped and counted, not written.
    """
    for p in c.cwip_projects:
        costs = {n: _taxable_paise(book.received_bills[n]["response"])
                 for n in p.bills if n in book.received_bills}
        project = api.post("/api/cwip", {
            "client_id": client_id,
            "project_name": p.name,
            "project_code": p.code,
            "asset_category": p.asset_category,
            "started_on": p.started_on,
            "approved_completion_date": p.approved_completion_date,
            "expected_completion_date": p.expected_completion_date,
            "approved_cost_paise": p.approved_cost_paise(sum(costs.values())),
        })
        project_id = _id(project)
        written["cwip_projects"] += 1
        for n in p.bills:
            bill = book.received_bills.get(n)
            if bill is None:
                written["cwip_tranches_skipped"] += 1
                continue
            api.post(f"/api/cwip/{project_id}/costs", {
                "client_id": client_id,
                "incurred_on": bill["date"],
                "description": f"{p.tranche_label}, bill {bill['bill_no']}",
                "amount_paise": costs[n],
                # The credit was claimed on the bill; a reclassification moves
                # the cost and nothing about the tax, so no tax is sent.
                "itc_eligible": True,
                "acquisition_mode": "from_bill",
                "purchase_bill_id": bill["id"],
            })
            written["cwip_tranches"] += 1
        if p.suspended_on:
            api.put(f"/api/cwip/{project_id}/status", {
                "client_id": client_id, "status": "suspended",
                "on_date": p.suspended_on})


def _payroll(api: Api, c, client_id: str, bank_id: Optional[str],
             written: dict) -> None:
    """Twelve months, left in the three states a run can be in.

    ATTENDANCE IS WRITTEN BEFORE EVERY RUN, and not because the figures need
    it — `_compute_slip` defaults to 26 days either way. It is written because
    the run REPORTS the absence: a slip whose `attendance_entered` is false is
    a named gap, `_release_gaps` recomputes it at finalise, and a Partner then
    has to type a reason to release over it. A demo in which every month is
    released over an outstanding gap teaches that the block is noise, which is
    the exact failure migration 328 was written to end.
    """
    if not c.employees:
        return
    api.put("/api/payroll/enablement", {
        "client_id": client_id, "enabled": True,
        "note": "Demo practice fixture — payroll is run in-house for this client.",
    })

    employee_ids = []
    for e in c.employees:
        employee_ids.append(_id(api.post("/api/payroll/employees", {
            "client_id": client_id, "name": e.name,
            "employee_code": e.employee_code,
            "designation": e.designation, "department": e.department,
            "pan": e.pan,
            # `joining_date` and `hra_percent` as the MODEL names them. Sent as
            # `date_of_joining` and `hra_paise` they were silently dropped by
            # Pydantic, and every seeded employee was stored with no joining
            # date and no house rent allowance at all.
            "joining_date": e.doj,
            "basic_paise": e.basic_paise,
            "hra_percent": e.hra_percent,
            "special_allowance_paise": e.special_paise,
            "uan": e.uan,
            "bank_account_no": e.bank_account_no,
            "bank_ifsc": e.bank_ifsc,
            "bank_name": e.bank_name,
        })))
        written["employees"] += 1

    for m in c.payroll:
        lop = dict(m.lop)
        api.put("/api/payroll/attendance", {
            "client_id": client_id, "month": m.month,
            "rows": [{"employee_id": eid,
                      "working_days": 26,
                      "days_present": 26 - lop.get(i, 0),
                      "lop_days": lop.get(i, 0)}
                     for i, eid in enumerate(employee_ids)],
        })

        run_id = _id(api.post("/api/payroll/runs",
                              {"client_id": client_id, "month": m.month}))
        written["payroll_runs"] += 1
        if m.leave_at == "draft":
            continue
        # No override_reason: the attendance above closes the only gap this
        # roster produces, so a clean release is the one that should happen —
        # and if a gap ever does appear the seeder stops with the 409 NAMING
        # it rather than quietly overriding it.
        api.post(f"/api/payroll/runs/{run_id}/finalize", {})
        written["payroll_finalized"] += 1
        if m.leave_at == "paid" and bank_id:
            api.post(f"/api/payroll/runs/{run_id}/disburse", {
                "bank_account_id": bank_id,
                "payment_date": f"{m.month}-28",
                "payment_reference": f"SAL/{m.month}",
            })
            written["payroll_disbursed"] += 1


def _engagements(api: Api, c, client_id: str, fy: str, fy_start: str,
                 written: dict) -> None:
    """The services the practice provides, and the obligations each implies.

    OBLIGATIONS ARE NOT CREATED WITH A CLIENT. They come from the 06:00 IST
    sweep for the current year, lazily when somebody opens a client's overview
    for GST only, and for everything else (the return, TDS, payroll, advance
    tax, the company's filings) from a fee engagement's service type -- so a
    seeded client had a compliance calendar of nothing, and one with no GSTIN
    had no obligation of any kind. The engagement is the door, and
    `generate-obligations` is the same call a CA presses; it is idempotent, and
    the financial year is passed because the default is the one the clock is
    in, which is not the books'.

    Fee engagements are also what billing reads, so this populates those
    screens too. The fees are the fixture's, in whole rupees.
    """
    for e in c.engagements:
        engagement = api.post("/api/engagements", {
            "client_id": client_id,
            "service_type": e.service_type,
            "fee_paise": e.fee_paise,
            "billing_cycle": e.billing_cycle,
            "start_date": fy_start,
            "status": "Active",
        })
        written["engagements"] += 1
        out = api.post(
            f"/api/engagements/{_id(engagement)}/generate-obligations"
            f"?financial_year={fy}", {}).get("data") or {}
        written["obligations"] += int(out.get("generated") or 0)


#: The sequence the GST workspace walks a saved return through. `ca_approved`
#: and `submitted` need the explicit confirmation flag and a Manager-or-above
#: caller (CGST Act s.37 / s.39: a return is approved by a person), which a
#: Partner is. `submitted` is the CA RECORDING that the return was filed on the
#: portal, with the date it was filed; nothing here is transmitted anywhere.
_RETURN_STEPS = ("validated", "ca_approved", "submitted")


def _return_windows(financial_year: str, quarterly: bool, last_month: str,
                    state_code: Optional[str] = None) -> list[tuple[str, str, str, str]]:
    """(period key MMYYYY, last day of the window, GSTR-1 filed on, GSTR-3B
    filed on) for every return the CA has already filed.

    A practice partway through the month after the year end has filed
    everything up to the month BEFORE the one left in draft (`last_month`): the
    twelfth month is still being entered, so a return for it would be built
    from a month that is not finished. A quarter is filed only when all three
    of its months are before that, which leaves the last quarter open on a
    QRMP client.

    The dates are the DUE dates, and they are asked of `compliance_engine`
    (the single source for every statutory date) and not restated here: a
    quarterly GSTR-3B is due on the 22nd or the 24th by the registration's
    STATE (Rule 61A), which a restated "24th" got wrong for a Maharashtra
    client and filed all three of its quarters two days late. So no seeded
    return is late, and the late-fee branch is the thing a CA sees only when
    they make it so.
    """
    import calendar
    from services.compliance_engine import MONTHLY, QUARTERLY, gstr1_due_date, gstr3b_due_date
    frequency = QUARTERLY if quarterly else MONTHLY
    start_year = int(financial_year[:4])
    months = [(start_year if m >= 4 else start_year + 1, m)
              for m in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3)]
    posted = [(y, m) for (y, m) in months if f"{y:04d}-{m:02d}" < last_month]

    def due(y: int, m: int) -> tuple[str, str]:
        return (gstr1_due_date(y, m, frequency).isoformat(),
                gstr3b_due_date(y, m, frequency, state_code).isoformat())

    out = []
    if not quarterly:
        for y, m in posted:
            out.append((f"{m:02d}{y:04d}", f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}", *due(y, m)))
        return out
    for i in range(0, len(months), 3):
        quarter = months[i:i + 3]
        if all(q in posted for q in quarter):
            y, m = quarter[0]
            ly, lm = quarter[-1]
            out.append((f"{m:02d}{y:04d}", f"{ly:04d}-{lm:02d}-{calendar.monthrange(ly, lm)[1]:02d}", *due(y, m)))
    return out


class _NotFiled(Exception):
    """A return the engine would not build or the server would not take: a finding about the product, reported."""


#: HTTP answers that mean every later call will fail the same way, so the run stops instead of listing them one by one:
#: no or expired login, no permission, a rate limit, a server error.
def _stops_the_run(status: int) -> bool:
    return status in (401, 403, 429) or status >= 500


def _gst_returns(api: Api, c, client_id: str, financial_year: str,
                 last_month: str, written: dict) -> None:
    """GSTR-1 and GSTR-3B for every month (or quarter) the practice has filed:
    computed from the books, saved, validated, approved and recorded as filed.

    WHY THIS EXISTS. The seeded returns were never saved or filed, so the
    return list, the filing history, the credit-ledger chain, the GSTR-1 to
    GSTR-3B tie-out and the annual return all rendered empty on a firm whose
    point is a year of GST work. These are the same doors a CA presses, in the
    order the screen offers them.

    A REFUSAL IS REPORTED, NOT FATAL, BUT ONLY THE KIND THAT IS A FINDING.
    Every other stage stops the run on a non-2xx, because a seeder that walks
    past a 422 writes a hundred rows pointing at nothing. A return is
    different: one month the engine will not build (a 400, 409 or 422, or the
    workspace's own 200 with success false) is a finding about the product, and
    the other clients' books are still worth seeding. It is printed, counted,
    named in the summary, and the run exits non-zero. A login that has expired,
    a missing permission, a rate limit or a server error is NOT that: every
    later call would fail the same way, so it stops the run. A call that gets no
    answer in time is reported as such, because the server may have saved the
    return anyway.

    A WINDOW WHOSE FILING DATE IS STILL TO COME IS SKIPPED. The filing date is
    the due date and the product refuses a date in the future, so a year in
    progress would otherwise leave a return saved, validated and approved but
    never filed; it is counted as not yet due.

    THE ARN IS NOT A REAL ONE, AND SAYS SO. `SEED-GSTR1-102025` is stored where
    the portal's acknowledgement number goes; nothing in this product validates
    that field, and a demo firm must not carry a number that looks like a
    portal's. # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a filing
    that did not happen, in a fictional firm.
    """
    from core.ist_clock import ist_today
    today = ist_today().isoformat()
    quarterly = c.gst_filing_frequency == "quarterly"
    for key, _window_end, gstr1_on, gstr3b_on in _return_windows(
            financial_year, quarterly, last_month, (c.gstin or "")[:2] or None):
        if max(gstr1_on, gstr3b_on) > today:
            written["returns_not_yet_due"] += 1
            continue
        for kind, compute, save, filed_on, label in (
                ("gstr1", "/api/gst/gstr1/from-books", "/api/gst-workspace/gstr1",
                 gstr1_on, "GSTR-1"),
                ("gstr3b", "/api/gst/gstr3b/from-books", "/api/gst-workspace/gstr3b",
                 gstr3b_on, "GSTR-3B")):
            try:
                body = {"client_id": client_id, "period": key}
                if kind == "gstr3b" and not quarterly:
                    # The build fills Table 5.1's interest from the date it is given, and it takes the MONTHLY due date
                    # for any period key (`gstr3b_computer._interest_5_1` says it cannot tell a quarter apart). A
                    # monthly return filed on its due date comes out as zeros; a QRMP quarter filed on ITS due date
                    # would be saved claiming months of interest, so a quarter is built without the date.
                    body["filed_on"] = filed_on
                comp = api.post(compute, body).get("data") or {}
                if comp.get("validation_errors"):
                    raise _NotFiled(f"the engine reports validation errors: "
                                    f"{str(comp['validation_errors'])[:200]}")
                if kind == "gstr1":
                    saved = api.post(save, {
                        "client_id": client_id, "period": comp["period"], "gstin": comp["gstin"],
                        "payload_json": comp["payload"], "summary_json": comp["summary"],
                        "total_taxable_paise": comp["taxable_total_paise"],
                        "total_igst_paise": comp["total_igst_paise"],
                        "total_cgst_paise": comp["total_cgst_paise"],
                        "total_sgst_paise": comp["total_sgst_paise"],
                        "total_cess_paise": comp["total_cess_paise"],
                    })
                else:
                    saved = api.post(save, {
                        "client_id": client_id, "period": comp["period"], "gstin": comp["gstin"],
                        "payload_json": comp["payload"], "summary_json": comp["working"],
                        "tax_liability_paise": comp["tax_liability_paise"],
                        "itc_claimed_paise": comp["itc_claimed_paise"],
                        "net_tax_paise": comp["net_tax_paise"],
                        "rcm_cash_paise": comp["rcm_cash_paise"],
                        "cash_payable_paise": comp["cash_payable_paise"],
                        "credit_ledger": comp["credit_ledger"],
                    })
                return_id = _id(saved)
                for status in _RETURN_STEPS:
                    step = {"status": status, "ca_approved": True}
                    if status == "submitted":
                        step.update({"arn": f"SEED-{kind.upper()}-{key}", "filed_date": filed_on})
                    filed = api.patch(f"/api/gst-workspace/{kind}/{return_id}/status", step)
                written[f"{kind}_filed"] += 1
                # RECORDING A RETURN AS FILED CLOSES ITS COMPLIANCE OBLIGATION (POST-A-254): the answer says whether it
                # did. A seeded firm whose calendar calls a filed return overdue is the contradiction that was found
                # here, so one that is not closed is reported, not assumed.
                closure = ((filed or {}).get("data") or {}).get("compliance_obligation") or {}
                if closure.get("closed"):
                    written["obligations_closed"] += 1
                elif closure.get("state") == "already_filed":
                    pass            # the calendar already says filed, which is what was wanted
                else:
                    written["obligations_left_open"].append(
                        f"{c.name} {label} {key}: {closure.get('message') or 'the answer did not say what happened to the obligation'}")
            except ApiRefusal as refusal:
                if _stops_the_run(refusal.status):
                    raise
                # The Api client's refusal is "<METHOD path → HTTP code>\n<detail>\nNothing further was written…":
                # the first two lines are the finding, the last is boilerplate.
                said = " — ".join(str(refusal).strip().splitlines()[:2])
                _return_not_filed(written, c, label, key, said)
            except _NotFiled as why:
                _return_not_filed(written, c, label, key, str(why))
            except (urllib.error.URLError, TimeoutError) as silence:
                _return_not_filed(
                    written, c, label, key,
                    f"no answer ({silence}); the server may have saved it, so check the return list before re-running")


def _return_not_filed(written: dict, c, label: str, key: str, said: str) -> None:
    msg = f"{c.name} {label} {key}: {said[:260]}"
    written["returns_refused"].append(msg)
    print(f"    ! {msg}")


@contextlib.contextmanager
def _a_finding_is_reported(written: dict, c, label: str, key: str):
    """Run one write that may be refused as a FINDING about the product, and report it instead of stopping the run.

    The same line `_gst_returns` draws: a 400, 409 or 422 (or the workspace's own 200 with success false, or the
    engine's validation errors) is a finding and the next client's books are still worth seeding; an expired login, a
    missing permission, a rate limit or a server error means every later call fails too and stops the run; a call with
    no answer is reported as such, because the server may have saved it."""
    try:
        yield
    except ApiRefusal as refusal:
        if _stops_the_run(refusal.status):
            raise
        _return_not_filed(written, c, label, key, " — ".join(str(refusal).strip().splitlines()[:2]))
    except _NotFiled as why:
        _return_not_filed(written, c, label, key, str(why))
    except (urllib.error.URLError, TimeoutError) as silence:
        _return_not_filed(written, c, label, key,
                          f"no answer ({silence}); the server may have saved it, so check before re-running")


#: Where each deduction the client has proof of goes in the engine's request. Only the two the demo holds; a proof with
#: no box here stops that client's return with a finding and is never dropped from the comparison silently.
_OLD_REGIME_BOXES = {
    ("80C", "PPF"): ("s80c", "ppf_paise"),
    ("80D", "Health insurance - self and family"): ("s80d", "self_family_premium_paise"),
}


def _income_tax(api: Api, c, client_id: str, financial_year: str, written: dict) -> None:
    """What the practice records for income tax: the section 40A(3) scan every client's books get, the losses brought
    forward, and, for a client whose facts allow it, a prepared return.

    EVERY FIGURE THAT IS TAX IS THE ENGINE'S. The fixture holds facts (salary, the tax deducted from it, a sale of
    shares, proofs of deductions); the business income is the BOOKS' (the book-to-tax bridge, or the section 44AD
    deemed income on the books' turnover); the tax, the advance-tax schedule, the capital gain and the deemed income
    come from the doors a CA's screen posts to. Nothing here has a rate, a slab or a limit in it.

    A client that owns assets has no computed return, deliberately: its book-to-tax bridge needs the section 32 block
    rates, which a human enters (POST-C-205), and the bridge says it is incomplete rather than assuming them. The
    fixture gives such a client no `itr_form`, so the demo shows the refusal and not a made-up number.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: nothing here reaches the income-tax portal, and the acknowledgement
    number stored on a seeded return is labelled as a seed's.
    """
    it = c.income_tax
    with _a_finding_is_reported(written, c, "section 40A(3) scan", f"FY {financial_year}"):
        found = api.post(f"/api/itr/disallowances/auto-detect-40a3?client_id={client_id}"
                         f"&financial_year={financial_year}", {})
        written["disallowances_detected"] += int(((found.get("data") or {}).get("detected")) or 0)
    if it is None:
        return
    for loss in it.losses:
        with _a_finding_is_reported(written, c, "brought-forward loss", loss.assessment_year):
            api.post("/api/itr/bf-losses", {
                "client_id": client_id, "assessment_year": loss.assessment_year, "loss_type": loss.loss_type,
                "original_amount_paise": loss.amount_paise, "notes": loss.note})
            written["bf_losses"] += 1
    if it.itr_form:
        with _a_finding_is_reported(written, c, f"{it.itr_form} return", f"FY {financial_year}"):
            _prepare_return(api, c, client_id, financial_year, it, written)


def _prepare_return(api: Api, c, client_id: str, financial_year: str, it, written: dict) -> None:
    """The return, in the order the computation and filing screens offer it."""
    from core.ist_clock import assessment_year_for
    ay = assessment_year_for(financial_year)
    if it.losses:
        # A loss brought forward is set off by the computation only if it is SENT to it, and this stage sends none: a
        # return computed here would overstate the tax without a word. Losses are recorded for the clients that have no
        # return, and a fixture that gives one client both is a finding.
        raise _NotFiled("a brought-forward loss is recorded but is not set off in a computation prepared here; give the "
                        "losses to a client without a return")
    business, presumptive = _the_business_income(api, c, client_id, financial_year, it)
    gain = _a_sale_of_shares(api, client_id, it, written)
    for section, sub_head, amount in it.deductions:
        api.post("/api/itr/deductions", {
            "client_id": client_id, "financial_year": financial_year, "section": section, "sub_head": sub_head,
            "claimed_amount_paise": amount,
            "notes": "Claimed on the client's word; no document is attached yet. Counts only if the old regime is chosen; "
                     "the comparison snapshot shows what it is worth."})
        written["deduction_claims"] += 1
    facts = {"business": business, "presumptive": presumptive, "gain": gain}

    # The advance tax is a payment against the tax this return computes, so it is asked of the engine first.
    first = _compute(api, c, financial_year, it, facts, advance=0, new_regime=True)
    estimated = max(0, int(first["tax"]["total_tax_paise"]) - it.salary_tds_paise)
    paid = _advance_tax(api, client_id, financial_year, estimated, it.presumptive_44ad, written)

    if it.deductions:
        # The old regime, for the comparison the client's regime choice rests on. It is not reviewed and not pinned.
        old = _compute(api, c, financial_year, it, facts, advance=paid, new_regime=False, boxes=_old_regime_boxes(it))
        _save_snapshot(api, client_id, financial_year, ay, it, old, facts, paid)
    final = _compute(api, c, financial_year, it, facts, advance=paid, new_regime=True)
    snapshot_id = _save_snapshot(api, client_id, financial_year, ay, it, final, facts, paid)
    api.post(f"/api/itr/snapshots/{snapshot_id}/review", {})
    _walk_the_filing(api, c, client_id, financial_year, ay, it, snapshot_id, written)


def _the_business_income(api: Api, c, client_id: str, financial_year: str, it) -> tuple[int, Optional[int]]:
    """(business income, presumptive income): the books' taxable income from the bridge, or the section 44AD deemed
    income on the books' turnover. A bridge that says it is incomplete is a finding, never a figure."""
    from core.ist_clock import fy_bounds
    start, end = fy_bounds(financial_year)
    if it.presumptive_44ad:
        books = api.get(f"/api/accounting/profit-loss?client_id={client_id}&start_date={start}&end_date={end}")
        turnover = int((((books.get("data") or {}).get("revenue")) or {}).get("total_paise") or 0)
        # The assessee the entity type makes this client is the SERVER's rule (this script imports nothing that needs the
        # API's dependencies, so it can run from any machine with a bare python3).
        from urllib.parse import quote
        said = api.get(f"/api/income-tax/assessee-kind?entity_type={quote(c.entity_type)}").get("data") or {}
        kind = said.get("kind")
        if kind is None:
            raise _NotFiled(said.get("refusal") or f"no tax basis is recorded for the entity type {c.entity_type!r}")
        # How the turnover was RECEIVED (a bank or a note) is not recorded in the books, so it is not stated here: the
        # scheme's rate and ceiling turn on it, the door's own defaults stand, and the answer's working says which applied.
        got = api.post("/api/income-tax/presumptive/44ad", {
            "fy": financial_year, "assessee_kind": kind, "is_resident": it.is_resident,
            "turnover_paise": turnover}).get("data") or {}
        if not got.get("eligible"):
            raise _NotFiled(f"section 44AD does not apply: {'; '.join(got.get('reasons') or [])[:200]}")
        return 0, int(got["presumptive_income_paise"])
    body: dict[str, Any] = {"client_id": client_id, "fy": financial_year}
    if not c.assets:
        # A client with no fixed assets has charged no depreciation, which is a reading of zero (POST-A-268: the bridge
        # cannot tell that from an account it could not read).
        body["depreciation_per_books_paise"] = 0
    bridge = api.post("/api/income-tax/book-to-tax-bridge", body).get("data") or {}
    if not bridge.get("is_complete"):
        why = "; ".join((bridge.get("missing") or []) + [r[:90] for r in (bridge.get("reasons") or [])[:1]])
        raise _NotFiled(f"the book-to-tax bridge is incomplete ({why[:220]}), so there is no business income to compute on")
    return int(bridge["taxable_income_paise"]), None


def _a_sale_of_shares(api: Api, client_id: str, it, written: dict) -> int:
    """Record the sale in the capital-gains register and return the gain the register computed (0 where there is none).
    Only the listed-equity box the seeder knows is supported; anything else is a finding, not a guess at a box."""
    sale = it.capital_gain
    if sale is None:
        return 0
    from core.ist_clock import ist_today
    if sale.sale_date > ist_today().isoformat():
        raise _NotFiled(f"the share sale is dated {sale.sale_date}, which is still to come, so it is not recorded")
    row = api.post("/api/income-tax/capital-gains", {
        "client_id": client_id, "asset_description": sale.description, "asset_type": sale.asset_type,
        "purchase_date": sale.purchase_date, "sale_date": sale.sale_date,
        "purchase_cost_paise": sale.purchase_cost_paise, "sale_value_paise": sale.sale_value_paise,
        "is_listed_security": sale.is_listed_security, "assessee_type": sale.assessee_type}).get("data") or {}
    written["capital_gains"] += 1
    if "112A" not in str(row.get("section_ref") or "") or row.get("gain_type") != "LTCG":
        raise _NotFiled(f"the register computed {row.get('gain_type')} under {row.get('section_ref')}; the seeder only "
                        "knows the long-term listed-equity box")
    return int(row["gain_paise"])


def _old_regime_boxes(it) -> dict:
    boxes: dict[str, dict] = {}
    for section, sub_head, amount in it.deductions:
        box = _OLD_REGIME_BOXES.get((section, sub_head))
        if box is None:
            raise _NotFiled(f"no box in the computation for {section} ({sub_head})")
        boxes.setdefault(box[0], {})[box[1]] = amount
    return boxes


def _compute(api: Api, c, financial_year: str, it, facts: dict, *, advance: int, new_regime: bool,
             boxes: Optional[dict] = None) -> dict:
    """One computation, asked of the engine the way the screen asks (the client's entity type included). The engine's
    refusals are findings: an answer carrying validation errors, or one resting on rates the engine has not verified for
    this year, is never saved, reviewed or filed."""
    body: dict[str, Any] = {
        "fy": financial_year, "use_new_regime": new_regime, "entity_type": c.entity_type,
        "is_resident": it.is_resident, "savings_interest_80tta_paise": it.savings_interest_paise,
        "gross_salary_paise": it.salary_paise, "other_income_paise": it.other_income_paise,
        "business_income_paise": facts["business"], "capital_gains_ltcg_paise": facts["gain"],
        "tds_deducted_paise": it.salary_tds_paise, "advance_tax_paid_paise": advance, **(boxes or {})}
    if facts["presumptive"] is not None:
        body["presumptive_income_paise"] = facts["presumptive"]
    comp = api.post("/api/income-tax/compute", body).get("data") or {}
    if not comp.get("regime"):
        raise _NotFiled("the engine returned no computation")
    if comp.get("validation_errors"):
        raise _NotFiled(f"the engine refused the computation: {str(comp['validation_errors'])[:200]}")
    if comp.get("rates_verified") is False:
        raise _NotFiled(f"the engine has not verified its rates for FY {financial_year}, so a return is not computed on them")
    return comp


def _advance_tax(api: Api, client_id: str, financial_year: str, estimated: int, presumptive: bool,
                 written: dict) -> int:
    """Pay the advance tax the engine's own schedule asks for, on each due date that has passed, and return what was
    paid. Each instalment brings the cumulative payment up to the schedule's required figure; the last therefore brings
    it to the whole estimate."""
    if estimated <= 0:
        return 0
    from core.ist_clock import ist_today
    today = ist_today().isoformat()
    schedule = (api.post("/api/income-tax/advance-tax/compute", {
        "fy": financial_year, "estimated_tax_paise": estimated, "installments": [],
        "is_presumptive_44ad_44ada": presumptive}).get("data") or {}).get("installments") or []
    paid, instalments = 0, []
    for row in schedule:
        if row["due_date"] > today:
            written["advance_tax_not_yet_due"] += 1
            continue
        owed = int(row["required_cumulative_paise"]) - paid
        if owed > 0:
            instalments.append({"installment_number": row["installment_number"], "paid_amount_paise": owed,
                                "paid_date": row["due_date"]})
            paid += owed
    if instalments:
        # The payment's challan number is a bank's, not ours to invent, so it is left unrecorded.
        api.post("/api/income-tax/advance-tax", {
            "fy": financial_year, "client_id": client_id, "estimated_tax_paise": estimated,
            "installments": instalments, "is_presumptive_44ad_44ada": presumptive})
        written["advance_tax_instalments"] += len(instalments)
    return paid


def _save_snapshot(api: Api, client_id: str, financial_year: str, ay: str, it, comp: dict, facts: dict,
                   advance: int) -> str:
    """Save a computation the way the computation screen does: the regime the SERVER applied, the inputs, and the
    server's whole answer."""
    net = int(((comp.get("payable")) or {}).get("net_payable_paise") or 0)
    out = api.post("/api/itr/snapshots", {
        "client_id": client_id, "financial_year": financial_year, "assessment_year": ay, "regime": comp["regime"],
        "income": {
            "gross_salary_paise": it.salary_paise, "business_income_paise": facts["business"],
            # Nothing is accepted into the return: the section 40A(3) scan only proposes (and found none here).
            "other_income_paise": it.other_income_paise, "total_disallowances_paise": 0,
            "advance_tax_paid_paise": advance, "tds_deducted_paise": it.salary_tds_paise,
            "taxable_income_paise": int(((comp.get("income")) or {}).get("taxable_income_paise") or 0),
            "tax_liability_paise": int(((comp.get("tax")) or {}).get("total_tax_paise") or 0),
            "net_payable_paise": net, "is_refund": net < 0},
        "computation_result": comp})
    return _id(out)


def _walk_the_filing(api: Api, c, client_id: str, financial_year: str, ay: str, it, snapshot_id: str,
                     written: dict) -> None:
    """Create the filing pinned to the reviewed computation and take it as far as the fixture says. Becoming filed is
    the acknowledgement's job and nothing else's (the transition door refuses it)."""
    from core.ist_clock import ist_today
    filing_id = _id(api.post("/api/itr/filings", {
        "client_id": client_id, "financial_year": financial_year, "assessment_year": ay,
        "itr_form": it.itr_form, "computation_snapshot_id": snapshot_id}))
    written["itr_filings"] += 1
    filed = it.take_it_to == "filed"
    for status in ("review", "partner_review") + (("ready_for_filing",) if filed else ()):
        api.post(f"/api/itr/filings/{filing_id}/transition", {"new_status": status})
    if not filed:
        written["itr_waiting"] += 1
        return
    if (it.filed_on or "") > ist_today().isoformat():
        written["itr_not_yet_filable"] += 1
        return
    acknowledged = api.post(f"/api/itr/filings/{filing_id}/acknowledge", {
        # Stored where the portal's acknowledgement number goes, and says it is a seed's: nothing validates the field.
        "acknowledgement_number": f"SEED-ITR-{c.pan}-AY{ay}", "filing_date": it.filed_on})
    written["itr_filed"] += 1
    closure = ((acknowledged or {}).get("data") or {}).get("compliance_obligation") or {}
    if closure.get("closed"):
        written["obligations_closed"] += 1
    elif closure.get("state") != "already_filed":
        written["obligations_left_open"].append(
            f"{c.name} {it.itr_form} FY {financial_year}: "
            f"{closure.get('message') or 'the answer did not say what happened to the obligation'}")


def _bank_rules(api: Api, c, client_id: str, written: dict) -> None:
    """The matching rules a CA writes for the recurring lines of a statement.

    A RULE IS A HUMAN'S DECISION, which is what grades the line it covers
    `ready` (`domain/banking/entry`): with no rule and no payee history every
    line was `needs_you` (21 to 60 per client) or at best `proposed`, and
    "Pass N ready" had nothing to pass on any of eight clients. They are
    written BEFORE the statement is imported so the first redraft already uses
    them (a rule written later marks the drafts stale for a redraft instead).

    NONE IS TRUSTED. A trusted rule passes its lines with no click, as the
    Manager who trusted it -- the one place the product acts unprompted -- and
    a seeded queue that has already passed its own ready lines shows nothing to
    press. The ledger is resolved by NAME from the client's own chart (the
    mock chart's codes are not the standard chart's), and a rule whose ledger
    the chart does not carry is skipped and counted, never written against a
    guess.
    """
    if not c.bank_rules:
        return
    chart = api.get(f"/api/accounting/accounts?client_id={client_id}").get("data") or []
    by_name = {a.get("account_name"): a.get("id") for a in chart if a.get("id")}
    for r in c.bank_rules:
        ledger_id = by_name.get(r.ledger)
        if not ledger_id:
            written["bank_rules_skipped"] += 1
            continue
        api.post("/api/banking/rules", {
            "client_id": client_id,
            "rule_name": r.rule_name,
            "description_pattern": r.description_pattern,
            "txn_type": "debit",
            "suggested_account_id": ledger_id,
            "suggested_gst_rate_bps": r.gst_rate_bps,
        })
        written["bank_rules"] += 1


def _statement(api: Api, c, client_id: str, bank_id: str,
               open_credits: list[dict], written: dict) -> None:
    """One statement for the year, and a queue with real work in it.

    WHAT IS ON IT AND WHY NOTHING ELSE IS — see `fixture.DemoBankLine`. In
    short: the operating outflows nobody has coded, and a few customer credits
    against invoices the fixture left OPEN. A line for a receipt the ledger
    already holds would invite the CA to Pass it and record the same rupees
    twice.

    The running balance is computed here rather than in the fixture because it
    depends on figures the ENGINE produced — the credits are the invoice
    totals off their own create responses, GST and rounding included, and a
    second copy of that arithmetic in the fixture is the mistake this
    repository keeps recording.
    """
    rows = [{"transaction_date": ln.line_date, "description": ln.description,
             "debit_paise": 0 if ln.is_credit else ln.amount_paise,
             "credit_paise": ln.amount_paise if ln.is_credit else 0,
             "reference_no": None}
            for ln in c.bank_lines]
    rows.extend(open_credits)
    if not rows:
        return
    rows.sort(key=lambda r: (r["transaction_date"], r["description"]))

    running = c.banks[0].opening_balance_paise
    for r in rows:
        running += r["credit_paise"] - r["debit_paise"]
        r["balance_paise"] = running

    out = api.post("/api/banking/statements/import", {
        "client_id": client_id,
        "bank_name": c.banks[0].bank_name,
        "account_number": c.banks[0].account_no,
        "bank_account_id": bank_id,
        "rows": rows,
    }).get("data") or {}
    written["bank_lines"] += int(out.get("imported") or 0)

    # PROPOSE, AND DELIBERATELY DO NOT PASS. "Pass N ready" is the thing the
    # banking screen exists to show, and a queue somebody has already emptied
    # shows nothing. Chunked the way the screen chunks it.
    for _ in range(40):
        got = api.post("/api/banking/entries/redraft",
                       {"client_id": client_id, "limit": 100}).get("data") or {}
        written["bank_drafts"] += int(got.get("drafted") or 0)
        if not int(got.get("remaining") or 0):
            break


def _credit_for_an_open_invoice(doc, invoice: dict, customer_name: str,
                                invoice_no: str, cutoff: str,
                                fy_end: str) -> Optional[dict]:
    """A bank credit that would clear an invoice nobody has paid.

    This is what makes the match queue worth opening: a credit whose amount IS
    an open document's outstanding figure, so `rank_suggestions` has something
    real to offer and `FindMatchModal` has a candidate to accept. Only
    invoices raised BEFORE the last two months qualify — a February invoice is
    not overdue in March, and a credit against one would be an odd thing for
    the demo to be showing.
    """
    if doc.settlement is not None and doc.settlement.paid_after_days is not None:
        return None
    if doc.doc_date >= cutoff:
        return None
    paid = min(_paid_on(doc.doc_date, 95), fy_end)
    return {"transaction_date": paid,
            "description": f"NEFT INW {customer_name} {invoice_no}",
            "debit_paise": 0,
            "credit_paise": _total_paise(invoice),
            "reference_no": f"N{doc.doc_date.replace('-', '')}{invoice_no[-4:]}"}


class _Book:
    """One client's books as the seeder writes them: the ids every document
    names, and the credits for invoices nobody paid that the statement is built
    from once the last invoice is known.

    A class and not a closure because both document kinds need the same dozen
    facts and `seed()` was already near the complexity limits the lint ratchet
    holds it to; the bodies are the ones that were inline, unchanged. A plain
    class and not a dataclass: the guard that validates every body this module
    sends loads it with `exec_module` and no `sys.modules` entry, and
    `@dataclass` under `from __future__ import annotations` looks its own
    module up there."""

    def __init__(self, api, client, client_id, customer_ids, vendor_ids,
                 catalogue, bank_id, financial_year, last_month, cutoff,
                 fy_end, written):
        self.api = api
        self.client = client                 # fixture.DemoClient
        self.client_id = client_id
        self.customer_ids = customer_ids
        self.vendor_ids = vendor_ids
        self.catalogue = catalogue
        self.bank_id = bank_id
        self.financial_year = financial_year
        self.last_month = last_month
        self.cutoff = cutoff
        self.fy_end = fy_end
        self.written = written
        #: Bank credits for invoices nobody paid, in the order they arose.
        self.open_credits: list[dict] = []
        #: The bills the books RECEIVED, by position (the `n` of the vendor's
        #: bill number): what a project under construction draws its cost
        #: from. A bill left as a draft posted nothing and is not here.
        self.received_bills: dict[int, dict] = {}

    def sale(self, n: int, d) -> None:
        api, c, written = self.api, self.client, self.written
        customer_id = self.customer_ids[d.party % len(self.customer_ids)]
        invoice_no = f"INV/{self.financial_year}/{n:04d}"
        invoice = api.post("/api/sales-invoices/", {
            "client_id": self.client_id,
            "customer_id": customer_id,
            # The series a real practice runs: a prefix, the FY, a padded
            # counter. `domain/gst/invoice_series` enforces Rule 46(b)'s
            # sixteen characters and character set at the door, so this
            # has to satisfy it — 'INV/2025-26/0001' is 16 exactly.
            "invoice_no": invoice_no,
            "invoice_date": d.doc_date,
            "place_of_supply": d.place_of_supply,
            "supply_state_code": d.place_of_supply,
            "is_inter_state": d.place_of_supply != c.state_code,
            "lines": [{
                "service_catalogue_id": self.catalogue[ln.hsn_sac_code],
                "description": ln.description,
                "hsn_sac": ln.hsn_sac_code,
                "quantity": float(ln.quantity),
                "unit": ln.unit,
                "rate_paise": ln.rate_paise,
                "gst_rate_percent": float(ln.gst_rate_percent),
            } for ln in d.lines],
        })
        written["sales_invoices"] += 1
        # ISSUED, so it posts, ages, moves stock and reaches the return.
        # A settlement against a DRAFT would be a receipt against a
        # receivable that does not exist, so the settle below is gated on
        # it rather than left to the fixture's own "recent" rule agreeing
        # by coincidence.
        posted = _post_the_document(api, "/api/sales-invoices", "issue",
                                    _id(invoice), d.doc_date, self.last_month)
        written["invoices_issued"] += 1 if posted else 0
        # THE TOTAL COMES OFF THE RESPONSE, never out of a second copy of
        # the GST arithmetic here: the engine has just computed it, lines,
        # rounding and all, and `domain/gst` is the one authority for it.
        if posted and _settle(api, c, d, invoice, self.client_id, customer_id,
                              self.bank_id):
            written["receipts"] += 1
        elif posted and len(self.open_credits) < _OPEN_CREDITS_PER_CLIENT and n % 3 == 0:
            credit = _credit_for_an_open_invoice(
                d, invoice, c.customers[d.party % len(c.customers)].name,
                invoice_no, self.cutoff, self.fy_end)
            if credit:
                self.open_credits.append(credit)

    def purchase(self, n: int, d) -> None:
        api, c, written = self.api, self.client, self.written
        vendor_id = self.vendor_ids[d.party % len(self.vendor_ids)]
        bill_no = f"{c.vendors[d.party % len(c.vendors)].name[:3].upper()}/{n:04d}"
        bill = api.post("/api/purchase-bills/", {
            "client_id": self.client_id,
            "vendor_id": vendor_id,
            # The VENDOR'S own number, not ours — `bill_no` is a fact about
            # the supplier's books, which is why the recurring purchase
            # path deliberately leaves it blank rather than inventing one.
            # Here the fixture IS the supplier, so it may state one.
            "bill_no": bill_no,
            "bill_date": d.doc_date,
            # `PurchaseBillIn` HAS NO `place_of_supply` — an inward supply
            # is told apart by `is_inter_state`, and the name it was sent
            # under was dropped in silence. No figure moves today (every
            # purchase in this fixture is intra-state) and it would the
            # first time one was not.
            "is_inter_state": d.place_of_supply != c.state_code,
            "is_reverse_charge": d.is_reverse_charge,
            "lines": [{
                "service_catalogue_id": self.catalogue[ln.hsn_sac_code],
                "description": ln.description,
                "hsn_sac": ln.hsn_sac_code,
                "quantity": float(ln.quantity),
                "unit": ln.unit,
                "rate_paise": ln.rate_paise,
                "gst_rate_percent": float(ln.gst_rate_percent),
            } for ln in d.lines],
        })
        written["purchase_bills"] += 1
        # RECEIVED — which is what posts Dr Expense / Dr GST Input / Cr
        # Trade Payables, withholds the TDS and brings the goods into
        # stock at the line's taxable value plus its §17(5)-blocked tax.
        received = _post_the_document(api, "/api/purchase-bills", "receive",
                                      _id(bill), d.doc_date, self.last_month)
        written["bills_received"] += 1 if received else 0
        if received:
            # The create response is kept whole and read only by the
            # client whose projects need it (`_taxable_paise` raises on a
            # response without the figure, which no other client has to meet).
            self.received_bills[n] = {
                "id": _id(bill), "date": d.doc_date, "bill_no": bill_no,
                "response": bill}
        if received and _pay(api, d, bill, self.client_id, vendor_id, self.bank_id):
            written["payments"] += 1


def seed(api: Api, firm: fixture.DemoFirm, *, add_to_existing: bool) -> dict:
    existing = api.get("/api/clients").get("data") or []
    rows = existing.get("clients") if isinstance(existing, dict) else existing
    if rows and not add_to_existing:
        raise SystemExit(
            f"\nThis firm already has {len(rows)} client(s). Merging a fictional "
            "practice into a real book cannot be undone from here.\n"
            "Pass --add-to-existing if that is genuinely what you want."
        )

    written = {"hsn_library": 0, "clients": 0, "catalogue": 0,
               "customers": 0, "vendors": 0, "msmed_classifications": 0,
               "bank_accounts": 0,
               "sales_invoices": 0, "invoices_issued": 0, "receipts": 0,
               "purchase_bills": 0, "bills_received": 0, "payments": 0,
               "fixed_assets": 0, "depreciation_months": 0,
               "employees": 0, "payroll_runs": 0, "payroll_finalized": 0,
               "payroll_disbursed": 0,
               "bank_lines": 0, "bank_drafts": 0, "tans": 0,
               "engagements": 0, "obligations": 0,
               "bank_rules": 0, "bank_rules_skipped": 0,
               "cwip_projects": 0, "cwip_tranches": 0, "cwip_tranches_skipped": 0,
               "gstr1_filed": 0, "gstr3b_filed": 0, "returns_not_yet_due": 0,
               "obligations_closed": 0, "obligations_left_open": [],
               "bf_losses": 0, "disallowances_detected": 0, "deduction_claims": 0,
               "capital_gains": 0, "advance_tax_instalments": 0, "advance_tax_not_yet_due": 0,
               "itr_filings": 0, "itr_waiting": 0, "itr_filed": 0, "itr_not_yet_filable": 0,
               "returns_refused": []}

    # ── THE FIRM'S HSN LIBRARY COMES FIRST, AND IT IS A GATE ─────────────────
    #
    # `routers/service_catalogue._hsn_in_library` refuses a catalogue item
    # whose HSN is not an ACTIVE row in this firm's own library (Decision C:
    # a code is SELECTED from the firm's list, never typed per item). So the
    # order is library → catalogue → document, and each step is a precondition
    # of the next. Written once for the firm because the library is firm-wide;
    # the catalogue below is per client, because a catalogue is.
    for item in {i.hsn_sac_code: i
                 for c in firm.clients for i in c.catalogue}.values():
        api.post("/api/firm-hsn-library/", {
            "hsn_code": item.hsn_sac_code,
            "description": item.name,
            "hsn_type": item.hsn_type,
            "gst_rate_pct": float(item.gst_rate_percent),
            "uqc": item.unit,
        })
        written["hsn_library"] += 1

    # Derived once from the year the fixture was built for, never from the
    # clock: `fixture.build` takes the year as a parameter precisely so a demo
    # is not a different set of books every month.
    start_year = int(firm.financial_year[:4])
    fy_start = f"{start_year}-04-01"
    fy_end = f"{start_year + 1}-03-31"
    #: An invoice raised inside the last two months is not overdue, so a bank
    #: credit clearing one would be an odd thing to be demonstrating.
    cutoff = f"{start_year + 1}-02-01"
    #: The month left in DRAFT — see `_post_the_document`. The fixture owns the
    #: answer because its stock sizing must agree with it (`fixture.stock_floor`
    #: counts only the documents that post).
    last_month = fixture.draft_month(firm.financial_year)

    for c in firm.clients:
        print(f"  {c.name} — {c.demonstrates}")
        client_id = _id(api.post("/api/clients", {
            "client_name": c.name,
            "entity_type": c.entity_type,
            "pan": c.pan,
            "gstin": c.gstin,
            "state_code": c.state_code,
            "state": "Maharashtra" if c.state_code == fixture.HOME_STATE else "Karnataka",
            "city": "Mumbai" if c.state_code == fixture.HOME_STATE else "Bengaluru",
            "gst_filing_frequency": c.gst_filing_frequency,
            # Marked, so a real book that ever ends up beside this one can tell
            # them apart. `ClientCreate` has carried the flag since it was
            # written and nothing reads it — which makes it exactly the right
            # marker to set and exactly the wrong thing to rely on for
            # isolation. The isolation is the separate firm.
            "is_test": True,
            "notes": f"Demo practice fixture — {c.demonstrates}",
        }))
        written["clients"] += 1

        # THE DEDUCTOR'S TAN, for a client that withholds from anyone. A TDS
        # statement is filed under it (s.203A) and `domain/tds/deductor.
        # resolve` refuses to build one without it -- GET /api/tds/deductor
        # answered `deductor_tan_missing` for every seeded client.
        if c.tan:
            api.put("/api/payroll/statutory-identity",
                    {"client_id": client_id, "tan": c.tan})
            written["tans"] += 1

        # ── THE CATALOGUE, AND WHY EVERY LINE MUST NAME ONE ──────────────
        #
        # Migration 206 made `service_catalogue_id` required on an invoice and
        # a bill line, and the door says why in its own refusal: a line
        # carrying only a description and an HSN is not a line this product
        # will save. The map is keyed on the CODE because the fixture dedupes
        # on the code, so there is one key and no second thing to keep in step.
        catalogue: dict[str, str] = {}
        for item in c.catalogue:
            catalogue[item.hsn_sac_code] = _id(api.post("/api/service-catalogue/", {
                "client_id": client_id,
                "name": item.name,
                "kind": item.kind,
                "hsn_sac": item.hsn_sac_code,
                "gst_rate_bps": int(float(item.gst_rate_percent) * 100),
                "default_rate_paise": item.rate_paise,
                # Goods only: `unit` is the CBIC UQC and a service has none,
                # which is the same split `domain/gst/goods_or_services` makes.
                "unit": item.unit if item.kind == "good" else None,
                # OPENING STOCK, sized by the fixture for the documents that
                # follow (`fixture.stock_floor`) so no position goes below nil
                # while they are written in date order. `routers/
                # service_catalogue` seeds the costing ledger from these and
                # gates on `kind == "good"`, so a service sending them is
                # ignored rather than refused — which is why they are sent
                # only for goods here and not left to that gate.
                "opening_qty_units": item.opening_qty_units or None,
                "opening_cost_paise": item.opening_cost_paise or None,
                # DATED TO THE BOOKS' OWN FIRST DAY. Left out, the router dates
                # the opening to the FINANCIAL YEAR THE CLOCK IS IN (the
                # client carries no `financial_year_start`), which for books
                # that begin 1 April 2025 put thirty InventoryOpening journals
                # in FY 2026-27 -- after a year of sales had already driven
                # five clients' stock negative.
                "opening_balance_date": fy_start if item.opening_qty_units else None,
                # None is a REAL third state and never zero (INV-09): zero
                # means "tell me when it runs out", and reading an absence as
                # zero records a decision nobody made.
                "reorder_level_units": item.reorder_level_units,
                "category": item.category,
            }))
            written["catalogue"] += 1

        # ── THE BANK COMES BEFORE THE DOCUMENTS THAT NAME IT ────────────
        # Every receipt, vendor payment, asset purchase and salary
        # disbursement below carries `bank_account_id`, so the money lands in
        # this client's own ledger rather than the firm's generic `%Bank%`
        # fallback. Creating it here is what makes that possible; creating it
        # later would mean a year of postings that all carry the fallback
        # disclosure.
        bank_ids = _banks(api, c, client_id, fy_start, written)
        bank_id = bank_ids[0] if bank_ids else None

        customer_ids = []
        for p in c.customers:
            customer_ids.append(_id(api.post("/api/customers/", {
                "client_id": client_id, "name": p.name, "gstin": p.gstin,
                "state_code": p.state_code, "credit_days": 30,
            })))
            written["customers"] += 1

        vendor_ids = []
        for p in c.vendors:
            vendor_ids.append(_id(api.post("/api/vendors/", {
                "client_id": client_id, "name": p.name, "gstin": p.gstin,
                "state_code": p.state_code, "credit_days": 30,
                "tds_section": p.tds_section,
                # A SECTION ALONE WITHHOLDS NOTHING. The purchase-bill engine
                # asks `tds_applicable` first (`VendorIn` defaults it False),
                # so with only the section set not one of 114 bills under 194C
                # and 194J carried any TDS, and the TDS register, challans,
                # returns and deposit worksheets were all empty. Only a client
                # that deducts at all (`deducts_tax`: not an individual) is
                # marked.
                "tds_applicable": c.deducts_tax and p.withholds_tds,
                # THE PAYEE'S PAN, out of its GSTIN (characters 3 to 12 are
                # the PAN). An unregistered vendor has none, which is the
                # s.206AA case -- the higher rate -- and a demo in which every
                # payee has a PAN cannot show it.
                "pan": p.pan,
                # THE THIRD STATE, DELIBERATELY. `rcm_documents` reads NULL as
                # *unrecorded* and names it as a gap rather than guessing, so a
                # demo where every vendor is classified cannot show that
                # branch. An unregistered party (no GSTIN) is left unrecorded.
                "gst_registration_status": "registered" if p.gstin else None,
            })))
            written["vendors"] += 1
            # ⚠️ `msme_status` IS NOT A FIELD OF `VendorIn`, and sending it
            # there was silently dropped by Pydantic until the body-shape
            # guard caught it — so every seeded vendor was unclassified and
            # §43B(h) reported the whole purchase ledger as a gap. It is
            # recorded through the Schedule III ageing screen's own door,
            # which is Manager+ because MSMED §2(n) changes taxable income
            # rather than a presentation.
            if p.msme_status or p.msmed_agreement_days:
                api.post("/api/accounting/schedule-iii/ageing/classify", {
                    "client_id": client_id, "target": "vendor",
                    "target_id": vendor_ids[-1],
                    "msme_status": p.msme_status,
                    "msmed_agreement_days": p.msmed_agreement_days,
                })
                written["msmed_classifications"] += 1

        # THE DOCUMENTS GO IN DATE ORDER, sales and purchases together, and
        # that is what `fixture.documents_in_order` is: a stock ledger is a
        # chain in the order it is WRITTEN, so every sale of the year before
        # any purchase put the position below nil on most clients (and the
        # opening quantities are sized for this order, `fixture.stock_floor`).
        # `open_credits` are bank credits for invoices nobody paid — built
        # while the invoices are written, because the AMOUNT is the engine's
        # own total off the create response and there is nowhere else to read
        # it from.
        book = _Book(api, c, client_id, customer_ids, vendor_ids, catalogue,
                     bank_id, firm.financial_year, last_month, cutoff, fy_end,
                     written)
        for step in fixture.documents_in_order(c):
            if step.kind == "sale":
                book.sale(step.n, step.doc)
            else:
                book.purchase(step.n, step.doc)
        open_credits = book.open_credits

        _fixed_assets(api, c, client_id, bank_id, firm.financial_year, written)
        _cwip(api, c, client_id, book, written)
        _payroll(api, c, client_id, bank_id, written)
        _engagements(api, c, client_id, firm.financial_year, fy_start, written)
        # LAST, because the credits above are known only once every invoice
        # has been written and the engine has told us what each one came to.
        if bank_id and c.banks[0].import_statement:
            _bank_rules(api, c, client_id, written)
            _statement(api, c, client_id, bank_id, open_credits, written)
        # LAST OF ALL, because a filed return locks the months it covers
        # against any later sales invoice, bill or note (`journal_period_lock_
        # reason`), and every document above has been written by now.
        if c.gstin:
            _gst_returns(api, c, client_id, firm.financial_year, last_month, written)
        # Income tax reads the books too (the bridge, the turnover), and is the only stage that does not need a GSTIN.
        _income_tax(api, c, client_id, firm.financial_year, written)

    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api-url", required=True,
                    help="e.g. http://localhost:8000")
    ap.add_argument("--token", required=True,
                    help="a Partner's Supabase JWT for the target firm")
    ap.add_argument("--financial-year", default="2025-26")
    ap.add_argument("--confirm", action="store_true",
                    help="actually write. Without it this is a dry run.")
    ap.add_argument("--add-to-existing", action="store_true",
                    help="write into a firm that already has clients")
    ap.add_argument("--pause", type=float, default=0.0,
                    help="seconds between calls, for a rate-limited host")
    args = ap.parse_args()

    firm = fixture.build(args.financial_year)
    plan = fixture.summary(firm)

    print(f"\n{firm.name} — FY {firm.financial_year}")
    print(f"  GSTIN {firm.gstin}  ·  PAN {firm.pan}")
    for k, v in plan.items():
        if k not in ("firm", "financial_year"):
            print(f"  {k.replace('_', ' '):24} {v}")
    print("\n  what each client is for:")
    for c in firm.clients:
        print(f"    · {c.name}: {c.demonstrates}")

    if not args.confirm:
        print(
            "\nDRY RUN — nothing was written.\n"
            "Re-run with --confirm to write this into the firm the token "
            "belongs to. Note that this repository applies migrations to the "
            "LIVE project on merge, so check which deployment --api-url points "
            "at before you do.\n"
        )
        return 0

    api = Api(args.api_url, args.token, pause=args.pause)
    print(f"\nwriting to {api.base} …\n")
    written = seed(api, firm, add_to_existing=args.add_to_existing)
    print(f"\ndone — {api.calls} API calls")
    for k, v in written.items():
        print(f"  {k.replace('_', ' '):24} {v}")
    if written["returns_refused"] or written["obligations_left_open"]:
        # Everything else was written; the exit code says the filing history, or the calendar beside it, is NOT whole.
        print(f"\n{len(written['returns_refused'])} return(s) or record(s) were not filed or recorded and "
              f"{len(written['obligations_left_open'])} filed return(s) left their obligation open; they are listed above.")
        for line in written["obligations_left_open"]:
            print(f"    ! {line}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
