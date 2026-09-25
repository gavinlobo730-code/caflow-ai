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
from dataclasses import dataclass, replace, field
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
    #: MSMED §15's proviso: a payment period agreed IN WRITING. NULL is the
    #: statutory default of fifteen days from acceptance (§2(b)), not an
    #: absence — forty-five is the number every article quotes and it is the
    #: EXCEPTION, so most vendors here carry None and one per client does not.
    msmed_agreement_days: Optional[int] = None
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
class DemoSettlement:
    """How and when a document was paid — or that it was not.

    ⚠️ A BOOK WHERE NOTHING IS PAID TEACHES A CA NOTHING, and that is what
    this fixture produced before: 315 invoices and 200 bills, every one of
    them outstanding in full. Receivables was a wall of "current", the
    collections queue had no age to sort by, `outstanding_paise` equalled
    `total_paise` on every row so `FindMatchModal`'s "· ₹X open" never
    rendered, the bank had nothing to match against, and §43B(h) reported
    EVERY purchase as unpaid — a screen that flags everything flags nothing.

    So the pattern is deliberately MIXED, and each branch exists to make one
    screen say something a CA can read:

      · most settled in full, 25-55 days out   → the ordinary book
      · some settled in PART                   → an open balance that is not
                                                 the face value, which is the
                                                 one case the matcher's own
                                                 `outstanding_paise` band and
                                                 the settlement modal exist for
      · an OLD tail left unpaid                → the 90+ ageing bucket, which
                                                 is what a CA actually opens
                                                 Receivables to find
      · the last two months unpaid             → "current", the normal state
                                                 of a recent invoice

    `fraction_bps` is basis points of the document's OWN total, which the
    seeder reads off the create response rather than recomputing — the GST is
    the engine's answer and a second copy of that arithmetic here is the
    mistake this repository keeps recording."""
    #: Days after the document date. None means it was never paid.
    paid_after_days: Optional[int]
    fraction_bps: int = 10_000
    #: TDS the CUSTOMER withheld (§194C/§194J). Sales only — on a purchase the
    #: client is the deductor and the tax comes off at the BILL, not the
    #: payment, which is why `PurchasePaymentIn` has no such field.
    tds_bps: int = 0


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
    #: None on a document nobody has paid. See DemoSettlement.
    settlement: Optional[DemoSettlement] = None


@dataclass(frozen=True)
class DemoEmployee:
    """One person on a client's payroll.

    ⚠️ `hra_percent`, NOT an HRA amount, and that was a real defect in the
    first version of this fixture. `EmployeeIn` carries `hra_percent: float`
    and has no `hra_paise` field at all, so the amount this used to send was
    silently DROPPED by Pydantic and every seeded employee was stored with
    `hra_percent = 0.0` — a §192 working with no house rent allowance in it,
    on a screen built to show exactly that. `joining_date` went the same way,
    sent as `date_of_joining`. Both are named here as the model names them, so
    the seeder cannot rename one on the way out.

    The BANK pair and the UAN are here because two statutory outputs refuse
    without them: `domain/payroll/bank_advice.py` NAMES every employee it
    leaves out of the salary file (no account, no IFSC, a malformed IFSC), and
    `domain/payroll/ecr.py` refuses a member with no UAN at file build. A demo
    whose every employee is named as a gap shows neither output working."""
    name: str
    designation: str
    department: str
    basic_paise: int
    #: Of BASIC. 40% is the metro rate §10(13A) and Rule 2A turn on.
    hra_percent: float
    special_paise: int
    pan: str
    doj: str
    employee_code: str
    uan: str
    bank_account_no: str
    bank_ifsc: str
    bank_name: str


