import type { ReactNode } from "react";
import FeeAccessGate from "@/components/billing/FeeAccessGate";

// This screen reads, or shows figures from, the practice's own fee tables, which the database shows only to a person
// with billing access (POST-B-024). See FeeAccessGate for why a person without it is told so rather than shown an
// empty list or a zero.
export default function FeeLayout({ children }: { children: ReactNode }) {
  return <FeeAccessGate>{children}</FeeAccessGate>;
}
