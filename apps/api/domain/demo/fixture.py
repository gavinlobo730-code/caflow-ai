"""
A fictional Indian practice with a full year of books — as DATA, not as writes.

WHY A DEMO FIRM IS A BUILD AND NOT A CHORE. The live book is 7 clients and 2
bank accounts with most tables empty, so every screen in this product renders
its empty state and nothing can be judged: a GSTR-1 with no invoices, an
ageing schedule with no documents, a capacity forecast with no tasks, a
concentration panel with one client. The plan's own note — "the demo is what
Track 4 judges and what justifies Track 5".

⚠️ IT IS A FIXTURE, NOT A SEEDER. This module holds no database handle, makes
no HTTP call and writes nothing. `scripts/seed_demo_firm.py` walks it and
POSTs it to a running API.

AND THAT SPLIT IS THE DESIGN DECISION, not an accident of structure. The
obvious seeder writes rows straight into Postgres — and would produce books
this product's own Verify Books would refuse, because every posting in this
schema goes through `services/phase2_journal_service._create_journal` and
nothing else. A demo whose trial balance does not foot is worse than no demo.
So the writer drives the API: the same doors a CA's browser uses, through
`rbac()`, the validators and the posting kernel. Which also means the fixture
needs to know nothing about where a rule lives — several of them (sales
invoice creation among them) are in a ROUTER rather than a service, so an
importing seeder would have had to reach into `routers/`.

EVERY IDENTIFIER IS GENERATED VALID, NEVER INVENTED. `domain/gst/gstin.
checksum_char` computes the fifteenth character, so every GSTIN here passes the
same check the product enforces at nine doors. Three fixture GSTINs already had
to be CORRECTED in this repository's history — `27AAAAA0000A1Z5` among them,
used in 77 files including two frontend placeholders that taught a CA an
example their own keystroke validator rejected. A demo is exactly where that
mistake gets seen.

EVERY AMOUNT IS INTEGER PAISE. The money rule applies to fictional money.

DETERMINISTIC. One fixed seed, so two runs produce the same practice and a test
can pin any figure in it. Nothing here reads the clock — the financial year is
a parameter, because a demo pinned to "now" is a different set of books every
month and a screen showing a locked period cannot be demonstrated at all.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional

from domain.gst.gstin import checksum_char

#: One seed, fixed. Two runs produce the same practice, which is what lets a
#: test assert a figure and a demo be rehearsed.
SEED = 20260401

#: Maharashtra. The practice and most of its clients are in one state so the
#: CGST+SGST split is the ordinary case and the handful of inter-state
#: supplies below are visibly the exception — which is what a GSTR-1 walk-through
#: needs to show.
HOME_STATE = "27"

#: A state the practice supplies INTO, so Table 3.2 and the IGST path are not
#: structurally empty. Karnataka.
AWAY_STATE = "29"


def pan(five_letters: str, four_digits: str, last: str) -> str:
    """A PAN in the Act's own shape — AAAAA9999A. Assembled rather than typed
    so a transposition cannot slip in."""
    return f"{five_letters}{four_digits}{last}"


def gstin_for(state: str, pan_value: str, entity: str = "1") -> str:
    """A GSTIN whose check digit is COMPUTED.

    2-digit state + PAN + entity number + 'Z' + the checksum. Generated rather
    than written down because a valid-shaped wrong GSTIN is the defect this
    codebase has had to correct in its own fixtures, and a demo is where a CA
    copies an example from.
    """
    first_fourteen = f"{state}{pan_value}{entity}Z"
    return first_fourteen + checksum_char(first_fourteen)


# ── The shapes the writer walks ──────────────────────────────────────────────

@dataclass(frozen=True)
class DemoPerson:
    name: str
    email: str
    role: str


@dataclass(frozen=True)
class DemoParty:
    """A customer or a vendor of one client."""
    name: str
    gstin: Optional[str]
    state_code: str
    #: Vendors only. None means the CA has not classified them, which is a real
    #: state the §43B(h) engine names rather than assumes.
    msme_status: Optional[str] = None
    tds_section: Optional[str] = None


@dataclass(frozen=True)
class DemoLine:
    description: str
    hsn_sac_code: str
    quantity: str
    unit: str
    rate_paise: int
    gst_rate_percent: str


@dataclass(frozen=True)
class DemoDocument:
    """One invoice or bill. `party` indexes into the client's own list."""
    doc_date: str
    party: int
    lines: tuple[DemoLine, ...]
    #: Set on the few inter-state documents, so IGST is not structurally nil.
    place_of_supply: str = HOME_STATE
    #: A purchase bill the CA marked as reverse charge (a GTA, an advocate).
    is_reverse_charge: bool = False


