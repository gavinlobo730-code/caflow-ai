"""The books, laid out the way ITR-3, ITR-5 and ITR-6 ask for them: Part A-BS, Part A-P&L and the depreciation schedules (POST-A-070).

WHAT WAS MISSING

    `itr_json.generate_itr_json` refuses a return for three reasons, and the last of them is that ITR-3, ITR-5 and ITR-6 need "the
    balance sheet and profit-and-loss schedules the form requires". The product already held the books in Schedule III shape
    (`services/year_end_financial_service.generate_financial_statements`) and the §32 block depreciation
    (`services/section_32_service`), and nothing said which box on the return each figure belongs in, so a CA keying a company's
    or a firm's return into the Department's utility did Part A from the trial balance by hand.

WHAT THIS DOES, AND THE ONE RULE THAT SHAPES IT

    It takes the year-end statements and the §32 working AS THEY ARE and says, for every figure, which box of the return it answers.
    It reads no ledger and computes no tax: a second reader of the ledger is a second answer to "what does the balance sheet say",
    and the Schedule III statements are the one answer. THE RULE: A FIGURE IS PLACED IN A BOX ONLY WHERE THE BOOKS SETTLE THE BOX.
    Where the form splits a figure the books keep whole (secured from unsecured loans, the heads of expenditure, quoted from unquoted
    investments) the whole is shown against the box that holds the parts, as a total with the split NOT RECORDED, and the CA splits it.
    A figure is never apportioned, because a guessed split is a wrong return that sums correctly.

    EVERY LINE OF THE STATEMENTS APPEARS EXACTLY ONCE, placed or listed as unplaced with the question that would place it, and the
    tie-out says so in numbers: the lines assembled add to the statements' own totals, the balance sheet balances, the profit and loss
    account reaches the statements' profit before tax, and the depreciation rows add to the §32 allowance. A difference is reported, never
    absorbed (the discipline of `opening_documents.reconcile`).

WHAT IS NOT KNOWN, AND SAYS SO

    * THE LINE-TO-BOX TABLE IS NOT CONFIRMED AGAINST THE FORM'S INSTRUCTIONS. The Department's schemas name every box and the table
      below places a Schedule III line only where the box's own name is that line's name (Sundry debtors for Trade receivables, Deferred
      tax for Deferred tax liabilities), or where the box is the form's total of a group the line belongs to. The instructions that
      would settle the doubtful ones are not reachable from this environment (the Department's site is refused at the proxy), so
      `MAPPING_CONFIRMED` is False and every answer carries it. A practising CA must read the table against the instructions before
      the first return is keyed from it; it is on the owner's list.
    * AS OR IND AS. The statements are Schedule III Division I. A company that follows Ind AS files the Ind AS balance sheet and
      profit and loss account, which are different parts of the same form, and the product records no accounting framework. The
      answer says which parts it filled and that the framework is the CA's to confirm.
    * THE BOOKS OF A TAXPAYER WITH NO BOOKS. A proprietor who is not required to maintain books fills a different part (`NoBooksOfAccBS`).
      Whether books are required is §44AA and §44AD facts this module does not hold, and it is not inferred.

THE DEPRECIATION SCHEDULES (Schedule DPM, DOA, DEP)

    They are built from `section_32_service.assemble`'s blocks, each placed on the return's row the CA recorded for it
    (`itr_depreciation_rows`). A block with no row recorded is listed with its figures and left off the schedules: its depreciation is still in
    the allowance, so the tie-out names the difference instead of the schedules quietly summing to less than the allowance.

THE FIXED-ASSET REGISTER FILLS A GROSS BLOCK ONLY WHERE IT TIES TO THE LEDGER (POST-A-344)

    ITR-3 and ITR-5 take the gross block and the depreciation to date of tangible and intangible assets together, and the register's
    totals fill them where its net block equals the ledger's two lines to the paisa. ITR-6 takes each kind apart, and the register's
    movement is by asset CATEGORY, so the split needs the Schedule III line of the ledger each category is booked to (the caller reads
    it: `domain/fixed_assets/asset_ledger` says which ledger books a category and `year_end_lines.schedule_line_for_account` says which
    line that ledger is on). A figure is placed only where the register's net block of each line equals the ledger's line to the paisa.
    THAT IS A REAL CONDITION AND NOT A FORMALITY: the standard chart books the depreciation of every category in ONE Accumulated
    Depreciation account, so the ledger's tangible line carries the amortisation of intangible assets and the two lines cannot match the
    register's unless no intangible asset has been amortised. Where they do not, the split is withheld with the difference in words.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the Income Tax Portal
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from domain.income_tax import itr_depreciation_rows as rows
from domain.income_tax import itr_schema
from domain.income_tax.itr_json import _to_rupees
from domain.money_sentence import rupee_text

#: See the module docstring. A named constant so a test can hold the claim: nothing in this module says the table is confirmed.
MAPPING_CONFIRMED = False

FORMS = rows.FORMS

#: The two layouts the three forms use for the balance sheet. ITR-3 and ITR-5 use the older "funds sourced and funds applied" form
#: (with a different set of box names for the owner's fund and the debtors); ITR-6 follows Schedule III Division I.
LAYOUT_FUNDS = "funds_sourced_and_applied"
LAYOUT_SCHEDULE_III = "schedule_iii"

#: How the books are said to be kept. Division I is what the statements are.
FRAMEWORK = "AS (Schedule III, Division I)"

#: The two lines of Schedule III the fixed-asset register is split between for ITR-6, whose balance sheet takes the gross block, the
#: depreciation (the amortisation, for an intangible asset) and the net block of each apart.
REGISTER_LINES = ("tangible_assets", "intangible_assets")

# ── the statements' own vocabulary ─────────────────────────────────────────────────────────────────────────────────────────────
LINE_LABELS: dict[str, str] = {
    "share_capital": "Share capital", "reserves_and_surplus": "Reserves and surplus",
    "long_term_borrowings": "Long-term borrowings", "deferred_tax_liabilities": "Deferred tax liabilities",
    "other_long_term_liabilities": "Other long-term liabilities", "long_term_provisions": "Long-term provisions",
    "short_term_borrowings": "Short-term borrowings", "trade_payables": "Trade payables",
    "other_current_liabilities": "Other current liabilities", "short_term_provisions": "Short-term provisions",
    "tangible_assets": "Tangible assets", "intangible_assets": "Intangible assets",
    "capital_wip": "Capital work-in-progress", "long_term_investments": "Long-term investments",
    "deferred_tax_assets": "Deferred tax assets", "long_term_loans_and_advances": "Long-term loans and advances",
    "other_non_current_assets": "Other non-current assets", "current_investments": "Current investments",
    "inventories": "Inventories", "trade_receivables": "Trade receivables", "cash_and_bank": "Cash and bank balances",
    "short_term_loans_and_advances": "Short-term loans and advances", "other_current_assets": "Other current assets",
    "revenue_from_operations": "Revenue from operations", "other_income": "Other income",
    "cost_of_materials_consumed": "Cost of materials consumed", "purchases_of_stock_in_trade": "Purchases of stock-in-trade",
    "changes_in_inventories": "Changes in inventories", "employee_benefit_expense": "Employee benefit expense",
    "finance_costs": "Finance costs", "depreciation_and_amortisation": "Depreciation and amortisation",
    "other_expenses": "Other expenses", "current_tax": "Current tax", "deferred_tax": "Deferred tax",
}

BS_LIABILITY_LINES = ("share_capital", "reserves_and_surplus", "long_term_borrowings", "deferred_tax_liabilities",
                      "other_long_term_liabilities", "long_term_provisions", "short_term_borrowings", "trade_payables",
                      "other_current_liabilities", "short_term_provisions")
BS_ASSET_LINES = ("tangible_assets", "intangible_assets", "capital_wip", "long_term_investments", "deferred_tax_assets",
                  "long_term_loans_and_advances", "other_non_current_assets", "current_investments", "inventories",
                  "trade_receivables", "cash_and_bank", "short_term_loans_and_advances", "other_current_assets")
PL_INCOME_LINES = ("revenue_from_operations", "other_income")
PL_EXPENSE_LINES = ("cost_of_materials_consumed", "purchases_of_stock_in_trade", "changes_in_inventories",
                    "employee_benefit_expense", "finance_costs", "depreciation_and_amortisation", "other_expenses")
PL_TAX_LINES = ("current_tax", "deferred_tax")


# ── the plan: which line answers which box ─────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Part:
    """A box under a group that the books settle on their own (a line, or the register), so it is filled and not left to the CA."""
    path: str
    label: str
    lines: tuple[str, ...] = ()
    #: "register": the fixed-asset register's gross block or accumulated depreciation, used only where it ties to the ledger.
    register: Optional[str] = None


@dataclass(frozen=True)
class Slot:
    key: str
    label: str                      # the form's own caption
    path: str                       # form-root-relative path of the box that carries the figure (a total, or a leaf box)
    lines: tuple[str, ...]          # the statement lines that make it up
    #: The object under which the form's parts of this figure are keyed (None where `path` is a single box, which may still carry
    #: `parts`: boxes BESIDE it that the register fills, as ITR-6's net block of tangible assets has a gross block and a depreciation).
    group: Optional[str] = None
    parts: tuple[Part, ...] = ()
    #: Why the books cannot split the figure into the form's parts. Required wherever `group` is set.
    question: str = ""
    #: A liability set against the assets in the funds-applied layout (the form's net current assets).
    deduct: bool = False
    note: str = ""
    #: (line, sentence) pairs: the sentence is said when THAT LINE comes out negative, which is a balance on the other side of the
    #: account and not a figure to be keyed as it stands. Asked of the line and not of the slot's total, because capital can carry a
    #: deficit in reserves without the group turning negative.
    line_notes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Unplaced:
    line: str
    question: str


@dataclass(frozen=True)
class Check:
    """A box the FORM computes from the parts a CA keys; shown beside the books' figure so the keyed return can be compared."""
    path: str
    label: str
    figure: str          # which statements figure answers it


