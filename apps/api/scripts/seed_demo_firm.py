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
        out = self._request("POST", path, body)
        # THE ENVELOPE IS CHECKED, ALWAYS. Several routers in this product
        # answer a refusal as HTTP 200 with `{"success": false}` — the GST
        # workspace notably — so a seeder trusting the status code would
        # report a practice it had not written.
        if isinstance(out, dict) and out.get("success") is False:
            raise SystemExit(
                f"\nPOST {path} was refused: {out.get('error')}\n"
                "The HTTP status was 200; this product answers some refusals "
                "that way, which is why the envelope is checked."
            )
        return out


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
            client_id: str, customer_id: str) -> bool:
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
        "allocations": [{"sales_invoice_id": _id(invoice),
                         "allocated_paise": settled}],
    })
    return True


def _pay(api: Api, doc, bill: dict, client_id: str, vendor_id: str) -> bool:
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
    })
    return True


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
               "customers": 0, "vendors": 0,
               "sales_invoices": 0, "receipts": 0,
               "purchase_bills": 0, "payments": 0, "employees": 0}

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
                "msme_status": p.msme_status,
                "tds_section": p.tds_section,
                # THE THIRD STATE, DELIBERATELY. `rcm_documents` reads NULL as
                # *unrecorded* and names it as a gap rather than guessing, so a
                # demo where every vendor is classified cannot show that
                # branch. An unregistered party (no GSTIN) is left unrecorded.
                "gst_registration_status": "registered" if p.gstin else None,
            })))
            written["vendors"] += 1

        for n, d in enumerate(c.sales, start=1):
            invoice = api.post("/api/sales-invoices/", {
                "client_id": client_id,
                "customer_id": customer_ids[d.party % len(customer_ids)],
                # The series a real practice runs: a prefix, the FY, a padded
                # counter. `domain/gst/invoice_series` enforces Rule 46(b)'s
                # sixteen characters and character set at the door, so this
                # has to satisfy it — 'INV/2025-26/0001' is 16 exactly.
                "invoice_no": f"INV/{firm.financial_year}/{n:04d}",
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
                       customer_ids[d.party % len(customer_ids)]):
                written["receipts"] += 1

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
                "place_of_supply": d.place_of_supply,
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
                    vendor_ids[d.party % len(vendor_ids)]):
                written["payments"] += 1

        for e in c.employees:
            api.post("/api/payroll/employees", {
                "client_id": client_id, "name": e.name,
                "designation": e.designation, "department": e.department,
                "pan": e.pan, "date_of_joining": e.doj,
                "basic_paise": e.basic_paise, "hra_paise": e.hra_paise,
                "special_allowance_paise": e.special_paise,
            })
            written["employees"] += 1

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
