"""What a demo client's year comes to, worked out from the fixture alone (POST-A-269).

WHY THIS EXISTS. The seeded books were out of proportion and nobody could see it
without seeding them: five of the eight companies made a loss before tax, the
largest carried assets tens of times their turnover, and six of the eight bank
ledgers were below nothing on 31 March. A real seed needs a migrated database,
PostgREST and the app, which a test run does not have. So this works the year
out from the same data the seeder writes, in the order it writes it, and a test
holds every company to a profit, a bank that never goes below nothing, and a
turnover inside the limits the product's own rules turn on.

WHAT IT FOLLOWS, AND WHERE IT IS ONLY AN ESTIMATE. Only what the seeder POSTS
counts: every month but `fixture.draft_month`, depreciation from April to
January (`seed_demo_firm._fixed_assets` stops two months short) and the payroll
runs it finalizes. Revenue is the taxable value of the lines; the cost of goods
sold is the moving weighted average the inventory engine prices an issue at
(`domain/inventory/costing`, the default formula), run over the documents in
`fixture.documents_in_order`; a bill a project under construction absorbs is
capital and not a cost. Depreciation follows Schedule II as
`routers/fixed_assets` charges it: a fixed annual figure from the year's
opening balance, a twelfth for each month posted. THREE FIGURES ARE BOUNDS AND
NOT EXACT, each on the side that cannot flatter a company: the employer's share
of payroll is allowed for generously (`EMPLOYER_COST_ALLOWANCE_BPS`, which is a
margin of safety and not a statutory rate), a bank pays every bill in full
without the tax it withholds, and a salary is paid gross.

THE QUEUE IS COUNTED BOTH WAYS. The rent, power and bank charges on the seeded
statement are left in the bank queue for a CA to pass at the demo, so the books
as seeded do not carry them and the books after a "Pass N ready" do. A company
must be in profit, and its bank above nothing, either way.

Nothing here reads the clock, holds a database handle or writes anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from domain.demo import fixture as F
from domain.fixed_assets import schedule_ii

#: An allowance for what an employer pays on top of a salary (its provident fund and insurance shares), in basis points
#: of gross pay. A margin of safety for an estimate that must not flatter a company, NOT a statutory rate: the payroll
#: engine computes the real shares, and this only has to be at least as large as they are.
EMPLOYER_COST_ALLOWANCE_BPS = 2_000

#: The months the seeder posts depreciation for: April to January (`seed_demo_firm._fixed_assets`).
DEPRECIATION_MONTHS = 10


@dataclass(frozen=True)
class YearEstimate:
    client: str
    turnover_paise: int
    goods_cost_paise: int
    services_bought_paise: int
    payroll_paise: int
    depreciation_paise: int
    #: What a firm credits its partners as remuneration (`fixture.partner_remuneration_credits`): an expense that moves no bank,
    #: because it is credited to the partners' current accounts and the tax withheld from it is deposited by a challan that
    #: posts nothing (POST-A-272).
    partner_remuneration_paise: int
    #: The bank-statement outgoings left in the queue for a CA to pass (rent, power, bank charges).
    queued_outgoings_paise: int
    #: Cost of the fixed assets, with any tax that was capitalised.
    fixed_assets_paise: int
    #: What the bills the client's projects under construction absorb come to (capital work in progress at the year end).
    projects_paise: int
    #: The client's first bank account's ledger: its lowest balance after any entry, and its balance on the last day.
    bank_lowest_paise: int
    bank_closing_paise: int
    #: The same lowest, once the queued outgoings are passed.
    bank_lowest_after_the_queue_paise: int
    #: The lowest running balance the imported statement prints: its opening balance less the outgoings on it, before
    #: any of the credits it also carries (which land late in the year).
    statement_lowest_paise: int

    @property
    def profit_before_tax_paise(self) -> int:
        """As the books are seeded: the queue not yet passed."""
        return (self.turnover_paise - self.goods_cost_paise - self.services_bought_paise
                - self.payroll_paise - self.depreciation_paise - self.partner_remuneration_paise)

    @property
    def profit_after_the_queue_paise(self) -> int:
        """Once a CA passes the queued outgoings."""
        return self.profit_before_tax_paise - self.queued_outgoings_paise


def _months(financial_year: str) -> list[date]:
    start = int(financial_year[:4])
    return [date(start + (1 if m < 4 else 0), m, 1) for m in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3)]


def _line_taxable(line: "F.DemoLine") -> int:
    return int((Decimal(line.quantity) * line.rate_paise).to_integral_value())


def _line_tax(line: "F.DemoLine") -> int:
    return int((Decimal(_line_taxable(line)) * Decimal(line.gst_rate_percent) / 100).to_integral_value())


def _depreciation(asset: "F.DemoAsset", financial_year: str) -> int:
    """The year's charge for one asset, as the register posts it from April to January."""
    if asset.category in schedule_ii.NOT_DEPRECIABLE:
        return 0
    cls = schedule_ii.default_class(asset.category)
    cost = asset.cost_paise + _capitalised_tax(asset)
    if asset.method == "SL":
        annual = (cost - asset.salvage_value_paise) // cls["useful_life_years"]
    else:
        annual = int(Decimal(cost) * cls["wdv_rate_percent"] / 100)
    bought = asset.purchase_date[:7]
    months = sum(1 for m in _months(financial_year)[:DEPRECIATION_MONTHS] if m.isoformat()[:7] >= bought)
    return annual * months // 12


def _gross_pay(e: "F.DemoEmployee") -> int:
    return e.basic_paise + int(Decimal(e.basic_paise) * Decimal(str(e.hra_percent)) / 100) + e.special_paise