_NOT_SPLIT_LOANS = ("The books keep borrowings as Schedule III does, long-term and short-term, and record neither whether a loan is "
                    "secured nor who lent it, which is how the form splits them.")
_NOT_SPLIT_INV = ("The books keep inventories as one line. The form splits them into raw material, work in progress, finished goods, "
                  "stock-in-trade and stores, which the stock ledger could answer item by item once each item is classed.")
_NOT_SPLIT_CASH = "The books keep cash and bank as one line. The form takes cash in hand and the balance with banks apart."
_NOT_SPLIT_INVESTMENTS = ("The books keep investments as two lines (long-term and current) and record neither whether a security is "
                          "quoted nor its kind (equity, preference, bonds, mutual funds), which is how the form splits them.")
_NOT_SPLIT_LA = ("The books keep loans and advances as two lines and record neither the purpose nor the kind (advances recoverable, "
                 "deposits, balances with the revenue authorities), which is how the form splits them.")
_NOT_SPLIT_CL = ("The books keep trade payables, other current liabilities and short-term provisions as three lines. The form takes "
                 "sundry creditors, leased-asset liabilities, interest accrued, provision for tax and the other provisions apart, "
                 "and the books do not record which of the liabilities in each line is which.")
_NOT_SPLIT_FUND = ("The books keep the capital account and the reserves as two lines, and the surplus in the profit and loss account "
                   "is derived from the year's results. The form takes capital from the revaluation, capital, statutory and other "
                   "reserves, which the books do not record.")
_NOT_SPLIT_DEBTORS = ("The books keep trade receivables as one line. The form takes those outstanding for more than the stated "
                      "period apart from the rest, which is a question of each invoice's age and not of the ledger's balance.")
_NOT_SPLIT_CREDITORS = ("The books keep trade payables as one line. The form takes those outstanding for more than the stated period "
                        "apart from the rest, which is a question of each bill's age and not of the ledger's balance.")
_NOT_SPLIT_SIII = "The books hold this Schedule III line whole; the form splits it into its parts, which the books do not record."
_NO_BOX_FUNDS = ("The funds-sourced-and-applied form has no box for this line of Schedule III, and which of its groups it belongs in "
                 "(a source of funds, a provision, a loan or an advance) is a reading of the form's instructions.")

_FUNDS_UNPLACED = (
    Unplaced("other_long_term_liabilities", _NO_BOX_FUNDS),
    Unplaced("long_term_provisions", _NO_BOX_FUNDS),
    Unplaced("other_non_current_assets", _NO_BOX_FUNDS),
)

_NEGATIVE_RESERVES = ("Reserves and surplus is a debit balance here (an accumulated loss). The funds-sourced-and-applied form takes "
                      "accumulated losses on the application side, not as a negative reserve, and where it is shown is the CA's "
                      "decision, so the figure is left as the books hold it.")


def _funds_slots(form: str) -> tuple[tuple[Slot, ...], tuple[Slot, ...]]:
    """(sources, applications) for ITR-3 and ITR-5, whose boxes differ in four names only."""
    itr5 = form == "ITR-5"
    owner_group = "PARTA_BS.FundSrc." + ("PartnerOrMemberFund" if itr5 else "PropFund")
    owner_total = owner_group + (".TotPartnerOrMemberFund" if itr5 else ".TotPropFund")
    owner_label = "Partners' / members' fund" if itr5 else "Proprietor's fund"
    sources = (
        Slot("owners_fund", owner_label, owner_total, ("share_capital", "reserves_and_surplus"), group=owner_group,
             question=_NOT_SPLIT_FUND, line_notes=(("reserves_and_surplus", _NEGATIVE_RESERVES),)),
        Slot("loan_funds", "Loan funds", "PARTA_BS.FundSrc.LoanFunds.TotLoanFund",
             ("long_term_borrowings", "short_term_borrowings"), group="PARTA_BS.FundSrc.LoanFunds", question=_NOT_SPLIT_LOANS),
        Slot("deferred_tax_liability", "Deferred tax liability", "PARTA_BS.FundSrc.DeferredTax", ("deferred_tax_liabilities",)),
    )
    ca = "PARTA_BS.FundApply.CurrAssetLoanAdv"
    if itr5:
        debtors = Slot("sundry_debtors", "Sundry debtors", ca + ".CurrAsset.SundryDebtorDtls.TotalSundryDebtors",
                       ("trade_receivables",), group=ca + ".CurrAsset.SundryDebtorDtls", question=_NOT_SPLIT_DEBTORS)
    else:
        debtors = Slot("sundry_debtors", "Sundry debtors", ca + ".CurrAsset.SndryDebtors", ("trade_receivables",))
    applications = (
        Slot("fixed_assets", "Fixed assets", "PARTA_BS.FundApply.FixedAsset.TotFixedAsset",
             ("tangible_assets", "intangible_assets", "capital_wip"), group="PARTA_BS.FundApply.FixedAsset",
             parts=(Part("PARTA_BS.FundApply.FixedAsset.NetBlock", "Net block", ("tangible_assets", "intangible_assets")),
                    Part("PARTA_BS.FundApply.FixedAsset.CapWrkProg", "Capital work-in-progress", ("capital_wip",)),
                    Part("PARTA_BS.FundApply.FixedAsset.GrossBlock", "Gross block", register="gross"),
                    Part("PARTA_BS.FundApply.FixedAsset.Depreciation", "Depreciation", register="accumulated")),
             question="The form takes the gross block and the depreciation to date apart; the ledger holds the net book value."),
        Slot("investments", "Investments", "PARTA_BS.FundApply.Investments.TotInvestments",
             ("long_term_investments", "current_investments"), group="PARTA_BS.FundApply.Investments",
             question=_NOT_SPLIT_INVESTMENTS),
        Slot("inventories", "Inventories", ca + ".CurrAsset.Inventories.TotInventries", ("inventories",),
             group=ca + ".CurrAsset.Inventories", question=_NOT_SPLIT_INV),
        debtors,
        Slot("cash_and_bank", "Cash and bank balances", ca + ".CurrAsset.CashOrBankBal.TotCashOrBankBal", ("cash_and_bank",),
             group=ca + ".CurrAsset.CashOrBankBal", question=_NOT_SPLIT_CASH),
        Slot("other_current_assets", "Other current assets", ca + ".CurrAsset.OthCurrAsset", ("other_current_assets",)),
        Slot("loans_and_advances", "Loans and advances", ca + ".LoanAdv.TotLoanAdv",
             ("short_term_loans_and_advances", "long_term_loans_and_advances"), group=ca + ".LoanAdv", question=_NOT_SPLIT_LA),
        Slot("deferred_tax_asset", "Deferred tax asset", "PARTA_BS.FundApply.MiscAdjust.DefTaxAsset", ("deferred_tax_assets",)),
        Slot("current_liabilities_and_provisions", "Current liabilities and provisions",
             ca + ".CurrLiabilitiesProv.TotCurrLiabilitiesProvision",
             ("trade_payables", "other_current_liabilities", "short_term_provisions"), group=ca + ".CurrLiabilitiesProv",
             question=_NOT_SPLIT_CL, deduct=True,
             note="Set against the current assets in the form's net current assets, so it reduces the funds applied."),
    )
    return sources, applications


