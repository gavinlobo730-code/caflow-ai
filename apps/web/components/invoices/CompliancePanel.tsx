"use client";

/**
 * CompliancePanel — the Invoice Hub's GST compliance section (Batch 7). Surfaces
 * the derived GST treatment + place-of-supply validation and drives the IRN and
 * E-Way Bill workflows on top of the EXISTING einvoice / eway-bill record
 * endpoints. Nothing here auto-submits to a government portal: the CA prepares a
 * record, generates the IRN/EWB on the IRP/NIC portal, then records the result —
 * every mutation is an explicit, confirmed action. Accounting/posting untouched.
 */
import { useMemo, useState } from "react";
import {
  ShieldCheck, FileCheck2, Truck, AlertTriangle, Loader2, QrCode, XCircle,
} from "lucide-react";
import { apiCall, fmt, type InvoiceDetail } from "@/lib/invoices/shared";
import {
  gstTreatment, treatmentLabel, validatePlaceOfSupply,
  irnEligibility, ewayEligibility, irnStatus, ewayStatus,
  type ComplianceInvoice, type EInvoiceRecord, type EWayRecord, type GstTreatment,
} from "@/lib/invoices/compliance";

const TREATMENTS: GstTreatment[] = [
  "regular", "export_with_payment", "export_without_payment",
  "sez_with_payment", "sez_without_payment", "deemed_export",
];
const WITHOUT_PAYMENT = new Set<GstTreatment>(["export_without_payment", "sez_without_payment"]);