@dataclass(frozen=True)
class DemoEmployee:
    name: str
    designation: str
    department: str
    basic_paise: int
    hra_paise: int
    special_paise: int
    pan: str
    doj: str


@dataclass(frozen=True)
class DemoCatalogueItem:
    """One row of a client's product/service catalogue.

    ⚠️ THE CATALOGUE IS NOT DECORATION — IT IS A PRECONDITION, AND ONLY RUNNING
    THE SEEDER FOUND THAT. `client_sales_invoice_lines` and
    `purchase_bill_lines` have required a `service_catalogue_id` since
    migration 206, so an invoice line that names only a description and an HSN
    is refused at the door with *"Product/Service is required on every line
    item … a new client has an empty catalogue until somebody adds to it."*
    The first `POST /api/sales-invoices/` of the first client returned 422 and
    the run stopped there, exactly as it is designed to.

    `kind` is DERIVED from the code rather than tagged, because the product
    already owns that rule: a Service Accounting Code is Chapter 99 of the
    tariff and goods run Chapters 1-98 (`domain/gst/goods_or_services`). A
    second authority here would be one more place to disagree with it."""
    name: str
    hsn_sac_code: str
    unit: str
    rate_paise: int
    gst_rate_percent: str

    @property
    def kind(self) -> str:
        return "service" if self.hsn_sac_code.startswith("99") else "good"

    @property
    def hsn_type(self) -> str:
        """`firm_hsn_library` spells the same fact its own way."""
        return "services" if self.kind == "service" else "goods"


@dataclass(frozen=True)
class DemoClient:
    name: str
    legal_name: str
    entity_type: str
    pan: str
    gstin: Optional[str]
    state_code: str
    #: What this client is FOR in the demo — the screen it makes non-empty.
    #: Written down because a demo whose clients are interchangeable shows one
    #: thing eight times.
    demonstrates: str
    customers: tuple[DemoParty, ...]
    vendors: tuple[DemoParty, ...]
    sales: tuple[DemoDocument, ...]
    purchases: tuple[DemoDocument, ...]
    employees: tuple[DemoEmployee, ...] = ()
    gst_filing_frequency: str = "monthly"
    #: Every item this client's own lines draw from, sales and purchases
    #: together. Deduped on the CODE, which is one-to-one with the item in both
    #: catalogues — so a line resolves its `service_catalogue_id` by HSN with
    #: no second key to keep in step.
    catalogue: tuple[DemoCatalogueItem, ...] = ()


@dataclass(frozen=True)
class DemoFirm:
    name: str
    pan: str
    gstin: str
    state_code: str
    financial_year: str
    people: tuple[DemoPerson, ...]
    clients: tuple[DemoClient, ...]


# ── The catalogue the generated documents draw on ────────────────────────────
#
# Real HSN and SAC codes at their ordinary rates, so a GSTR-1 Table 12 and the
# HSN-digit rule have something true to work on. Six digits throughout: CGST
# Notification 78/2020 requires six above ₹5 crore and four on B2B below it, so
# six satisfies both and the demo never shows a shortfall it did not mean to.

_GOODS = [
    ("Cotton fabric, woven", "520811", "MTR", 24_000, "5"),
    ("Readymade shirts", "620520", "PCS", 89_500, "12"),
    ("Stainless steel utensils", "732393", "PCS", 45_000, "18"),
    ("Packaged biscuits", "190531", "BOX", 12_500, "18"),
    ("Corrugated cartons", "481910", "NOS", 3_400, "12"),
    ("Portland cement", "252329", "TON", 3_85_000, "28"),
]

_SERVICES = [
    ("Management consultancy", "998311", "OTH", 7_50_000, "18"),
    ("Accounting and bookkeeping", "998222", "OTH", 2_50_000, "18"),
    ("Goods transport by road", "996511", "OTH", 1_80_000, "5"),
    ("Legal advisory", "998213", "OTH", 5_00_000, "18"),
    ("Software development", "998314", "OTH", 9_00_000, "18"),
    ("Site construction works", "995414", "OTH", 18_00_000, "18"),
]


