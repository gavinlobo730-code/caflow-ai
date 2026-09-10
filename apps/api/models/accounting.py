"""
Pydantic request models for accounting endpoints.
Double-entry: debit_paise == credit_paise enforced at validation level.
CGST Act §2(59): all money values stored as integer paise (never float).
"""
from datetime import date as _date
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
from enum import Enum


def _posting_date(v: Optional[str]) -> Optional[str]:
    """A posting date is an ISO date, and nothing else (ACC-27).

    `entry_date` was a bare `str` with no validator, unlike the FYLabel
    discipline CLAUDE.md mandates one field over — and the consequence was not
    a bad-looking record. Two layers parse this string DIFFERENTLY:
    period_validation_service uses `strptime("%Y-%m-%d")`, which accepts
    "2025-4-1", and phase2_journal_service uses `date.fromisoformat`, which
    (before Python 3.11 relaxed it, and by intent here) does not. So a
    single-digit month passed the firm-level lock, failed the client-level
    parse, and the kernel treated the failure as "no year lock" — posting into
    a client year that year-end finalisation had closed. Postgres then stored
    it happily, because it is a valid DATE.

    Refused at the boundary AND in the kernel. Two checks for one rule is
    usually the thing to avoid; here the kernel is reached by paths that never
    construct a Pydantic model at all, so neither is redundant.
    """
    if v is None:
        return v
    s = str(v).strip()
    try:
        _date.fromisoformat(s)
    except (TypeError, ValueError):
        raise ValueError(
            f"entry_date must be an ISO date, YYYY-MM-DD — got '{v}'."
        )
    return s


class AccountType(str, Enum):
    ASSET = "Asset"
    LIABILITY = "Liability"
    EQUITY = "Equity"
    INCOME = "Income"
    EXPENSE = "Expense"


class AccountIn(BaseModel):
    name: str
    code: Optional[str] = None
    account_type: AccountType
    parent_id: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True

    # ACC-09. chart_of_accounts has carried these since migration 057 and
    # nothing but the CSV import ever wrote them, so Account Groups rendered
    # every account of every firm under one "Ungrouped → General" heading —
    # the screen was not broken, it was being told nothing.
    #
    # They are TEXT and not a foreign key on purpose: they are the Indian
    # chart's own vocabulary ("Current Assets" → "Sundry Debtors"), which every
    # practice words slightly differently and which the Tally import brings in
    # verbatim. parent_id is the structural link; these two are the grouping a
    # CA reads the trial balance by.
    parent_group: Optional[str] = None
    sub_group: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Account name cannot be blank.")
        return v.strip()


class AccountUpdateIn(BaseModel):
    """A correction to a ledger. account_type is deliberately absent — it
    decides which side of the trial balance the account falls on, so changing
    it after a posting silently restates every report."""
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    parent_id: Optional[str] = None
    parent_group: Optional[str] = None
    sub_group: Optional[str] = None


class JournalLineIn(BaseModel):
    account_id: str
    debit_paise: int = 0
    credit_paise: int = 0
    narration: Optional[str] = None

    @model_validator(mode="after")
    def exactly_one_side(self) -> "JournalLineIn":
        if self.debit_paise < 0 or self.credit_paise < 0:
            raise ValueError("debit_paise and credit_paise must be non-negative integers.")
        if self.debit_paise == 0 and self.credit_paise == 0:
            raise ValueError("Each journal line must have either a debit or credit amount.")
        if self.debit_paise > 0 and self.credit_paise > 0:
            raise ValueError("A journal line cannot have both debit and credit amounts.")
        return self


# Manual journals may only use the entry types the journal_entries CHECK
# constraint allows (Sales/Purchase/Payment/Receipt/Journal/Contra/Opening).
ALLOWED_JOURNAL_ENTRY_TYPES = {
    "Journal", "Contra", "Payment", "Receipt", "Sales", "Purchase", "Opening",
}