def _schedule_iii_slots() -> tuple[tuple[Slot, ...], tuple[Slot, ...]]:
    """(equity and liabilities, assets) for ITR-6, whose Part A-BS is Schedule III Division I."""
    # The Department spells it "EquityAndLiablities"; the path is its spelling, not ours.
    el = "PARTA_BSFor6FrmAY13.EquityAndLiablities"
    asset = "PARTA_BSFor6FrmAY13.Assets"
    nc, cur = el + ".NonCurrLiabilities", el + ".CurrentLiabilities"
    nca, ca = asset + ".NonCurrAssets", asset + ".CurrentAssets"

    def g(key, label, container, total, line, question=_NOT_SPLIT_SIII, **kw):
        return Slot(key, label, f"{container}.{total}", (line,), group=container, question=question, **kw)

    liabilities = (
        g("share_capital", "Share capital", el + ".ShareHolderFund.ShareCapital", "TotShareCapital", "share_capital"),
        g("reserves_and_surplus", "Reserves and surplus", el + ".ShareHolderFund.ResrNSurp", "TotResrNSurp", "reserves_and_surplus"),
        g("long_term_borrowings", "Long-term borrowings", nc + ".LongTermBorrowings", "TotalLTBorrowings", "long_term_borrowings",
          _NOT_SPLIT_LOANS),
        Slot("deferred_tax_liabilities", "Deferred tax liabilities (net)", nc + ".NetDefferedTaxLiability",
             ("deferred_tax_liabilities",)),
        g("other_long_term_liabilities", "Other long-term liabilities", nc + ".OthLongTermLiablities", "TotalOthLtLiabilities",
          "other_long_term_liabilities"),
        g("long_term_provisions", "Long-term provisions", nc + ".LongTermProvisions", "Total", "long_term_provisions"),
        g("short_term_borrowings", "Short-term borrowings", cur + ".ShortTrmBorrowings", "TotShortTrmBorrowings",
          "short_term_borrowings", _NOT_SPLIT_LOANS),
        g("trade_payables", "Trade payables", cur + ".TradePayables", "TotalTradePayables", "trade_payables", _NOT_SPLIT_CREDITORS),
        g("other_current_liabilities", "Other current liabilities", cur + ".OthCurrLiabilities", "TotOthCurrLiabilities",
          "other_current_liabilities"),
        g("short_term_provisions", "Short-term provisions", cur + ".ShortTermProv", "TotShortTermProvisions",
          "short_term_provisions"),
    )
    assets = (
        Slot("tangible_assets", "Tangible assets (net block)", nca + ".FixedAsset.Tangible.NetBlock", ("tangible_assets",),
             parts=(Part(nca + ".FixedAsset.Tangible.GrossBlock", "Gross block", register="gross_tangible_assets"),
                    Part(nca + ".FixedAsset.Tangible.Depreciation", "Depreciation", register="accumulated_tangible_assets"))),
        Slot("intangible_assets", "Intangible assets (net block)", nca + ".FixedAsset.InTangible.NetBlock", ("intangible_assets",),
             parts=(Part(nca + ".FixedAsset.InTangible.GrossBlock", "Gross block", register="gross_intangible_assets"),
                    Part(nca + ".FixedAsset.InTangible.Amortization", "Amortisation", register="accumulated_intangible_assets"))),
        Slot("capital_wip", "Capital work-in-progress", nca + ".FixedAsset.CapWrkProg", ("capital_wip",)),
        g("long_term_investments", "Non-current investments", nca + ".NonCurrInvstmnts", "TotNonCurrInvstmnts",
          "long_term_investments", _NOT_SPLIT_INVESTMENTS),
        Slot("deferred_tax_assets", "Deferred tax assets (net)", nca + ".NetDeferredTaxAssets", ("deferred_tax_assets",)),
        g("long_term_loans_and_advances", "Long-term loans and advances", nca + ".LongTrmLoanAdv", "TotLTLoanAdv",
          "long_term_loans_and_advances", _NOT_SPLIT_LA),
        g("other_non_current_assets", "Other non-current assets", nca + ".OthNonCurrAssets", "Total", "other_non_current_assets"),
        g("current_investments", "Current investments", ca + ".CurrInvstmnts", "TotCurrInvstmnts", "current_investments",
          _NOT_SPLIT_INVESTMENTS),
        g("inventories", "Inventories", ca + ".Inventories", "TotInventries", "inventories", _NOT_SPLIT_INV),
        g("trade_receivables", "Trade receivables", ca + ".TradeReceivables", "TotalTradeReceivables", "trade_receivables",
          _NOT_SPLIT_DEBTORS),
        g("cash_and_bank", "Cash and cash equivalents", ca + ".CashNCashEquivalents", "TotCashNCashEquivalents", "cash_and_bank",
          _NOT_SPLIT_CASH),
        g("short_term_loans_and_advances", "Short-term loans and advances", ca + ".TotShortTermLoanAdv", "TotShrtTermLoans",
          "short_term_loans_and_advances", _NOT_SPLIT_LA),
        Slot("other_current_assets", "Other current assets", ca + ".OtherCurrAssets", ("other_current_assets",)),
    )
    return liabilities, assets


_PL_NOT_SPLIT_EMPLOYEE = ("The books keep employee benefit expense whole. The form takes salaries and wages, bonus, the "
                          "contributions to each fund and the other benefits apart, which the payroll holds but the ledger line does not.")
_PL_NOT_SPLIT_INCOME = ("The books keep other income whole. The form takes rent, commission, dividends, interest, profit on sale of "
                        "assets and investments, and the rest apart, which the books do not record account by account.")
_PL_NOT_SPLIT_INTEREST = ("The books keep finance costs whole. The form takes interest paid to non-residents apart from the rest, and "
                          "finance costs include borrowing costs other than interest, which the books do not tell from interest.")

_PL_UNPLACED = (
    Unplaced("revenue_from_operations",
             "The form takes revenue in the trading account as sales and gross receipts net of duty or tax (business) or gross "
             "receipts of a profession, and takes the duties and taxes received in a box of their own. The books hold revenue net "
             "of GST and cannot say which of those each revenue account is, and the form's total includes the GST received, which "
             "is not a revenue line."),
    Unplaced("cost_of_materials_consumed",
             "The form takes materials in the manufacturing account (opening stock, purchases, wages and factory overheads, closing "
             "stock) and the books hold one line for what was consumed."),
    Unplaced("purchases_of_stock_in_trade",
             "The form takes purchases in the trading account net of duty or tax, and whether the books' figure carries the credit "
             "that was blocked or reversed is not recorded."),
    Unplaced("changes_in_inventories",
             "The form takes the opening and the closing stock of finished goods separately, and the books hold only the change "
             "across every kind of inventory."),
    Unplaced("other_expenses",
             "The form takes each head of expenditure in its own box (freight, rent, repairs, insurance, travel, audit fee, bad "
             "debts and the rest) and the books hold one line. Which account is which head is a classification the chart does not "
             "carry."),
)


def _pl_paths(form: str) -> dict[str, str]:
    """The profit and loss account's boxes. ITR-3 keeps the debits flat; ITR-5 and ITR-6 put them under `DebitPlAcnt`, and the
    tax provision under `DebitsToPL`."""
    flat = form == "ITR-3"
    debit = "PARTA_PL.DebitsToPL" if flat else "PARTA_PL.DebitsToPL.DebitPlAcnt"
    tax = "PARTA_PL.TaxProvAppr" if flat else "PARTA_PL.DebitsToPL.TaxProvAppr"
    return {
        "other_income": "PARTA_PL.CreditsToPL.OthIncome.TotOthIncome",
        "other_income_group": "PARTA_PL.CreditsToPL.OthIncome",
        "employee": debit + ".EmployeeComp.TotEmployeeComp", "employee_group": debit + ".EmployeeComp",
        "interest": debit + ".InterestExpdrtDtls.InterestExpdr", "interest_group": debit + ".InterestExpdrtDtls",
        "depreciation": debit + ".DepreciationAmort",
        "pbt": debit + ".PBT",
        "current_tax": tax + ".ProvForCurrTax", "deferred_tax": tax + ".ProvDefTax", "pat": tax + ".ProfitAfterTax",
    }