@dataclass(frozen=True)
class DemoAsset:
    """One row of a client's fixed-asset register.

    THE CATEGORY IS THE STATUTORY KEY, not a label. `routers/fixed_assets`
    resolves the Companies Act 2013 Schedule II Part C useful LIFE from it and
    DERIVES the WDV rate as `R = 1 − (residual/cost)^(1/n)`, so a category with
    no Part C class is REFUSED rather than given a plausible rate. Every
    category named here is one `domain/fixed_assets/schedule_ii.PART_C` holds.

    Three of the assets below exist to make a branch visible rather than to
    add volume:

      · one is LAND, which `_NOT_DEPRECIABLE` excludes entirely — a register
        where everything depreciates cannot show that it asked;
      · one is a motor car whose input tax CGST §17(5) blocks, so the tax is
        CAPITALISED into the cost and depreciates, which is the one case
        `capitalised_cost_paise` exists for and the reason `itc_eligible`
        cannot be defaulted;
      · the methods are mixed, because SL divides by the life and WDV runs the
        derived rate down to a floor, and a register of one method shows one.
    """
    name: str
    category: str
    purchase_date: str
    cost_paise: int
    method: str = "WDV"                       # "SL" | "WDV"
    salvage_value_paise: int = 0
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    #: None = the CA has not said. False = §17(5) blocked, so the tax is part
    #: of the cost. Never defaulted — see the class docstring.
    itc_eligible: Optional[bool] = None
    itc_blocked_reason: Optional[str] = None
    location: Optional[str] = None


@dataclass(frozen=True)
class DemoBankAccount:
    """A bank account of one client, and the ledger behind it.

    `coa_account_id` is deliberately NOT here: `POST /api/banking/accounts`
    creates a ledger for an unlinked account rather than defaulting to "not
    linked", which is how two banks came to share code 1101 and render as one
    line. Letting it do that is the demonstration.
    """
    bank_name: str
    account_no: str
    ifsc: str
    account_type: str = "Current"
    opening_balance_paise: int = 0
    #: A statement is imported for this account. False on the credit card —
    #: see DemoBankLine.
    import_statement: bool = True


@dataclass(frozen=True)
class DemoBankLine:
    """One line of a bank statement — and one the BOOKS DO NOT ALREADY HOLD.

    ⚠️ THE STATEMENT CARRIES NO LINE FOR A RECEIPT OR A PAYMENT THIS FIXTURE
    HAS ALREADY RECORDED, and that is a decision rather than an omission.
    Passing a statement line CREATES a voucher — `domain/banking` turns a
    credit into a Receipt and a debit into a Payment — so a line for money the
    ledger already carries invites the CA to record the same rupees twice, on
    the very screen the demo is meant to sell. Linking each one instead
    (`POST /transactions/{id}/match` is linkage only and posts nothing) would
    be one extra call per settled document for no screen that is not already
    populated by the lines below.

    So what IS here is exactly what an unworked statement holds: the ordinary
    operating outflows nobody has coded — rent, electricity, internet, courier
    and the bank's own charges, which carry GST and are BANK-24's whole point
    — and a few customer credits against invoices the fixture left OPEN, which
    is what gives the match queue a real candidate to offer. The
    reconciliation then reports a difference, honestly, because that is the
    state of every bank account somebody has not finished working.

    ⚠️ AND NO STATEMENT IS IMPORTED FOR THE CREDIT CARD. A card states the
    amount OWED the other way up, and `account_kind.mirror_imported_statement`
    is applied on the UPLOAD path — `POST /statements/import` takes
    already-parsed rows and does not mirror them, so a card statement sent
    through this door would carry every sign inverted. The card ACCOUNT is
    created (its ledger is a liability, and that is what Schedule III and the
    register are being shown) and its statement is not.
    """
    line_date: str
    description: str
    amount_paise: int
    is_credit: bool = False
    #: Basis points of GST inside the amount, where the CA can tell. Only the
    #: bank's own charges carry one — `bank_charge_gst` reads exactly this and
    #: a RECORDED ZERO declares nothing, so every other line leaves it None.
    gst_rate_bps: Optional[int] = None


