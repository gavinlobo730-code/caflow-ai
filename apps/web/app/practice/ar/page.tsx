"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ClipboardList, RefreshCw } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { practiceSalesHref } from "@/lib/invoices/workspaceNav";
import { readPracticeBooks, type PracticeBooks } from "@/lib/invoices/practiceBooks";
import { formatPaise } from "@/lib/services/formatting";
import { PartnerGuard } from "@/components/practice/PartnerGuard";
import { PageHeader } from "@/components/ui/page-header";

type Bucket = { paise: number; count: number };
interface Aging {
  buckets: Record<string, Bucket>;
  total_outstanding_paise: number;
  overdue_paise: number;
  overdue_count: number;
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
            {ORDER.map(({ key, label }) => (
              <tr key={key} className="border-b border-ps-border last:border-0">
                <td className="px-4 py-2.5 text-brand">{label}</td>
                <td className="px-4 py-2.5 text-right tabular-nums">{formatPaise(buckets[key]?.paise ?? 0)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-gray-500">{buckets[key]?.count ?? 0}</td>
              </tr>
            ))}
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

export default function ARPage() {
  return <PartnerGuard><ARDashboard /></PartnerGuard>;
}