export function CompliancePanel({
  invoice, clientId, einvoiceRecords, ewayRecords, onChanged, onToast,
}: {
  invoice: InvoiceDetail;
  clientId: string;
  einvoiceRecords: EInvoiceRecord[];
  ewayRecords: EWayRecord[];
  onChanged: () => void;
  onToast: (msg: string, type: "success" | "error") => void;
}) {
  const [modal, setModal] = useState<null | "prepIrn" | "recordIrn" | "prepEway" | "recordEway" | "cancelIrn" | "cancelEway">(null);
  const [busy, setBusy] = useState(false);

  const irn = irnStatus(invoice.id, einvoiceRecords);
  const eway = ewayStatus(invoice.id, ewayRecords);

  const compInv: ComplianceInvoice = useMemo(() => ({
    status: invoice.status,
    is_interstate: invoice.is_interstate,
    supply_state_code: invoice.supply_state_code,
    recipient_gstin: invoice.customers?.gstin ?? null,
    is_reverse_charge: null,
    gst_treatment: irn.record?.gst_treatment ?? null,
    taxable_amount_paise: invoice.taxable_amount_paise,
    line_hsn_codes: invoice.lines.map((l) => l.hsn_sac),
  }), [invoice, irn.record]);

  const treatment = gstTreatment(compInv);
  const posIssues = validatePlaceOfSupply(compInv);
  const irnElig = irnEligibility(compInv, irn.state === "generated");
  const ewayElig = ewayEligibility(compInv, eway.state === "generated");

  async function run(fn: () => Promise<void>, okMsg: string) {
    setBusy(true);
    try { await fn(); onToast(okMsg, "success"); setModal(null); onChanged(); }
    catch (e) { onToast(e instanceof Error ? e.message : "Action failed", "error"); }
    finally { setBusy(false); }
  }

  async function prepareIrn(t: GstTreatment, lut: string) {
    await run(async () => {
      const r = await apiCall("/api/einvoice/records", "POST", {
        client_id: clientId, invoice_number: invoice.invoice_no, invoice_date: invoice.invoice_date,
        sales_invoice_id: invoice.id, gst_treatment: t, lut_number: lut.trim() || undefined,
      });
      if (!r.success) throw new Error(r.error ?? "Could not prepare the IRN record");
    }, "IRN record prepared — generate it on the IRP portal, then record it");
  }
  async function recordIrn(f: { irn: string; ack_number: string; ack_date: string; qr_data: string }) {
    const id = irn.record?.id;
    if (!id) return;
    await run(async () => {
      const r = await apiCall(`/api/einvoice/records/${id}/irn-generated`, "POST", {
        irn: f.irn.trim(), ack_number: f.ack_number.trim(), ack_date: f.ack_date, qr_data: f.qr_data.trim() || undefined,
      });
      if (!r.success) throw new Error(r.error ?? "Could not record the IRN");
    }, `IRN ${f.irn.trim()} recorded`);
  }
  async function cancelIrn(reason: string) {
    const id = irn.record?.id;
    if (!id) return;
    await run(async () => {
      const r = await apiCall(`/api/einvoice/records/${id}/cancel`, "POST", { cancellation_reason: reason });
      if (!r.success) throw new Error(r.error ?? "Could not cancel the IRN");
    }, "IRN cancellation recorded");
  }

  async function prepareEway(f: { dispatch_from: string; ship_to: string; goods_description: string; hsn_code: string }) {
    await run(async () => {
      const r = await apiCall("/api/eway-bill/records", "POST", {
        client_id: clientId, invoice_number: invoice.invoice_no, sales_invoice_id: invoice.id,
        dispatch_from: f.dispatch_from.trim(), ship_to: f.ship_to.trim(),
        goods_description: f.goods_description.trim() || "Goods per invoice",
        taxable_value_paise: invoice.taxable_amount_paise, hsn_code: f.hsn_code.trim() || undefined,
      });
      if (!r.success) throw new Error(r.error ?? "Could not prepare the E-Way Bill record");
    }, "E-Way Bill record prepared — generate it on the NIC portal, then record it");
  }
  async function recordEway(f: { ewb_number: string; ewb_date: string; ewb_valid_upto: string }) {
    const id = eway.record?.id;
    if (!id) return;
    await run(async () => {
      const r = await apiCall(`/api/eway-bill/records/${id}/generated`, "POST", {
        ewb_number: f.ewb_number.trim(), ewb_date: f.ewb_date, ewb_valid_upto: f.ewb_valid_upto,
      });
      if (!r.success) throw new Error(r.error ?? "Could not record the E-Way Bill");
    }, `E-Way Bill ${f.ewb_number.trim()} recorded`);
  }
  async function cancelEway(reason: string) {
    const id = eway.record?.id;
    if (!id) return;
    await run(async () => {
      const r = await apiCall(`/api/eway-bill/records/${id}/cancel`, "POST", { cancellation_reason: reason });
      if (!r.success) throw new Error(r.error ?? "Could not cancel the E-Way Bill");
    }, "E-Way Bill cancellation recorded");
  }

  const recipientGstin = invoice.customers?.gstin ?? null;

  return (
    <section className="space-y-3">
      <h4 className="text-xs font-semibold text-[#334155] flex items-center gap-1.5"><ShieldCheck size={13} /> Compliance</h4>

      {/* GST treatment + place of supply */}
      <div className="rounded-lg border border-[#F1F5F9] p-3 space-y-2">
        <Row label="GST treatment" value={treatment.label} />
        <Row label="Recipient GSTIN" value={recipientGstin || "Unregistered (B2C)"} mono={!!recipientGstin} />
        <Row label="Place of supply" value={invoice.supply_state_code || "—"} />
        {posIssues.map((i, k) => (
          <p key={k} className={`text-[11px] flex items-start gap-1 ${i.severity === "error" ? "text-red-600" : "text-amber-600"}`}>
            <AlertTriangle size={11} className="mt-0.5 flex-shrink-0" /> {i.message}
          </p>
        ))}
      </div>

      {/* IRN */}
      <ComplianceCard
        icon={<FileCheck2 size={13} />}
        title="e-Invoice (IRN)"
        state={irn.state}
      >
        {irn.state === "generated" ? (
          <div className="space-y-2">
            <Row label="IRN" value={irn.irn ?? "—"} mono />
            {irn.record?.ack_number && <Row label="Ack no." value={irn.record.ack_number} mono />}
            {irn.qrData && (
              <div className="rounded bg-[#F8FAFC] border border-[#EEF2F7] p-2">
                <p className="text-[10px] text-[#94A3B8] flex items-center gap-1 mb-1"><QrCode size={11} /> Signed QR payload</p>
                <p className="text-[10px] font-mono text-[#475569] break-all max-h-16 overflow-y-auto">{irn.qrData}</p>
              </div>
            )}
            <button onClick={() => setModal("cancelIrn")} className="text-[11px] text-red-600 hover:underline inline-flex items-center gap-1"><XCircle size={11} /> Cancel IRN</button>
          </div>
        ) : irn.state === "cancelled" ? (
          <p className="text-[11px] text-[#94A3B8]">IRN cancelled{irn.record?.cancellation_reason ? ` — ${irn.record.cancellation_reason}` : ""}.</p>
        ) : irn.state === "draft" ? (
          <div className="space-y-2">
            <p className="text-[11px] text-[#64748B]">Record prepared ({irn.record?.gst_treatment ? treatmentLabel(irn.record.gst_treatment) : "regular"}). Generate the IRN on the IRP portal, then record it.</p>
            <PrimaryBtn onClick={() => setModal("recordIrn")}>Record IRN</PrimaryBtn>
          </div>
        ) : (
          <EligibilityBlock elig={irnElig} actionLabel="Prepare IRN" onAction={() => setModal("prepIrn")} />
        )}
      </ComplianceCard>

      {/* E-Way Bill */}
      <ComplianceCard
        icon={<Truck size={13} />}
        title="E-Way Bill"
        state={eway.state}
      >
        {eway.state === "generated" ? (
          <div className="space-y-2">
            <Row label="EWB no." value={eway.ewbNumber ?? "—"} mono />
            {eway.validUpto && <Row label="Valid upto" value={eway.validUpto} />}
            <button onClick={() => setModal("cancelEway")} className="text-[11px] text-red-600 hover:underline inline-flex items-center gap-1"><XCircle size={11} /> Cancel E-Way Bill</button>
          </div>
        ) : eway.state === "cancelled" ? (
          <p className="text-[11px] text-[#94A3B8]">E-Way Bill cancelled{eway.record?.cancellation_reason ? ` — ${eway.record.cancellation_reason}` : ""}.</p>
        ) : eway.state === "draft" ? (
          <div className="space-y-2">
            <p className="text-[11px] text-[#64748B]">Record prepared. Generate the E-Way Bill on the NIC portal, then record it.</p>
            <PrimaryBtn onClick={() => setModal("recordEway")}>Record E-Way Bill</PrimaryBtn>
          </div>
        ) : (
          <EligibilityBlock elig={ewayElig} actionLabel="Prepare E-Way Bill" onAction={() => setModal("prepEway")} />
        )}
      </ComplianceCard>

      {modal === "prepIrn" && <PrepareIrnModal busy={busy} onClose={() => setModal(null)} onSubmit={prepareIrn} />}
      {modal === "recordIrn" && <RecordIrnModal busy={busy} onClose={() => setModal(null)} onSubmit={recordIrn} />}
      {modal === "cancelIrn" && <CancelModal title="Cancel IRN" busy={busy} onClose={() => setModal(null)} onSubmit={cancelIrn} note="Cancel the IRN on the IRP portal first, then record it here." />}
      {modal === "prepEway" && <PrepareEwayModal busy={busy} invoice={invoice} onClose={() => setModal(null)} onSubmit={prepareEway} />}
      {modal === "recordEway" && <RecordEwayModal busy={busy} onClose={() => setModal(null)} onSubmit={recordEway} />}
      {modal === "cancelEway" && <CancelModal title="Cancel E-Way Bill" busy={busy} onClose={() => setModal(null)} onSubmit={cancelEway} note="Cancel the E-Way Bill on the NIC portal first, then record it here." />}
    </section>
  );
}

