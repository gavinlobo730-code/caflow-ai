"use client";

/**
 * Bank Reconciliation — placeholder (Phase B.0 quarantine).
 *
 * The previous implementation read/wrote bank_transactions and bank_reconciliations
 * directly from the browser against a divergent column set (`date`, `reconciled`)
 * that does not match the live schema (`transaction_date`, `match_status`), so it
 * was non-functional. Per the banking foundation cleanup, all bank mutations now
 * go through the backend banking service; the reconciliation workflow itself
 * (matching, period close, exception handling) is scheduled for Phase B.4 and will
 * be built on that backend foundation. This screen intentionally performs no
 * direct database access.
 */

import Link from "next/link";
import { ChevronLeft, Banknote } from "lucide-react";

export default function BankReconciliationPage() {
  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Bank Reconciliation</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Match bank statements against the ledger</p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-[#F1F5F9] p-10 text-center space-y-3">
        <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center mx-auto">
          <Banknote className="w-5 h-5 text-blue-500" />
        </div>
        <h2 className="text-sm font-semibold text-[#1E293B]">Reconciliation is being rebuilt</h2>
        <p className="text-xs text-[#94A3B8] max-w-md mx-auto">
          Banking now runs on a unified backend service (Phase B.0). Statement import and
          posting to the ledger are available under <span className="font-medium">Accounting → Banks</span> in a
          client&apos;s workspace. The full reconciliation workflow — matching, period close and
          exceptions — arrives in Phase B.4 on this new foundation.
        </p>
      </div>
    </div>
  );
}
