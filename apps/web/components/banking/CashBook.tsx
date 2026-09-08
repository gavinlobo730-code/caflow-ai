"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { apiGet, getAuthToken } from "@/lib/invoices/shared";

/**
 * Cash Book — every Cash ledger in date order, and the one rule cash has.
 *
 * A COMPONENT ON THE BANK BOOK ROUTE, NOT ITS OWN PAGE, and that is a routing
 * constraint rather than a design preference. public/_redirects sits at the
 * Cloudflare Pages cap of 100 dynamic rules; every new /clients/[id]/* page
 * costs 2 more, and rules past the cap are SILENTLY IGNORED —
 * scripts/generate-redirects.js's module doc records that this once took out
 * the whole client workspace. The one remaining static-sibling merge
 * (year-end/xbrl into :engagementId) would mean calling "xbrl" an engagement
 * id, so the cheap lever is spent.
 *
 * It also happens to be the better report: "where is my money" is one question,
 * and Tally pairs the Cash Book and Bank Book for exactly that reason.
 *
 * WHAT DID NOT EXIST BEFORE THIS. A repo-wide search for "cash book", "petty
 * cash" and their variants returned four hits and none was a feature: a seeded
 * ledger, a test fixture, a line of prose, and some help text. "1001 Cash in
 * Hand" and "1002 Petty Cash" were in every chart of accounts and no automatic
 * flow had ever posted to either — which is why this had to wait for Phase 1a,
 * where a cash receipt started reaching Cash in Hand at all. Built before that,
 * it would have reported zero for every client.
 *
 * ZERO BUSINESS LOGIC HERE. The lines, the opening and closing balances and the
 * negative-balance findings all come from GET /api/accounting/cash-book, which
 * reuses the same reporting engine the account ledger uses — the running
 * balance is computed in SQL over the account's whole history. This page sorts
 * nothing and sums nothing.
 *
 * THE NEGATIVE BALANCE IS SHOWN FIRST, ABOVE THE LEDGER, because it is the
 * finding rather than a detail of it: a bank account may go overdrawn, physical
 * cash may not, so a negative cash balance is always an error in the books.
 */

interface CashLine {
  entry_date: string;
  narration?: string | null;
  reference_no?: string | null;
  debit_paise: number;
  credit_paise: number;
  balance_paise?: number | null;
}

interface CashAccount {
  account_id: string;
  account_code?: string | null;
  account_name?: string | null;
  opening_balance_paise: number;
  closing_balance_paise: number;
  total_lines?: number | null;
  lines: CashLine[];
}

interface NegativeDay {
  account_id: string;
  account_name: string;
  on_date: string;
  balance_paise: number;
  what_to_check: string;
}

interface CashBook {
  accounts: CashAccount[];
  negative_days: NegativeDay[];
  cash_accounts_checked: number;
  clean: boolean;
}

function rupees(paise: number | null | undefined): string {
  const p = Number(paise ?? 0);
  const sign = p < 0 ? "-" : "";
  const abs = Math.abs(p);
  return `${sign}₹${Math.floor(abs / 100).toLocaleString("en-IN")}.${String(abs % 100).padStart(2, "0")}`;
}

export function CashRegister({ clientId }: { clientId: string }) {
  const [book, setBook] = useState<CashBook | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = await getAuthToken();
      const res = await apiGet(
        `/api/accounting/cash-book?client_id=${encodeURIComponent(clientId)}`,
        token,
      );
      if (!res.success) throw new Error(res.error ?? "Could not load the cash book");
      setBook(res.data as CashBook);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the cash book");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { if (clientId) void load(); }, [clientId, load]);

  return (
    <div className="space-y-5">
      <div className="min-w-0">
        <h3 className="text-xs font-semibold text-[#1E293B]">Cash Book</h3>
        <p className="text-[11px] text-[#94A3B8] mt-0.5">
          Every Cash ledger in date order with a running balance. To record cash,
          use a receipt or a vendor payment with the mode set to Cash — it posts
          to Cash in Hand.
        </p>
      </div>

      {loading && <p className="text-[11px] text-[#94A3B8]">Loading…</p>}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3">
          <p className="text-[11px] text-red-800">{error}</p>
          <button onClick={() => void load()}
                  className="mt-2 text-[11px] text-red-700 underline disabled:opacity-40"
                  disabled={loading}>
            Try again
          </button>
        </div>
      )}

      {book && book.negative_days.length > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 space-y-2">
          <div className="flex items-center gap-1.5">
            <AlertTriangle size={13} className="text-amber-700" />
            <p className="text-[11px] font-semibold text-amber-900">
              Cash goes negative, which cannot happen in fact
            </p>
          </div>
          {book.negative_days.map((n) => (
            <p key={`${n.account_id}-${n.on_date}`} className="text-[11px] text-amber-900">
              {n.what_to_check}
            </p>
          ))}
        </div>
      )}

      {book && book.cash_accounts_checked === 0 && (
        <p className="text-[11px] text-[#94A3B8]">
          This client has no Cash ledger. &quot;Cash in Hand&quot; is seeded with every
          chart of accounts, so this usually means the chart was replaced.
        </p>
      )}

      {book?.accounts.map((a) => (
        <div key={a.account_id} className="rounded-xl border border-[#F1F5F9] bg-white">
          <div className="flex items-baseline justify-between px-4 py-2.5 border-b border-[#F1F5F9]">
            <h3 className="text-xs font-semibold text-[#1E293B]">
              {a.account_code} {a.account_name}
            </h3>
            <p className="text-[11px] text-[#64748B] font-mono">
              Opening {rupees(a.opening_balance_paise)} · Closing{" "}
              <span className={a.closing_balance_paise < 0 ? "text-red-600 font-semibold" : ""}>
                {rupees(a.closing_balance_paise)}
              </span>
            </p>
          </div>
          {a.lines.length === 0 ? (
            <p className="px-4 py-3 text-[11px] text-[#94A3B8]">
              No cash movements in this period.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-[#64748B] border-b border-[#F1F5F9]">
                    <th className="text-left font-medium px-4 py-1.5">Date</th>
                    <th className="text-left font-medium px-4 py-1.5">Particulars</th>
                    <th className="text-right font-medium px-4 py-1.5">Receipts</th>
                    <th className="text-right font-medium px-4 py-1.5">Payments</th>
                    <th className="text-right font-medium px-4 py-1.5">Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {a.lines.map((l, i) => (
                    <tr key={`${a.account_id}-${i}`} className="border-b border-[#F8FAFC]">
                      <td className="px-4 py-1.5 whitespace-nowrap">{l.entry_date}</td>
                      <td className="px-4 py-1.5">{l.narration ?? l.reference_no ?? ""}</td>
                      <td className="px-4 py-1.5 text-right font-mono">
                        {l.debit_paise ? rupees(l.debit_paise) : ""}
                      </td>
                      <td className="px-4 py-1.5 text-right font-mono">
                        {l.credit_paise ? rupees(l.credit_paise) : ""}
                      </td>
                      <td className={`px-4 py-1.5 text-right font-mono ${
                        (l.balance_paise ?? 0) < 0 ? "text-red-600 font-semibold" : ""}`}>
                        {rupees(l.balance_paise)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