def _pl_slots(form: str) -> tuple[Slot, ...]:
    p = _pl_paths(form)
    return (
        Slot("other_income", "Other income", p["other_income"], ("other_income",), group=p["other_income_group"],
             question=_PL_NOT_SPLIT_INCOME),
        Slot("employee_benefit_expense", "Employee compensation", p["employee"], ("employee_benefit_expense",),
             group=p["employee_group"], question=_PL_NOT_SPLIT_EMPLOYEE),
        Slot("finance_costs", "Interest", p["interest"], ("finance_costs",), group=p["interest_group"],
             question=_PL_NOT_SPLIT_INTEREST),
        Slot("depreciation_and_amortisation", "Depreciation and amortisation", p["depreciation"],
             ("depreciation_and_amortisation",)),
        Slot("current_tax", "Provision for current tax", p["current_tax"], ("current_tax",)),
        Slot("deferred_tax", "Provision for deferred tax", p["deferred_tax"], ("deferred_tax",)),
    )


def _pl_checks(form: str) -> tuple[Check, ...]:
    p = _pl_paths(form)
    return (Check(p["pbt"], "Profit before tax", "pbt"), Check(p["pat"], "Profit after tax", "pat"))


def plan_for(form: str) -> dict[str, Any]:
    """Every table the assembly reads for one form. Public so the tests can hold each path against the schema."""
    if form not in FORMS:
        raise ValueError(f"{form} is not one of {', '.join(FORMS)}.")
    if form == "ITR-6":
        liabilities, assets = _schedule_iii_slots()
        return {"layout": LAYOUT_SCHEDULE_III, "liability_slots": liabilities, "asset_slots": assets, "unplaced": (),
                "pl_slots": _pl_slots(form), "pl_unplaced": _PL_UNPLACED, "pl_checks": _pl_checks(form),
                "bs_checks": (Check("PARTA_BSFor6FrmAY13.EquityAndLiablities.TotEquityAndLiabilities",
                                    "Total equity and liabilities", "total_equity_and_liabilities"),
                              Check("PARTA_BSFor6FrmAY13.TotalAssets", "Total assets", "total_assets"))}
    sources, applications = _funds_slots(form)
    return {"layout": LAYOUT_FUNDS, "liability_slots": sources, "asset_slots": applications, "unplaced": _FUNDS_UNPLACED,
            "pl_slots": _pl_slots(form), "pl_unplaced": _PL_UNPLACED, "pl_checks": _pl_checks(form), "bs_checks": ()}


def root_path(form: str, path: str) -> str:
    """The path the Department's schema and `itr_schema.resolve` use: `ITR.ITR3.<path>`."""
    return f"ITR.{rows.form_root(form)}.{path}"


# ── assembly ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _amount(lines: dict[str, int], names: tuple[str, ...]) -> int:
    return sum(int(lines.get(n, 0) or 0) for n in names)


@lru_cache(maxsize=None)
def _form_minimum(form: str, path: str) -> Optional[int]:
    """The least whole-rupee figure the Department's schema accepts in a box (its `minimum`), or None where it states none."""
    minimum = (itr_schema.resolve(form, root_path(form, path)) or {}).get("minimum")
    return minimum if isinstance(minimum, int) and not isinstance(minimum, bool) else None


def _register_against_ledger(difference_paise: int) -> str:
    """How far the register's figure is from the ledger's, in words a CA reads: "₹15,599.96 higher", never a count of paise."""
    if difference_paise == 0:
        return "the same"
    return f"{rupee_text(abs(difference_paise))} {'higher' if difference_paise > 0 else 'lower'}"


def _below_minimum(label: str, amount: int, minimum: int) -> str:
    return (f"{label} comes to {rupee_text(amount)} in the books, a balance on the other side of the account, and the "
            f"Department's schema accepts nothing below {rupee_text(minimum * 100)} in this box. It is shown as the books hold it "
            f"and is not a figure to key as it stands: where a balance of this kind belongs on the form is the CA's decision.")


def _box(form: str, path: str, label: str, amount: Optional[int]) -> dict:
    out = {"label": label, "json_path": root_path(form, path), "amount_paise": amount,
           "amount_rupees": None if amount is None else _to_rupees(amount)}
    # A box the schema bounds from below does not take a figure under the bound, and a figure the engine nets by Schedule III line can
    # come out under it (an overdrawn account in cash and bank, customers' advances inside receivables). Said on the box, because the
    # tie-out cannot: the books tie, and the form would still refuse the figure.
    minimum = _form_minimum(form, path)
    if amount is not None and minimum is not None and out["amount_rupees"] < minimum:
        out["below_form_minimum"] = {"minimum_rupees": minimum, "sentence": _below_minimum(label, amount, minimum)}
    return out


def _slot_out(form: str, slot: Slot, lines: dict[str, int], register: Optional[dict]) -> tuple[dict, list[str]]:
    gaps: list[str] = []
    amount = _amount(lines, slot.lines)
    parts_out: list[dict] = []
    placed = 0
    for part in slot.parts:
        if part.register:
            figure = (register or {}).get(part.register)
            parts_out.append({**_box(form, part.path, part.label, figure),
                              "state": "placed" if figure is not None else "not_recorded", "source": "fixed-asset register"})
            continue
        part_amount = _amount(lines, part.lines)
        parts_out.append({**_box(form, part.path, part.label, part_amount), "state": "placed", "source": "ledger"})
        placed += part_amount
    out = {
        "key": slot.key, "label": slot.label,
        **_box(form, slot.path, slot.label, amount),
        # A single box to key, or the total of a group whose parts the CA keys under `parts_under`.
        "role": "group_total" if slot.group else "box",
        "parts_under": root_path(form, slot.group) if slot.group else None,
        "lines": [{"line": n, "label": LINE_LABELS[n], "amount_paise": int(lines.get(n, 0) or 0)} for n in slot.lines],
        "parts": parts_out,
        "not_split_paise": amount - placed if slot.group else 0,
        "question": slot.question, "note": slot.note, "deduct": slot.deduct,
    }
    negative = [note for line, note in slot.line_notes if int(lines.get(line, 0) or 0) < 0]
    below = [b["below_form_minimum"]["sentence"] for b in [out, *parts_out] if "below_form_minimum" in b]
    if negative or below:
        out["negative_notes"] = negative + below
    gaps += below
    return out, gaps


