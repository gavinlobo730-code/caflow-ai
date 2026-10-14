"use client";

import type { ReactNode } from "react";
import { PageHeader } from "@/components/ui/page-header";
import { usePermissions } from "@/lib/auth/AuthContext";

/**
 * Says so when the signed-in person may not read the practice's fees, instead of showing them an empty screen.
 *
 * WHY THIS EXISTS (POST-B-024). The practice's own fee invoices, receipts and engagements are the practice's
 * economics, which core/permissions reserves to `billing:read` (a Partner's, or a grant from the Partner on the Team
 * screen). The database returns those rows only to a person who holds it and returns NOTHING, without an error, to
 * everyone else. A fee-receivables screen over nothing says "Rs 0.00 outstanding" and "No unpaid fee invoices
 * found", which is a statement about the practice; here it would be false, because it would be a statement about
 * the person looking. So a person without the permission is told, in words, that the screen is withheld from them
 * and that an empty list would not mean there is nothing owed.
 *
 * It asks the same permission the API's billing routes ask (`billing:read`, resolved per person). Until the
 * permission map has loaded NOTHING is known about the person, so the page renders as it always did; a gate that
 * hid the page until then would turn a slow identity call into a screen that never opens (the same choice as
 * PayrollAccessGate).
 */
export default function FeeAccessGate({ children }: { children: ReactNode }) {
  const { can, resolved } = usePermissions();
  if (resolved && !can("billing", "read")) {
    return (
      <div className="mx-auto max-w-2xl p-6" role="status">
        <PageHeader
          title="You do not have access to the practice's fees"
          subtitle="Fee invoices, receipts and engagements are the practice's own economics, so they are shown only to people your Partner has given billing access."
        />
        <p className="mt-4 text-sm text-ps-body">
          Nothing about the practice&apos;s fees is shown to you here, and that is not the same as there being nothing
          owed. Ask your Partner to give you billing access from the Team screen if you need it.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
