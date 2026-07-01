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
from typing import Optional

from fastapi import HTTPException

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.phase2_journal")


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

            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=invoice.get("invoice_date", str(datetime.now(timezone.utc).date())),
                reference_no=invoice["invoice_no"],
                narration=f"Sales invoice {invoice['invoice_no']} to customer — CGST Act §9",
                entry_type="Sales",
                lines=lines,
            )
        except ValueError:
            # Re-raise account resolution and balance errors so the router returns 422
            raise
        except Exception as e:
            _logger.error("journal_for_sales_invoice error: %s", e)
            return None

    def journal_for_receipt(
        self, receipt: dict, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Dr Bank Account      = amount_paise (cash received)
        Dr TDS Receivable    = tds_paise    (if the client deducted TDS — IT Act §194J)
        Cr Trade Receivables = amount_paise + tds_paise (total settlement)
        The invoice can be fully settled even when cash < invoice value because the
        TDS portion is recorded as a receivable (claimable against the firm's IT,
        reconcilable to 26AS/AIS).
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_receipt: %s", receipt.get("receipt_no"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

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

            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=receipt.get("receipt_date", str(datetime.now(timezone.utc).date())),
                reference_no=receipt["receipt_no"],
                narration=f"Receipt {receipt['receipt_no']} from customer",
                entry_type="Receipt",
                lines=lines,
            )
        except ValueError:
            raise
        except Exception as e:
            _logger.error("journal_for_receipt error: %s", e)
            return None

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

            lines = [
                {
                    "account_id": purchases_id,
                    "debit_paise": bill["taxable_amount_paise"],
                    "credit_paise": 0,
                    "narration": "Purchase / expense",
                },
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

            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=bill.get("bill_date", str(datetime.now(timezone.utc).date())),
                reference_no=bill.get("bill_no", ""),
                narration=narration,
                entry_type="Purchase",
                lines=lines,
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

            return self._create_journal(
                db=db,
                firm_id=firm_id,
                client_id=client_id,
                entry_date=payment.get("payment_date", str(datetime.now(timezone.utc).date())),
                reference_no=payment["payment_no"],
                narration=f"Vendor payment {payment['payment_no']}",
                entry_type="Payment",
                lines=lines,
            )
        except ValueError:
            raise
        except Exception as e:
            _logger.error("journal_for_purchase_payment error: %s", e)
            return None

    def journal_for_payroll(
        self, run: dict, firm_id: str, client_id: str
    ) -> Optional[str]:
        """
        Create payroll accrual journal on finalization.
        IT Act §192: TDS on salary — credited to TDS Payable (24Q).
        EPF Act: PF Payable (employer + employee combined).
        ESI Act: ESI Payable. PT: state-wise Professional Tax Payable.

        Dr  Salaries Expense        (total gross)
          Cr  Net Salary Payable    (net pay)
          Cr  PF Payable            (employee + employer PF)
          Cr  ESI Payable           (employee + employer ESI)
          Cr  PT Payable
          Cr  TDS Payable - Salary
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

            gross    = run["total_gross_paise"]
            net      = run["total_net_paise"]
            pf       = run["total_pf_paise"]
            esi      = run["total_esi_paise"]
            pt       = run["total_pt_paise"]
            tds      = run["total_tds_paise"]

            # Net salary = gross - employee deductions; gross includes employer cost
            # Rebalance: Dr Salaries Expense = net + employee_pf + employee_esi + pt + tds
            # Employer PF/ESI are additional Dr (PF Expense / ESI Expense) — simplified here
            # as single Salaries Expense debit for MVP

            lines = [
                {"account_id": salary_exp_id, "debit_paise": gross, "credit_paise": 0,
                 "narration": f"Salary expense for {run['month']} — IT Act §192"},
                {"account_id": net_sal_id,    "debit_paise": 0, "credit_paise": net,
                 "narration": "Net salary payable to employees"},
            ]

            if pf > 0:
                lines.append({"account_id": pf_id, "debit_paise": 0, "credit_paise": pf,
                               "narration": "PF payable (employee + employer) — EPF Act"})
            if esi > 0:
                lines.append({"account_id": esi_id, "debit_paise": 0, "credit_paise": esi,
                               "narration": "ESI payable (employee + employer) — ESI Act"})
            if pt > 0:
                lines.append({"account_id": pt_id, "debit_paise": 0, "credit_paise": pt,
                               "narration": "Professional Tax payable — IT Act §16(iii)"})
            if tds > 0:
                lines.append({"account_id": tds_sal_id, "debit_paise": 0, "credit_paise": tds,
                               "narration": "TDS on salary payable 24Q — IT Act §192"})

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

        # Prevent duplicate journal entries: same reference_no + entry_date + client_id
        if not _USE_MOCK:
            try:
                existing = db.table("journal_entries").select("id").eq("client_id", client_id).eq("reference_no", reference_no).eq("entry_date", entry_date).limit(1).execute()
                if existing.data:
                    _logger.warning(
                        "Duplicate journal detected for ref=%s date=%s client=%s — skipping",
                        reference_no, entry_date, client_id,
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

        entry_resp = db.table("journal_entries").insert(entry_payload).execute()
        if not entry_resp.data:
            raise RuntimeError(f"Failed to insert journal_entry for ref={reference_no}")

        entry_id = entry_resp.data[0]["id"]

        line_payloads = [
            {
                "journal_entry_id": entry_id,
                "account_id":       l["account_id"],
                "debit_paise":      l["debit_paise"],
                "credit_paise":     l["credit_paise"],
                "narration":        l.get("narration", ""),
            }
            for l in lines
        ]
        db.table("journal_lines").insert(line_payloads).execute()

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