@dataclass(frozen=True)
class DemoPayrollMonth:
    """One month of payroll, and how far it is taken.

    THE THREE STATES ARE ALL PRESENT ON PURPOSE. A run left at `draft` has
    posted no journal, registered no §192 TDS and paid nobody — it is the
    state the recompute and delete paths exist for (PAY-04, PAY-21) and the
    only state in which the attendance can still be corrected. `finalized` has
    posted the accrual and is immutable. `paid` has also cleared Net Salary
    Payable against the bank. A demo showing one state cannot show that any of
    that is a sequence.
    """
    month: str                                      # YYYY-MM
    #: (employee index, days of loss of pay). Empty means a full month for
    #: everybody — which is a CLAIM, and the reason attendance is written
    #: rather than left to `_compute_slip`'s 26-day default: a zero LOP because
    #: somebody confirmed it and a zero LOP because nobody said anything are
    #: the same number meaning opposite things.
    lop: tuple[tuple[int, int], ...] = ()
    leave_at: str = "paid"                          # draft | finalized | paid


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
    #: The client's own bank accounts. The FIRST is the one every receipt,
    #: vendor payment, asset purchase and salary disbursement names, so the
    #: money lands in that client's own ledger rather than falling through
    #: `resolve_payment_account`'s generic `%Bank%` branch — which is a real
    #: fallback with a real disclosure (`posting_account_notice`), and a demo
    #: in which EVERY posting carries it teaches that the notice is noise.
    banks: tuple[DemoBankAccount, ...] = ()
    #: Statement lines for the first bank account. See DemoBankLine.
    bank_lines: tuple[DemoBankLine, ...] = ()
    assets: tuple[DemoAsset, ...] = ()
    payroll: tuple[DemoPayrollMonth, ...] = ()
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
               *, away_every: int = 0, tds_bps: int = 0,
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
    docs = sorted(out, key=lambda d: d.doc_date)

    # ── SETTLED IN A SECOND PASS, ON ITS OWN RANDOM, AND THAT IS THE POINT ──
    #
    # Drawing the settlement inside the loop above would consume from `rng`
    # between the draws that pick the date, the party and the lines — so
    # adding payments would have silently RESHUFFLED every document in the
    # fixture. It did, on the first attempt: purchase bills went 200 → 236
    # and every existing count in the tests and the plan became wrong for a
    # change that was supposed to be purely additive.
    #
    # The second stream is seeded from facts about the document set that are
    # already fixed — its length and its first date — so it is deterministic,
    # differs per client, and consumes nothing from `rng`.
    #: The last two months are left OUTSTANDING whatever the dice say: an
    #: invoice raised in February is not overdue in March, and a book where
    #: even the newest document is settled reads as fabricated.
    recent = {m.isoformat()[:7] for m in months[-2:]}
    srng = random.Random(SEED + len(docs) * 7919
                         + sum(ord(ch) for ch in (docs[0].doc_date if docs else "")))
    return tuple(
        replace(d, settlement=_settlement(srng, d.doc_date[:7] in recent,
                                          tds_bps=tds_bps))
        for d in docs
    )


def _settlement(rng: random.Random, is_recent: bool, *,
                tds_bps: int = 0) -> Optional[DemoSettlement]:
    """One document's payment story. See DemoSettlement for why it is mixed.

    The proportions are chosen to leave every ageing bucket populated and
    none of them dominant: roughly three quarters of the older documents
    settled, one in eight settled in part, one in eight never — which on a
    year of invoices puts a readable number in 90+ without making the client
    look insolvent."""
    if is_recent:
        return None                                  # current, not yet due
    roll = rng.random()
    if roll < 0.75:
        return DemoSettlement(paid_after_days=rng.randint(25, 55),
                              tds_bps=tds_bps)
    if roll < 0.875:
        # Part-paid: the case where `outstanding_paise` is neither the face
        # value nor nil, which is the only one the matcher's band and the
        # settlement modal's "· ₹X open" are built for.
        return DemoSettlement(paid_after_days=rng.randint(30, 70),
                              fraction_bps=rng.randrange(3_500, 7_500, 500),
                              tds_bps=tds_bps)
    return None                                      # the 90+ tail


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
            msmed_agreement_days=(45 if (as_vendor and i == 1) else None),
            tds_section=_TDS[i % len(_TDS)] if as_vendor else None,
        ))
    return tuple(out)


