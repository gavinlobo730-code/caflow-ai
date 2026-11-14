"use client";

import { Fragment, useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, ClipboardList, RefreshCw } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { practiceSalesHref } from "@/lib/invoices/workspaceNav";
import { readPracticeBooks, type PracticeBooks } from "@/lib/invoices/practiceBooks";
import { formatPaise } from "@/lib/services/formatting";
import { PartnerGuard } from "@/components/practice/PartnerGuard";
import { PageHeader } from "@/components/ui/page-header";
import { formatDate } from "@/lib/dates/format";

type Bucket = { paise: number; count: number };
/** One invoice in a bucket, as the server listed it (POST-A-099): the same reading the bucket's total is made of. */
type ListedInvoice = {
  id: string;
  invoice_no: string | null;
  customer_id: string | null;
  /** null when the name could not be read (`customer_names_read` false) or the customer is not found. */
  customer_name: string | null;
  invoice_date: string | null;
  /** The day the ageing runs from: the due date, or the invoice's date plus its credit days. */
  ageing_from: string | null;
  days_overdue: number;
  outstanding_paise: number;
};
interface Aging {
  buckets: Record<string, Bucket>;
  total_outstanding_paise: number;
  overdue_paise: number;
  overdue_count: number;
  invoices_by_bucket?: Record<string, { invoices: ListedInvoice[]; truncated: boolean }>;
  customer_names_read?: boolean;
}

const ORDER: { key: string; label: string }[] = [
  { key: "not_due", label: "Current / Not due" },
  { key: "0-30", label: "0–30 days" },
  { key: "31-60", label: "31–60 days" },
  { key: "61-90", label: "61–90 days" },
  { key: "90+", label: "90+ days" },
];

