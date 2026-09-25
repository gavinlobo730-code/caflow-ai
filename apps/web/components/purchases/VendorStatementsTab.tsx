"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, FileText } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Callout } from "@/components/ui/callout";
import { DrCr } from "@/components/ui/drcr";
import { formatPaise } from "@/lib/services/formatting";
import { getCurrentFinancialYear } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { objectWithLists } from "@/lib/api/shape";

/**
 * The supplier's account, as the client's books have it.
 *
 * ⚠️ `GET /api/vendors/{id}/statement` WAS BUILT, TESTED AND REACHED BY NOBODY.
 * `vendor_statement_service` is a near-twin of `customer_statement_service` —
 * opening payable, the period's bills, payments, debit and credit notes with a
 * running balance, closing payable, FX-aware — and the Sales screen has had a
 * whole **Statements** tab with a generate, a PDF and an email since Phase 4.1
 * while the Purchases screen had nothing at all. The AP mirror of a live AR
 * feature, which is a shape this repository has found before.
 *
 * ── IT IS A RECONCILIATION, NOT A DEMAND, AND THAT DECIDES WHAT IS HERE ─────
 *
 * A CUSTOMER statement is sent to the client's customer asking to be paid, so
 * that tab carries an email path and `customer_statement_service` logs every
 * delivery. A VENDOR statement is what the CA works FROM: the supplier sends
 * theirs, and this is the other side to compare it against. So there is a
 * download and deliberately **no email** — adding one means a deliveries table
 * and a migration, which is a feature rather than the unwiring this fixes.
 *
 * ── THE SIGN IS THE ONE THING THAT IS NOT COSMETIC ─────────────────────────
 *
 * `vendor_statement_service.build_statement` runs the balance CREDIT-positive:
 * a bill increases it, and a positive closing figure is money the CLIENT owes
 * the supplier. `DrCr` is given `isDebit={false}` for exactly that reason —
 * left to infer the side from the sign it would print Dr, stating the debt
 * against the wrong party on a document somebody reconciles from. The PDF
 * carries the same flip through `statement_pdf_service.VENDOR`.
 */
interface StmtTxn {
  date: string;
  type: string;
  reference: string | null;
  particulars: string;
  debit_paise: number;
  credit_paise: number;
  running_balance_paise: number;
}

