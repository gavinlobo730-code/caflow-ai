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
        Cr GST Output (CGST/SGST/IGST) as applicable
        CGST Act §9: GST on taxable outward supplies.
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_sales_invoice: %s", invoice.get("invoice_no"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            receivables_id = self._find_account(db, firm_id, client_id, "%Trade Receivable%")
            sales_id       = self._find_account(db, firm_id, client_id, "%Sales%")
            gst_output_id  = self._find_account(db, firm_id, client_id, "%GST Output%")

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

            if invoice.get("cgst_paise", 0) > 0:
                lines.append({
                    "account_id": gst_output_id,
                    "debit_paise": 0,
                    "credit_paise": invoice["cgst_paise"],
                    "narration": "CGST output tax payable",
                })
            if invoice.get("sgst_paise", 0) > 0:
                lines.append({
                    "account_id": gst_output_id,
                    "debit_paise": 0,
                    "credit_paise": invoice["sgst_paise"],
                    "narration": "SGST output tax payable",
                })
            if invoice.get("igst_paise", 0) > 0:
                lines.append({
                    "account_id": gst_output_id,
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
        Dr Bank Account      = amount_paise
        Cr Trade Receivables = amount_paise
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_receipt: %s", receipt.get("receipt_no"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            bank_id        = self._find_account(db, firm_id, client_id, "%Bank%")
            receivables_id = self._find_account(db, firm_id, client_id, "%Trade Receivable%")

            lines = [
                {
                    "account_id": bank_id,
                    "debit_paise": receipt["amount_paise"],
                    "credit_paise": 0,
                    "narration": "Cash/bank received from customer",
                },
                {
                    "account_id": receivables_id,
                    "debit_paise": 0,
                    "credit_paise": receipt["amount_paise"],
                    "narration": "Trade receivable cleared",
                },
            ]

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
        Dr GST Output Tax Payable (CGST/SGST/IGST)
        Cr Trade Receivables = total_paise
        CGST Act §34: Credit notes for reduction in taxable value.
        """
        if _USE_MOCK:
            _logger.info("[MOCK] journal_for_credit_note: %s", cn.get("credit_note_no"))
            return None

        try:
            from core.supabase_client import get_supabase
            db = get_supabase()

            sales_id       = self._find_account(db, firm_id, client_id, "%Sales%")
            gst_output_id  = self._find_account(db, firm_id, client_id, "%GST Output%")
            receivables_id = self._find_account(db, firm_id, client_id, "%Trade Receivable%")

            lines = [
                {
                    "account_id": sales_id,
                    "debit_paise": cn["taxable_amount_paise"],
                    "credit_paise": 0,
                    "narration": "Sales returns — credit note",
                },
            ]

            if cn.get("cgst_paise", 0) > 0:
                lines.append({
                    "account_id": gst_output_id,
                    "debit_paise": cn["cgst_paise"],
                    "credit_paise": 0,
                    "narration": "CGST output tax reversed",
                })
            if cn.get("sgst_paise", 0) > 0:
                lines.append({
                    "account_id": gst_output_id,
                    "debit_paise": cn["sgst_paise"],
                    "credit_paise": 0,
                    "narration": "SGST output tax reversed",
                })
            if cn.get("igst_paise", 0) > 0:
                lines.append({
                    "account_id": gst_output_id,
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

            gst_input_id = self._find_account(db, firm_id, client_id, "%GST Input%")
            payables_id  = self._find_account(db, firm_id, client_id, "%Trade Payable%")
            tds_pay_id   = self._find_account(db, firm_id, client_id, "%TDS Payable%")

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

            payables_id = self._find_account(db, firm_id, client_id, "%Trade Payable%")
            bank_id     = self._find_account(db, firm_id, client_id, "%Bank%")

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
            bank_id    = self._find_account(db, firm_id, client_id, "%Bank%")

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
            bank_id       = self._find_account(db, firm_id, client_id, "%Bank%")

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

    def _find_account(
        self,
        db,
        firm_id: str,
        client_id: str,
        name_pattern: str,
    ) -> str:
        """
        Search chart_of_accounts by account_name ILIKE for an active account
        scoped to this firm (client_id may be NULL for firm-wide accounts).

        Raises:
            ValueError: If no matching active account is found.
                        Callers must set up Chart of Accounts before posting.
        """
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
    ) -> str:
        """
        Insert a balanced double-entry journal entry and its lines.
        Validates that total debits == total credits before insert.
        All monetary values are integer paise (BIGINT) — never float.
        Returns the journal_entry_id.
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
            "is_posted":    True,
            "posted_at":    now_iso,
        }

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
            "Auto-posted journal %s | ref=%s | dr=%d cr=%d",
            entry_id, reference_no, total_debit, total_credit,
        )
        return entry_id


# Module-level singleton
phase2_journal_service = Phase2JournalService()