def _documents(client: "F.DemoClient", financial_year: str) -> tuple[int, int, int, list[tuple[date, int]]]:
    """Turnover, cost of goods sold, services bought, and the receipts and payments, over the documents the seeder
    posts, in the order it writes them."""
    draft = F.draft_month(financial_year)
    capitalised = {n for p in client.cwip_projects for n in p.bills}
    stock = {item.hsn_sac_code: [Decimal(str(item.opening_qty_units)), item.opening_cost_paise]
             for item in client.catalogue if item.kind == "good"}
    turnover = goods_cost = services = 0
    cash: list[tuple[date, int]] = []
    for step in F.documents_in_order(client):
        doc = step.doc
        if doc.doc_date[:7] == draft:
            continue
        taxable = sum(_line_taxable(ln) for ln in doc.lines)
        tax = sum(_line_tax(ln) for ln in doc.lines)
        if step.kind == "sale":
            turnover += taxable
            goods_cost += _issue(stock, doc)
            owed_to_us = taxable + tax
        else:
            services += _receive(stock, doc, capitalised_bill=step.n in capitalised)
            # A reverse-charge supplier charges no tax on the bill; the recipient pays it to the government.
            owed_to_us = -(taxable if doc.is_reverse_charge else taxable + tax)
        st = doc.settlement
        if st is not None and st.paid_after_days is not None:
            settled = owed_to_us * st.fraction_bps // 10_000
            withheld = settled * st.tds_bps // 10_000 if step.kind == "sale" else 0
            cash.append((date.fromisoformat(doc.doc_date) + timedelta(days=st.paid_after_days), settled - withheld))
    return turnover, goods_cost, services, cash


def _issue(stock: dict, doc: "F.DemoDocument") -> int:
    """What a sale takes out of stock, at the moving weighted average."""
    cost_of_sale = 0
    for ln in doc.lines:
        if ln.hsn_sac_code.startswith("99"):
            continue
        qty, value = stock[ln.hsn_sac_code]
        taken = Decimal(ln.quantity)
        cost = int((Decimal(value) * taken / qty).to_integral_value()) if qty else 0
        stock[ln.hsn_sac_code] = [qty - taken, value - cost]
        cost_of_sale += cost
    return cost_of_sale


def _receive(stock: dict, doc: "F.DemoDocument", *, capitalised_bill: bool) -> int:
    """A bill's goods into stock; returns the services it charges to the year (none if a project absorbs the bill)."""
    services = 0
    for ln in doc.lines:
        if ln.hsn_sac_code.startswith("99"):
            services += 0 if capitalised_bill else _line_taxable(ln)
        else:
            qty, value = stock[ln.hsn_sac_code]
            stock[ln.hsn_sac_code] = [qty + Decimal(ln.quantity), value + _line_taxable(ln)]
    return services


def _lowest_and_closing(events: list[tuple[date, int]], year_end: date) -> tuple[int, int]:
    """The lowest balance after any entry (entries of one day in amount order, outgoings first) and the closing one."""
    balance, lowest = 0, None
    for _, amount in sorted(e for e in events if e[0] <= year_end):
        balance += amount
        lowest = balance if lowest is None else min(lowest, balance)
    return (lowest if lowest is not None else 0), balance


def _capitalised_tax(a: "F.DemoAsset") -> int:
    return a.igst_paise + a.cgst_paise + a.sgst_paise if a.itc_eligible is False else 0


def estimate(client: "F.DemoClient", financial_year: str) -> YearEstimate:
    """One client's year, as the seeder would leave its books."""
    year_start = _months(financial_year)[0]
    year_end = date(year_start.year + 1, 3, 31)
    turnover, goods_cost, services, cash = _documents(client, financial_year)

    for a in client.assets:
        cash.append((date.fromisoformat(a.purchase_date), -F.paid_from_the_bank_paise(a)))
    for c in F.capital_introductions(client, financial_year):
        cash.append((date.fromisoformat(c.on), c.amount_paise))
    gross = sum(_gross_pay(e) for e in client.employees)
    for m in client.payroll:
        if m.leave_at == "paid":
            cash.append((date.fromisoformat(f"{m.month}-28"), -gross))
    payroll = gross * sum(1 for m in client.payroll if m.leave_at != "draft") \
        * (10_000 + EMPLOYER_COST_ALLOWANCE_BPS) // 10_000

    queue = [(date.fromisoformat(ln.line_date), -ln.amount_paise) for ln in client.bank_lines if not ln.is_credit]
    opening = [(year_start, client.banks[0].opening_balance_paise)] if client.banks else []
    lowest, closing = _lowest_and_closing(cash + opening, year_end)
    lowest_queued, _ = _lowest_and_closing(cash + opening + queue, year_end)
    statement_lowest, _ = _lowest_and_closing(opening + queue, year_end)
    draft = F.draft_month(financial_year)
    absorbed = {n for p in client.cwip_projects for n in p.bills}
    projects = sum(F.document_taxable_paise(d) for n, d in enumerate(client.purchases, start=1)
                   if n in absorbed and d.doc_date[:7] != draft)
    return YearEstimate(
        client=client.name,
        turnover_paise=turnover,
        goods_cost_paise=goods_cost,
        services_bought_paise=services,
        payroll_paise=payroll,
        depreciation_paise=sum(_depreciation(a, financial_year) for a in client.assets),
        partner_remuneration_paise=sum(cr.amount_paise for cr in F.partner_remuneration_credits(client, financial_year)),
        queued_outgoings_paise=-sum(amount for _, amount in queue),
        fixed_assets_paise=sum(a.cost_paise + _capitalised_tax(a) for a in client.assets),
        projects_paise=projects,
        bank_lowest_paise=lowest,
        bank_closing_paise=closing,
        bank_lowest_after_the_queue_paise=lowest_queued,
        statement_lowest_paise=statement_lowest,
    )