class JournalEntryUpdateIn(BaseModel):
    """A correction to an existing entry. Every field optional — a CA fixing a
    narration should not have to resend the lines.

    EXCEPT on a posted entry, where `lines` (if the amounts are changing at all)
    must be the COMPLETE set. edit_posted_journal replaces the lines wholesale
    so that the audit trigger records a clean before/after for every figure, and
    so the Dr = Cr check runs against what the entry will actually be rather
    than a fragment of it.

    client_id is absent on purpose: moving an entry between clients is not a
    correction, it is two entries.
    """
    entry_date: Optional[str] = None      # YYYY-MM-DD
    reference_no: Optional[str] = None
    narration: Optional[str] = None
    entry_type: Optional[str] = None
    lines: Optional[list[JournalLineIn]] = None

    _check_entry_date = field_validator("entry_date")(_posting_date)

    @field_validator("entry_type")
    @classmethod
    def entry_type_allowed(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ALLOWED_JOURNAL_ENTRY_TYPES:
            raise ValueError(
                f"Invalid entry_type '{v}'. Allowed: {', '.join(sorted(ALLOWED_JOURNAL_ENTRY_TYPES))}."
            )
        return v


class JournalEntryIn(BaseModel):
    client_id: str
    entry_date: str  # YYYY-MM-DD, validated — see _posting_date
    reference_no: Optional[str] = None
    narration: Optional[str] = None
    entry_type: str = "Journal"
    status: str = "draft"            # "draft" (off-books) | "posted" (to the ledger)
    attachments: list[dict] = []     # supporting documents: [{"name","url"}, ...]
    lines: list[JournalLineIn]

    _check_entry_date = field_validator("entry_date")(_posting_date)

    @field_validator("entry_type")
    @classmethod
    def entry_type_allowed(cls, v: str) -> str:
        if v not in ALLOWED_JOURNAL_ENTRY_TYPES:
            raise ValueError(
                f"Invalid entry_type '{v}'. Allowed: {', '.join(sorted(ALLOWED_JOURNAL_ENTRY_TYPES))}."
            )
        return v

    @field_validator("status")
    @classmethod
    def status_allowed(cls, v: str) -> str:
        if v not in ("draft", "posted"):
            raise ValueError("status must be 'draft' or 'posted'.")
        return v

    @field_validator("lines")
    @classmethod
    def min_two_lines(cls, v: list) -> list:
        if len(v) < 2:
            raise ValueError("A journal entry must have at least 2 lines.")
        return v

    @model_validator(mode="after")
    def balanced_entry(self) -> "JournalEntryIn":
        total_debit = sum(ln.debit_paise for ln in self.lines)
        total_credit = sum(ln.credit_paise for ln in self.lines)
        if total_debit != total_credit:
            raise ValueError(
                f"Journal entry is unbalanced: debits={total_debit} paise, credits={total_credit} paise."
            )
        return self


class JournalReversalIn(BaseModel):
    reversal_date: str  # YYYY-MM-DD
    narration: Optional[str] = None


class DepreciationMethod(str, Enum):
    SL = "SL"
    WDV = "WDV"


class FixedAssetIn(BaseModel):
    client_id: str
    asset_name: str
    asset_category: str = "Other"
    purchase_date: str  # YYYY-MM-DD
    purchase_cost_paise: int
    salvage_value_paise: int = 0
    useful_life_years: Optional[int] = None
    depreciation_method: DepreciationMethod = DepreciationMethod.WDV
    wdv_rate_percent: Optional[float] = None
    location: Optional[str] = None
    notes: Optional[str] = None

    # ── IT Act §32, which is a different system from Schedule II above ──────
    # Neither of these touches the Companies Act charge. `it_block_key` says
    # which §32 BLOCK the asset falls in — a CA determination, because §2(11)
    # groups by nature AND rate and the Schedule II category does not decide
    # it. `put_to_use_date` is what the second proviso to §32(1) turns on, and
    # it is NOT the purchase date: an asset bought in February and put to use
    # in June belongs to the next previous year entirely. Both default to None,
    # which the §32 computation reports as a named gap (migration 357).
    it_block_key: Optional[str] = None
    put_to_use_date: Optional[str] = None    # YYYY-MM-DD

    # ── FA-07: how it was acquired, and from whom ───────────────────────────
    # 'paid' | 'credit' | 'from_bill'. Decides the CREDIT leg — see
    # phase2_journal_service.journal_for_asset_acquisition and migration 343.
    # Defaulted to 'paid' so an existing caller keeps today's behaviour, except
    # that 'paid' now credits the account the money actually left.
    acquisition_mode: str = "paid"
    vendor_id: Optional[str] = None
    purchase_bill_id: Optional[str] = None
    bank_account_id: Optional[str] = None
    payment_mode: Optional[str] = None
    # Tax on the acquisition, as it appeared on the document.
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    # None = not stated. False = CGST Act §17(5) blocked, so the tax is
    # capitalised into the asset's cost and DEPRECIATES rather than being
    # claimed or expensed.
    itc_eligible: Optional[bool] = None
    itc_blocked_reason: Optional[str] = None

    @field_validator("igst_paise", "cgst_paise", "sgst_paise")
    @classmethod
    def tax_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Tax amounts must be non-negative paise integers.")
        return v

    @field_validator("acquisition_mode")
    @classmethod
    def known_mode(cls, v: str) -> str:
        if v not in ("paid", "credit", "from_bill"):
            raise ValueError(
                "acquisition_mode must be 'paid' (bought and paid for now), "
                "'credit' (owed to a vendor) or 'from_bill' (the purchase bill "
                "already posted, so this only reclassifies its cost).")
        return v

    @model_validator(mode="after")
    def acquisition_facts_must_agree(self):
        """A mode that names no counterparty posts to the wrong account silently.

        'from_bill' without a bill would post a reclassification out of an
        expense nothing put there; 'credit' without a vendor would credit Trade
        Payables with no one owed. Both balance, and both are wrong — which is
        the shape of defect this whole finding is about.
        """
        if self.acquisition_mode == "from_bill" and not self.purchase_bill_id:
            raise ValueError(
                "acquisition_mode 'from_bill' needs purchase_bill_id — the entry "
                "reclassifies that bill's cost out of purchases, and without the "
                "bill there is nothing to reclassify.")
        if self.acquisition_mode == "credit" and not self.vendor_id:
            raise ValueError(
                "acquisition_mode 'credit' needs vendor_id — the entry credits "
                "Trade Payables, and a payable with no vendor cannot be settled.")
        if (self.igst_paise or self.cgst_paise or self.sgst_paise) \
                and self.itc_eligible is None:
            raise ValueError(
                "Tax was entered but itc_eligible was not set. Whether CGST Act "
                "§17(5) blocks the credit changes both the balance sheet and the "
                "depreciable cost, so it cannot be left to a default.")
        return self

    @field_validator("purchase_cost_paise", "salvage_value_paise")
    @classmethod
    def must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Cost/salvage values must be non-negative paise integers.")
        return v


class DepreciationIn(BaseModel):
    period: Optional[str] = None  # YYYY-MM; defaults to current month


class DepreciationRunIn(BaseModel):
    """Post every unposted month in a range, for every live asset of a client.

    A RANGE, named by the CA, is a different act from the single endpoint's one
    month: it is a request for those months, so the run posts them in order and
    reports each one. It cannot create a gap, because it starts at each asset's
    earliest unposted month — see routers/fixed_assets.run_depreciation (FA-04).
    """
    client_id: str
    from_period: str    # YYYY-MM, inclusive
    to_period: str      # YYYY-MM, inclusive


class FixedAssetUpdateIn(BaseModel):
    """A correction to an asset already in the register (FA-10).

    Every field is Optional and unset means "leave alone" — `model_dump(
    exclude_unset=True)` is what the router splits into tiers, NOT
    exclude_none, because clearing `location` to null is a real edit and
    exclude_none would silently drop it (PAY-12's mechanism).

    The three tiers are NOT a presentation choice, they are three different
    mechanisms:

      A — asset_name, location, notes, and the two IT Act §32 facts
          (it_block_key, put_to_use_date): no GL, no statutory consequence
          under the Companies Act. §32 is a different system entirely and
          reads them itself — see domain/income_tax/section_32.py.
      B — purchase_cost_paise, asset_category, purchase_date and the
          acquisition facts: the acquisition JOURNAL is wrong too, so the
          correction is a reversal and a re-post through the one kernel.
      C — useful_life_years, salvage_value_paise, depreciation_method,
          wdv_rate_percent: a revision of an accounting ESTIMATE (Schedule II
          Part C Note 7, AS 10), which applies to the remaining carrying
          amount over the remaining life. Prospective — never a rewrite of a
          month already posted.

    purchase_cost_paise here is the CAPITALISED figure the register holds, not
    the typed cost: capitalised_cost_paise() has already folded §17(5)-blocked
    tax into it, the raw cost is stored nowhere, and re-capitalising a stored
    value would add the blocked tax a second time. Sending the tax fields
    alongside a cost re-runs that calculation once, from the figures given.
    """
    asset_name: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    it_block_key: Optional[str] = None
    put_to_use_date: Optional[str] = None

    purchase_cost_paise: Optional[int] = None
    asset_category: Optional[str] = None
    purchase_date: Optional[str] = None
    acquisition_mode: Optional[str] = None
    vendor_id: Optional[str] = None
    purchase_bill_id: Optional[str] = None
    bank_account_id: Optional[str] = None
    payment_mode: Optional[str] = None
    igst_paise: Optional[int] = None
    cgst_paise: Optional[int] = None
    sgst_paise: Optional[int] = None
    itc_eligible: Optional[bool] = None
    itc_blocked_reason: Optional[str] = None

    useful_life_years: Optional[int] = None
    salvage_value_paise: Optional[int] = None
    depreciation_method: Optional[DepreciationMethod] = None
    wdv_rate_percent: Optional[float] = None

    #: Why the correction is being made. Recorded on the audit entry and on the
    #: re-posted journal's narration, because a reversal on the ledger with no
    #: reason beside it is what an auditor asks about first.
    reason: Optional[str] = None

    @field_validator("purchase_cost_paise", "salvage_value_paise",
                     "igst_paise", "cgst_paise", "sgst_paise")
    @classmethod
    def money_must_be_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("Amounts must be non-negative paise integers.")
        return v

    @field_validator("acquisition_mode")
    @classmethod
    def known_mode(cls, v):
        if v is not None and v not in ("paid", "credit", "from_bill"):
            raise ValueError(
                "acquisition_mode must be 'paid', 'credit' or 'from_bill'.")
        return v


class DisposalIn(BaseModel):
    disposal_type: str = "Sale"  # Sale | Scrapped | Written Off
    sale_proceeds_paise: int = 0
    disposal_date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    notes: Optional[str] = None

    @field_validator("sale_proceeds_paise")
    @classmethod
    def must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("sale_proceeds_paise must be non-negative.")
        return v