// ── Presentational bits ───────────────────────────────────────────────────────
function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-[11px] text-[#94A3B8] flex-shrink-0">{label}</span>
      <span className={`text-[11px] text-[#334155] text-right break-all ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

const STATE_BADGE: Record<string, string> = {
  none: "bg-[#F1F5F9] text-[#64748B]",
  draft: "bg-amber-100 text-amber-700",
  generated: "bg-green-100 text-green-700",
  cancelled: "bg-red-100 text-red-600",
};

function ComplianceCard({ icon, title, state, children }: { icon: React.ReactNode; title: string; state: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-[#F1F5F9] p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-[#334155] flex items-center gap-1.5">{icon} {title}</span>
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATE_BADGE[state] ?? STATE_BADGE.none}`}>
          {state === "none" ? "Not started" : state}
        </span>
      </div>
      {children}
    </div>
  );
}

function EligibilityBlock({ elig, actionLabel, onAction }: { elig: { eligible: boolean; blockers: string[]; warnings: string[] }; actionLabel: string; onAction: () => void }) {
  return (
    <div className="space-y-2">
      {elig.blockers.map((b, i) => (
        <p key={`b${i}`} className="text-[11px] text-red-600 flex items-start gap-1"><XCircle size={11} className="mt-0.5 flex-shrink-0" /> {b}</p>
      ))}
      {elig.warnings.map((w, i) => (
        <p key={`w${i}`} className="text-[11px] text-amber-600 flex items-start gap-1"><AlertTriangle size={11} className="mt-0.5 flex-shrink-0" /> {w}</p>
      ))}
      <PrimaryBtn disabled={!elig.eligible} onClick={onAction}>{actionLabel}</PrimaryBtn>
    </div>
  );
}

