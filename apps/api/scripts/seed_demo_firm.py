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
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional

sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from domain.demo import fixture  # noqa: E402


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
            raise SystemExit(
                f"\n{method} {path} → HTTP {e.code}\n{detail}\n"
                "Nothing further was written. Fix the cause and re-run; this "
                "script only ever ADDS, so the rows already created stay."
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

    def _write(self, method: str, path: str, body: dict) -> dict:
        out = self._request(method, path, body)
        # THE ENVELOPE IS CHECKED, ALWAYS. Several routers in this product
        # answer a refusal as HTTP 200 with `{"success": false}` — the GST
        # workspace notably — so a seeder trusting the status code would
        # report a practice it had not written.
        if isinstance(out, dict) and out.get("success") is False:
            raise SystemExit(
                f"\n{method} {path} was refused: {out.get('error')}\n"
                "The HTTP status was 200; this product answers some refusals "
                "that way, which is why the envelope is checked."
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


def _pay(api: Api, doc, bill: dict, client_id: str, vendor_id: str,
         bank_account_id: Optional[str] = None) -> bool:
    """A vendor payment against one bill.

    NO `tds_paise` HERE and that is not an omission: on a purchase the client
    is the DEDUCTOR and the tax comes off at the bill, so the payment is
    already net — `PurchasePaymentIn` has no such field for exactly that
    reason. The bills left unpaid are what gives §43B(h) something to report:
    a screen that flags every purchase flags nothing."""
    st = doc.settlement
    if st is None or st.paid_after_days is None:
        return False
    settled = _total_paise(bill) * st.fraction_bps // 10_000
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
               "sales_invoices": 0, "receipts": 0,
               "purchase_bills": 0, "payments": 0,
               "fixed_assets": 0, "depreciation_months": 0,
               "employees": 0, "payroll_runs": 0, "payroll_finalized": 0,
               "payroll_disbursed": 0,
               "bank_lines": 0, "bank_drafts": 0}

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

        #: Bank credits for invoices nobody paid — built while the invoices
        #: are written, because the AMOUNT is the engine's own total off the
        #: create response and there is nowhere else to read it from.
        open_credits: list[dict] = []
        for n, d in enumerate(c.sales, start=1):
            invoice_no = f"INV/{firm.financial_year}/{n:04d}"
            invoice = api.post("/api/sales-invoices/", {
                "client_id": client_id,
                "customer_id": customer_ids[d.party % len(customer_ids)],
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
                    "service_catalogue_id": catalogue[ln.hsn_sac_code],
                    "description": ln.description,
                    "hsn_sac": ln.hsn_sac_code,
                    "quantity": float(ln.quantity),
                    "unit": ln.unit,
                    "rate_paise": ln.rate_paise,
                    "gst_rate_percent": float(ln.gst_rate_percent),
                } for ln in d.lines],
            })
            written["sales_invoices"] += 1
            # THE TOTAL COMES OFF THE RESPONSE, never out of a second copy of
            # the GST arithmetic here: the engine has just computed it, lines,
            # rounding and all, and `domain/gst` is the one authority for it.
            if _settle(api, c, d, invoice, client_id,
                       customer_ids[d.party % len(customer_ids)], bank_id):
                written["receipts"] += 1
            elif len(open_credits) < _OPEN_CREDITS_PER_CLIENT and n % 3 == 0:
                credit = _credit_for_an_open_invoice(
                    d, invoice, c.customers[d.party % len(c.customers)].name,
                    invoice_no, cutoff, fy_end)
                if credit:
                    open_credits.append(credit)

        for n, d in enumerate(c.purchases, start=1):
            bill = api.post("/api/purchase-bills/", {
                "client_id": client_id,
                "vendor_id": vendor_ids[d.party % len(vendor_ids)],
                # The VENDOR'S own number, not ours — `bill_no` is a fact about
                # the supplier's books, which is why the recurring purchase
                # path deliberately leaves it blank rather than inventing one.
                # Here the fixture IS the supplier, so it may state one.
                "bill_no": f"{c.vendors[d.party % len(c.vendors)].name[:3].upper()}/{n:04d}",
                "bill_date": d.doc_date,
                # `PurchaseBillIn` HAS NO `place_of_supply` — an inward supply
                # is told apart by `is_inter_state`, and the name it was sent
                # under was dropped in silence. No figure moves today (every
                # purchase in this fixture is intra-state) and it would the
                # first time one was not.
                "is_inter_state": d.place_of_supply != c.state_code,
                "is_reverse_charge": d.is_reverse_charge,
                "lines": [{
                    "service_catalogue_id": catalogue[ln.hsn_sac_code],
                    "description": ln.description,
                    "hsn_sac": ln.hsn_sac_code,
                    "quantity": float(ln.quantity),
                    "unit": ln.unit,
                    "rate_paise": ln.rate_paise,
                    "gst_rate_percent": float(ln.gst_rate_percent),
                } for ln in d.lines],
            })
            written["purchase_bills"] += 1
            if _pay(api, d, bill, client_id,
                    vendor_ids[d.party % len(vendor_ids)], bank_id):
                written["payments"] += 1

        _fixed_assets(api, c, client_id, bank_id, firm.financial_year, written)
        _payroll(api, c, client_id, bank_id, written)
        # LAST, because the credits above are known only once every invoice
        # has been written and the engine has told us what each one came to.
        if bank_id and c.banks[0].import_statement:
            _statement(api, c, client_id, bank_id, open_credits, written)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
