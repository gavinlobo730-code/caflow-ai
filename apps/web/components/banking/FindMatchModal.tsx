"use client";
// "Find the invoice/bill" — the searchable candidate picker (B.1.6)
//
// Moved verbatim out of app/clients/[id]/bank/page.tsx on 2026-09-03, when
// the bank module was rebuilt around ENTRIES (docs/architecture/09-bank-entries.md).
// The 4,964-line page was the reason small changes went unreviewed; each tab
// is its own file now. Behaviour here is unchanged by the move.

import { useEffect, useState, useCallback } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import { fmt, rsToP, QueueTxn } from "@/components/banking/shared";

// ── "Find other matches" (B.1.6) ───────────────────────────────────────────
// "Suggest matches" ranks the best five WITHIN an amount band, which is right
// most of the time and useless the rest: a part-payment, an unusual shortfall,
// or a document from four months back is simply not in the band, and until now
// a CA who KNEW the invoice number had no way to type it in.
//
// Every filter here is a query parameter. The browser does no filtering,
// ranking or matching of its own — it renders what the API returned and sends
// the chosen row to the existing /match endpoint.

export interface CandidateResult {
  matched_entity_type: string; matched_entity_id: string; label: string;
  amount_paise: number; entity_date: string | null;
  party_name: string | null; party_id: string | null;
  outstanding_paise: number | null;
  // candidate − bank. Positive = the bank line is SHORT of the document (the
  // TDS shape); negative = the bank line is LARGER, which the band used to hide.
  difference_paise: number;
  tds_rate_bps: number | null;
  is_exact: boolean;
  summary: string;
}
interface CandidateSearchPayload {
  transaction_id: string; amount_paise: number; direction: "credit" | "debit";
  allowed_types: string[]; results: CandidateResult[];
  total: number; limit: number; offset: number; truncated: boolean;
}

const CANDIDATE_TYPE_LABELS: Record<string, string> = {
  sales_invoice: "Sales invoices", purchase_bill: "Purchase bills",
  receipt: "Receipts", purchase_payment: "Payments", journal_entry: "Journal entries",
};

interface CandidateFilters {
  q: string; dateFrom: string; dateTo: string;
  minRs: string; maxRs: string; entityType: string;
}
const NO_CANDIDATE_FILTERS: CandidateFilters = {
  q: "", dateFrom: "", dateTo: "", minRs: "", maxRs: "", entityType: "",
};
const PER_PAGE = 25;