function PrimaryBtn({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled}
      className="text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1">
      {children}
    </button>
  );
}

// ── Modals ────────────────────────────────────────────────────────────────────
const inputCls = "w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500";

function ModalShell({ title, note, onClose, children }: { title: string; note?: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative w-full max-w-sm bg-white rounded-xl shadow-xl p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-[#0F172A]">{title}</h3>
        {note && <p className="text-[11px] text-[#64748B]">{note}</p>}
        {children}
      </div>
    </div>
  );
}
function Actions({ onClose, onSubmit, busy, label }: { onClose: () => void; onSubmit: () => void; busy: boolean; label: string }) {
  return (
    <div className="flex justify-end gap-2 pt-1">
      <button onClick={onClose} disabled={busy} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50">Cancel</button>
      <button onClick={onSubmit} disabled={busy} className="text-xs px-3.5 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5">
        {busy && <Loader2 size={12} className="animate-spin" />} {label}
      </button>
    </div>
  );
}
function L({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block space-y-1"><span className="block text-xs font-medium text-[#475569]">{label}</span>{children}</label>;
}

function PrepareIrnModal({ busy, onClose, onSubmit }: { busy: boolean; onClose: () => void; onSubmit: (t: GstTreatment, lut: string) => void }) {
  const [t, setT] = useState<GstTreatment>("regular");
  const [lut, setLut] = useState("");
  return (
    <ModalShell title="Prepare IRN" note="This only creates the record. You generate the IRN on the IRP portal — nothing is auto-submitted." onClose={onClose}>
      <L label="GST treatment">
        <select value={t} onChange={(e) => setT(e.target.value as GstTreatment)} className={inputCls}>
          {TREATMENTS.map((x) => <option key={x} value={x}>{treatmentLabel(x)}</option>)}
        </select>
      </L>
      {WITHOUT_PAYMENT.has(t) && (
        <L label="LUT / Bond number"><input value={lut} onChange={(e) => setLut(e.target.value)} placeholder="LUT/2026/001" className={inputCls} /></L>
      )}
      <Actions onClose={onClose} onSubmit={() => onSubmit(t, lut)} busy={busy} label="Prepare record" />
    </ModalShell>
  );
}

function RecordIrnModal({ busy, onClose, onSubmit }: { busy: boolean; onClose: () => void; onSubmit: (f: { irn: string; ack_number: string; ack_date: string; qr_data: string }) => void }) {
  const today = new Date().toISOString().split("T")[0];
  const [irn, setIrn] = useState(""); const [ack, setAck] = useState(""); const [date, setDate] = useState(today); const [qr, setQr] = useState("");
  const ok = irn.trim().length > 0 && ack.trim().length > 0;
  return (
    <ModalShell title="Record IRN" note="Enter the IRN details from the IRP portal (# CA REVIEW REQUIRED — recorded, not submitted)." onClose={onClose}>
      <L label="IRN"><input value={irn} onChange={(e) => setIrn(e.target.value)} placeholder="64-char IRN" className={inputCls} /></L>
      <L label="Acknowledgement no."><input value={ack} onChange={(e) => setAck(e.target.value)} className={inputCls} /></L>
      <L label="Acknowledgement date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></L>
      <L label="Signed QR payload (optional)"><textarea value={qr} onChange={(e) => setQr(e.target.value)} rows={2} className={inputCls} /></L>
      <Actions onClose={onClose} onSubmit={() => ok && onSubmit({ irn, ack_number: ack, ack_date: date, qr_data: qr })} busy={busy} label="Record IRN" />
    </ModalShell>
  );
}

function PrepareEwayModal({ busy, invoice, onClose, onSubmit }: { busy: boolean; invoice: InvoiceDetail; onClose: () => void; onSubmit: (f: { dispatch_from: string; ship_to: string; goods_description: string; hsn_code: string }) => void }) {
  const [from, setFrom] = useState(invoice.supply_state_code ?? "");
  const [to, setTo] = useState("");
  const [goods, setGoods] = useState("");
  const [hsn, setHsn] = useState(invoice.lines[0]?.hsn_sac ?? "");
  const ok = from.trim() && to.trim();
  return (
    <ModalShell title="Prepare E-Way Bill" note={`Taxable value ${fmt(invoice.taxable_amount_paise)}. This creates the record; you generate the EWB on the NIC portal.`} onClose={onClose}>
      <div className="grid grid-cols-2 gap-2">
        <L label="Dispatch from (state)"><input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="27" className={inputCls} /></L>
        <L label="Ship to (state)"><input value={to} onChange={(e) => setTo(e.target.value)} placeholder="29" className={inputCls} /></L>
      </div>
      <L label="Goods description"><input value={goods} onChange={(e) => setGoods(e.target.value)} placeholder="Goods per invoice" className={inputCls} /></L>
      <L label="HSN (optional)"><input value={hsn} onChange={(e) => setHsn(e.target.value)} className={inputCls} /></L>
      <Actions onClose={onClose} onSubmit={() => ok && onSubmit({ dispatch_from: from, ship_to: to, goods_description: goods, hsn_code: hsn })} busy={busy} label="Prepare record" />
    </ModalShell>
  );
}

function RecordEwayModal({ busy, onClose, onSubmit }: { busy: boolean; onClose: () => void; onSubmit: (f: { ewb_number: string; ewb_date: string; ewb_valid_upto: string }) => void }) {
  const today = new Date().toISOString().split("T")[0];
  const [num, setNum] = useState(""); const [date, setDate] = useState(today); const [valid, setValid] = useState(today);
  return (
    <ModalShell title="Record E-Way Bill" note="Enter the EWB details from the NIC portal." onClose={onClose}>
      <L label="E-Way Bill number"><input value={num} onChange={(e) => setNum(e.target.value)} placeholder="12-digit EWB no." className={inputCls} /></L>
      <div className="grid grid-cols-2 gap-2">
        <L label="EWB date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></L>
        <L label="Valid upto"><input type="date" value={valid} onChange={(e) => setValid(e.target.value)} className={inputCls} /></L>
      </div>
      <Actions onClose={onClose} onSubmit={() => num.trim() && onSubmit({ ewb_number: num, ewb_date: date, ewb_valid_upto: valid })} busy={busy} label="Record E-Way Bill" />
    </ModalShell>
  );
}

function CancelModal({ title, note, busy, onClose, onSubmit }: { title: string; note: string; busy: boolean; onClose: () => void; onSubmit: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <ModalShell title={title} note={note} onClose={onClose}>
      <L label="Cancellation reason"><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" className={inputCls} /></L>
      <Actions onClose={onClose} onSubmit={() => reason.trim() && onSubmit(reason)} busy={busy} label={title} />
    </ModalShell>
  );
}
