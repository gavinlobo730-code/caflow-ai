"use client";

/**
 * Phase 3 cleanup — firm-level accounting screens have been retired.
 *
 * Accounting now flows exclusively through the client workspace
 * (Client → Accounting), with the firm's own books represented as the internal
 * "practice" client. This notice replaces the old duplicate firm-level pages so
 * existing links don't 404; it performs no data access.
 */

import Link from "next/link";
import { ChevronLeft, ArrowRight, Building2 } from "lucide-react";

export default function MovedToClientWorkspace({
  feature,
  tab,
}: {
  feature: string;
  tab?: string;
}) {
  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <h1 className="text-xl font-semibold text-[#0F172A]">{feature}</h1>
      </div>

      <div className="bg-white rounded-xl border border-[#F1F5F9] p-8 text-center space-y-4">
        <div className="w-11 h-11 rounded-full bg-blue-50 flex items-center justify-center mx-auto">
          <Building2 className="w-5 h-5 text-blue-500" />
        </div>
        <div className="space-y-1.5">
          <h2 className="text-sm font-semibold text-[#1E293B]">{feature} moved to the client workspace</h2>
          <p className="text-xs text-[#94A3B8] max-w-md mx-auto">
            Accounting now runs through each client&apos;s workspace{tab ? ` → Accounting → ${tab}` : " → Accounting"},
            powered entirely by the backend reporting engine. The firm&apos;s own books appear there
            as the practice client — no separate firm-level path.
          </p>
        </div>
        <Link
          href="/clients"
          className="inline-flex items-center gap-1.5 text-xs font-medium px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          Choose a client <ArrowRight className="w-3.5 h-3.5" />
        </Link>
      </div>
    </div>
  );
}