def balance_sheet(form: str, statements: dict, register: Optional[dict] = None) -> dict:
    """Part A-BS for one form from the year-end statements, with its reconciliation."""
    plan = plan_for(form)
    bs = statements["balance_sheet"]
    liab_lines = {k: int(v or 0) for k, v in bs["equity_and_liabilities"].items()}
    asset_lines = {k: int(v or 0) for k, v in bs["assets"].items()}

    gaps: list[str] = []
    # One dict for both sides: the funds-applied layout sets the current liabilities against the assets, so a slot on the asset side
    # can be made of liability lines. The two sets of line names are disjoint (`BS_LIABILITY_LINES`, `BS_ASSET_LINES`).
    every_line = {**liab_lines, **asset_lines}
    liability_slots, asset_slots = [], []
    for slot in plan["liability_slots"]:
        out, g = _slot_out(form, slot, every_line, register)
        liability_slots.append(out)
        gaps += g
    for slot in plan["asset_slots"]:
        out, g = _slot_out(form, slot, every_line, register)
        asset_slots.append(out)
        gaps += g

    unplaced = []
    for u in plan["unplaced"]:
        source = liab_lines if u.line in BS_LIABILITY_LINES else asset_lines
        unplaced.append({"line": u.line, "label": LINE_LABELS[u.line], "amount_paise": int(source.get(u.line, 0) or 0),
                         "side": "liability" if u.line in BS_LIABILITY_LINES else "asset", "question": u.question})

    liabilities_in_slots = sum(s["amount_paise"] for s in liability_slots)
    assets_in_slots = sum(s["amount_paise"] for s in asset_slots if not s["deduct"])
    deducted = sum(s["amount_paise"] for s in asset_slots if s["deduct"])
    # Funds sourced are the liability-side slots; funds applied are the assets less the liabilities set against them. The ITR-6
    # layout has no deduction, so `deducted` is nil there.
    unplaced_liabilities = sum(u["amount_paise"] for u in unplaced if u["side"] == "liability")
    unplaced_assets = sum(u["amount_paise"] for u in unplaced if u["side"] == "asset")

    checks = []
    for c in plan["bs_checks"]:
        figure = (bs["total_equity_and_liabilities_paise"] if c.figure == "total_equity_and_liabilities"
                  else bs["total_assets_paise"])
        checks.append({**_box(form, c.path, c.label, figure), "kind": "form_computes"})

    if plan["layout"] == LAYOUT_FUNDS:
        reconciliation = {
            "funds_sourced_paise": liabilities_in_slots,
            "funds_applied_paise": assets_in_slots - deducted,
            "unplaced_liabilities_paise": unplaced_liabilities,
            "unplaced_assets_paise": unplaced_assets,
            # Sourced and applied differ by exactly what is unplaced, and by nothing else.
            "difference_paise": (liabilities_in_slots + unplaced_liabilities) - ((assets_in_slots - deducted) + unplaced_assets),
        }
    else:
        reconciliation = {
            "total_equity_and_liabilities_paise": liabilities_in_slots,
            "total_assets_paise": assets_in_slots,
            "difference_paise": liabilities_in_slots - assets_in_slots,
        }
    return {
        "title": "Part A-BS — balance sheet",
        "layout": plan["layout"],
        "liability_side_label": "Funds sourced" if plan["layout"] == LAYOUT_FUNDS else "Equity and liabilities",
        "asset_side_label": "Funds applied" if plan["layout"] == LAYOUT_FUNDS else "Assets",
        "liability_slots": liability_slots, "asset_slots": asset_slots, "unplaced": unplaced, "checks": checks,
        "reconciliation": reconciliation,
        "gaps": gaps,
    }


def profit_loss(form: str, statements: dict) -> dict:
    """Part A-P&L for one form from the year-end statements."""
    plan = plan_for(form)
    pl = statements["profit_loss"]
    lines: dict[str, int] = {**{k: int(v or 0) for k, v in pl["income"].items()},
                             **{k: int(v or 0) for k, v in pl["expenses"].items()},
                             "current_tax": int(pl.get("current_tax_paise") or 0),
                             "deferred_tax": int(pl.get("deferred_tax_paise") or 0)}
    slots, gaps = [], []
    for s in plan["pl_slots"]:
        out, g = _slot_out(form, s, lines, None)
        slots.append(out)
        gaps += g
    unplaced = []
    for u in plan["pl_unplaced"]:
        unplaced.append({"line": u.line, "label": LINE_LABELS[u.line], "amount_paise": int(lines.get(u.line, 0) or 0),
                         "side": "income" if u.line in PL_INCOME_LINES else "expense", "question": u.question})
    checks = []
    for c in plan["pl_checks"]:
        figure = pl["profit_before_tax_paise"] if c.figure == "pbt" else pl["profit_after_tax_paise"]
        checks.append({**_box(form, c.path, c.label, figure), "kind": "form_computes"})

    income = sum(lines.get(n, 0) for n in PL_INCOME_LINES)
    expense = sum(lines.get(n, 0) for n in PL_EXPENSE_LINES)
    tax = sum(lines.get(n, 0) for n in PL_TAX_LINES)
    return {
        "title": "Part A-P&L — profit and loss account",
        "slots": slots, "unplaced": unplaced, "checks": checks, "gaps": gaps,
        "reconciliation": {
            "income_paise": income, "expense_paise": expense, "profit_before_tax_paise": income - expense,
            "tax_paise": tax, "profit_after_tax_paise": income - expense - tax,
            "difference_paise": (income - expense) - int(pl["profit_before_tax_paise"]),
        },
    }


# ── depreciation: Schedules DPM, DOA and DEP ───────────────────────────────────────────────────────────────────────────────────
#: The row's boxes that a block's §32 working fills, the field of the working each one reads, and the forms whose box of that NAME
#: means what the label says. `_total` is the allowance: depreciation plus the additional depreciation of §32(1)(iia). The names are the
#: Department's, and a row that lacks one (ITR-6 has no `AdjustmentSec115BAC`, the 45 per cent row has fewer columns) simply does not get it.
#:
#: A NAME IS TRUSTED ONLY WHERE IT MEANS THE SAME THING ON EVERY FORM THAT HAS IT. The Department did not keep the names of the last
#: columns: ITR-3 has `RealizationPeriodLessThan180days`, `AddlnDeprOnLessThan180DayAdditions` and `AddlnDeprOnAssetLessThan180Days`,
#: and ITR-5 and ITR-6 have `RealizationPeriodDuringYear`, `AddlnDeprDuringYearAdditions` and `AddlnDeprOnLessThan180DayAdditions`, in
#: that order, so the SAME NAME (`AddlnDeprOnLessThan180DayAdditions`) is the second of the three additional-depreciation columns on
#: one form and the third on the other. Filling by name would put this year's half-rate additional depreciation into last year's
#: carried-forward column on two forms of three, and validate. See `_DETAIL_BY_HAND`.
_ALL = FORMS
_DETAIL_FILLED: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("WDVFirstDay", "opening_wdv_paise", "Written down value on the first day of the year", _ALL),
    ("AdditionsGrThan180Days", "additions_full_rate_paise", "Additions put to use for 180 days or more", _ALL),
    ("RealizationTotalPeriod", "realization_against_full_paise", "Consideration out of the opening value and those additions", _ALL),
    ("FullRateDeprAmt", "depreciation_base_full_paise", "Amount on which depreciation at the full rate is allowed", _ALL),
    ("AdditionsLessThan180Days", "additions_half_rate_paise", "Additions put to use for less than 180 days", _ALL),
    ("RealizationPeriodLessThan180days", "realization_against_half_paise", "Consideration out of those additions", ("ITR-3",)),
    ("HalfRateDeprAmt", "depreciation_base_half_paise", "Amount on which depreciation at half the rate is allowed", _ALL),
    ("DepreciationAtFullRate", "depreciation_at_full_rate_paise", "Depreciation at the full rate", _ALL),
    ("DepreciationAtHalfRate", "depreciation_at_half_rate_paise", "Depreciation at half the rate", _ALL),
    ("AddlnDeprOnGT180DayAdditions", "additional_on_full_rate_additions_paise",
     "Additional depreciation on additions of 180 days or more", _ALL),
    ("AddlnDeprOnLessThan180DayAdditions", "additional_on_half_rate_additions_paise",
     "Additional depreciation on additions of less than 180 days", ("ITR-3",)),
    ("TotalDepreciation", "_total", "Total depreciation", _ALL),
    ("NetAggregateDepreciation", "_total", "Net aggregate depreciation", _ALL),
    ("CapGainUs50", "short_term_capital_gain_paise", "Capital gain (loss) under section 50", _ALL),
    ("WDVLastDay", "closing_wdv_paise", "Written down value on the last day of the year", _ALL),
)

#: The figures the working HAS and the form's names do not place, by form: (the boxes it could be, the field, what it is, why). They are
#: shown on the row with the number, so the CA keys it, and are not written into a box: a figure in the wrong column of a schedule the
#: portal accepts is the failure this repository records most often.
_RENAMED = ("The Department names this column differently on ITR-5 and ITR-6, and the names of the three additional-depreciation "
            "columns are in a different order from ITR-3's, so the name does not settle which column it is. The figure is the working's; "
            "key it into the column the form prints for it.")
_DETAIL_BY_HAND: dict[str, tuple[tuple[tuple[str, ...], str, str, str], ...]] = {
    "ITR-5": (
        (("RealizationPeriodDuringYear",), "realization_against_half_paise", "Consideration out of the additions of less than 180 days", _RENAMED),
        (("AddlnDeprDuringYearAdditions", "AddlnDeprOnLessThan180DayAdditions"), "additional_on_half_rate_additions_paise",
         "Additional depreciation on additions of less than 180 days", _RENAMED),
    ),
}
_DETAIL_BY_HAND["ITR-6"] = _DETAIL_BY_HAND["ITR-5"]

