"use client";

/**
 * The two documents a reverse-charge purchase owes (PUR-19).
 *
 * WHAT WAS MISSING
 *   The reverse-charge accounting is complete — the tax is kept out of what
 *   the vendor is owed, the liability is self-accounted and GSTR-3B declares
 *   it — but the product never produced the two DOCUMENTS the CGST Act makes
 *   the RECIPIENT issue. On an inward supply from an unregistered person the
 *   s.31(3)(f) self-invoice IS the document the input credit rests on (Rule
 *   36(1)(b) with s.16(2)(a)).
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Whether a document is due, what its
 * particulars say, what could not be stated and why — all of it is
 * `domain/gst/rcm_documents.py`'s answer, served by
 * /api/rcm-documents/preview/*. In particular the screen does NOT know that
 * s.31(3)(f) reaches only an unregistered supplier while s.31(3)(g) reaches
 * every payment: that is the distinction the whole feature turns on, and a
 * copy of it here is a second place for it to be wrong.
 */
import { useCallback, useEffect, useState } from "react";
import { X, FileText, AlertTriangle, Check, Info } from "lucide-react";
import { api, type RcmDocumentPreview } from "@/lib/api";

export function RcmDocumentPanel({
  clientId, kind, purchaseBillId, purchasePaymentId, onClose, onIssued,
}: {
  clientId: string;
  kind: "self_invoice" | "payment_voucher";
  purchaseBillId?: string;
  purchasePaymentId?: string;
  onClose: () => void;
  onIssued?: () => void;
}) {
  const [preview, setPreview] = useState<RcmDocumentPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [issuing, setIssuing] = useState(false);
  const [error, setError] = useState("");
  const [number, setNumber] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const res = kind === "self_invoice"
        ? await api.rcmDocuments.previewSelfInvoice({
            client_id: clientId, purchase_bill_id: purchaseBillId ?? "" })
        : await api.rcmDocuments.previewPaymentVoucher({
            client_id: clientId, purchase_payment_id: purchasePaymentId ?? "" });
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't read the document.");
      setPreview(res.data);
      // The suggested number is the server's. It stays editable — Rule 46(b)
      // allows one or multiple series and a client arriving mid-year has one
      // running already — and what is written is what the box says.
      setNumber(res.data.particulars?.document_no ?? "");
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't read the document.");
    } finally {
      setBusy(false);
    }
  }, [clientId, kind, purchaseBillId, purchasePaymentId]);

  useEffect(() => { load(); }, [load]);

  async function issue() {
    if (issuing || !preview?.due) return;
    setIssuing(true); setError("");
    try {
      const res = await api.rcmDocuments.issue({
        client_id: clientId, kind,
        purchase_bill_id: purchaseBillId, purchase_payment_id: purchasePaymentId,
        document_no: number.trim() || undefined,
      });
      if (!res.success) throw new Error(res.error ?? "Couldn't issue the document.");
      await load();
      onIssued?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't issue the document.");
    } finally {
      setIssuing(false);
    }
  }

  const p = preview?.particulars ?? null;
  const issued = preview?.existing ?? null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/20">
      <div className="w-full max-w-2xl h-full bg-white shadow-xl flex flex-col">
        <div className="px-5 py-4 border-b border-[#F1F5F9] flex items-start justify-between">
          <div>
            <p className="text-sm font-semibold text-[#0F172A] flex items-center gap-2">
              <FileText size={15} className="text-blue-600" />
              {kind === "self_invoice" ? "Self-invoice" : "Payment voucher"}
            </p>
            {/* The SECTION comes off the wire, so the screen never asserts
                which provision it is issuing under. */}
            <p className="text-[11px] text-[#94A3B8] mt-0.5">
              {preview?.section} · {preview?.rule}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-1 rounded hover:bg-[#F1F5F9] text-[#64748B]">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-700 flex gap-2">
              <AlertTriangle size={13} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {busy && !preview && <p className="text-xs text-[#94A3B8]">Loading…</p>}

          {issued && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 text-xs text-emerald-800 flex gap-2">
              <Check size={13} className="shrink-0 mt-0.5" />
              <span>
                Issued as <span className="font-mono">{issued.document_no}</span> on{" "}
                {String(issued.document_date).slice(0, 10)}. A second one would be a
                duplicate statutory record, not a correction.
              </span>
            </div>
          )}

          {/* WHY NOT — the Act does not ask for it. A settled answer. */}
          {preview && !preview.due && preview.reasons.length > 0 && (
            <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg px-3 py-2 text-xs text-[#334155] space-y-1">
              {preview.reasons.map((r, i) => <p key={i}>{r}</p>)}
            </div>
          )}

          {/* WHAT IS MISSING — nobody can yet tell. Different from the above,
              and shown differently, because this one is actionable. */}
          {preview && preview.gaps.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-900 space-y-1">
              <p className="font-semibold flex items-center gap-1.5">
                <Info size={12} /> Not decided yet
              </p>
              {preview.gaps.map((g, i) => <p key={i}>{g}</p>)}
            </div>
          )}

          {p && (
            <>
              <div className="grid grid-cols-2 gap-4">
                <label className="text-xs">
                  <span className="block text-[#94A3B8] mb-1">Document number</span>
                  <input value={number} onChange={(e) => setNumber(e.target.value)}
                    disabled={!!issued}
                    className="w-full px-2.5 py-1.5 border border-[#E2E8F0] rounded-lg font-mono text-xs disabled:bg-[#F8FAFC]" />
                </label>
                <div className="text-xs">
                  <span className="block text-[#94A3B8] mb-1">Date</span>
                  <p className="px-2.5 py-1.5">{p.document_date}</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 text-xs">
                <div>
                  <p className="text-[#94A3B8] mb-1">Supplier</p>
                  <p className="font-medium text-[#1E293B]">{p.supplier.name}</p>
                  {p.supplier.address && <p className="text-[#64748B]">{p.supplier.address}</p>}
                  {/* Absent on a self-invoice BY CONSTRUCTION — the document
                      exists because the supplier is not registered. */}
                  {p.supplier.gstin
                    ? <p className="font-mono text-[#64748B]">{p.supplier.gstin}</p>
                    : <p className="text-[#94A3B8] italic">Not registered</p>}
                </div>
                <div>
                  <p className="text-[#94A3B8] mb-1">Recipient (issuing)</p>
                  <p className="font-medium text-[#1E293B]">{p.recipient.name}</p>
                  {p.recipient.address && <p className="text-[#64748B]">{p.recipient.address}</p>}
                  {p.recipient.gstin && <p className="font-mono text-[#64748B]">{p.recipient.gstin}</p>}
                </div>
              </div>

              {p.lines.length > 0 && (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                      <th className="py-1.5 text-left font-semibold">Description</th>
                      <th className="py-1.5 text-left font-semibold">HSN/SAC</th>
                      <th className="py-1.5 text-right font-semibold">Taxable</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {p.lines.map((l, i) => (
                      <tr key={i}>
                        <td className="py-1.5 text-[#1E293B]">{l.description}</td>
                        <td className="py-1.5 font-mono text-[#64748B]">{l.hsn_sac ?? "—"}</td>
                        <td className="py-1.5 text-right tabular-nums">
                          {(l.taxable_paise / 100).toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <div className="bg-[#F8FAFC] rounded-lg px-3 py-2 text-xs space-y-1">
                {p.amount_paid_paise > 0 && (
                  <div className="flex justify-between">
                    <span className="text-[#64748B]">Amount paid (Rule 52(f))</span>
                    <span className="tabular-nums">₹{(p.amount_paid_paise / 100).toFixed(2)}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-[#64748B]">Taxable value</span>
                  <span className="tabular-nums">₹{(p.taxable_paise / 100).toFixed(2)}</span>
                </div>
                {p.taxes.map((t) => (
                  <div key={t.head} className="flex justify-between">
                    <span className="text-[#64748B]">{t.head}</span>
                    <span className="tabular-nums">₹{(t.amount_paise / 100).toFixed(2)}</span>
                  </div>
                ))}
                <div className="flex justify-between font-semibold pt-1 border-t border-[#E2E8F0]">
                  <span>Tax payable on reverse charge</span>
                  <span className="tabular-nums">₹{(p.total_tax_paise / 100).toFixed(2)}</span>
                </div>
                {p.place_of_supply[0] && (
                  <div className="flex justify-between">
                    <span className="text-[#64748B]">Place of supply</span>
                    <span className="font-mono">{p.place_of_supply[0]}</span>
                  </div>
                )}
              </div>

              {/* Every caveat the server attached, verbatim — a document shown
                  without the sentence saying its own bill contradicts itself is
                  exactly the disclosure a reader would rely on. */}
              {p.caveats.length > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-900 space-y-1">
                  {p.caveats.map((c, i) => <p key={i}>{c}</p>)}
                </div>
              )}
              {p.gaps.length > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-900 space-y-1">
                  {p.gaps.map((g, i) => <p key={i}>{g}</p>)}
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-5 py-3 border-t border-[#F1F5F9] flex items-center justify-between">
          <p className="text-[10px] text-[#94A3B8] max-w-sm">
            Check the particulars before issuing. Nothing is sent to any portal.
          </p>
          <div className="flex gap-2">
            <button onClick={onClose}
              className="px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">
              Close
            </button>
            <button onClick={issue}
              disabled={!preview?.due || !!issued || issuing || busy}
              className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
              {issuing ? "Issuing…" : "Issue"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