def _employees(rng: random.Random, count: int, doj: str,
               *, code_prefix: str) -> tuple[DemoEmployee, ...]:
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
    #: Real-shaped IFSCs — four letters, a zero, six alphanumerics, which is
    #: `domain/payroll/identity.IFSC_RE` and what the ECR and the bank advice
    #: both refuse without.
    ifscs = ["HDFC0001234", "ICIC0004421", "SBIN0007788", "UTIB0000915",
             "KKBK0006630", "BARB0PUNEXX", "MAHB0001102", "PUNB0123400"]
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
            hra_percent=40.0,
            special_paise=(basic * 25) // 100,
            pan=pan(letters, f"{rng.randint(1000, 9999)}",
                    rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")),
            doj=doj,
            employee_code=f"{code_prefix}{i + 1:03d}",
            # Twelve digits, which is all EPFO's own format is. Derived from
            # the index rather than drawn, so the roster is stable whatever
            # else is added to the fixture before it.
            uan=f"1006{i + 11:04d}{i + 3:04d}",
            bank_account_no=f"{50100000 + i * 137:08d}{i + 1:03d}",
            bank_ifsc=ifscs[i % len(ifscs)],
            bank_name="HDFC Bank" if i % 2 == 0 else "State Bank of India",
        ))
    return tuple(out)


