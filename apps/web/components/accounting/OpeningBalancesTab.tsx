"use client";

/**
 * Opening balances, bill by bill (ACC-14).
 *
 * WHAT WAS MISSING
 *   `opening_balance_service` brings a client's opening position into the
 *   ledger as three aggregates — Trade Receivables, Trade Payables and each
 *   bank. That is right for the general ledger and useless for ageing, which is
 *   per document: every AR/AP ageing screen and the Schedule III ageing note
 *   (MCA G.S.R. 207(E) of 24-03-2021) bucket by the DUE DATE of each open
 *   document. A control-account total has no dates, so on day one the whole
 *   opening receivable ages to nothing.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). What may be recorded, what the
 * difference between the balance and its documents means, and the sentence that
 * describes it are all `domain/accounting/opening_documents.py`'s answers.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, AlertTriangle, X, Info, Check } from "lucide-react";
import {
  api,
  type DoubleOpening,
  type OpeningDocumentKinds,
  type OpeningDocumentListing,
} from "@/lib/api";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { confirmDialog } from "@/components/ui/confirm-dialog";

type Kind = "receivable" | "payable";
type Msg = { type: "ok" | "err"; text: string } | null;

interface Party { id: string; name: string }

const BLANK = {
  party_id: "",
  document_no: "",
  document_date: "",
  due_date: "",
  amount: "",
};

function rupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function OpeningBalancesTab({ clientId }: { clientId: string }) {
  const [kind, setKind] = useState<Kind>("receivable");
  const [listing, setListing] = useState<OpeningDocumentListing | null>(null);
  const [kinds, setKinds] = useState<OpeningDocumentKinds | null>(null);
  const [parties, setParties] = useState<Party[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  /** Accounts the opening position was posted into TWICE — the masters and the
   *  trial-balance import are separate journal families and neither corrects
   *  the other. Read once for the client, not per side. */
  const [doubles, setDoubles] = useState<DoubleOpening[]>([]);
  const [msg, setMsg] = useState<Msg>(null);

  const busy = saving || busyId !== null;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.openingDocuments.list(clientId, kind);
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't read the opening documents.");
      setListing(res.data);
      setLoadFailed(false);
    } catch {
      // Not swallowed into an empty list: on this tab "none" reads as "nothing
      // to reconcile", which is the one answer that must not be guessed.
      setListing(null);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId, kind]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    let alive = true;
    api.openingDocuments.reconciliation(clientId)
      .then((r) => { if (alive && r.success && r.data) setDoubles(r.data.double_openings ?? []); })
      .catch(() => { if (alive) setDoubles([]); });
    return () => { alive = false; };
  }, [clientId]);

  useEffect(() => {
    let alive = true;
    api.openingDocuments.kinds()
      .then((r) => { if (alive && r.success && r.data) setKinds(r.data); })
      .catch(() => { /* the labels fall back to the two we render */ });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    const fetcher: Promise<{ success: boolean; data?: { id: string; name: string }[] | null }> =
      kind === "receivable"
        ? api.customers.list(clientId)
        : api.vendors.list(clientId) as unknown as Promise<{ success: boolean; data?: { id: string; name: string }[] | null }>;
    fetcher
      .then((r) => {
        if (!alive || !r.success || !r.data) return;
        setParties(r.data.map((p) => ({ id: p.id, name: p.name })));
      })
      .catch(() => { if (alive) setParties([]); });
    return () => { alive = false; };
  }, [clientId, kind]);

  const partyLabel = kind === "receivable" ? "Customer" : "Vendor";
  const numberLabel = useMemo(
    () => kinds?.kinds?.find((k) => k.value === kind)?.number
      ?? (kind === "receivable" ? "Invoice number" : "Bill number"),
    [kinds, kind]);

  async function handleSave() {
    const paise = paiseFromRupeeInput(form.amount);
    if (paise === null || paise <= 0) {
      setMsg({ type: "err", text: "Enter the amount still outstanding at the opening date." });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const res = await api.openingDocuments.create({
        client_id: clientId,
        kind,
        party_id: form.party_id,
        document_no: form.document_no.trim(),
        document_date: form.document_date,
        due_date: form.due_date || null,
        outstanding_paise: paise,
      });
      if (!res.success) throw new Error(res.error ?? "Couldn't record the document.");
      setShowForm(false);
      setForm(BLANK);
      setMsg({ type: "ok", text: "Recorded. It ages from its own date and posts no journal — the opening balance already carries it." });
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't record the document." });
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove(id: string, no: string) {
    const ok = await confirmDialog({
      title: `Remove ${no}?`,
      message: "The opening balance on the party record does not change — this "
             + "removes only the breakup, so the amount stops ageing against "
             + "this document.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    setBusyId(id);
    setMsg(null);
    try {
      const res = await api.openingDocuments.remove(id, clientId, kind);
      if (!res.success) throw new Error(res.error ?? "Couldn't remove the document.");
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't remove the document." });
    } finally {
      setBusyId(null);
    }
  }

  const unreconciled = (listing?.reconciliation ?? []).filter((r) => !r.agrees);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink">Opening balances, bill by bill</h2>
          <p className="text-[11px] text-ps-label mt-1 max-w-2xl">
            The opening balance on each customer and vendor is what the ledger
            carries. Ageing is per document, so record the invoices and bills
            still open at the opening date here — with the numbers and dates the
            other system used. Nothing is posted: this is the breakup of a
            balance the ledger already has.
          </p>
        </div>
        <button onClick={() => { setForm(BLANK); setShowForm(true); }} disabled={busy}
          className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5">
          <Plus size={13} /> Add a document
        </button>
      </div>

      <div className="inline-flex rounded-lg bg-ps-muted p-0.5">
        {(["receivable", "payable"] as Kind[]).map((k) => (
          <button key={k} onClick={() => setKind(k)}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
              kind === k ? "bg-white text-ps-ink shadow-sm" : "text-ps-label hover:text-ps-body"}`}>
            {kinds?.kinds?.find((x) => x.value === k)?.label
              ?? (k === "receivable" ? "Receivable" : "Payable")}
          </button>
        ))}
      </div>

      {msg && (
        <div className={`rounded-lg px-3 py-2 text-xs ${msg.type === "ok"
          ? "bg-emerald-50 border border-emerald-200 text-emerald-800"
          : "bg-red-50 border border-red-200 text-red-700"}`}>
          {msg.text}
        </div>
      )}

      {loadFailed && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-900 flex gap-2">
          <AlertTriangle size={13} className="shrink-0 mt-0.5" />
          <span>The opening documents could not be read, so nothing below is the whole of them. Reload before adding one.</span>
        </div>
      )}

      {listing && (
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            ["Opening balance on the party records", listing.opening_balance_paise],
            ["Documents recorded here", listing.documents_paise],
            ["Not broken up", listing.opening_balance_paise - listing.documents_paise],
          ].map(([label, value]) => (
            <div key={label as string} className="border border-ps-border rounded-lg px-3 py-2">
              <p className="text-[10px] text-ps-hint leading-tight">{label}</p>
              <p className="text-sm font-semibold text-ps-ink tabular-nums mt-0.5">
                {rupees(value as number)}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* OPENED TWICE. The trial-balance import and the party masters post into
          separate journal families that never reconcile against each other, so
          a bank balance entered on the master AND carried on an imported trial
          balance is posted twice and the balance sheet is out by exactly it.
          Which of the two is the mistake is the CA's answer, so the panel shows
          both figures and offers no difference. */}
      {doubles.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-800 space-y-1">
          <p className="font-semibold flex items-center gap-1.5">
            <AlertTriangle size={12} /> {doubles.length}{" "}
            {doubles.length === 1 ? "account was" : "accounts were"} opened twice
          </p>
          {doubles.map((d) => <p key={d.account_id}>{d.sentence}</p>)}
          <p className="text-[10px] text-red-700/80 pt-0.5">
            Reverse whichever opening you did not mean. Nothing here is undone
            automatically — both postings are real journal entries.
          </p>
        </div>
      )}

      {/* THE DIFFERENCE, PARTY BY PARTY. The server's own sentence, verbatim:
          an ageing schedule that does not foot to its own control account is
          exactly the disclosure a reader would rely on. */}
      {unreconciled.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-900 space-y-1">
          <p className="font-semibold flex items-center gap-1.5">
            <Info size={12} /> {unreconciled.length} {unreconciled.length === 1 ? "party does" : "parties do"} not add up
          </p>
          {unreconciled.map((r) => <p key={r.party_id}>{r.sentence}</p>)}
        </div>
      )}
      {listing && unreconciled.length > 0 === false && listing.documents.length > 0 && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 text-xs text-emerald-800 flex gap-2">
          <Check size={13} className="shrink-0 mt-0.5" />
          <span>Every party&apos;s documents add up to its opening balance, so the ageing schedule foots to the control account.</span>
        </div>
      )}

      {loading ? (
        <p className="text-xs text-ps-hint">Loading…</p>
      ) : !listing || listing.documents.length === 0 ? (
        <p className="text-xs text-ps-hint">
          No opening documents recorded. Until they are, the opening balance
          appears in the ledger and in no ageing bucket.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-ps-muted text-ps-hint text-left">
                <th className="py-2 font-semibold">{numberLabel}</th>
                <th className="py-2 font-semibold">{partyLabel}</th>
                <th className="py-2 font-semibold">Date</th>
                <th className="py-2 font-semibold">Due</th>
                <th className="py-2 font-semibold text-right">Outstanding</th>
                <th className="py-2 font-semibold" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ps-bg">
              {listing.documents.map((d) => (
                <tr key={d.id}>
                  <td className="py-2 font-mono text-ps-ink">{d.document_no}</td>
                  <td className="py-2 text-ps-body">{d.party_name ?? "—"}</td>
                  <td className="py-2 text-ps-label">{d.document_date ?? "—"}</td>
                  <td className="py-2 text-ps-label">{d.due_date ?? "—"}</td>
                  <td className="py-2 text-right tabular-nums">{rupees(d.outstanding_paise)}</td>
                  <td className="py-2 text-right">
                    <button onClick={() => handleRemove(d.id, d.document_no)} disabled={busy}
                      className="px-2 py-1 text-[11px] text-ps-hint hover:text-red-600 disabled:opacity-40">
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {kinds?.section_194_aggregate && kind === "payable" && (
        <p className="text-[10px] text-ps-hint leading-tight max-w-2xl">
          {kinds.section_194_aggregate}
        </p>
      )}

      {showForm && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/20">
          <div className="w-full max-w-md h-full bg-white shadow-xl flex flex-col">
            <div className="px-5 py-4 border-b border-ps-muted flex items-center justify-between">
              <p className="text-sm font-semibold text-ps-ink">
                Add an opening {kind === "receivable" ? "invoice" : "bill"}
              </p>
              <button onClick={() => setShowForm(false)} aria-label="Close"
                className="p-1 rounded hover:bg-ps-muted text-ps-label"><X size={16} /></button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              <label className="text-xs block">
                <span className="block text-ps-body font-medium mb-1">{partyLabel} *</span>
                <select value={form.party_id}
                  onChange={(e) => setForm((f) => ({ ...f, party_id: e.target.value }))}
                  className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg">
                  <option value="">Select…</option>
                  {parties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>

              <label className="text-xs block">
                <span className="block text-ps-body font-medium mb-1">{numberLabel} *</span>
                <input value={form.document_no}
                  onChange={(e) => setForm((f) => ({ ...f, document_no: e.target.value }))}
                  className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg font-mono" />
                <span className="block text-[10px] text-ps-hint mt-1 leading-tight">
                  The number the other system issued. It is not part of this
                  client&apos;s own series and no gap is reported against it.
                </span>
              </label>

              <div className="grid grid-cols-2 gap-3">
                <label className="text-xs block">
                  <span className="block text-ps-body font-medium mb-1">Document date *</span>
                  <input type="date" value={form.document_date}
                    onChange={(e) => setForm((f) => ({ ...f, document_date: e.target.value }))}
                    className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg" />
                </label>
                <label className="text-xs block">
                  <span className="block text-ps-body font-medium mb-1">Due date</span>
                  <input type="date" value={form.due_date}
                    onChange={(e) => setForm((f) => ({ ...f, due_date: e.target.value }))}
                    className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg" />
                </label>
              </div>

              <label className="text-xs block">
                <span className="block text-ps-body font-medium mb-1">Still outstanding *</span>
                <input value={form.amount} inputMode="decimal"
                  onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
                  placeholder="0.00"
                  className="w-full px-2.5 py-1.5 border border-ps-border rounded-lg text-right tabular-nums" />
                <span className="block text-[10px] text-ps-hint mt-1 leading-tight">
                  What is still open at the opening date, not the document&apos;s
                  original value. A document already settled by then is not part
                  of the opening balance.
                </span>
              </label>
            </div>

            <div className="px-5 py-3 border-t border-ps-muted flex items-center justify-between">
              <p className="text-[10px] text-ps-hint max-w-[14rem] leading-tight">
                No journal is posted. The tax on this document was declared where
                it was issued.
              </p>
              <div className="flex gap-2">
                <button onClick={() => setShowForm(false)}
                  className="px-3 py-1.5 text-xs border border-ps-border rounded-lg hover:bg-ps-bg">
                  Cancel
                </button>
                <button onClick={handleSave} disabled={saving}
                  className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                  {saving ? "Saving…" : "Record"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
