import { ModuleWorklist } from "@/components/hub/ModuleWorklist";

/** The Sales tile's firm-level destination: which clients' CUSTOMERS still
 *  owe them money, and how much (accounting-hub-2-05, migration 432).
 *
 *  ⚠️ THIS PATH WAS A `MovedToClientWorkspace` TOMBSTONE, the Sales half of
 *  the pair `/accounting/fixed-assets` was the other half of, and the tile did
 *  not link here — it linked to `/accounting/receivables`, which reads the
 *  PRACTICE's own `fee_invoices`. So a client whose customers owed it ₹19.9
 *  crore showed ₹0 on the screen the tile's number opened. The figure here is
 *  the tile's own, over `client_sales_invoices`, and every row opens that
 *  client's Sales section, where the invoices themselves still live. */
export default function Page() {
  return <ModuleWorklist tile="sales" heading="Sales" />;
}
