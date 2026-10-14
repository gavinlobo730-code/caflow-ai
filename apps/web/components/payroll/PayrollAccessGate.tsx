"use client";

import type { ReactNode } from "react";
import { PageHeader } from "@/components/ui/page-header";
import { usePermissions } from "@/lib/auth/AuthContext";

/**
 * Says so when the signed-in person may not read payroll, instead of showing them an empty screen.
 *
 * WHY THIS EXISTS (migration 485). The payroll screens read the employee, run, payslip, attendance, leave and
 * declaration tables straight from the browser. Since 485 the database returns those rows only to a person who
 * holds `payroll:read` (Manager and above by default, or a grant from the Partner on the Team screen) and, for
 * everyone else, returns NOTHING without an error. An empty employee list reads as "this client has no
 * employees", which is a statement about the world, and here it would be false: it would be a statement about
 * the person looking. So a person without the permission is told, in words, that the screen is withheld from
 * them and that an empty list would not mean there is nothing.
 *
 * It asks the same permission the API's payroll routes ask (`payroll:read`, resolved per person). Until the
 * permission map has loaded NOTHING is known about the person, so the page renders as it always did; a gate
 * that hid the page until then would turn a slow identity call into a payroll screen that never opens.
 */
export default function PayrollAccessGate({ children }: { children: ReactNode }) {
  const { can, resolved } = usePermissions();
  if (resolved && !can("payroll", "read")) {
    return (
      <div className="mx-auto max-w-2xl p-6" role="status">
        <PageHeader
          title="You do not have access to payroll"
          subtitle="Payroll holds salaries, bank accounts and tax identifiers, so it is shown only to people your Partner has given payroll access."
        />
        <p className="mt-4 text-sm text-ps-body">
          Nothing from payroll is shown to you here, and that is not the same as there being no employees or no
          payroll runs. Ask your Partner to give you payroll access from the Team screen if you need it.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