#: The boxes of a row the books do NOT hold, and why. Shown once on the schedule so a blank is a recorded absence and not a nil.
NOT_RECORDED_BOXES: dict[str, str] = {
    "AdjustmentSec115BAC": "The adjustment for a change to the section 115BAC regime is not recorded.",
    "Total": "The form computes it from the boxes above it.",
    "AddlnDeprOnAssetLessThan180Days": ("The second half of the additional depreciation on an asset put to use for less than "
                                        "180 days last year is not carried forward by the working."),
    "DepDisAllowUs38_2": ("The part of the depreciation disallowed under section 38(2) for use other than for the business is "
                          "not recorded, so net aggregate depreciation is shown equal to the total."),
    "ProportionateAggDepreciation": ("The proportionate depreciation allowable on a succession or amalgamation is not recorded."),
    "ExpdrOnTrforSaleAsset": "The expenditure on the transfer of an asset is not recorded.",
}

_NATURE_SUMMARY = {"PlantMachinery": "PlantMachinerySummary", "Building": "BuildingSummary"}
_SINGLE_SUMMARY = {"FurnitureFittings": "FurnitureSummary", "IntangibleAssets": "IntangibleAssetSummary", "Ships": "ShipsSummary"}
_DEP = "ScheduleDEP.SummaryFromDeprSch"
_DEP_TOTALS = (("PlantMachinerySummary.TotPlntMach", "Total, plant and machinery", ("PlantMachinery",)),
               ("BuildingSummary.TotBuildng", "Total, building", ("Building",)),
               ("TotalDepreciation", "Total depreciation", ()))


def _dep_summary_path(row: rows.Row) -> Optional[str]:
    """Schedule DEP's box for a row, named by the Department's own nature key and rate. None for Land, which has none."""
    if row.nature in _SINGLE_SUMMARY:
        return f"{_DEP}.{_SINGLE_SUMMARY[row.nature]}"
    if row.nature in _NATURE_SUMMARY and row.rate_percent is not None:
        return f"{_DEP}.{_NATURE_SUMMARY[row.nature]}.DeprBlockTot{row.rate_percent}Percent"
    return None


def _block_allowance(block: dict) -> int:
    return int(block.get("depreciation_paise") or 0) + int(block.get("additional_depreciation_paise") or 0)


def _put_aside(block: dict, reason: str) -> dict:
    """A block that cannot be placed: its figures and the reason, so it is listed and never dropped."""
    return {
        "block_key": block["block_key"], "rate_percent": block.get("rate_percent"),
        "itr_schedule_row": block.get("itr_schedule_row"), "reason": reason,
        "opening_wdv_paise": int(block.get("opening_wdv_paise") or 0),
        "depreciation_paise": int(block.get("depreciation_paise") or 0),
        "additional_depreciation_paise": int(block.get("additional_depreciation_paise") or 0),
        "allowance_paise": _block_allowance(block),
        "closing_wdv_paise": int(block.get("closing_wdv_paise") or 0),
        "short_term_capital_gain_paise": int(block.get("short_term_capital_gain_paise") or 0),
    }


def _why_not_placeable(form: str, block: dict, by_row: dict[str, dict]) -> tuple[Optional[rows.Row], Optional[str]]:
    """(the row the block sits on, None) or (None, the sentence saying why it cannot sit anywhere)."""
    recorded = block.get("itr_schedule_row")
    if not recorded:
        return None, ("No row on the return is recorded for this block, so it cannot be placed. Record which nature of asset the "
                      "block is on the §32 block screen; its depreciation is still in the allowance.")
    row = rows.row_by_key(form, recorded)
    if row is None:
        return None, (f"The row recorded for this block ({recorded}) is not a row of {form}'s depreciation schedules. "
                      f"Record one of this form's rows.")
    clash = rows.disagreement(row, int(block.get("rate_percent") or 0))
    if clash:
        return None, clash
    if row.key in by_row:
        return None, (f"Block \"{by_row[row.key]['block_key']}\" is already on {row.caption}. A block is a nature at one rate "
                      f"(§2(11)), so two blocks of one nature and rate are one block: merge them in the register.")
    return row, None


def _row_entry(form: str, row: rows.Row, block: dict) -> dict:
    """One row of Schedule DPM or DOA from one block's working."""
    boxes = []
    for box, source, label, forms in _DETAIL_FILLED:
        if box not in row.boxes or form not in forms:
            continue
        value = _block_allowance(block) if source == "_total" else block.get(source)
        boxes.append({**_box(form, row.path(box), label, None if value is None else int(value)),
                      "box": box, "state": "placed" if value is not None else "not_recorded"})
    by_hand = []
    for names, source, label, why in _DETAIL_BY_HAND.get(form, ()):
        present = [n for n in names if n in row.boxes]
        if present:
            value = block.get(source)
            by_hand.append({"boxes": present, "label": label, "reason": why,
                            "amount_paise": None if value is None else int(value),
                            "amount_rupees": None if value is None else _to_rupees(int(value))})
    # A figure of the working that this row has NO box for, on this form: the 45 per cent row has no half-rate columns and Land has two
    # boxes in all, so a block there that carries additions or half-rate depreciation would otherwise lose them without a word, with the
    # allowance still tying (the allowance is the sum, not the columns). Listed with the number so the CA sees what the form cannot hold.
    has_a_box = {source for box, source, _l, forms in _DETAIL_FILLED if box in row.boxes and form in forms}
    has_a_box |= {source for names, source, _l, _w in _DETAIL_BY_HAND.get(form, ()) if any(n in row.boxes for n in names)}
    without_a_box = []
    for _box_name, source, label, _forms in _DETAIL_FILLED:
        value = block.get(source)
        if source == "_total" or source in has_a_box or not value:
            continue
        without_a_box.append({"label": label, "amount_paise": int(value), "amount_rupees": _to_rupees(int(value)),
                              "reason": f"This row has no box for the figure on {form}; it is the working's and is in no box of the return."})
    notes = [b["below_form_minimum"]["sentence"] for b in boxes if "below_form_minimum" in b]
    deleted = int(block.get("deletions_paise") or 0)
    set_against = int(block.get("realization_against_full_paise") or 0) + int(block.get("realization_against_half_paise") or 0)
    if deleted > set_against:
        # §50: where the moneys payable exceed the block, the block is nil and the excess is a short-term capital gain. The realization
        # columns carry what was set against the block; whether the form wants the whole consideration in them is a reading of the form's
        # instructions this environment cannot reach, so the CA is told the two figures and not given a choice made for them.
        notes.append(f"The moneys payable for assets sold ({rupee_text(deleted)}) exceed what the block could take. The realization "
                     f"boxes carry the {rupee_text(set_against)} set against the block, and the {rupee_text(deleted - set_against)} "
                     f"excess is in the capital gain under section 50. Whether the form's consideration column takes the whole "
                     f"{rupee_text(deleted)} is the CA's to confirm from the form's instructions.")
    return {
        "row_key": row.key, "schedule": row.schedule, "caption": row.caption, "rate_percent": row.rate_percent,
        "block_key": block["block_key"], "allowance_paise": _block_allowance(block), "boxes": boxes,
        "to_key_by_hand": by_hand, "figures_without_a_box": without_a_box, "notes": notes,
        "not_recorded": sorted(b for b in row.boxes if b in NOT_RECORDED_BOXES),
    }


