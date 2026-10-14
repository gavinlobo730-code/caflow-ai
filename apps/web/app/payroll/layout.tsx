import type { ReactNode } from "react";
import PayrollAccessGate from "@/components/payroll/PayrollAccessGate";

// Every payroll screen reads payroll tables, which the database shows only to a person with payroll access
// (migration 485). See PayrollAccessGate for why a person without it is told so rather than shown an empty list.
export default function PayrollLayout({ children }: { children: ReactNode }) {
  return <PayrollAccessGate>{children}</PayrollAccessGate>;
}