export function FindMatchModal({ txn, onClose, onPicked, onSettle }: {
  txn: QueueTxn;
  onClose: () => void;
  onPicked: (r: CandidateResult) => Promise<void>;
  onSettle: (r: CandidateResult) => void;
}) {
  const isCredit = txn.credit_paise > 0;
  const txnAmount = isCredit ? txn.credit_paise : txn.debit_paise;

  const [q, setQ] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [minRs, setMinRs] = useState("");
  const [maxRs, setMaxRs] = useState("");
  const [entityType, setEntityType] = useState("");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<CandidateSearchPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState<string | null>(null);

  // The filters are passed to run() rather than closed over, so run() changes
  // identity only when the transaction does — which is what lets the first-open
  // effect below fire once instead of on every keystroke.
  const run = useCallback(async (offset: number, f: CandidateFilters) => {
    setLoading(true); setError(null);
    const params: Record<string, string> = { limit: String(PER_PAGE), offset: String(offset) };
    if (f.q.trim()) params.q = f.q.trim();
    if (f.dateFrom) params.date_from = f.dateFrom;
    if (f.dateTo) params.date_to = f.dateTo;
    if (f.minRs !== "") params.min_amount_paise = String(rsToP(parseFloat(f.minRs) || 0));
    if (f.maxRs !== "") params.max_amount_paise = String(rsToP(parseFloat(f.maxRs) || 0));
    if (f.entityType) params.entity_type = f.entityType;
    try {
      const res = (await api.banking.candidateSearch(txn.id, params)) as
        { success: boolean; data: CandidateSearchPayload; error?: string | null };
      if (!res.success) throw new Error(res.error ?? "Couldn't search for matches.");
      setData(res.data);
    } catch (e) {
      setData(null);
      setError(e instanceof Error ? e.message : "Couldn't search for matches.");
    } finally {
      setLoading(false);
    }
  }, [txn.id]);

  // First open shows everything in reach, so the modal is useful before a single
  // character is typed. Re-running is explicit after that — a query per keystroke
  // over a client's whole document history is a lot of load for little gain.
  useEffect(() => { setPage(0); run(0, NO_CANDIDATE_FILTERS); }, [run]);

  const filters: CandidateFilters = { q, dateFrom, dateTo, minRs, maxRs, entityType };

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setPage(0);
    run(0, filters);
  }
  function goTo(next: number) {
    setPage(next);
    run(next * PER_PAGE, filters);
  }

  async function pick(r: CandidateResult) {
    setPicking(r.matched_entity_id);
    try { await onPicked(r); }
    finally { setPicking(null); }
  }

  const shown = data?.results ?? [];
  const total = data?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / PER_PAGE) - 1);

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[#0F172A]">Find other matches</h3>
            <p className="text-xs text-[#64748B] mt-0.5 truncate">
              {txn.description} · {txn.transaction_date} · {fmt(txnAmount)} {isCredit ? "credit" : "debit"}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>

        <form onSubmit={submit} className="px-5 py-3 border-b border-[#F1F5F9] space-y-2">
          <div className="flex gap-2">
            <input
              value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Invoice number, party name…"
              aria-label="Search documents"
              className="flex-1 px-2 py-1.5 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500" />
            <button type="submit" disabled={loading}
              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
              {loading ? "Searching…" : "Search"}
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <select value={entityType} onChange={(e) => setEntityType(e.target.value)}
              aria-label="Document type"
              className="px-2 py-1 text-[11px] border border-[#E2E8F0] rounded text-[#475569]">
              {/* Only what money moving THIS way can settle. The backend applies
                  the same rule and refuses anything else outright, so this list
                  narrows the request rather than deciding it. */}
              <option value="">All types</option>
              {(data?.allowed_types ?? []).map((t) => (
                <option key={t} value={t}>{CANDIDATE_TYPE_LABELS[t] ?? t}</option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-[10px] text-[#94A3B8]">
              From
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                aria-label="Dated from"
                className="px-1.5 py-1 text-[11px] border border-[#E2E8F0] rounded text-[#475569]" />
            </label>
            <label className="flex items-center gap-1 text-[10px] text-[#94A3B8]">
              To
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                aria-label="Dated to"
                className="px-1.5 py-1 text-[11px] border border-[#E2E8F0] rounded text-[#475569]" />
            </label>
            <label className="flex items-center gap-1 text-[10px] text-[#94A3B8]">
              ₹ min
              <input type="number" step="0.01" min="0" value={minRs} onChange={(e) => setMinRs(e.target.value)}
                aria-label="Minimum amount in rupees"
                className="w-24 px-1.5 py-1 text-[11px] border border-[#E2E8F0] rounded text-[#475569]" />
            </label>
            <label className="flex items-center gap-1 text-[10px] text-[#94A3B8]">
              ₹ max
              <input type="number" step="0.01" min="0" value={maxRs} onChange={(e) => setMaxRs(e.target.value)}
                aria-label="Maximum amount in rupees"
                className="w-24 px-1.5 py-1 text-[11px] border border-[#E2E8F0] rounded text-[#475569]" />
            </label>
          </div>
        </form>

        <div className="px-5 py-3 overflow-y-auto flex-1 space-y-1.5">
          {error && <p className="text-xs text-red-600">{error}</p>}
          {!error && !loading && shown.length === 0 && (
            <p className="text-xs text-[#94A3B8]">
              Nothing here matches. Widen the dates or clear a filter — this search already
              looks past the amount, so a document of any size is reachable.
            </p>
          )}
          {data?.truncated && (
            <p className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
              There were more documents than this search reads at once. Narrow the dates or
              the amount to be sure you are seeing everything.
            </p>
          )}
          {shown.map((r) => (
            <div key={`${r.matched_entity_type}:${r.matched_entity_id}`}
              className="flex items-center justify-between gap-3 border border-[#F1F5F9] rounded px-2.5 py-1.5">
              <div className="min-w-0">
                <p className="text-[11px] text-[#334155] truncate">{r.label}</p>
                <p className="text-[10px] text-[#94A3B8]">
                  {r.entity_date ?? "—"} · {fmt(r.amount_paise)}
                  {r.outstanding_paise !== null && r.outstanding_paise !== r.amount_paise
                    ? ` · ${fmt(r.outstanding_paise)} open` : ""}
                  {" · "}{r.summary}
                </p>
              </div>
              <div className="shrink-0">
                {/* Same rule as the suggestion list: a SHORT match settles only
                    what arrived and leaves the document partly open, which is
                    wrong when the shortfall is withheld TDS. Route it to the
                    settlement modal rather than let one click under-settle. */}
                {r.difference_paise > 0 ? (
                  <button onClick={() => onSettle(r)}
                    className="text-[10px] px-2 py-0.5 bg-amber-600 text-white rounded hover:bg-amber-700"
                    title={`Bank line is ${fmt(r.difference_paise)} short of this document`}>
                    {r.tds_rate_bps ? "Settle with TDS" : "Settle difference"}
                  </button>
                ) : (
                  <button onClick={() => pick(r)} disabled={picking !== null}
                    className="text-[10px] px-2 py-0.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                    {picking === r.matched_entity_id ? "Matching…" : "Match"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between px-5 py-3 border-t border-[#F1F5F9]">
          <p className="text-[10px] text-[#94A3B8]">
            {total === 0 ? "No documents" :
              `${page * PER_PAGE + 1}–${Math.min((page + 1) * PER_PAGE, total)} of ${total}`}
          </p>
          <div className="flex gap-2">
            <button onClick={() => goTo(page - 1)} disabled={page === 0 || loading}
              className="text-[11px] px-2 py-1 border border-[#E2E8F0] rounded text-[#475569] disabled:opacity-40">
              Previous
            </button>
            <button onClick={() => goTo(page + 1)} disabled={page >= lastPage || loading}
              className="text-[11px] px-2 py-1 border border-[#E2E8F0] rounded text-[#475569] disabled:opacity-40">
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// Label only — the split itself is computed server-side (CLAUDE.md: no business
// logic in the frontend). 0% is a real, deliberate answer; the absence of a
// rate is a different one, and posts the gross as one line.
//
// Deliberately neutral about direction and about banking: the same list now
// offers input credit on a payment (CGST Act s.16) and output tax on a receipt
// (s.9), so a label that said "standard for banking services" would be wrong
// half the time. Short, because this is a column now, not a drawer.
