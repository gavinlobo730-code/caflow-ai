import type { ReactNode } from "react";
import PayrollAccessGate from "@/components/payroll/PayrollAccessGate";

// The client's payroll tab reads the same tables as /payroll and is withheld in the same words from a person
// without payroll access. See PayrollAccessGate.
export default function ClientPayrollLayout({ children }: { children: ReactNode }) {
  return <PayrollAccessGate>{children}</PayrollAccessGate>;
}