def _catalogue(*lists) -> tuple[DemoCatalogueItem, ...]:
    """The union of the catalogues a client's documents are drawn from, in
    first-seen order and deduped on the code. Order is fixed rather than
    sorted so the fixture stays deterministic — the seed is the whole point."""
    seen: dict[str, DemoCatalogueItem] = {}
    for items in lists:
        for name, hsn, unit, rate, gst in items:
            seen.setdefault(hsn, DemoCatalogueItem(name, hsn, unit, rate, gst))
    return tuple(seen.values())


def _fy_months(financial_year: str) -> list[date]:
    """The twelve first-of-months of an Indian financial year, April first."""
    start_year = int(financial_year[:4])
    out = []
    for i in range(12):
        m = 4 + i
        out.append(date(start_year + (0 if m <= 12 else 1), m if m <= 12 else m - 12, 1))
    return out


def _doc_date(rng: random.Random, month: date) -> str:
    """A day inside the month, never the 29th-31st — so February needs no
    special case and no document lands on a date that does not exist."""
    return (month + timedelta(days=rng.randint(0, 27))).isoformat()


def _lines(rng: random.Random, catalogue, count: int) -> tuple[DemoLine, ...]:
    out = []
    for _ in range(count):
        desc, hsn, unit, rate, gst = rng.choice(catalogue)
        # A quantity with up to three decimals — every quantity column in this
        # schema is NUMERIC(10,3) and `domain/quantity` refuses a fourth.
        qty = f"{rng.randint(1, 40)}.000" if unit != "OTH" else "1.000"
        # Vary the rate a little so no two invoices are identical, in whole
        # rupees so the paise arithmetic stays exact.
        varied = rate + rng.randint(-5, 15) * 100
        out.append(DemoLine(
            description=desc, hsn_sac_code=hsn, quantity=qty, unit=unit,
            rate_paise=max(100, varied), gst_rate_percent=gst,
        ))
    return tuple(out)


def _documents(rng: random.Random, months: list[date], parties: int,
               catalogue, per_month: tuple[int, int],
               *, away_every: int = 0,
               reverse_charge_every: int = 0) -> tuple[DemoDocument, ...]:
    """A year of documents, a few each month.

    `away_every` puts every Nth document in another state so IGST and GSTR-1
    Table 3.2 are not structurally empty; `reverse_charge_every` does the same
    for §9(3) purchases, which drive Table 3.1(d), the self-invoice and the
    payment voucher.
    """
    out: list[DemoDocument] = []
    n = 0
    for month in months:
        for _ in range(rng.randint(*per_month)):
            n += 1
            away = away_every and n % away_every == 0
            out.append(DemoDocument(
                doc_date=_doc_date(rng, month),
                party=rng.randrange(parties),
                lines=_lines(rng, catalogue, rng.randint(1, 3)),
                place_of_supply=AWAY_STATE if away else HOME_STATE,
                is_reverse_charge=bool(
                    reverse_charge_every and n % reverse_charge_every == 0),
            ))
    return tuple(sorted(out, key=lambda d: d.doc_date))


# ── The practice ─────────────────────────────────────────────────────────────

_CUSTOMER_NAMES = [
    "Nandini Retail Private Limited", "Gokhale Stores", "Shreyas Traders",
    "Bharat Distributors LLP", "Mahalaxmi Agencies", "Konkan Wholesale",
    "Pune Super Bazaar", "Deccan Supply Company",
]

_VENDOR_NAMES = [
    "Ravindra Packaging Private Limited", "Satara Mills", "Ganesh Transport",
    "Adv. S. R. Kulkarni", "Vaishali Stationers", "Konark Power Solutions",
    "Hinjewadi Facilities LLP", "Nashik Raw Materials",
]

#: MSMED §2(n) classifications. `None` is a REAL third state — an unclassified
#: vendor is NAMED by the §43B(h) engine rather than assumed to be Others, and
#: a demo with none of them cannot show that.
_MSME = ["micro", "small", "medium", None, "small", None, "micro", "medium"]

#: The §194 sections a practice actually withholds under. None means no
#: withholding on that vendor.
_TDS = ["194C", "194J", None, "194J", None, "194I", "194C", None]