function ARDashboard() {
  const [aging, setAging] = useState<Aging | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Where the practice's own invoices are worked (PRE-A-018). Three answers kept
  // apart (see lib/invoices/practiceBooks): the practice client, "there is
  // none", and "could not find out". Starts as the third, so nothing claims the
  // practice is not set up before the server has said so.
  const [books, setBooks] = useState<PracticeBooks>({ state: "unknown" });
  // The bucket whose invoices are shown (POST-A-099). One at a time, so the totals stay readable beside it.
  const [openBucket, setOpenBucket] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    // A separate read, started alongside and tolerated on its own: the ageing
    // is the page, and a failed lookup of where its invoices live must never
    // blank it. It is awaited before the page is shown so that "could not look
    // up" is never displayed for a lookup still in flight.
    const lookup = api.practice.get().catch(() => undefined);
    try {
      const r = await api.billing.arAging() as ApiResp<Aging>;
      setAging(r.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load AR aging");
    } finally {
      setBooks(readPracticeBooks(await lookup));
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading AR aging…</div>;
  if (error) return <div className="p-8 text-sm text-red-600">{error}</div>;

  const buckets = aging?.buckets ?? {};
  const practiceInvoicesHref = books.state === "known" ? practiceSalesHref(books.clientId) : null;
  const practiceReceiptsHref = books.state === "known" ? practiceSalesHref(books.clientId, { tab: "receipts" }) : null;
  return (
    <div className="p-6 max-w-3xl">
      <PageHeader
        icon={<ClipboardList size={18} className="text-brand" />}
        title="AR Aging"
        actions={
          <button onClick={load} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand">
            <RefreshCw size={13} /> Refresh
          </button>
        }
        className="mb-5"
      />
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-2xs uppercase tracking-wide text-gray-500 border-b border-gray-200">
              <th className="px-4 py-2.5 font-medium">Bucket</th>
              <th className="px-4 py-2.5 font-medium text-right">Outstanding</th>
              <th className="px-4 py-2.5 font-medium text-right">Invoices</th>
            </tr>
          </thead>
          <tbody>
            {ORDER.map(({ key, label }) => {
              const count = buckets[key]?.count ?? 0;
              const isOpen = openBucket === key;
              const listed = aging?.invoices_by_bucket?.[key];
              return (
                <Fragment key={key}>
                  <tr className="border-b border-ps-border last:border-0">
                    <td className="px-4 py-2.5 text-brand">
                      {count > 0 && listed ? (
                        <button type="button" onClick={() => setOpenBucket(isOpen ? null : key)}
                          aria-expanded={isOpen} aria-controls={`ar-bucket-${key}`}
                          className="inline-flex items-center gap-1 hover:underline">
                          {isOpen ? <ChevronDown size={13} aria-hidden="true" /> : <ChevronRight size={13} aria-hidden="true" />}
                          {label}
                        </button>
                      ) : label}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{formatPaise(buckets[key]?.paise ?? 0)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-gray-500">{count}</td>
                  </tr>
                  {isOpen && listed && (
                    <tr id={`ar-bucket-${key}`} className="border-b border-ps-border bg-ps-bg">
                      <td colSpan={3} className="px-4 py-3">
                        <BucketInvoices bucketKey={key} invoices={listed.invoices} truncated={listed.truncated} count={count}
                          namesRead={aging?.customer_names_read !== false} books={books} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="bg-ps-bg font-semibold">
              <td className="px-4 py-2.5 text-brand">Total outstanding</td>
              <td className="px-4 py-2.5 text-right tabular-nums">{formatPaise(aging?.total_outstanding_paise ?? 0)}</td>
              <td className="px-4 py-2.5"></td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="text-xs text-gray-500 mt-3">
        Overdue: <span className="font-medium text-red-600">{formatPaise(aging?.overdue_paise ?? 0)}</span>
        {" "}across {aging?.overdue_count ?? 0} invoice(s). Aging is due-date based, computed server-side.
      </p>
      <div className="text-xs text-gray-500 mt-3">
        {practiceInvoicesHref && practiceReceiptsHref ? (
          <p>
            The invoices behind these figures are worked in the practice&apos;s own books:{" "}
            <Link href={practiceInvoicesHref} className="underline hover:text-brand">open the Sales invoices</Link>
            {" "}to issue or chase one, or{" "}
            <Link href={practiceReceiptsHref} className="underline hover:text-brand">record a receipt</Link>.
          </p>
        ) : books.state === "not_provisioned" ? (
          <p>
            The practice has not been set up yet, so its invoices have nowhere to be issued.{" "}
            <Link href="/practice" className="underline hover:text-brand">Set up the practice</Link>.
          </p>
        ) : (
          <p>Could not look up the practice&apos;s books, so the link to its invoices is not shown. Refresh to try again.</p>
        )}
      </div>
    </div>
  );
}

/** The invoices behind one bucket, most overdue first (soonest due first in the not-due bucket, where none is overdue), each opening its own drawer in the practice's books where a receipt is recorded. */
function BucketInvoices({ bucketKey, invoices, truncated, count, namesRead, books }: {
  bucketKey: string; invoices: ListedInvoice[]; truncated: boolean; count: number; namesRead: boolean; books: PracticeBooks;
}) {
  return (
    <div className="space-y-2">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-gray-500">
            <th className="py-1 font-medium">Invoice</th>
            <th className="py-1 font-medium">Customer</th>
            <th className="py-1 font-medium">Ageing from</th>
            <th className="py-1 font-medium text-right">Days overdue</th>
            <th className="py-1 font-medium text-right">Still owed</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((inv) => {
            // Each invoice opens in the practice's own books, where a receipt against it is recorded. Without a known practice there is
            // nowhere to send it, so the number is shown and not linked.
            const invoiceHref = books.state === "known" ? practiceSalesHref(books.clientId, { invoiceId: inv.id }) : null;
            const number = inv.invoice_no || "Unnumbered invoice";
            return (
              <tr key={inv.id} className="border-t border-ps-border">
                <td className="py-1">{invoiceHref ? <Link href={invoiceHref} className="underline hover:text-brand">{number}</Link> : number}</td>
                <td className="py-1">{inv.customer_name ?? (namesRead ? "Customer not found" : "Name not read")}</td>
                <td className="py-1">{formatDate(inv.ageing_from)}</td>
                <td className="py-1 text-right tabular-nums">{inv.days_overdue}</td>
                <td className="py-1 text-right tabular-nums">{formatPaise(inv.outstanding_paise)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {truncated && (
        <p className="text-gray-500">
          Showing the {invoices.length} {bucketKey === "not_due" ? "soonest due" : "most overdue"} of the {count} invoices in this bucket.
        </p>
      )}
      {!namesRead && <p className="text-gray-500">The customers&apos; names could not be read this time. Refresh to try again.</p>}
    </div>
  );
}

export default function ARPage() {
  return <PartnerGuard><ARDashboard /></PartnerGuard>;
}