def _asset_date(months: list[date], month_index: int, day: int) -> str:
    """A date inside the financial year, addressed by month rather than typed.

    Nothing in this module reads the clock, so an asset cannot carry a literal
    date and still move with `financial_year`. `month_index` 0 is April; a
    NEGATIVE index is a year the asset was ALREADY held, which is what gives
    the movement note an opening gross block rather than a register in which
    every asset was bought this year."""
    m = months[month_index % 12]
    year = m.year + (month_index // 12)
    return date(year, m.month, day).isoformat()


def _bank_lines(months: list[date], spec) -> tuple[DemoBankLine, ...]:
    """A year of the operating outflows nobody has coded yet.

    `spec` is (description, day of month, amount in paise, GST bps or None).
    Every month gets every line, because rent and electricity do — the
    variation a demo needs is in the CODING, not in whether the landlord was
    paid."""
    out = []
    for m in months:
        for desc, day, amount, gst in spec:
            out.append(DemoBankLine(
                line_date=date(m.year, m.month, day).isoformat(),
                description=desc, amount_paise=amount,
                is_credit=False, gst_rate_bps=gst))
    return tuple(sorted(out, key=lambda r: (r.line_date, r.description)))


def _payroll_months(months: list[date], *, employees: int) -> tuple[DemoPayrollMonth, ...]:
    """Twelve months, left in three different states — see DemoPayrollMonth.

    The last month is a DRAFT, the one before it FINALIZED and every earlier
    one PAID. Reading forward that is exactly where a practice stands partway
    through the month after the year end: last month's accrual posted and not
    yet disbursed, this month still being computed."""
    out = []
    for n, m in enumerate(months):
        if n == len(months) - 1:
            leave_at = "draft"
        elif n == len(months) - 2:
            leave_at = "finalized"
        else:
            leave_at = "paid"
        # Two months with real loss of pay, so `month_on_month` has a movement to
        # explain and the payslip is not the same document twelve times.
        lop: tuple[tuple[int, int], ...] = ()
        if n == 4 and employees > 2:
            lop = ((2, 3),)
        elif n == 8 and employees > 5:
            lop = ((5, 2), (2, 1))
        out.append(DemoPayrollMonth(month=m.isoformat()[:7], lop=lop,
                                    leave_at=leave_at))
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
               away_every=7, rcm_every=0, employees=0, sales_tds_bps=0,
               frequency="monthly", banks=(), operating_lines=(),
               assets=()) -> DemoClient:
        return DemoClient(
            name=name, legal_name=legal, entity_type=entity, pan=pan_value,
            gstin=gstin_for(state, pan_value) if registered else None,
            state_code=state,
            demonstrates=demonstrates,
            customers=_parties(rng, _CUSTOMER_NAMES, state, customers, as_vendor=False),
            vendors=_parties(rng, _VENDOR_NAMES, state, vendors, as_vendor=True),
            sales=_documents(rng, months, customers, sales_catalogue,
                             sales_per_month, away_every=away_every,
                             tds_bps=sales_tds_bps),
            purchases=_documents(rng, months, vendors, purchase_catalogue,
                                 purchases_per_month,
                                 reverse_charge_every=rcm_every),
            # ⚠️ CALLED HERE, AFTER `_documents`, AND THE POSITION IS LOAD-
            # BEARING. `_employees` draws from the shared `rng`, and Python
            # evaluates a call's arguments in order — so lifting it to a local
            # above this constructor moved every later draw and silently
            # reshuffled the whole practice: sales went 315 → 314 and purchase
            # bills 200 → 209 on a change that added no document. Same trap
            # `_documents` records for the settlement stream, one level up.
            employees=_employees(rng, employees, f"{financial_year[:4]}-04-01",
                                 code_prefix=f"{name[:3].upper()}-"),
            banks=banks,
            bank_lines=_bank_lines(months, operating_lines) if banks else (),
            assets=assets,
            # A month of payroll needs somebody to pay. The states the months
            # are left in are the engine's own (see _payroll_months); nothing
            # here chooses per client, because a demo in which one client's
            # payroll is ahead of another's teaches nothing and hides the
            # sequence that does.
            payroll=_payroll_months(months, employees=employees) if employees else (),
            gst_filing_frequency=frequency,
            catalogue=_catalogue(sales_catalogue, purchase_catalogue),
        )

    def asset(name, category, month_index, day, cost, method="WDV",
              **kw) -> DemoAsset:
        """One asset, dated by its MONTH OF THE FINANCIAL YEAR rather than by
        a literal — 0 is April, 8 is December, and a NEGATIVE index is a year
        the client already held it. Nothing in this module may read a clock and
        `financial_year` is a parameter, so a typed date would pin the whole
        register to one year."""
        return DemoAsset(name=name, category=category,
                         purchase_date=_asset_date(months, month_index, day),
                         cost_paise=cost, method=method, **kw)

    # ── The operating outflows that reach the BANK and not the books ────────
    #
    # These are the lines a CA actually works on the bank screen: rent, power,
    # connectivity, courier, and the bank's own charges — the last carrying
    # GST, which is the whole of BANK-24 (a credit the CA declares on a bank
    # line reaches Table 4(A)(5), and used to reach nothing). Whole rupees, so
    # the paise arithmetic downstream is exact.
    _FACTORY_OUTFLOWS = (
        ("Rent - Hinjewadi Facilities LLP", 5, 1_75_000_00, None),
        ("MSEDCL electricity - factory", 9, 62_400_00, None),
        ("Airtel broadband and leased line", 12, 4_130_00, None),
        ("Blue Dart courier - consignments", 18, 2_360_00, None),
        ("Bank charges - NEFT, collection and folio", 27, 1_180_00, 1_800),
    )
    _OFFICE_OUTFLOWS = (
        ("Rent - office premises", 5, 85_000_00, None),
        ("MSEDCL electricity - office", 9, 14_800_00, None),
        ("Bank charges - NEFT and folio", 27, 826_00, 1_800),
    )
    _SMALL_OUTFLOWS = (
        ("Rent - shop premises", 5, 28_000_00, None),
        ("Bank charges - folio and cheque book", 27, 354_00, 1_800),
    )

    clients = (
        client("Anand Textiles", "Anand Textiles Private Limited",
               "Private Limited", pan("AABCA", "7412", "M"),
               demonstrates="the ordinary monthly GST client — the volume "
                            "every return screen, ageing schedule and "
                            "reconciliation is judged on",
               customers=6, vendors=5, sales_per_month=(4, 8),
               banks=(
                   DemoBankAccount("HDFC Bank", "50200041178822", "HDFC0001234",
                                   opening_balance_paise=8_50_000_00),
                   # THE CARD, AND NO STATEMENT FOR IT — see DemoBankLine.
                   # Its ledger is a LIABILITY, which is the whole of BANK-21
                   # and what the register's sign convention and the Schedule
                   # III caption are being shown.
                   DemoBankAccount("HDFC Bank Business Regalia", "4854980011223344",
                                   "HDFC0001234", account_type="Credit Card",
                                   opening_balance_paise=1_42_600_00,
                                   import_statement=False),
               ),
               operating_lines=_FACTORY_OUTFLOWS,
               assets=(
                   # Held since the year before, so the movement note opens
                   # with a gross block rather than starting from nil.
                   asset("Factory building - Bhiwandi", "Building", -18, 1,
                         4_20_00_000_00, "SL"),
                   asset("Sulzer rapier looms (6)", "Plant & Machinery", -6, 12,
                         1_85_00_000_00),
                   asset("Warping and sizing line", "Plant & Machinery", 1, 8,
                         42_00_000_00),
                   asset("Office computers and printers", "Computer & IT Equipment",
                         3, 21, 2_40_000_00),
                   # §17(5)(a) blocks the credit on a motor car for personal
                   # carriage, so the ₹4,32,000 of tax is CAPITALISED and
                   # depreciates. The one asset in the register whose cost is
                   # not the figure on the invoice line.
                   asset("Toyota Innova - director", "Vehicles", 5, 14,
                         24_00_000_00,
                         igst_paise=0, cgst_paise=2_16_000_00,
                         sgst_paise=2_16_000_00, itc_eligible=False,
                         itc_blocked_reason="CGST §17(5)(a) — motor vehicle for "
                                            "the transport of persons, seating "
                                            "capacity not more than thirteen"),
               )),
        client("Kavya Consulting", "Kavya Consulting LLP", "LLP",
               pan("AAGFK", "3159", "R"),
               demonstrates="QRMP — Rule 61A quarterly returns with monthly "
                            "payment, which the return builder handles "
                            "differently and no other client here exercises",
               sales_catalogue=_SERVICES, purchase_catalogue=_SERVICES,
               customers=3, vendors=3, frequency="quarterly",
               # ITS CUSTOMERS WITHHOLD §194J, and nothing else here does.
               # A receipt carrying `tds_paise` settles amount + TDS (§198
               # deems the tax received, §199 gives the credit), so this is
               # the only client whose TDS Receivable is not structurally nil
               # and the only one where a ₹1,00,000 invoice is shown fully
               # settled by a ₹90,000 bank credit — the behaviour SALES-07
               # built and no screen exercised.
               sales_tds_bps=1_000,
               banks=(DemoBankAccount("ICICI Bank", "000705001234", "ICIC0000007",
                                      opening_balance_paise=3_20_000_00),),
               operating_lines=_OFFICE_OUTFLOWS,
               assets=(
                   asset("MacBook Pro fleet (4)", "Computer & IT Equipment",
                         0, 18, 9_60_000_00),
                   asset("Workstations and storage", "Furniture & Fixtures",
                         2, 6, 3_40_000_00, "SL"),
               )),
        client("Meher Enterprises", "Meher Enterprises", "Proprietorship",
               pan("AFXPM", "9026", "D"),
               demonstrates="a proprietor — the §44AD presumptive path and an "
                            "ITR-4, where the entity type is the whole "
                            "difference",
               customers=4, vendors=3, sales_per_month=(2, 4),
               banks=(DemoBankAccount("Bank of Maharashtra", "60123456789",
                                      "MAHB0000456",
                                      opening_balance_paise=1_40_000_00),),
               operating_lines=_SMALL_OUTFLOWS,
               assets=(
                   asset("Delivery scooter", "Vehicles", 4, 9, 95_000_00),
               )),
        client("Rathod Logistics", "Rathod Logistics Private Limited",
               "Private Limited", pan("AAECR", "5583", "N"),
               demonstrates="reverse charge — a goods transport agency, so "
                            "§9(3), Table 3.1(d), the self-invoice and the "
                            "payment voucher are not structurally nil",
               sales_catalogue=_SERVICES, purchase_catalogue=_SERVICES,
               customers=5, vendors=4, rcm_every=3,
               banks=(DemoBankAccount("Axis Bank", "918020033445566", "UTIB0000915",
                                      opening_balance_paise=6_10_000_00),),
               operating_lines=_OFFICE_OUTFLOWS,
               assets=(
                   # Schedule II Part C gives a lorry RUN ON HIRE six years
                   # against eight for one that is not, and this client's
                   # whole business is running them on hire — the category
                   # decides the life, so it is not a label.
                   asset("Tata LPT 1618 tipper", "Vehicles", -9, 3, 28_50_000_00),
                   asset("Ashok Leyland Dost (2)", "Vehicles", 2, 17, 17_20_000_00),
                   asset("Forklift - Pune depot", "Plant & Machinery", 6, 4,
                         6_50_000_00),
                   asset("Weighbridge and office equipment", "Office Equipment",
                         7, 22, 1_20_000_00, "SL"),
               )),
        client("Sunrise Foods", "Sunrise Foods Private Limited",
               "Private Limited", pan("AADCS", "6647", "P"),
               demonstrates="payroll and inventory — eight employees spanning "
                            "the ESI and Bonus Act ceilings, so both engines "
                            "have somebody they reach and somebody they do not",
               customers=5, vendors=5, employees=8, sales_per_month=(3, 6),
               banks=(DemoBankAccount("State Bank of India", "38104455662",
                                      "SBIN0007788",
                                      opening_balance_paise=11_75_000_00),),
               operating_lines=_FACTORY_OUTFLOWS,
               assets=(
                   asset("Cold storage - Ranjangaon", "Building", -24, 1,
                         1_50_00_000_00, "SL"),
                   # Part C gives a continuous process plant 25 years against
                   # the general rate's 15 — the second class under one
                   # category, which is why the table is a list per category
                   # and not a number.
                   asset("Packaging and sealing line", "Plant & Machinery",
                         -3, 20, 3_40_00_000_00),
                   asset("Blast freezer", "Plant & Machinery", 1, 11,
                         28_00_000_00),
                   asset("Plant computers and weighing scales",
                         "Computer & IT Equipment", 4, 26, 3_10_000_00),
               )),
        client("Deshmukh & Sons", "Deshmukh and Sons", "Partnership",
               pan("AAJFD", "2274", "L"),
               demonstrates="a firm — §184 partner remuneration, §194T on a "
                            "partner payment, and the firm rate the entity "
                            "registry holds",
               customers=3, vendors=3, sales_per_month=(1, 3),
               banks=(DemoBankAccount("Bank of Baroda", "04410200009876",
                                      "BARB0PUNEXX",
                                      opening_balance_paise=2_30_000_00),),
               operating_lines=_SMALL_OUTFLOWS,
               assets=(
                   asset("Office furniture and fittings", "Furniture & Fixtures",
                         0, 25, 2_20_000_00, "SL"),
               )),
        client("Priya Sharma", "Priya Sharma", "Individual",
               pan("AKQPS", "1138", "F"),
               demonstrates="an individual below the registration threshold — "
                            "salary, capital gains and the §115BAC election, "
                            "with no GSTIN at all",
               registered=False, customers=2, vendors=2,
               sales_per_month=(0, 1), purchases_per_month=(0, 1),
               away_every=0,
               # A SAVINGS account, the only one here — the register's
               # `balance_label` and the Schedule III caption both turn on the
               # account type, and a demo of eight current accounts shows one
               # branch of that.
               banks=(DemoBankAccount("Kotak Mahindra Bank", "1712345678",
                                      "KKBK0006630", account_type="Savings",
                                      opening_balance_paise=4_60_000_00),)),
        client("Vaibhav Infra", "Vaibhav Infra Private Limited",
               "Private Limited", pan("AAGCV", "8890", "T"),
               demonstrates="construction — capital work in progress, its "
                            "Schedule III line and its ageing schedule, which "
                            "nothing else here produces",
               sales_catalogue=_SERVICES, purchase_catalogue=_SERVICES,
               customers=3, vendors=5, employees=4,
               banks=(DemoBankAccount("Yes Bank", "004163900001122", "YESB0000041",
                                      opening_balance_paise=9_40_000_00),),
               operating_lines=_OFFICE_OUTFLOWS,
               assets=(
                   # LAND, which `_NOT_DEPRECIABLE` excludes — the one row in
                   # the whole register that is never charged, and a register
                   # in which everything depreciates cannot show that the
                   # engine asked.
                   asset("Land - Chakan plot", "Land", -30, 1, 5_50_00_000_00,
                         "SL"),
                   asset("Hitachi ZX210 excavator", "Plant & Machinery", -12, 9,
                         4_20_00_000_00),
                   asset("Site cabins and scaffolding", "Furniture & Fixtures",
                         3, 15, 3_80_000_00, "SL"),
                   asset("Total station and survey kit", "Office Equipment",
                         6, 2, 4_90_000_00, "SL"),
               )),
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
        "bank_accounts": sum(len(c.banks) for c in firm.clients),
        "bank_statement_lines": sum(len(c.bank_lines) for c in firm.clients),
        "fixed_assets": sum(len(c.assets) for c in firm.clients),
        # Land is in the register and is never charged — counted apart so the
        # dry run says so rather than leaving the reader to wonder why the
        # depreciation run reports fewer assets than the register holds.
        "assets_never_depreciated": sum(
            1 for c in firm.clients for a in c.assets if a.category == "Land"),
        "assets_with_blocked_tax": sum(
            1 for c in firm.clients for a in c.assets if a.itc_eligible is False),
        "payroll_runs": sum(len(c.payroll) for c in firm.clients),
        "payroll_runs_paid": sum(1 for c in firm.clients for m in c.payroll
                                 if m.leave_at == "paid"),
        "payslips": sum(len(c.payroll) * len(c.employees) for c in firm.clients),
        # What a CA opens Receivables to see. Counted here rather than left to
        # the seeder's own tally so the DRY RUN can state it before anything
        # is written — a plan that does not mention the money is not the plan.
        "receipts": sum(1 for c in firm.clients for d in c.sales
                        if d.settlement and d.settlement.paid_after_days is not None),
        "part_settled_invoices": sum(
            1 for c in firm.clients for d in c.sales
            if d.settlement and d.settlement.paid_after_days is not None
            and d.settlement.fraction_bps < 10_000),
        "invoices_still_open": sum(
            1 for c in firm.clients for d in c.sales
            if not d.settlement or d.settlement.paid_after_days is None),
        "vendor_payments": sum(1 for c in firm.clients for d in c.purchases
                               if d.settlement and d.settlement.paid_after_days is not None),
        "bills_still_open": sum(
            1 for c in firm.clients for d in c.purchases
            if not d.settlement or d.settlement.paid_after_days is None),
        "receipts_with_tds_withheld": sum(
            1 for c in firm.clients for d in c.sales
            if d.settlement and d.settlement.paid_after_days is not None
            and d.settlement.tds_bps),
        "reverse_charge_bills": sum(
            1 for c in firm.clients for d in c.purchases if d.is_reverse_charge),
        "inter_state_sales": sum(
            1 for c in firm.clients for d in c.sales
            if d.place_of_supply != HOME_STATE),
        "vendors_classified_under_msmed": sum(
            1 for c in firm.clients for v in c.vendors if v.msme_status),
        "vendors_with_a_written_payment_agreement": sum(
            1 for c in firm.clients for v in c.vendors
            if v.msmed_agreement_days),
        "unregistered_parties": sum(
            1 for c in firm.clients
            for p in (*c.customers, *c.vendors) if p.gstin is None),
    }
