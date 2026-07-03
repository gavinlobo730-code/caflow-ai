"""
Phase 2 Auto-Journal Service.
Every transaction creates a balanced double-entry journal automatically.
No manual posting allowed for Phase 2 transactions.

CGST Act Section 8: Intra-state supply → CGST + SGST; Inter-state → IGST.
IT Act Section 194C/194I/194J: TDS deducted at source on applicable payments.
"""
import os
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException

# Multi-Currency Phase 2 — currency metadata + the authoritative in-kernel gate.
# Light imports only (policy + rate-type vocabulary); the ExchangeRateService and
# providers are imported lazily in exchange_rate_service() to keep the hot path light.
from domain.currency.policy import BASE_CURRENCY, CurrencyPolicy
from domain.currency.rate_types import DEFAULT_RATE_TYPE, is_valid_rate_type

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.phase2_journal")


def _is_unique_violation(err: Exception) -> bool:
    """True when a Postgres/PostgREST error is a unique-constraint violation (23505).
    Used so the kernel can treat a concurrent duplicate insert as idempotent."""
    s = str(err).lower()
    return "23505" in s or "duplicate key" in s or "already exists" in s


class Phase2JournalService:
    """Auto-journal service for Phase 2 transaction types."""

    # ------------------------------------------------------------------ #
    #  Public Methods                                                       #
    # ------------------------------------------------------------------ #

    def journal_for_sales_invoice(
        self, invoice: dict, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Create journal entry for a posted sales invoice.
        Dr Trade Receivables = total_paise
        Cr Sales Revenue     = taxable_amount_paise
        Cr GST Output (CGST/SGST/IGST) as applicable — per-head accounts.
        CGST Act §9: GST on taxable outward supplies.
        CGST Act §8: Intra-state → CGST+SGST; Inter-state → IGST.
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_sales_invoice: %s", invoice.get("invoice_no"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            receivables_id = self._find_account(
                db, firm_id, client_id, "%Trade Receivable%", system_key="ar"
            )
            sales_id = self._find_account(
                db, firm_id, client_id, "%Sales%", system_key="revenue"
            )

            lines = [
                {
                    "account_id": receivables_id,
                    "debit_paise": invoice["total_paise"],
                    "credit_paise": 0,
                    "narration": "Trade receivable on sale",
                },
                {
                    "account_id": sales_id,
                    "debit_paise": 0,
                    "credit_paise": invoice["taxable_amount_paise"],
                    "narration": "Sales revenue",
                },
            ]

            # CGST Act §8: separate posting per GST head so each head hits its own ledger.
            # Falls back to combined %GST Output% for standard single-account charts.
            if invoice.get("cgst_paise", 0) > 0:
                cgst_id = self._find_account(
                    db, firm_id, client_id, "%GST Output%", system_key="gst_cgst"
                )
                lines.append({
                    "account_id": cgst_id,
                    "debit_paise": 0,
                    "credit_paise": invoice["cgst_paise"],
                    "narration": "CGST output tax payable",
                })
            if invoice.get("sgst_paise", 0) > 0:
                sgst_id = self._find_account(
                    db, firm_id, client_id, "%GST Output%", system_key="gst_sgst"
                )
                lines.append({
                    "account_id": sgst_id,
                    "debit_paise": 0,
                    "credit_paise": invoice["sgst_paise"],
                    "narration": "SGST output tax payable",
                })
            if invoice.get("igst_paise", 0) > 0:
                igst_id = self._find_account(
                    db, firm_id, client_id, "%GST Output%", system_key="gst_igst"
                )
                lines.append({
                    "account_id": igst_id,
                    "debit_paise": 0,
                    "credit_paise": invoice["igst_paise"],
                    "narration": "IGST output tax payable",
                })

            _ccy = self._currency_kwargs(db, invoice, firm_id, client_id, lines)
            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=invoice.get("invoice_date", str(datetime.now(timezone.utc).date())),
                reference_no=invoice["invoice_no"],
                narration=f"Sales invoice {invoice['invoice_no']} to customer — CGST Act §9",
                entry_type="Sales",
                lines=lines,
                **_ccy,
            )
        except ValueError:
            # Re-raise account resolution and balance errors so the router returns 422
            raise
        except Exception as e:
            _logger.error("journal_for_sales_invoice error: %s", e)
            return None

    def receipt_journal_lines(self, db, receipt: dict, firm_id: str, client_id: str) -> list[dict]:
        """Build (but do not post) the double-entry lines for a receipt:
        Dr Bank Account      = amount_paise (cash received)
        Dr TDS Receivable    = tds_paise    (if the client deducted TDS — IT Act §194J)
        Cr Trade Receivables = amount_paise + tds_paise (total settlement)
        The invoice can be fully settled even when cash < invoice value because the
        TDS portion is recorded as a receivable (claimable against the firm's IT,
        reconcilable to 26AS/AIS).

        R2.12: extracted out of journal_for_receipt so services/receipt_service.py's
        settle_receipt_atomic path (which posts the journal, the receipt row, and
        every allocation in ONE database transaction) can resolve the same GL
        accounts and build the same lines without going through the separate
        post_journal_atomic RPC journal_for_receipt itself still uses for the
        (unmodified) multi-currency receipt path.
        """
        cash_paise = int(receipt["amount_paise"])
        tds_paise  = int(receipt.get("tds_paise", 0) or 0)
        settlement = cash_paise + tds_paise

        bank_id        = self._find_account(db, firm_id, client_id, "%Bank%", system_key="bank")
        receivables_id = self._find_account(
            db, firm_id, client_id, "%Trade Receivable%", system_key="ar"
        )

        lines = [
            {
                "account_id": bank_id,
                "debit_paise": cash_paise,
                "credit_paise": 0,
                "narration": "Cash/bank received from customer",
            },
        ]
        if tds_paise > 0:
            tds_recv_id = self._find_account(
                db, firm_id, client_id, "%TDS Receivable%", system_key="tds_receivable"
            )
            lines.append({
                "account_id": tds_recv_id,
                "debit_paise": tds_paise,
                "credit_paise": 0,
                "narration": "TDS deducted by client — receivable (IT Act §194J)",
            })
        lines.append({
            "account_id": receivables_id,
            "debit_paise": 0,
            "credit_paise": settlement,
            "narration": "Trade receivable cleared (cash + TDS)",
        })
        return lines

    def journal_for_receipt(
        self, receipt: dict, firm_id: str, client_id: str
    ) -> Optional[str]:
        """Build the receipt's journal lines and post them via post_journal_atomic
        (the single-document atomic path — see receipt_journal_lines' docstring for
        why the line-building is factored out). Used by the multi-currency receipt
        path (create_foreign_receipt); the plain-INR path posts through
        settle_receipt_atomic instead (services/receipt_service.py), which folds
        this same journal into the receipt+allocations transaction."""
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_receipt: %s", receipt.get("receipt_no"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()
            lines = self.receipt_journal_lines(db, receipt, firm_id, client_id)
            _ccy = self._currency_kwargs(db, receipt, firm_id, client_id, lines)
            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=receipt.get("receipt_date", str(datetime.now(timezone.utc).date())),
                reference_no=receipt["receipt_no"],
                narration=f"Receipt {receipt['receipt_no']} from customer",
                entry_type="Receipt",
                lines=lines,
                **_ccy,
            )
        except ValueError:
            raise
        except Exception as e:
            # F7: do NOT swallow. A receipt settles AR, so a silently-dropped
            # journal would leave settled AR with no GL entry. Re-raise so the
            # caller aborts before (or rolls back) the AR mutation.
            _logger.error("journal_for_receipt error: %s", e)
            raise

    def journal_for_credit_note(
        self, cn: dict, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Dr Sales Returns (Sales Revenue account) = taxable_amount_paise
        Dr GST Output Tax Payable (CGST/SGST/IGST) — per-head accounts
        Cr Trade Receivables = total_paise
        CGST Act §34: Credit notes for reduction in taxable value.
        CGST Act §8: Intra-state → CGST+SGST; Inter-state → IGST.
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_credit_note: %s", cn.get("credit_note_no"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            sales_id = self._find_account(
                db, firm_id, client_id, "%Sales%", system_key="revenue"
            )
            receivables_id = self._find_account(
                db, firm_id, client_id, "%Trade Receivable%", system_key="ar"
            )

            lines = [
                {
                    "account_id": sales_id,
                    "debit_paise": cn["taxable_amount_paise"],
                    "credit_paise": 0,
                    "narration": "Sales returns — credit note",
                },
            ]

            # CGST Act §34: per-head GST reversal matches the original posting heads.
            if cn.get("cgst_paise", 0) > 0:
                cgst_id = self._find_account(
                    db, firm_id, client_id, "%GST Output%", system_key="gst_cgst"
                )
                lines.append({
                    "account_id": cgst_id,
                    "debit_paise": cn["cgst_paise"],
                    "credit_paise": 0,
                    "narration": "CGST output tax reversed",
                })
            if cn.get("sgst_paise", 0) > 0:
                sgst_id = self._find_account(
                    db, firm_id, client_id, "%GST Output%", system_key="gst_sgst"
                )
                lines.append({
                    "account_id": sgst_id,
                    "debit_paise": cn["sgst_paise"],
                    "credit_paise": 0,
                    "narration": "SGST output tax reversed",
                })
            if cn.get("igst_paise", 0) > 0:
                igst_id = self._find_account(
                    db, firm_id, client_id, "%GST Output%", system_key="gst_igst"
                )
                lines.append({
                    "account_id": igst_id,
                    "debit_paise": cn["igst_paise"],
                    "credit_paise": 0,
                    "narration": "IGST output tax reversed",
                })

            lines.append({
                "account_id": receivables_id,
                "debit_paise": 0,
                "credit_paise": cn["total_paise"],
                "narration": "Trade receivable reduced by credit note",
            })

            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=cn.get("credit_note_date", str(datetime.now(timezone.utc).date())),
                reference_no=cn["credit_note_no"],
                narration=f"Credit note {cn['credit_note_no']} — CGST Act §34",
                entry_type="Journal",
                lines=lines,
            )
        except ValueError:
            raise
        except Exception as e:
            _logger.error("journal_for_credit_note error: %s", e)
            return None

    def journal_for_debit_note(
        self, dn: dict, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Vendor-side purchase return (mirror of the credit note on the AP side):
        Dr Trade Payables      = total_paise         (we owe the vendor less)
        Cr Purchases/Expense   = taxable_amount_paise (reverse the expense)
        Cr GST Input Tax Credit (CGST/SGST/IGST)     (reverse the ITC claimed)
        CGST Act §34: debit notes for reduction in value/tax.
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_debit_note: %s", dn.get("debit_note_no"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            payables_id = self._find_account(
                db, firm_id, client_id, "%Trade Payable%", system_key="ap"
            )
            try:
                purchases_id = self._find_account(db, firm_id, client_id, "%Purchase%")
            except ValueError:
                purchases_id = self._find_account(db, firm_id, client_id, "%Expense%")
            gst_input_id = self._find_account(
                db, firm_id, client_id, "%GST Input%", system_key="gst_input"
            )

            lines = [{
                "account_id": payables_id,
                "debit_paise": dn["total_paise"],
                "credit_paise": 0,
                "narration": "Trade payable reduced by debit note",
            }, {
                "account_id": purchases_id,
                "debit_paise": 0,
                "credit_paise": dn["taxable_amount_paise"],
                "narration": "Purchase returns — debit note",
            }]
            gst_reversed = int(dn.get("cgst_paise", 0)) + int(dn.get("sgst_paise", 0)) + int(dn.get("igst_paise", 0))
            if gst_reversed > 0:
                lines.append({
                    "account_id": gst_input_id,
                    "debit_paise": 0,
                    "credit_paise": gst_reversed,
                    "narration": "GST input tax credit reversed",
                })

            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=dn.get("debit_note_date", str(datetime.now(timezone.utc).date())),
                reference_no=dn["debit_note_no"],
                narration=f"Debit note {dn['debit_note_no']} — CGST Act §34",
                entry_type="Journal",
                lines=lines,
            )
        except ValueError:
            raise
        except Exception as e:
            _logger.error("journal_for_debit_note error: %s", e)
            return None

    def journal_for_purchase_bill(
        self, bill: dict, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Dr Purchases/Expense account = taxable_amount_paise
        Dr GST Input Tax Credit (CGST/SGST/IGST) as applicable
        Cr Trade Payables = net_payable_paise  (total - tds)
        Cr TDS Payable    = tds_paise (if >0)
        IT Act §194C/194I/194J: TDS deducted at source.
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_purchase_bill: %s", bill.get("bill_no"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            # Expense / purchases account — prefer explicit account, else resolve by name
            if bill.get("expense_account_id"):
                purchases_id = bill["expense_account_id"]
            else:
                # Try Purchase account first, then Professional Fees / Expense as fallback
                try:
                    purchases_id = self._find_account(db, firm_id, client_id, "%Purchase%")
                except ValueError:
                    purchases_id = self._find_account(db, firm_id, client_id, "%Expense%")

            gst_input_id = self._find_account(
                db, firm_id, client_id, "%GST Input%", system_key="gst_input"
            )
            payables_id = self._find_account(
                db, firm_id, client_id, "%Trade Payable%", system_key="ap"
            )
            tds_pay_id = self._find_account(
                db, firm_id, client_id, "%TDS Payable%", system_key="tds_payable"
            )

            # H10: classify the expense per LINE — group each line's taxable by its own
            # expense_account_id so purchases hit the right ledger (schedule-wise P&L,
            # §40(a)(ia) mapping). Lines with no account fall back to the resolved
            # Purchases/Expense account. Grouping keeps one debit per distinct account.
            line_rows = (db.table("purchase_bill_lines")
                         .select("expense_account_id, taxable_amount_paise")
                         .eq("bill_id", bill.get("id")).execute().data) or []
            by_account: dict = {}
            for lr in line_rows:
                acc = lr.get("expense_account_id") or purchases_id
                by_account[acc] = by_account.get(acc, 0) + int(lr.get("taxable_amount_paise") or 0)
            # Fallback: no line rows available (e.g. header-only) → single purchases debit.
            if not by_account or sum(by_account.values()) != int(bill.get("taxable_amount_paise") or 0):
                by_account = {purchases_id: int(bill.get("taxable_amount_paise") or 0)}
            lines = [
                {"account_id": acc, "debit_paise": amt, "credit_paise": 0,
                 "narration": "Purchase / expense"}
                for acc, amt in by_account.items() if amt
            ]

            if bill.get("cgst_paise", 0) > 0:
                lines.append({
                    "account_id": gst_input_id,
                    "debit_paise": bill["cgst_paise"],
                    "credit_paise": 0,
                    "narration": "CGST input tax credit",
                })
            if bill.get("sgst_paise", 0) > 0:
                lines.append({
                    "account_id": gst_input_id,
                    "debit_paise": bill["sgst_paise"],
                    "credit_paise": 0,
                    "narration": "SGST input tax credit",
                })
            if bill.get("igst_paise", 0) > 0:
                lines.append({
                    "account_id": gst_input_id,
                    "debit_paise": bill["igst_paise"],
                    "credit_paise": 0,
                    "narration": "IGST input tax credit",
                })

            net_payable = bill.get("net_payable_paise", bill["total_paise"])
            lines.append({
                "account_id": payables_id,
                "debit_paise": 0,
                "credit_paise": net_payable,
                "narration": "Trade payable to vendor",
            })

            tds_paise = bill.get("tds_paise", 0)
            if tds_paise > 0:
                section = bill.get("tds_section", "194C")
                lines.append({
                    "account_id": tds_pay_id,
                    "debit_paise": 0,
                    "credit_paise": tds_paise,
                    "narration": f"TDS payable — IT Act §{section}",
                })

            section_note = bill.get("tds_section", "194C") if tds_paise > 0 else "NA"
            narration = (
                f"Purchase bill {bill.get('bill_no', 'N/A')} from vendor — "
                f"IT Act §{section_note}"
            )

            _ccy = self._currency_kwargs(db, bill, firm_id, client_id, lines)
            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=bill.get("bill_date", str(datetime.now(timezone.utc).date())),
                reference_no=bill.get("bill_no", ""),
                narration=narration,
                entry_type="Purchase",
                lines=lines,
                **_ccy,
            )
        except ValueError:
            raise
        except Exception as e:
            _logger.error("journal_for_purchase_bill error: %s", e)
            return None

    def journal_for_purchase_payment(
        self, payment: dict, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Dr Trade Payables = amount_paise
        Cr Bank Account   = amount_paise
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_purchase_payment: %s", payment.get("payment_no"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            payables_id = self._find_account(
                db, firm_id, client_id, "%Trade Payable%", system_key="ap"
            )
            bank_id = self._find_account(
                db, firm_id, client_id, "%Bank%", system_key="bank"
            )

            lines = [
                {
                    "account_id": payables_id,
                    "debit_paise": payment["amount_paise"],
                    "credit_paise": 0,
                    "narration": "Trade payable cleared",
                },
                {
                    "account_id": bank_id,
                    "debit_paise": 0,
                    "credit_paise": payment["amount_paise"],
                    "narration": "Bank payment to vendor",
                },
            ]

            _ccy = self._currency_kwargs(db, payment, firm_id, client_id, lines)
            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=payment.get("payment_date", str(datetime.now(timezone.utc).date())),
                reference_no=payment["payment_no"],
                narration=f"Vendor payment {payment['payment_no']}",
                entry_type="Payment",
                lines=lines,
                **_ccy,
            )
        except ValueError:
            raise
        except Exception as e:
            # R2.9 adversarial review finding (CONFIRMED): unlike journal_for_receipt
            # (hardened under F7/R1.6 to re-raise), this used to swallow the error and
            # return None. A vendor payment relieves the AP sub-ledger the same way a
            # receipt relieves AR, so a silently-dropped journal here leaves a payment
            # marked paid with NO corresponding GL entry — the exact phantom-subledger
            # bug F7 closed for receipts. Re-raise so the caller aborts before the
            # payment row (and the bill's paid_paise/status) is ever written.
            _logger.error("journal_for_purchase_payment error: %s", e)
            raise

    @staticmethod
    def _build_payroll_lines(account_ids: dict, run: dict) -> list[dict]:
        """Build a BALANCED payroll-accrual journal (fixes F13).

        The employer's total cost of employment = gross wages + employer PF/ESI.
        By the payroll identity (net = gross − employee PF − employee ESI − PT −
        TDS, and total_pf/total_esi carry employee+employer), that total equals
        (net + PF + ESI + PT + TDS) — i.e. the sum of every payable credit. Booking
        the Salaries Expense debit as that sum makes the entry balance by
        construction, whatever the mix of contributions. The prior code debited
        only `gross`, leaving it short by the employer PF/ESI, so _create_journal's
        balance check raised and finalization 500'd on essentially every run.

        Employer PF/ESI is folded into Salaries Expense here (matching the module's
        single-expense-account design). A future enhancement could split it into a
        dedicated "Contribution to PF & Other Funds" account for the Schedule III
        employee-benefit sub-classification — see roadmap.
        """
        net = run["total_net_paise"]
        pf = run["total_pf_paise"]
        esi = run["total_esi_paise"]
        pt = run["total_pt_paise"]
        tds = run["total_tds_paise"]
        month = run.get("month", "")

        # Payable credits — only include a line when the amount is non-zero.
        credits: list[tuple[str, int, str]] = [
            (account_ids["net"], net, "Net salary payable to employees"),
        ]
        if pf > 0:
            credits.append((account_ids["pf"], pf, "PF payable (employee + employer) — EPF Act"))
        if esi > 0:
            credits.append((account_ids["esi"], esi, "ESI payable (employee + employer) — ESI Act"))
        if pt > 0:
            credits.append((account_ids["pt"], pt, "Professional Tax payable — IT Act §16(iii)"))
        if tds > 0:
            credits.append((account_ids["tds"], tds, "TDS on salary payable 24Q — IT Act §192"))

        total_cost = sum(amount for _, amount, _ in credits)  # = gross + employer PF/ESI

        # Defensive invariant (fail loud instead of posting a wrong-but-balanced
        # journal): because the debit is DEFINED as sum(credits), the kernel's
        # balance check can no longer catch a mis-computed run. total_cost must equal
        # gross + employer PF/ESI, hence lie in [gross, gross + PF + ESI]. A value
        # below gross means `net` was reduced by a deduction with no matching credit
        # leg here (e.g. a future loan/advance recovery) — which would silently
        # understate salary expense. Guarded so that regression surfaces immediately.
        gross = int(run.get("total_gross_paise") or 0)
        if gross and not (gross <= total_cost <= gross + pf + esi):
            raise ValueError(
                f"Payroll journal identity violated: total_cost={total_cost} outside "
                f"[{gross}, {gross + pf + esi}] — a deduction is missing a credit leg."
            )

        lines: list[dict] = [{
            "account_id": account_ids["salary_exp"], "debit_paise": total_cost, "credit_paise": 0,
            "narration": f"Salaries + employer statutory contributions for {month} — IT Act §192",
        }]
        for account_id, amount, narration in credits:
            lines.append({"account_id": account_id, "debit_paise": 0, "credit_paise": amount,
                          "narration": narration})
        return lines

    def journal_for_payroll(
        self, run: dict, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Create payroll accrual journal on finalization.
        IT Act §192: TDS on salary — credited to TDS Payable (24Q).
        EPF Act: PF Payable (employer + employee combined).
        ESI Act: ESI Payable. PT: state-wise Professional Tax Payable.

        Dr  Salaries Expense        (gross wages + employer PF/ESI = total cost)
          Cr  Net Salary Payable    (net pay)
          Cr  PF Payable            (employee + employer PF)
          Cr  ESI Payable           (employee + employer ESI)
          Cr  PT Payable
          Cr  TDS Payable - Salary

        The debit is the employer's TOTAL cost of employment, so the entry
        balances (see _build_payroll_lines). A prior version debited only `gross`,
        which is short by the employer PF/ESI, so every finalization with the
        default contributions failed the posting-kernel balance check (F13).
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_payroll: %s", run.get("month"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            # Payroll accounts use name matching only — no system_account_key for these
            salary_exp_id  = self._find_account(db, firm_id, client_id, "%Salaries Expense%")
            net_sal_id     = self._find_account(db, firm_id, client_id, "%Net Salary Payable%")
            pf_id          = self._find_account(db, firm_id, client_id, "%PF Payable%")
            esi_id         = self._find_account(db, firm_id, client_id, "%ESI Payable%")
            pt_id          = self._find_account(db, firm_id, client_id, "%PT Payable%")
            tds_sal_id     = self._find_account(db, firm_id, client_id, "%TDS Payable - Salary%")

            lines = self._build_payroll_lines(
                {
                    "salary_exp": salary_exp_id, "net": net_sal_id, "pf": pf_id,
                    "esi": esi_id, "pt": pt_id, "tds": tds_sal_id,
                },
                run,
            )

            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=str(datetime.now(timezone.utc).date()),
                reference_no=f"PAY-{run['month']}",
                narration=f"Payroll accrual for {run['month']}",
                entry_type="Journal",
                lines=lines,
            )
        except ValueError:
            raise
        except Exception as e:
            _logger.error("journal_for_payroll error: %s", e)
            return None

    def journal_for_asset_acquisition(
        self, asset: dict, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Asset acquisition journal.
        Dr  Fixed Asset Account (cost_paise)
          Cr  Bank / Creditor (cost_paise)
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_asset_acquisition: %s", asset.get("asset_name"))
            return None
        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            category = asset.get("asset_category", "Plant & Machinery")
            cat_map = {
                "Plant & Machinery": "%Plant & Machinery%",
                "Furniture": "%Furniture & Fixtures%",
                "Computer": "%Computers & Software%",
                "Vehicle": "%Vehicles%",
                "Building": "%Land & Building%",
                "Intangible": "%Intangible Assets%",
            }
            asset_acct = self._find_account(db, firm_id, client_id, cat_map.get(category, "%Plant & Machinery%"))
            bank_id    = self._find_account(db, firm_id, client_id, "%Bank%", system_key="bank")

            cost = asset["purchase_cost_paise"]
            return self._create_journal(
                db=db, firm_id=firm_id, client_id=client_id,
                entry_date=asset["purchase_date"],
                reference_no=f"FA-ACQ-{asset.get('asset_code', asset['id'][:8])}",
                narration=f"Asset acquisition: {asset['asset_name']}",
                entry_type="Journal",
                lines=[
                    {"account_id": asset_acct, "debit_paise": cost, "credit_paise": 0,
                     "narration": f"Fixed asset: {asset['asset_name']}"},
                    {"account_id": bank_id, "debit_paise": 0, "credit_paise": cost,
                     "narration": "Bank payment for asset acquisition"},
                ],
            )
        except Exception as e:
            _logger.error("journal_for_asset_acquisition error: %s", e)
            return None

    def journal_for_depreciation(
        self, asset: dict, depreciation_paise: int, period: str, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Monthly/annual depreciation journal.
        Dr  Depreciation Expense        (depreciation_paise)
          Cr  Accumulated Depreciation  (depreciation_paise)
        """
        if _USE_MOCK:
            return None
        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            depn_exp_id  = self._find_account(db, firm_id, client_id, "%Depreciation Expense%")
            accum_dep_id = self._find_account(db, firm_id, client_id, "%Accumulated Depreciation%")

            return self._create_journal(
                db=db, firm_id=firm_id, client_id=client_id,
                entry_date=str(datetime.now(timezone.utc).date()),
                reference_no=f"FA-DEPN-{asset.get('asset_code', asset['id'][:8])}-{period}",
                narration=f"Depreciation on {asset['asset_name']} for {period}",
                entry_type="Journal",
                lines=[
                    {"account_id": depn_exp_id,  "debit_paise": depreciation_paise, "credit_paise": 0,
                     "narration": f"Depreciation: {asset['asset_name']} ({asset['depreciation_method']})"},
                    {"account_id": accum_dep_id, "debit_paise": 0, "credit_paise": depreciation_paise,
                     "narration": f"Accumulated depreciation: {asset['asset_name']}"},
                ],
            )
        except Exception as e:
            _logger.error("journal_for_depreciation error: %s", e)
            return None

    def journal_for_asset_disposal(
        self, asset: dict, sale_proceeds_paise: int, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Asset disposal journal.
        Dr  Accumulated Depreciation  (accumulated_depreciation_paise)
        Dr  Bank                      (sale_proceeds_paise)
        Dr/Cr  P&L on Disposal        (balancing — loss or gain)
          Cr  Fixed Asset Account     (purchase_cost_paise)
        """
        if _USE_MOCK:
            return None
        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            category = asset.get("asset_category", "Plant & Machinery")
            cat_map = {
                "Plant & Machinery": "%Plant & Machinery%",
                "Furniture": "%Furniture & Fixtures%",
                "Computer": "%Computers & Software%",
                "Vehicle": "%Vehicles%",
                "Building": "%Land & Building%",
                "Intangible": "%Intangible Assets%",
            }
            asset_acct    = self._find_account(db, firm_id, client_id, cat_map.get(category, "%Plant & Machinery%"))
            accum_dep_id  = self._find_account(db, firm_id, client_id, "%Accumulated Depreciation%")
            bank_id       = self._find_account(db, firm_id, client_id, "%Bank%", system_key="bank")

            cost        = asset["purchase_cost_paise"]
            accum_depn  = asset.get("accumulated_depreciation_paise", 0)
            wdv         = cost - accum_depn
            gain_loss   = sale_proceeds_paise - wdv  # positive = gain, negative = loss

            lines = [
                {"account_id": accum_dep_id, "debit_paise": accum_depn, "credit_paise": 0,
                 "narration": "Accumulated depreciation cleared on disposal"},
                {"account_id": bank_id,       "debit_paise": sale_proceeds_paise, "credit_paise": 0,
                 "narration": "Sale proceeds from asset disposal"},
                {"account_id": asset_acct,    "debit_paise": 0, "credit_paise": cost,
                 "narration": f"Fixed asset removed: {asset['asset_name']}"},
            ]

            if gain_loss > 0:
                gain_id = self._find_account(db, firm_id, client_id, "%Profit on Asset Disposal%")
                lines.append({"account_id": gain_id, "debit_paise": 0, "credit_paise": gain_loss,
                               "narration": "Gain on disposal of fixed asset"})
            elif gain_loss < 0:
                loss_id = self._find_account(db, firm_id, client_id, "%Loss on Asset Disposal%")
                lines.append({"account_id": loss_id, "debit_paise": abs(gain_loss), "credit_paise": 0,
                               "narration": "Loss on disposal of fixed asset"})

            return self._create_journal(
                db=db, firm_id=firm_id, client_id=client_id,
                entry_date=asset.get("disposal_date", str(datetime.now(timezone.utc).date())),
                reference_no=f"FA-DISP-{asset.get('asset_code', asset['id'][:8])}",
                narration=f"Asset disposal: {asset['asset_name']}",
                entry_type="Journal",
                lines=lines,
            )
        except Exception as e:
            _logger.error("journal_for_asset_disposal error: %s", e)
            return None

    # ------------------------------------------------------------------ #
    #  Private Helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def bank_txn_lines(
        debit_paise: int,
        credit_paise: int,
        account_id: str,
        bank_coa_account_id: str,
    ) -> tuple[int, str, list[dict]]:
        """
        Pure, side-effect-free construction of the double-entry for a single bank
        statement line. Returned as (amount_paise, entry_type, lines).

        Double-entry rules (IT Act §145 — mercantile/double-entry):
          money OUT of bank  (debit_paise > 0)  → Dr counter-account / Cr bank   ("Payment")
          money INTO  bank   (credit_paise > 0)  → Dr bank / Cr counter-account   ("Receipt")
        Exactly one of debit/credit is non-zero on a bank line. Integer paise only.
        """
        debit_paise = int(debit_paise or 0)
        credit_paise = int(credit_paise or 0)
        amount = max(debit_paise, credit_paise)
        if amount <= 0:
            raise ValueError("Bank transaction has zero amount")
        if debit_paise > 0:
            return amount, "Payment", [
                {"account_id": account_id, "debit_paise": amount, "credit_paise": 0},
                {"account_id": bank_coa_account_id, "debit_paise": 0, "credit_paise": amount},
            ]
        return amount, "Receipt", [
            {"account_id": bank_coa_account_id, "debit_paise": amount, "credit_paise": 0},
            {"account_id": account_id, "debit_paise": 0, "credit_paise": amount},
        ]

    def journal_for_bank_transaction(
        self,
        db,
        firm_id: str,
        client_id: str,
        txn: dict,
        account_id: str,
        bank_coa_account_id: str,
    ) -> str:
        """
        Create a balanced journal entry for a posted bank transaction, reusing the
        shared engine (_create_journal — integer paise, balance-validated, dedup).
        Account classification is the caller's responsibility (it supplies the
        mapped GL account); this only forms and posts the entry. Returns the
        journal_entry_id.
        """
        amount, entry_type, lines = self.bank_txn_lines(
            txn.get("debit_paise", 0), txn.get("credit_paise", 0),
            account_id, bank_coa_account_id,
        )
        # Reference embeds the bank txn id so re-posting the same line is
        # idempotent (dedup) while distinct lines never collide.
        ref = f"{(txn.get('reference_no') or 'BANK')}-{str(txn.get('id', ''))[:8]}"
        narration = f"Bank import: {txn.get('description', '')}".strip()
        return self._create_journal(
            db, firm_id=firm_id, client_id=client_id,
            entry_date=str(txn["transaction_date"])[:10],
            reference_no=ref, narration=narration, entry_type=entry_type, lines=lines,
        )

    def _find_account(
        self,
        db,
        firm_id: str,
        client_id: str,
        name_pattern: str,
        system_key: Optional[str] = None,
    ) -> str:
        """
        Resolve a chart_of_accounts row by system_account_key first, then by
        account_name ILIKE as fallback. Mirrors the pattern in
        domain/reporting/resolver.py._by_key_or_name.

        system_key lookup: firm-wide, not client-filtered (keys are stable).
        name_pattern fallback: client_id OR NULL scope (mirrors the original behaviour).

        Raises:
            ValueError: If neither key nor name lookup finds an active account.
        """
        if system_key:
            try:
                resp = (
                    db.table("chart_of_accounts")
                    .select("id")
                    .eq("firm_id", firm_id)
                    .eq("system_account_key", system_key)
                    .eq("is_active", True)
                    .limit(1)
                    .execute()
                )
                if resp.data:
                    return resp.data[0]["id"]
            except Exception as e:
                _logger.warning("_find_account key lookup failed (%s): %s", system_key, e)

        # Name-pattern fallback — preserves pre-key behaviour for all accounts
        try:
            resp = (
                db.table("chart_of_accounts")
                .select("id")
                .eq("firm_id", firm_id)
                .or_(f"client_id.eq.{client_id},client_id.is.null")
                .ilike("account_name", name_pattern)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if resp.data:
                return resp.data[0]["id"]
        except Exception as e:
            _logger.warning("_find_account lookup failed (%s): %s", name_pattern, e)

        raise ValueError(
            f"Required account not found: {name_pattern}. "
            "Please set up Chart of Accounts before posting."
        )

    def exchange_rate_service(self, db):
        """The ExchangeRateService available to the posting pipeline (Phase 2, Task 3).

        Manual provider by default (no automatic fetching); another provider is used
        only if explicitly configured. NOT invoked for INR postings — same-currency
        is the identity (rate 1) handled inline — so the INR path stays zero-overhead.
        The seam exists so foreign-document phases obtain an immutable RateQuote and
        freeze it on the posting, with zero change to the kernel or reports."""
        from domain.currency import ExchangeRateService, ManualRateProvider
        return ExchangeRateService([ManualRateProvider(db)], default_source="manual")

    def _currency_kwargs(self, db, doc_row: dict, firm_id: str, client_id: str, lines: list[dict]) -> dict:
        """For a foreign document (Multi-Currency Phase 3): reconstruct the frozen
        rate from the stored row, stamp each journal line's foreign (memo) amount at
        that rate (G4 dual storage), and return the currency kwargs for
        _create_journal — including the re-resolved CurrencyPolicy so the kernel's
        authoritative gate is satisfied. INR / feature-off ⇒ returns {} and stamps
        nothing, so INR postings are byte-for-byte unchanged."""
        from domain.currency.document_currency import document_currency_from_row
        from domain.currency.policy import resolve_currency_policy

        dc = document_currency_from_row(db, doc_row or {})
        if not dc.is_foreign:
            return {}
        for l in lines:
            l["txn_currency"] = dc.currency
            l["exchange_rate"] = dc.rate
            l["txn_debit"] = dc.to_txn(int(l.get("debit_paise") or 0))
            l["txn_credit"] = dc.to_txn(int(l.get("credit_paise") or 0))
        firm = (db.table("firms").select("multi_currency_entitled").eq("id", firm_id).limit(1).execute().data or [None])[0]
        client = (db.table("clients").select("functional_currency, multi_currency_enabled").eq("id", client_id).limit(1).execute().data or [None])[0]
        return {
            "txn_currency": dc.currency, "exchange_rate": dc.rate, "rate_source": dc.rate_source,
            "rate_type": dc.rate_type, "rate_date": dc.rate_date, "rate_selected_by": dc.rate_selected_by,
            "rate_overridden": dc.rate_overridden, "currency_policy": resolve_currency_policy(firm, client),
        }

    def _create_journal(
        self,
        db,
        firm_id: str,
        client_id: str,
        entry_date: str,
        reference_no: str,
        narration: str,
        entry_type: str,
        lines: list[dict],
        is_posted: bool = True,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        created_by: Optional[str] = None,
        reversal_of: Optional[str] = None,
        attachments: Optional[list] = None,
        # ── Multi-Currency Phase 2 (all optional; default → INR/rate 1, dormant) ──
        txn_currency: Optional[str] = None,
        exchange_rate: Optional[Decimal] = None,
        rate_source: Optional[str] = None,
        rate_type: Optional[str] = None,
        rate_date: Optional[str] = None,
        rate_selected_by: Optional[str] = None,
        rate_overridden: bool = False,
        currency_policy: Optional[CurrencyPolicy] = None,
    ) -> str:
        """
        Insert a balanced double-entry journal entry and its lines.
        Validates that total debits == total credits before insert.
        All monetary values are integer paise (BIGINT) — never float.
        Returns the journal_entry_id.

        Phase 3.5: pass is_posted=False to create a DRAFT (off-books until a human
        approves it via journal_posting_service.post_draft). Default True keeps
        every existing caller's behaviour unchanged. source_type/source_id record
        the origin so posting the draft can fire its deferred downstream action.
        """
        total_debit  = sum(l["debit_paise"]  for l in lines)
        total_credit = sum(l["credit_paise"] for l in lines)
        if total_debit != total_credit:
            raise ValueError(
                f"Journal imbalance: debit={total_debit} credit={total_credit} "
                f"for ref={reference_no}"
            )
        # M8: a balanced-but-zero journal is meaningless — never post it.
        if total_debit == 0:
            raise ValueError(f"Refusing to post a zero-value journal entry for ref={reference_no}")

        # ── Multi-Currency Phase 2 (foundation): resolve the currency metadata ────
        # Base currency is authoritative and always INR (Capability A). Everything
        # defaults to the INR / rate=1 identity, so INR postings are byte-for-byte
        # unchanged. A non-INR txn currency or rate≠1 is REFUSED unless an ACTIVE
        # CurrencyPolicy is supplied — the kernel is the authoritative gate (G2),
        # fail-safe to INR. No current caller passes foreign values, so the foreign
        # branch is dormant; base balancing (above) is unaffected either way.
        base_ccy = BASE_CURRENCY
        entry_ccy = (txn_currency or base_ccy).strip().upper()
        rate = exchange_rate if exchange_rate is not None else Decimal(1)
        eff_rate_type = rate_type or DEFAULT_RATE_TYPE
        eff_rate_date = rate_date or entry_date
        eff_rate_source = rate_source or (
            "identity" if entry_ccy == base_ccy and rate == Decimal(1) else None
        )
        is_foreign = entry_ccy != base_ccy or rate != Decimal(1)
        if is_foreign:
            if currency_policy is None or not getattr(currency_policy, "active", False):
                raise ValueError(
                    "Multi-currency posting requires an active currency policy; only "
                    "INR postings are permitted while the feature is dormant."
                )
            if not is_valid_rate_type(eff_rate_type):
                raise ValueError(f"unknown rate_type {eff_rate_type!r}")
            if rate <= 0:
                raise ValueError("exchange_rate must be positive")

        # Idempotency fast path (firm-scoped): same firm+client+reference_no+entry_date
        # is already posted → return it. The UNIQUE index (migration 143) is the
        # authoritative backstop for the concurrent race this SELECT can't close (H2).
        def _find_existing():
            return (db.table("journal_entries").select("id")
                    .eq("firm_id", firm_id).eq("client_id", client_id)
                    .eq("reference_no", reference_no).eq("entry_date", entry_date)
                    .limit(1).execute())
        if not _USE_MOCK and reference_no:
            try:
                existing = _find_existing()
                if existing.data:
                    _logger.warning(
                        "Duplicate journal detected for firm=%s ref=%s date=%s client=%s — skipping",
                        firm_id, reference_no, entry_date, client_id,
                    )
                    return existing.data[0]["id"]
            except Exception:
                pass

        now_iso = datetime.now(timezone.utc).isoformat()
        entry_payload = {
            "firm_id":      firm_id,
            "client_id":    client_id,
            "entry_date":   entry_date,
            "reference_no": reference_no,
            "narration":    narration,
            "entry_type":   entry_type,
            "is_posted":    is_posted,
            "status":       "posted" if is_posted else "draft",
            "posted_at":    now_iso if is_posted else None,
            "posted_by":    created_by if is_posted else None,
            "created_by":   created_by,
            "source_type":  source_type,
            "source_id":    source_id,
        }
        # Additive, optional fields — only written when a caller supplies them, so
        # every existing posting path (invoices, receipts, opening balances, …) is
        # byte-for-byte unchanged. reversal_of links a reversal to its original;
        # attachments carries manual-journal supporting documents.
        if reversal_of is not None:
            entry_payload["reversal_of"] = reversal_of
        if attachments is not None:
            entry_payload["attachments"] = attachments
        # Rate-selection provenance (G6) — additive; only stamped when a rate was
        # actually chosen, so INR auto-postings keep a byte-for-byte-unchanged entry
        # payload (rate_overridden defaults FALSE, rate_selected_at NULL at the DB).
        if rate_overridden:
            entry_payload["rate_overridden"] = True
        if rate_selected_by is not None:
            entry_payload["rate_selected_by"] = rate_selected_by
            entry_payload["rate_selected_at"] = now_iso

        # Atomic posting (F2): the header and ALL its lines are inserted in ONE
        # server-side transaction via post_journal_atomic (migration 152). A line
        # failure now rolls the header back with it, so it can never strand an
        # immutable orphan header (which the immutability trigger made unrepairable).
        # The RPC also closes the (firm, client, reference_no, entry_date) idempotency
        # race — on a concurrent duplicate (23505) it returns the winning entry's id.
        line_payloads = [
            {
                "account_id":       l["account_id"],
                "debit_paise":      l["debit_paise"],
                "credit_paise":     l["credit_paise"],
                "narration":        l.get("narration", ""),
                # Multi-Currency Phase 2 dual storage (G4): the base (INR) amount stays
                # authoritative in debit_paise/credit_paise; for INR postings the txn
                # amount equals the base and the rate is 1. Per-line overrides support
                # future foreign documents; no current caller supplies them.
                "txn_currency":  (l.get("txn_currency") or entry_ccy),
                "base_currency": base_ccy,
                "exchange_rate": str(l["exchange_rate"] if l.get("exchange_rate") is not None else rate),
                "txn_debit":     l["txn_debit"] if l.get("txn_debit") is not None else l["debit_paise"],
                "txn_credit":    l["txn_credit"] if l.get("txn_credit") is not None else l["credit_paise"],
                "rate_source":   l.get("rate_source", eff_rate_source),
                "rate_type":     l.get("rate_type", eff_rate_type),
                "rate_date":     l.get("rate_date", eff_rate_date),
            }
            for l in lines
        ]
        if hasattr(db, "rpc"):
            # Real Supabase client (prod) and the e2e FakeDB both expose rpc — this
            # is the atomic path that makes F2 impossible. DEPLOYMENT REQUIREMENT:
            # migration 152 (which creates post_journal_atomic) MUST be applied to
            # the target database before this code is deployed — there is no
            # fallback, deliberately: falling back to the old two-insert path would
            # silently reintroduce the F2 orphan-header bug this milestone fixes.
            # A missing function surfaces as a clear, diagnosable error below
            # instead of an opaque 500, so a migrate-before-deploy mistake is
            # immediately obvious rather than presenting as "every posting is down."
            try:
                result = db.rpc(
                    "post_journal_atomic",
                    {"p_entry": entry_payload, "p_lines": line_payloads},
                ).execute()
            except Exception as rpc_err:
                msg = str(rpc_err).lower()
                if "post_journal_atomic" in msg or "function" in msg and ("not exist" in msg or "not found" in msg or "pgrst202" in msg):
                    raise RuntimeError(
                        "post_journal_atomic RPC not found — migration 152 "
                        "(apps/api/migrations/152_atomic_journal_posting.sql) must be "
                        "applied to this database before the API is deployed."
                    ) from rpc_err
                raise
            entry_id = result.data
            if not entry_id:
                raise RuntimeError(f"Failed to post journal for ref={reference_no}")
        else:
            # In-memory test double without rpc — two inserts (trivially atomic in
            # a synchronous fake). Never reached in production (the Supabase client
            # always exposes rpc).
            entry_resp = db.table("journal_entries").insert(entry_payload).execute()
            if not entry_resp.data:
                raise RuntimeError(f"Failed to insert journal_entry for ref={reference_no}")
            entry_id = entry_resp.data[0]["id"]
            db.table("journal_lines").insert(
                [{**lp, "journal_entry_id": entry_id} for lp in line_payloads]
            ).execute()

        _logger.info(
            "%s journal %s | ref=%s | dr=%d cr=%d",
            "Posted" if is_posted else "Drafted", entry_id, reference_no, total_debit, total_credit,
        )
        return entry_id

    def reverse_entry(
        self,
        db,
        firm_id: str,
        entry_id: str,
        reversal_date: str,
        narration: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> str:
        """Post an equal-and-opposite reversal of a posted journal entry THROUGH the
        kernel — the single reversal path used by manual journal reversal AND by
        document cancellation (sales invoice / purchase bill).

        Append-only: the original entry is never modified or deleted (immutability
        preserved); a new balanced entry with swapped debit/credit is posted and
        linked via reversal_of. Firm-scoped. `created_by` MUST be the internal
        users.id. Returns the reversal entry id.

        Raises HTTPException: 404 (not found in firm), 422 (not posted / no lines),
        409 (already a reversal / already reversed).
        """
        res = (db.table("journal_entries").select("*")
               .eq("id", entry_id).eq("firm_id", firm_id).limit(1).execute())
        orig = (res.data or [None])[0]
        if not orig:
            raise HTTPException(status_code=404, detail="Journal entry not found")
        if not orig.get("is_posted"):
            raise HTTPException(status_code=422, detail="Only posted journal entries can be reversed")
        if orig.get("reversal_of"):
            raise HTTPException(status_code=409, detail="This entry is itself a reversal — cannot reverse a reversal")
        already = (db.table("journal_entries").select("id")
                   .eq("firm_id", firm_id).eq("reversal_of", entry_id).limit(1).execute().data)
        if already:
            raise HTTPException(status_code=409, detail=f"Journal {entry_id} has already been reversed")

        lines = (db.table("journal_lines").select("*")
                 .eq("journal_entry_id", entry_id).execute().data) or []
        if not lines:
            raise HTTPException(status_code=422, detail="Cannot reverse a journal entry with no lines")

        narration = narration or f"Reversal of journal {entry_id}"
        rev_lines = [{
            "account_id":   l["account_id"],
            "debit_paise":  int(l.get("credit_paise") or 0),
            "credit_paise": int(l.get("debit_paise") or 0),
            "narration":    narration,
        } for l in lines]
        ref = f"REV-{orig.get('reference_no') or entry_id[:8]}"
        return self._create_journal(
            db=db, firm_id=firm_id, client_id=orig["client_id"], entry_date=reversal_date,
            reference_no=ref, narration=narration, entry_type=orig.get("entry_type") or "Journal",
            lines=rev_lines, is_posted=True, created_by=created_by, reversal_of=entry_id,
        )


# Module-level singleton
phase2_journal_service = Phase2JournalService()
