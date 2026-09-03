"use client";

import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { BankRegister } from "@/components/banking/BankBook";

/**
 * Bank Book — the bank ledger: every statement line in date order with a
 * running balance, its cleared status (C / R), and the self-check against the
 * balance column the bank's own statement carried.
 *
 * It was a tab of the Bank module until 2026-09-03, and moved here because it
 * is a REPORT — something a CA opens to look a figure up ("what was the
 * balance on the 14th?") — not a step in the month's work. The work is Bank ›
 * Entries; this is what the work produced.
 *
 * ZERO BUSINESS LOGIC HERE. Every figure comes from api.banking.register,
 * which pages server-side: the running balance is computed in date order on
 * the server and this page sorts nothing and sums nothing. The register is
 * read-only by design — a posted journal is corrected by a reversal, never
 * edited, and the register follows.
 */
export default function BankBookReportPage() {
  const router = useRouter();
  const { clientId } = useClientNav();

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="min-w-0">
        <button
          onClick={() => router.push(`/clients/${clientId}/reports`)}
          className="flex items-center gap-1 text-[11px] text-[#94A3B8] hover:text-[#64748B] mb-1.5"
        >
          <ArrowLeft size={12} /> Reports
        </button>
        <h2 className="text-sm font-semibold text-[#1E293B]">Bank Book</h2>
        <p className="text-[11px] text-[#94A3B8] mt-0.5">
          The bank ledger — running balance, cleared status, and the check against the
          statement&apos;s own balance column. To pass entries, go to Bank › Entries.
        </p>
      </div>
      <BankRegister clientId={clientId} />
    </div>
  );
}