def _dep_summary(form: str, placed_rows: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """Schedule DEP: one box per row, and the form's own totals shown beside the books' for comparison."""
    summary: list[dict] = []
    gaps: list[str] = []
    for r in placed_rows:
        path = _dep_summary_path(rows.row_by_key(form, r["row_key"]))
        if path is None:
            continue
        if itr_schema.resolve(form, root_path(form, path)) is None:
            gaps.append(f"{form} has no summary box for {r['caption']}; its depreciation is in the schedule but not the summary.")
            continue
        summary.append({**_box(form, path, r["caption"], r["allowance_paise"]), "kind": "box"})
    checks = []
    for tail, label, natures in _DEP_TOTALS:
        path = f"{_DEP}.{tail}"
        if itr_schema.resolve(form, root_path(form, path)) is None:
            continue
        figure = sum(r["allowance_paise"] for r in placed_rows
                     if not natures or rows.row_by_key(form, r["row_key"]).nature in natures)
        checks.append({**_box(form, path, label, figure), "kind": "form_computes"})
    return summary, checks, gaps


def depreciation(form: str, section_32: dict) -> dict:
    """Schedules DPM, DOA and DEP for one form from `section_32_service.assemble`'s answer."""
    by_row: dict[str, dict] = {}
    placed_rows: list[dict] = []
    unplaced: list[dict] = []
    for block in section_32.get("blocks") or []:
        row, why = _why_not_placeable(form, block, by_row)
        if row is None:
            unplaced.append(_put_aside(block, why))
            continue
        by_row[row.key] = block
        placed_rows.append(_row_entry(form, row, block))

    summary, checks, gaps = _dep_summary(form, placed_rows)
    allowance = int(section_32.get("allowance_paise") or 0)
    placed = sum(r["allowance_paise"] for r in placed_rows)
    aside = sum(u["allowance_paise"] for u in unplaced)
    return {
        "title": "Schedules DPM, DOA and DEP — depreciation under section 32",
        "rows": placed_rows, "summary": summary, "checks": checks, "unplaced": unplaced,
        "not_recorded": [{"box": b, "reason": why} for b, why in NOT_RECORDED_BOXES.items()
                         if any(b in r.boxes for r in rows.rows_for(form))],
        "reconciliation": {
            "placed_allowance_paise": placed, "unplaced_allowance_paise": aside, "section_32_allowance_paise": allowance,
            "difference_paise": placed + aside - allowance,
            "short_term_capital_gain_paise": int(section_32.get("short_term_capital_gain_paise") or 0),
        },
        "gaps": (gaps + list(section_32.get("statutory_gaps") or [])
                 + [f"{r['caption']}: {f['label']} ({rupee_text(f['amount_paise'])}) — {f['reason']}"
                    for r in placed_rows for f in r["figures_without_a_box"]]
                 + [f"{r['caption']}: {n}" for r in placed_rows for n in r["notes"]]),
        "unclassified_assets": list(section_32.get("unclassified_assets") or []),
        "blocks_without_opening_wdv": list(section_32.get("blocks_without_opening_wdv") or []),
    }


# ── the fixed-asset register, used only where it ties to the ledger ───────────────────────────────────────────────────────────
def usable_register(register: Optional[dict], statements: dict) -> tuple[Optional[dict], Optional[str], Optional[dict]]:
    """(register figures to use, a sentence if they were withheld, the tie-out row).

    The form takes the gross block and the depreciation to date apart and the ledger holds the net book value, so the register is the
    only source of the first two. It is used only where its net block equals the ledger's tangible and intangible assets to the paisa
    and where it could say how much of each asset's depreciation belongs to which year; a register that disagrees with the ledger is
    reported, and the gross block and depreciation are left for the CA, because a gross block that does not tie to the net block is
    not a figure to key.
    """
    if not register:
        return None, ("The fixed-asset register was not read, so the gross block and the depreciation to date are left for the CA to "
                      "key. The net block is the ledger's."), None
    ledger_net = int(statements["balance_sheet"]["assets"].get("tangible_assets", 0) or 0) + \
        int(statements["balance_sheet"]["assets"].get("intangible_assets", 0) or 0)
    net = int(register["net"])
    row = {"name": "register_net_block_vs_ledger", "informational": True,
           "expected_paise": ledger_net, "actual_paise": net, "difference_paise": net - ledger_net}
    if not register.get("split_known", True):
        return None, ("The register could not say how much of each asset's depreciation belongs to this year, so the gross block and "
                      "the depreciation to date are left for the CA to key."), row
    if net != ledger_net:
        return None, (f"The fixed-asset register's net block differs from the ledger's tangible and intangible assets: the register's "
                      f"is {_register_against_ledger(net - ledger_net)}, so the gross block and the depreciation to date are left for "
                      f"the CA to key. Reconcile the register to the ledger first."), row
    return {"gross": int(register["gross"]), "accumulated": int(register["accumulated"])}, None, row


def splits_fixed_assets(form: str) -> bool:
    """Whether the form takes the gross block and the depreciation of tangible and of intangible assets apart (ITR-6), which is the
    only form whose split needs the ledger line each asset category is booked to."""
    return plan_for(form)["layout"] == LAYOUT_SCHEDULE_III


def _has_a_figure(category: dict) -> bool:
    """Whether the category holds a cost or a depreciation at the year end (its net block is the difference, so it needs no test of its own)."""
    return any(int(category.get(k) or 0) for k in ("closing_gross_paise", "closing_accum_paise"))


def register_categories_to_place(classes: Any) -> list[str]:
    """The asset categories that hold a figure at the year end, which are the ones whose ledger line has to be known. A category the
    register holds only at nil (every asset of it sold, or none costed) is no figure on either line, so no line is asked of it."""
    return [str(c["asset_class"]) for c in classes or () if _has_a_figure(c)]


def _line_label(line: Any) -> str:
    return LINE_LABELS.get(line, str(line))


def register_by_line(register: Optional[dict], statements: dict) -> tuple[Optional[dict], Optional[str], list[dict]]:
    """(the register's gross block and depreciation per line, a sentence if they were withheld, the per-line tie-out rows).

    `register["classes"]` is the movement of each asset category and `register["ledger_lines"]` the Schedule III line of the ledger each
    category is booked to (None where it could not be read). A category that holds a figure and is not on tangible or on intangible assets
    withholds the split, because its figure belongs to neither box and a gross block that leaves it out is not the register's. The split is
    used only where the register's net block of EACH line equals the ledger's line to the paisa; a difference is reported on the row and
    in the sentence and is never absorbed into either line.
    """
    left = "the gross block and the depreciation to date of each are left for the CA to key"
    if not register or register.get("classes") is None or register.get("ledger_lines") is None:
        return None, ("The fixed-asset register was not split between tangible and intangible assets, so " + left + ". The net block of "
                      "each is the ledger's."), []
    ledger_lines = register["ledger_lines"]
    per_line = {line: {"gross": 0, "accumulated": 0, "net": 0} for line in REGISTER_LINES}
    unreadable: list[str] = []
    for category in register["classes"]:
        if not _has_a_figure(category):
            continue
        name = str(category["asset_class"])
        line = ledger_lines.get(name)
        if line not in REGISTER_LINES:
            unreadable.append(f"no ledger account could be found for the category {name!r}" if line is None else
                              f"the category {name!r} is booked to a ledger that Schedule III places under {_line_label(line)}")
            continue
        per_line[line]["gross"] += int(category.get("closing_gross_paise") or 0)
        per_line[line]["accumulated"] += int(category.get("closing_accum_paise") or 0)
        per_line[line]["net"] += int(category.get("closing_net_paise") or 0)
    if unreadable:
        return None, ("The fixed-asset register could not be split between tangible and intangible assets: " + "; ".join(unreadable)
                      + ". So " + left + ". The net block of each is the ledger's."), []
    # The two kinds must add to the register's own totals: a split of categories that does not is not the register's figure.
    if (sum(v["gross"] for v in per_line.values()) != int(register["gross"])
            or sum(v["accumulated"] for v in per_line.values()) != int(register["accumulated"])):
        return None, ("The fixed-asset register's categories do not add to its totals, so " + left + ". The net block of each is the "
                      "ledger's."), []

    assets = statements["balance_sheet"]["assets"]
    rows_out: list[dict] = []
    for line in REGISTER_LINES:
        ledger = int(assets.get(line, 0) or 0)
        rows_out.append({"name": f"register_{line.split('_')[0]}_net_block_vs_ledger",
                         "label": f"The fixed-asset register's net block of {line.split('_')[0]} assets equals the ledger's",
                         "expected_paise": ledger, "actual_paise": per_line[line]["net"],
                         "difference_paise": per_line[line]["net"] - ledger})
    if any(r["difference_paise"] for r in rows_out):
        tangible, intangible = rows_out[0]["difference_paise"], rows_out[1]["difference_paise"]
        opening = (f"The fixed-asset register's net block differs from the ledger's: the register's tangible assets are "
                   f"{_register_against_ledger(tangible)} and its intangible assets {_register_against_ledger(intangible)}, so "
                   + left + ". ")
        if tangible > 0 and tangible == -intangible:
            # The ledger's tangible line is lower than the register's by exactly what the intangible line is higher: the shape of an
            # amortised intangible asset whose amortisation sits in the shared account on the tangible line.
            return None, (opening + "That is what an amortised intangible asset does: the standard chart books the depreciation of every "
                          "category in one Accumulated Depreciation account, which sits on one of the two lines, so the ledger's lines "
                          "cannot match the register's category by category."), rows_out
        return None, (opening + "The register and the ledger disagree by an amount that moves between the two lines in no pattern the "
                      "books explain, and need reconciling."), rows_out
    flat = {}
    for line in REGISTER_LINES:
        flat[f"gross_{line}"] = per_line[line]["gross"]
        flat[f"accumulated_{line}"] = per_line[line]["accumulated"]
    return flat, None, rows_out


# ── the whole assembly ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _each_once(plan_lines: tuple[str, ...], placed: list[str]) -> int:
    """How many of the statement's lines are not placed exactly once (0 when every line is accounted for)."""
    return sum(1 for n in plan_lines if placed.count(n) != 1) + sum(1 for n in placed if n not in plan_lines)


def assemble(*, form: str, assessment_year: str, financial_year: str, statements: dict,
             section_32: Optional[dict] = None, register: Optional[dict] = None) -> dict:
    """Part A-BS, Part A-P&L and the depreciation schedules for one form, with the tie-out that proves nothing was dropped.

    `statements` is `generate_financial_statements`' answer, `section_32` is `section_32_service.assemble`'s, and `register` is
    `{gross, accumulated, net, split_known}` from the fixed-asset movement (or None). Nothing here reads a database.
    """
    if form not in FORMS:
        raise ValueError(f"{form} is not one of {', '.join(FORMS)}; Part A schedules are assembled for those.")
    usable, register_gap, register_check = usable_register(register, statements)
    split_gap: Optional[str] = None
    split_rows: list[dict] = []
    splits = splits_fixed_assets(form)
    by_line: Optional[dict] = None
    if usable is not None and splits:
        by_line, split_gap, split_rows = register_by_line(register, statements)
        usable = {**usable, **(by_line or {})}
    bs = balance_sheet(form, statements, usable)
    pl = profit_loss(form, statements)
    dep = depreciation(form, section_32) if section_32 is not None else None

    st_bs = statements["balance_sheet"]
    st_pl = statements["profit_loss"]
    # Every placed or unplaced line, whichever list it landed in, sorted by the statements' own side of the balance sheet.
    placed_bs = [ln for s in bs["liability_slots"] + bs["asset_slots"] for ln in s["lines"]] + \
        [{"line": u["line"], "amount_paise": u["amount_paise"]} for u in bs["unplaced"]]
    bs_placed_liab = [ln["line"] for ln in placed_bs if ln["line"] in BS_LIABILITY_LINES]
    bs_placed_asset = [ln["line"] for ln in placed_bs if ln["line"] in BS_ASSET_LINES]
    pl_placed = [ln["line"] for s in pl["slots"] for ln in s["lines"]] + [u["line"] for u in pl["unplaced"]]
    liabilities_total = sum(ln["amount_paise"] for ln in placed_bs if ln["line"] in BS_LIABILITY_LINES)
    assets_total = sum(ln["amount_paise"] for ln in placed_bs if ln["line"] in BS_ASSET_LINES)
    rec_pl = pl["reconciliation"]

    def check(name: str, label: str, expected: int, actual: int, informational: bool = False, unit: str = "paise") -> dict:
        # `unit` says what the three numbers are: a COUNT of lines for the placed-once checks, so a screen does not print one misplaced
        # line as one paisa, and so the tie-out's money difference is made of money only.
        return {"name": name, "label": label, "expected_paise": expected, "actual_paise": actual,
                "difference_paise": actual - expected, "informational": informational, "unit": unit}

    checks = [
        check("balance_sheet_lines_placed_once", "Every balance sheet line is placed exactly once", 0,
              _each_once(BS_LIABILITY_LINES, bs_placed_liab) + _each_once(BS_ASSET_LINES, bs_placed_asset), unit="count"),
        check("balance_sheet_liabilities", "Equity and liabilities assembled equal the statements'",
              int(st_bs["total_equity_and_liabilities_paise"]), liabilities_total),
        check("balance_sheet_assets", "Assets assembled equal the statements'", int(st_bs["total_assets_paise"]), assets_total),
        check("balance_sheet_balances", "The assembled balance sheet balances", 0, liabilities_total - assets_total),
        check("balance_sheet_reconciliation", "Funds sourced and applied differ by what is unplaced and nothing else", 0,
              int(bs["reconciliation"]["difference_paise"])),
        check("profit_loss_lines_placed_once", "Every profit and loss line is placed exactly once", 0,
              _each_once(PL_INCOME_LINES + PL_EXPENSE_LINES + PL_TAX_LINES, pl_placed), unit="count"),
        check("profit_before_tax", "Profit before tax from the assembled lines equals the statements'",
              int(st_pl["profit_before_tax_paise"]), int(rec_pl["profit_before_tax_paise"])),
        check("profit_after_tax", "Profit after tax from the assembled lines equals the statements'",
              int(st_pl["profit_after_tax_paise"]), int(rec_pl["profit_after_tax_paise"])),
    ]
    if register_check:
        checks.append(check(register_check["name"], "The fixed-asset register's net block equals the ledger's",
                            register_check["expected_paise"], register_check["actual_paise"], informational=True))
    for r in split_rows:
        checks.append(check(r["name"], r["label"], r["expected_paise"], r["actual_paise"], informational=True))
    if dep is not None:
        checks.append(check("depreciation_rows_and_unplaced_blocks", "The depreciation rows and the blocks left off them add to the §32 allowance",
                            dep["reconciliation"]["section_32_allowance_paise"],
                            dep["reconciliation"]["placed_allowance_paise"] + dep["reconciliation"]["unplaced_allowance_paise"]))
        checks.append(check("depreciation_summary", "Schedule DEP adds to the rows",
                            dep["reconciliation"]["placed_allowance_paise"],
                            sum(s["amount_paise"] for s in dep["summary"])
                            + sum(r["allowance_paise"] for r in dep["rows"]
                                  if _dep_summary_path(rows.row_by_key(form, r["row_key"])) is None)))

    gaps = list(bs["gaps"])
    if register_gap or split_gap:
        gaps.append(register_gap or split_gap)
    if usable is not None and (by_line or not splits):
        # The register's cost and depreciation are placed, and what ties them to the ledger is the net block alone: the statements hold
        # no gross cost to compare, and this module reads no ledger.
        gaps.append("The gross block and the depreciation to date are the fixed-asset register's. What ties them to the ledger is the net "
                    "block only, and a register and a ledger that agree on the net block can still differ on the cost and on the "
                    "depreciation (an asset entered at its written-down value, say), so check them against the fixed assets note "
                    "before keying.")
    if bs["layout"] == LAYOUT_SCHEDULE_III:
        # ITR-6 also takes the impairment losses of each kind of asset, and the register has no column for one.
        gaps.append("The form also takes the impairment losses of tangible and of intangible assets. The fixed-asset register does not "
                    "record them, so they are left for the CA to key.")
    gaps.append(f"The statements are {FRAMEWORK}. The product records no accounting framework, so whether this company or firm files "
                f"the Ind AS parts of the form instead is the CA's to confirm.")
    gaps.append("The line-to-box table has not been read against the form's instructions (they are not reachable from this "
                "environment). Check each placement before the first return is keyed from it.")
    unsplit = [s for s in bs["liability_slots"] + bs["asset_slots"] if s["not_split_paise"]]
    if unsplit:
        gaps.append(f"{len(unsplit)} balance sheet figure(s) are totals whose parts the books do not record; the CA splits them.")
    gaps += pl["gaps"]
    if dep is not None:
        gaps += dep["gaps"]
    bad = [c for c in checks if not c["informational"] and c["difference_paise"] != 0]
    return {
        "form": form, "assessment_year": assessment_year, "financial_year": financial_year,
        "period": {"start": statements.get("fy_start"), "end": statements.get("fy_end")},
        "framework": FRAMEWORK, "mapping_confirmed": MAPPING_CONFIRMED,
        "balance_sheet": bs, "profit_loss": pl, "depreciation": dep,
        "tie_out": {
            "checks": checks,
            "difference_paise": sum(abs(c["difference_paise"]) for c in checks if not c["informational"] and c["unit"] == "paise"),
            "lines_misplaced": sum(abs(c["difference_paise"]) for c in checks if not c["informational"] and c["unit"] == "count"),
            "ok": not bad, "trial_balance_hash": statements.get("trial_balance_hash"),
            "balance_sheet_is_balanced": bool(st_bs.get("is_balanced")),
        },
        "gaps": gaps,
    }