interface StmtData {
  vendor: { id: string; name: string; email: string | null; gstin: string | null };
  period: { start_date: string; end_date: string };
  opening_balance_paise: number;
  closing_balance_paise: number;
  transactions: StmtTxn[];
  totals: {
    billed_paise: number;
    paid_paise: number;
    debited_paise: number;
    credited_paise: number;
    transaction_count: number;
  };
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** April 1 to March 31 of the given label — the FY is a fact about the date. */
function fyBounds(label: string): { start: string; end: string } {
  const startYear = Number(label.slice(0, 4));
  return { start: `${startYear}-04-01`, end: `${startYear + 1}-03-31` };
}

async function authToken(): Promise<string> {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  return session?.access_token ?? "";
}

/** A payable is credit-positive here, so the side is STATED, never inferred. */
const payable = (paise: number) => <DrCr paise={paise} isDebit={false} />;
const amount = (paise: number) => (paise ? formatPaise(paise) : "—");

export function VendorStatementsTab({ clientId }: { clientId: string }) {
  // The dates are this tab's own filter and the CA edits them freely; the
  // financial year only seeds them, and it seeds from the year we are actually
  // in rather than one carried in from elsewhere on the screen.
  const seed = fyBounds(getCurrentFinancialYear());
  const [vendors, setVendors] = useState<{ id: string; name: string }[]>([]);
  const [vendorId, setVendorId] = useState("");
  const [start, setStart] = useState(seed.start);
  const [end, setEnd] = useState(seed.end);
  const [stmt, setStmt] = useState<StmtData | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One action at a time: a second click generates over an answer the first is
  // still fetching, or downloads the PDF twice.
  const actionInFlight = loading || downloading;

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    let live = true;
    // ⚠️ `selectAll` TAKES A CALLABLE, not a builder, for the same reason
    // `core/db_paging.fetch_all` does: a PostgREST builder is stateful, so
    // reusing one stacks each page's `.range()` on the last. It returns
    // `{data, error}` rather than the rows. Both are exactly the arity trap
    // that shipped a broken reorder report and three dead hub tiles.
    //
    // `.order("id")` after `.order("name")` is the tiebreaker an OFFSET-paged
    // read needs: `name` is not unique, and without it a tie can land either
    // side of a page boundary and come back twice or never.
    selectAll<{ id: string; name: string }>(() =>
      getSupabaseClient().from("vendors").select("id, name")
        .eq("client_id", clientId).order("name").order("id")
    )
      .then(({ data }) => { if (live) setVendors(data ?? []); })
      .catch(() => { if (live) setVendors([]); });
    return () => { live = false; };
  }, [clientId]);

  const generate = useCallback(async () => {
    if (!vendorId || actionInFlight) return;
    setLoading(true);
    setError(null);
    setStmt(null);
    try {
      const token = await authToken();
      const res = await fetch(
        `${API}/api/vendors/${encodeURIComponent(vendorId)}/statement`
        + `?client_id=${encodeURIComponent(clientId)}`
        + `&start_date=${start}&end_date=${end}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      const json = await res.json();
      // The envelope before the payload, and the payload before it is mapped
      // over — this router answers its own failures as HTTP 200.
      if (!json?.success) {
        setError(json?.error || "Could not generate the statement.");
        return;
      }
      setStmt(objectWithLists<StmtData>(json.data, "transactions"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not generate the statement.");
    } finally {
      setLoading(false);
    }
  }, [vendorId, clientId, start, end, actionInFlight]);

  async function download() {
    if (!vendorId || actionInFlight) return;
    setDownloading(true);
    setError(null);
    try {
      const token = await authToken();
      const res = await fetch(
        `${API}/api/vendors/${encodeURIComponent(vendorId)}/statement/pdf`
        + `?client_id=${encodeURIComponent(clientId)}`
        + `&start_date=${start}&end_date=${end}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      );
      if (!res.ok) throw new Error("Could not download the statement.");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `vendor-statement-${start}-${end}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not download the statement.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[14rem] flex-1">
              <label htmlFor="vs-vendor" className="text-xs text-ps-label">Vendor</label>
              <select
                id="vs-vendor"
                value={vendorId}
                onChange={(e) => { setVendorId(e.target.value); setStmt(null); }}
                className="w-full mt-1 px-3 py-2 text-sm bg-white border border-ps-border rounded-md text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand"
              >
                <option value="">{vendors.length ? "Choose a vendor…" : "No vendor recorded yet"}</option>
                {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="vs-start" className="text-xs text-ps-label">From</label>
              <input id="vs-start" type="date" value={start}
                     onChange={(e) => setStart(e.target.value)}
                     className="mt-1 px-3 py-2 text-sm bg-white border border-ps-border rounded-md text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand" />
            </div>
            <div>
              <label htmlFor="vs-end" className="text-xs text-ps-label">To</label>
              <input id="vs-end" type="date" value={end}
                     onChange={(e) => setEnd(e.target.value)}
                     className="mt-1 px-3 py-2 text-sm bg-white border border-ps-border rounded-md text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand" />
            </div>
            <button
              onClick={generate}
              disabled={actionInFlight || !vendorId}
              className="flex items-center gap-1.5 text-sm bg-brand text-white px-3.5 py-2 rounded-md hover:bg-brand-dark disabled:opacity-50"
            >
              <FileText size={13} /> {loading ? "Generating…" : "Generate"}
            </button>
            <button
              onClick={download}
              disabled={actionInFlight || !stmt}
              title={stmt ? "Download as PDF" : "Generate the statement first"}
              className="flex items-center gap-1.5 text-sm text-ps-label border border-ps-border px-3.5 py-2 rounded-md hover:bg-ps-bg disabled:opacity-50"
            >
              <Download size={13} /> {downloading ? "Preparing…" : "PDF"}
            </button>
          </div>
        </CardContent>
      </Card>

      {error && <Callout tone="problem">{error}</Callout>}

      {stmt && (
        <Card>
          <CardContent className="p-0">
            <div className="flex flex-wrap items-baseline justify-between gap-2 px-5 py-3 border-b border-ps-border">
              <div>
                <h3 className="text-sm font-semibold text-ps-ink">{stmt.vendor.name}</h3>
                <p className="text-2xs text-ps-hint">
                  {stmt.period.start_date} to {stmt.period.end_date}
                  {stmt.vendor.gstin ? ` · ${stmt.vendor.gstin}` : ""}
                </p>
              </div>
              <p className="text-2xs text-ps-label">
                Closing payable <span className="font-semibold text-ps-ink">{payable(stmt.closing_balance_paise)}</span>
              </p>
            </div>

            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-3xs uppercase tracking-wide text-ps-hint border-b border-ps-border">
                  <th className="px-5 py-2.5 font-medium">Date</th>
                  <th className="px-3 py-2.5 font-medium">Particulars</th>
                  <th className="px-3 py-2.5 font-medium">Ref</th>
                  <th className="px-3 py-2.5 font-medium text-right">Debit</th>
                  <th className="px-3 py-2.5 font-medium text-right">Credit</th>
                  <th className="px-5 py-2.5 font-medium text-right">Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-border">
                <tr className="bg-ps-bg">
                  <td className="px-5 py-2.5" />
                  <td className="px-3 py-2.5 font-medium text-ps-ink">Opening balance</td>
                  <td className="px-3 py-2.5" />
                  <td className="px-3 py-2.5" />
                  <td className="px-3 py-2.5" />
                  <td className="px-5 py-2.5 text-right">{payable(stmt.opening_balance_paise)}</td>
                </tr>
                {stmt.transactions.map((t, i) => (
                  <tr key={`${t.type}-${t.reference ?? i}-${i}`} className="hover:bg-ps-hover">
                    <td className="px-5 py-2.5 text-ps-label whitespace-nowrap">{t.date}</td>
                    <td className="px-3 py-2.5 text-ps-ink">{t.particulars}</td>
                    <td className="px-3 py-2.5 text-ps-hint">{t.reference ?? "—"}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-ps-body">{amount(t.debit_paise)}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-ps-body">{amount(t.credit_paise)}</td>
                    <td className="px-5 py-2.5 text-right">{payable(t.running_balance_paise)}</td>
                  </tr>
                ))}
                <tr className="bg-ps-bg">
                  <td className="px-5 py-2.5" />
                  <td className="px-3 py-2.5 font-medium text-ps-ink">Closing payable</td>
                  <td className="px-3 py-2.5" />
                  <td className="px-3 py-2.5" />
                  <td className="px-3 py-2.5" />
                  <td className="px-5 py-2.5 text-right font-semibold">{payable(stmt.closing_balance_paise)}</td>
                </tr>
              </tbody>
            </table>

            <div className="px-5 py-3 border-t border-ps-border text-2xs text-ps-label">
              Billed {formatPaise(stmt.totals.billed_paise)}
              {" · "}Paid {formatPaise(stmt.totals.paid_paise)}
              {" · "}Debit notes {formatPaise(stmt.totals.debited_paise)}
              {" · "}Credit notes {formatPaise(stmt.totals.credited_paise)}
            </div>
            <p className="px-5 pb-3 text-3xs text-ps-hint">
              A statement of account, not a tax invoice — derived from posted documents only.
              Compare it against the statement the supplier sends.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