def _parties(rng: random.Random, names: list[str], state: str, count: int,
             *, as_vendor: bool) -> tuple[DemoParty, ...]:
    out = []
    for i in range(count):
        name = names[i % len(names)]
        # One party in every set is UNREGISTERED — a real thing, and what makes
        # the B2C tables and `rcm_documents`' §31(3)(f) branch non-empty.
        unregistered = i == count - 1
        letters = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))
        digits = f"{rng.randint(1000, 9999)}"
        p = pan(letters, digits, rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"))
        out.append(DemoParty(
            name=name,
            gstin=None if unregistered else gstin_for(state, p),
            state_code=state,
            msme_status=_MSME[i % len(_MSME)] if as_vendor else None,
            tds_section=_TDS[i % len(_TDS)] if as_vendor else None,
        ))
    return tuple(out)


def _employees(rng: random.Random, count: int, doj: str) -> tuple[DemoEmployee, ...]:
    people = [
        ("Rohan Kulkarni", "Production Supervisor", "Operations", 32_000_00),
        ("Sneha Patil", "Accounts Executive", "Finance", 28_000_00),
        ("Imran Shaikh", "Machine Operator", "Operations", 18_500_00),
        ("Anita Joshi", "Quality Analyst", "Operations", 24_000_00),
        ("Vikram Rao", "Plant Manager", "Operations", 65_000_00),
        ("Fatima Ansari", "HR Executive", "Administration", 26_000_00),
        # Deliberately below the ESI ₹21,000 ceiling and below the Bonus Act
        # §2(13) ₹21,000 one, so both engines have somebody they REACH and
        # somebody they do not.
        ("Sunil Gaikwad", "Helper", "Operations", 12_000_00),
        ("Priya Nair", "Finance Controller", "Finance", 95_000_00),
    ]
    out = []
    for i in range(count):
        name, desig, dept, basic = people[i % len(people)]
        letters = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5))
        out.append(DemoEmployee(
            name=name, designation=desig, department=dept,
            basic_paise=basic,
            # HRA at 40% of basic (the metro rate §10(13A) and Rule 2A turn on)
            # and the balance as special allowance — the shape a real Indian
            # salary structure takes, and what makes the §192 working readable.
            hra_paise=(basic * 40) // 100,
            special_paise=(basic * 25) // 100,
            pan=pan(letters, f"{rng.randint(1000, 9999)}",
                    rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")),
            doj=doj,
        ))
    return tuple(out)


def build(financial_year: str = "2025-26") -> DemoFirm:
    """The practice, for one financial year.

    The YEAR IS A PARAMETER and nothing here reads the clock: a demo pinned to
    "now" is a different set of books every month, and a locked period — which
    is half of what makes this product's accounting worth showing — cannot be
    demonstrated at all if every date is recent.
    """
    rng = random.Random(SEED)
    months = _fy_months(financial_year)

    firm_pan = pan("AACFS", "4821", "K")

    def client(name, legal, entity, pan_value, *, demonstrates,
               state=HOME_STATE, registered=True, customers=4, vendors=4,
               sales_catalogue=_GOODS, purchase_catalogue=_GOODS,
               sales_per_month=(2, 5), purchases_per_month=(1, 4),
               away_every=7, rcm_every=0, employees=0,
               frequency="monthly") -> DemoClient:
        return DemoClient(
            name=name, legal_name=legal, entity_type=entity, pan=pan_value,
            gstin=gstin_for(state, pan_value) if registered else None,
            state_code=state,
            demonstrates=demonstrates,
            customers=_parties(rng, _CUSTOMER_NAMES, state, customers, as_vendor=False),
            vendors=_parties(rng, _VENDOR_NAMES, state, vendors, as_vendor=True),
            sales=_documents(rng, months, customers, sales_catalogue,
                             sales_per_month, away_every=away_every),
            purchases=_documents(rng, months, vendors, purchase_catalogue,
                                 purchases_per_month,
                                 reverse_charge_every=rcm_every),
            employees=_employees(rng, employees, f"{financial_year[:4]}-04-01"),
            gst_filing_frequency=frequency,
            catalogue=_catalogue(sales_catalogue, purchase_catalogue),
        )

    clients = (
        client("Anand Textiles", "Anand Textiles Private Limited",
               "Private Limited", pan("AABCA", "7412", "M"),
               demonstrates="the ordinary monthly GST client — the volume "
                            "every return screen, ageing schedule and "
                            "reconciliation is judged on",
               customers=6, vendors=5, sales_per_month=(4, 8)),
        client("Kavya Consulting", "Kavya Consulting LLP", "LLP",
               pan("AAGFK", "3159", "R"),
               demonstrates="QRMP — Rule 61A quarterly returns with monthly "
                            "payment, which the return builder handles "
                            "differently and no other client here exercises",
               sales_catalogue=_SERVICES, purchase_catalogue=_SERVICES,
               customers=3, vendors=3, frequency="quarterly"),
        client("Meher Enterprises", "Meher Enterprises", "Proprietorship",
               pan("AFXPM", "9026", "D"),
               demonstrates="a proprietor — the §44AD presumptive path and an "
                            "ITR-4, where the entity type is the whole "
                            "difference",
               customers=4, vendors=3, sales_per_month=(2, 4)),
        client("Rathod Logistics", "Rathod Logistics Private Limited",
               "Private Limited", pan("AAECR", "5583", "N"),
               demonstrates="reverse charge — a goods transport agency, so "
                            "§9(3), Table 3.1(d), the self-invoice and the "
                            "payment voucher are not structurally nil",
               sales_catalogue=_SERVICES, purchase_catalogue=_SERVICES,
               customers=5, vendors=4, rcm_every=3),
        client("Sunrise Foods", "Sunrise Foods Private Limited",
               "Private Limited", pan("AADCS", "6647", "P"),
               demonstrates="payroll and inventory — eight employees spanning "
                            "the ESI and Bonus Act ceilings, so both engines "
                            "have somebody they reach and somebody they do not",
               customers=5, vendors=5, employees=8, sales_per_month=(3, 6)),
        client("Deshmukh & Sons", "Deshmukh and Sons", "Partnership",
               pan("AAJFD", "2274", "L"),
               demonstrates="a firm — §184 partner remuneration, §194T on a "
                            "partner payment, and the firm rate the entity "
                            "registry holds",
               customers=3, vendors=3, sales_per_month=(1, 3)),
        client("Priya Sharma", "Priya Sharma", "Individual",
               pan("AKQPS", "1138", "F"),
               demonstrates="an individual below the registration threshold — "
                            "salary, capital gains and the §115BAC election, "
                            "with no GSTIN at all",
               registered=False, customers=2, vendors=2,
               sales_per_month=(0, 1), purchases_per_month=(0, 1),
               away_every=0),
        client("Vaibhav Infra", "Vaibhav Infra Private Limited",
               "Private Limited", pan("AAGCV", "8890", "T"),
               demonstrates="construction — capital work in progress, its "
                            "Schedule III line and its ageing schedule, which "
                            "nothing else here produces",
               sales_catalogue=_SERVICES, purchase_catalogue=_SERVICES,
               customers=3, vendors=5, employees=4),
    )

    return DemoFirm(
        name="Sharma & Associates",
        pan=firm_pan,
        gstin=gstin_for(HOME_STATE, firm_pan),
        state_code=HOME_STATE,
        financial_year=financial_year,
        people=(
            DemoPerson("Rajesh Sharma", "rajesh@sharma-associates.example", "Partner"),
            DemoPerson("Neha Deshpande", "neha@sharma-associates.example", "Manager"),
            DemoPerson("Aditya Kale", "aditya@sharma-associates.example", "Executive"),
            DemoPerson("Sanjana Iyer", "sanjana@sharma-associates.example", "Reviewer"),
        ),
        clients=clients,
    )


def summary(firm: DemoFirm) -> dict:
    """What the fixture holds, for the writer's dry run and the plan's own
    count. Derived, never stated — a written-down total drifts the first time a
    client is added."""
    return {
        "firm": firm.name,
        "financial_year": firm.financial_year,
        "people": len(firm.people),
        "clients": len(firm.clients),
        "customers": sum(len(c.customers) for c in firm.clients),
        "vendors": sum(len(c.vendors) for c in firm.clients),
        "sales_invoices": sum(len(c.sales) for c in firm.clients),
        "purchase_bills": sum(len(c.purchases) for c in firm.clients),
        "employees": sum(len(c.employees) for c in firm.clients),
        "reverse_charge_bills": sum(
            1 for c in firm.clients for d in c.purchases if d.is_reverse_charge),
        "inter_state_sales": sum(
            1 for c in firm.clients for d in c.sales
            if d.place_of_supply != HOME_STATE),
        "unregistered_parties": sum(
            1 for c in firm.clients
            for p in (*c.customers, *c.vendors) if p.gstin is None),
    }
