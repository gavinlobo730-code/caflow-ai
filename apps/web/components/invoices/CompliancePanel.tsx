"use client";

/**
 * CompliancePanel — the Invoice Hub's GST compliance section (Batch 7). Surfaces
 * the derived GST treatment + place-of-supply validation and drives the IRN and
 * E-Way Bill workflows on top of the EXISTING einvoice / eway-bill record
 * endpoints. Nothing here auto-submits to a government portal: the CA prepares a
 * record, generates the IRN/EWB on the IRP/NIC portal, then records the result —
 * every mutation is an explicit, confirmed action. Accounting/posting untouched.
 */
import { useEffect, useMemo, useState } from "react";
import {
  ShieldCheck, FileCheck2, Truck, AlertTriangle, Loader2, QrCode, XCircle,
} from "lucide-react";
import { Modal as ModalShell } from "@/components/ui/modal";
import { apiCall, apiGet, getAuthToken, fmt, type InvoiceDetail } from "@/lib/invoices/shared";
import { todayLocalISO } from "@/lib/dateMath";
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
    // THE INVOICE'S OWN FIELDS, not a hardcoded null and not the e-invoice
    // record's separate vocabulary (SALES-19). `is_reverse_charge` was pinned
    // to null, so the treatment summary said "not reverse charge" on every
    // invoice including the ones that are; and the treatment came only from an
    // IRN record, so an invoice marked zero-rated or SEZ — the fields GSTR-1 is
    // actually built from — showed as "Regular" until somebody prepared one.
    //
    // `invoice.gst_treatment` is DERIVED server-side from supply_type +
    // invoice_type + the IGST charged (apps/api/domain/gst/treatment.py). The
    // e-invoice record's own value is kept as the fallback for the window where
    // this frontend has redeployed ahead of the backend.
    is_reverse_charge: invoice.is_reverse_charge ?? null,
    gst_treatment: invoice.gst_treatment ?? irn.record?.gst_treatment ?? null,
    taxable_amount_paise: invoice.taxable_amount_paise,
    line_hsn_codes: invoice.lines.map((l) => l.hsn_sac),
    // Rule 138's consignment value is measured PER LINE, including the tax and
    // cess charged on it and excluding exempt goods where the invoice carries
    // both (Explanation 2 to Rule 138(1)). `taxable_amount_paise` alone cannot
    // answer it, and comparing it against ₹50,000 advised a ₹56,640 consignment
    // as "usually not required" — see assessEway in lib/invoices/compliance.
    lines: invoice.lines.map((l) => ({
      hsn_sac: l.hsn_sac,
      taxable_amount_paise: l.taxable_amount_paise,
      cgst_paise: l.cgst_paise,
      sgst_paise: l.sgst_paise,
      igst_paise: l.igst_paise,
      gst_rate_bps: l.gst_rate_bps,
    })),
    // What the server decided (apps/api/domain/gst/eway.py, the authority).
    // The browser mirror is only reached where this is absent.
    eway_assessment: invoice.eway_assessment ?? null,
  }), [invoice, irn.record]);

  const treatment = gstTreatment(compInv);
  const posIssues = validatePlaceOfSupply(compInv);
  const irnElig = irnEligibility(compInv, irn.state === "generated");
  const ewayElig = ewayEligibility(compInv, eway.state === "generated");

  // Every compliance mutation is authenticated: run() fetches the bearer token
  // once and threads it into the apiCall (omitting it would 401 at the backend).
  async function run(fn: (token: string) => Promise<void>, okMsg: string) {
    setBusy(true);
    try {
      const token = await getAuthToken();
      await fn(token);
      onToast(okMsg, "success");
      setModal(null);
      onChanged();
    }
    catch (e) { onToast(e instanceof Error ? e.message : "Action failed", "error"); }
    finally { setBusy(false); }
  }

  async function prepareIrn(t: GstTreatment, lut: string) {
    await run(async (token) => {
      const r = await apiCall("/api/einvoice/records", "POST", {
        client_id: clientId, invoice_number: invoice.invoice_no, invoice_date: invoice.invoice_date,
        sales_invoice_id: invoice.id, gst_treatment: t, lut_number: lut.trim() || undefined,
      }, token);
      if (!r.success) throw new Error(r.error ?? "Could not prepare the IRN record");
    }, "IRN record prepared — generate it on the IRP portal, then record it");
  }
  async function recordIrn(f: { irn: string; ack_number: string; ack_date: string; qr_data: string }) {
    const id = irn.record?.id;
    if (!id) return;
    await run(async (token) => {
      const r = await apiCall(`/api/einvoice/records/${id}/irn-generated`, "POST", {
        irn: f.irn.trim(), ack_number: f.ack_number.trim(), ack_date: f.ack_date, qr_data: f.qr_data.trim() || undefined,
      }, token);
      if (!r.success) throw new Error(r.error ?? "Could not record the IRN");
    }, `IRN ${f.irn.trim()} recorded`);
  }
  async function cancelIrn(reason: string) {
    const id = irn.record?.id;
    if (!id) return;
    await run(async (token) => {
      const r = await apiCall(`/api/einvoice/records/${id}/cancel`, "POST", { cancellation_reason: reason }, token);
      if (!r.success) throw new Error(r.error ?? "Could not cancel the IRN");
    }, "IRN cancellation recorded");
  }

  async function prepareEway(f: { dispatch_from: string; ship_to: string; goods_description: string; hsn_code: string; distance_km: string; vehicle_type: string; transport_mode: string }) {
    await run(async (token) => {
      const r = await apiCall("/api/eway-bill/records", "POST", {
        client_id: clientId, invoice_number: invoice.invoice_no, sales_invoice_id: invoice.id,
        dispatch_from: f.dispatch_from.trim(), ship_to: f.ship_to.trim(),
        goods_description: f.goods_description.trim() || "Goods per invoice",
        taxable_value_paise: invoice.taxable_amount_paise, hsn_code: f.hsn_code.trim() || undefined,
        // Rule 138(10)'s inputs. Stored since migration 156 and, until
        // 2026-09-12, asked for by no screen — so the validity the product held
        // was whatever somebody re-keyed off the portal, with the one figure
        // that determines it sitting empty beside it (SALES-28).
        distance_km: f.distance_km.trim() ? Number(f.distance_km.trim()) : undefined,
        vehicle_type: f.vehicle_type || undefined,
        transport_mode: f.transport_mode || undefined,
      }, token);
      if (!r.success) throw new Error(r.error ?? "Could not prepare the E-Way Bill record");
    }, "E-Way Bill record prepared — generate it on the NIC portal, then record it");
  }
  async function recordEway(f: { ewb_number: string; ewb_date: string; ewb_valid_upto: string }) {
    const id = eway.record?.id;
    if (!id) return;
    await run(async (token) => {
      const r = await apiCall(`/api/eway-bill/records/${id}/generated`, "POST", {
        ewb_number: f.ewb_number.trim(), ewb_date: f.ewb_date, ewb_valid_upto: f.ewb_valid_upto,
      }, token);
      if (!r.success) throw new Error(r.error ?? "Could not record the E-Way Bill");
    }, `E-Way Bill ${f.ewb_number.trim()} recorded`);
  }
  async function cancelEway(reason: string) {
    const id = eway.record?.id;
    if (!id) return;
    await run(async (token) => {
      const r = await apiCall(`/api/eway-bill/records/${id}/cancel`, "POST", { cancellation_reason: reason }, token);
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
      {modal === "recordEway" && <RecordEwayModal busy={busy} recordId={eway.record?.id ?? ""} onClose={() => setModal(null)} onSubmit={recordEway} />}
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

function Actions({ onClose, onSubmit, busy, label, disabled }: { onClose: () => void; onSubmit: () => void; busy: boolean; label: string; disabled?: boolean }) {
  return (
    <div className="flex justify-end gap-2 pt-1">
      <button onClick={onClose} disabled={busy} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] disabled:opacity-50">Cancel</button>
      <button onClick={onSubmit} disabled={busy || disabled} className="text-xs px-3.5 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5">
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
  const today = todayLocalISO();
  const [irn, setIrn] = useState(""); const [ack, setAck] = useState(""); const [date, setDate] = useState(today); const [qr, setQr] = useState("");
  const ok = irn.trim().length > 0 && ack.trim().length > 0;
  return (
    <ModalShell title="Record IRN" note="Enter the IRN details from the IRP portal (# CA REVIEW REQUIRED — recorded, not submitted)." onClose={onClose}>
      <L label="IRN"><input value={irn} onChange={(e) => setIrn(e.target.value)} placeholder="64-char IRN" className={inputCls} /></L>
      <L label="Acknowledgement no."><input value={ack} onChange={(e) => setAck(e.target.value)} className={inputCls} /></L>
      <L label="Acknowledgement date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></L>
      <L label="Signed QR payload (optional)"><textarea value={qr} onChange={(e) => setQr(e.target.value)} rows={2} className={inputCls} /></L>
      <Actions onClose={onClose} onSubmit={() => ok && onSubmit({ irn, ack_number: ack, ack_date: date, qr_data: qr })} busy={busy} disabled={!ok} label="Record IRN" />
    </ModalShell>
  );
}

function PrepareEwayModal({ busy, invoice, onClose, onSubmit }: { busy: boolean; invoice: InvoiceDetail; onClose: () => void; onSubmit: (f: { dispatch_from: string; ship_to: string; goods_description: string; hsn_code: string; distance_km: string; vehicle_type: string; transport_mode: string }) => void }) {
  const [from, setFrom] = useState(invoice.supply_state_code ?? "");
  const [to, setTo] = useState("");
  const [goods, setGoods] = useState("");
  const [hsn, setHsn] = useState(invoice.lines[0]?.hsn_sac ?? "");
  // Rule 138(10)'s inputs. Distance is optional here on purpose — without it
  // the server refuses to compute a validity and says so, which is better than
  // blocking a record the CA can still generate on the portal.
  const [distance, setDistance] = useState("");
  const [vehicleType, setVehicleType] = useState("regular");
  const [transportMode, setTransportMode] = useState("road");
  const ok = from.trim() && to.trim();
  return (
    <ModalShell title="Prepare E-Way Bill" note={`Taxable value ${fmt(invoice.taxable_amount_paise)}. This creates the record; you generate the EWB on the NIC portal.`} onClose={onClose}>
      <div className="grid grid-cols-2 gap-2">
        <L label="Dispatch from (state)"><input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="27" className={inputCls} /></L>
        <L label="Ship to (state)"><input value={to} onChange={(e) => setTo(e.target.value)} placeholder="29" className={inputCls} /></L>
      </div>
      <L label="Goods description"><input value={goods} onChange={(e) => setGoods(e.target.value)} placeholder="Goods per invoice" className={inputCls} /></L>
      <L label="HSN (optional)"><input value={hsn} onChange={(e) => setHsn(e.target.value)} className={inputCls} /></L>
      <div className="grid grid-cols-3 gap-2">
        <L label="Distance (km)">
          <input value={distance} inputMode="numeric"
            onChange={(e) => setDistance(e.target.value.replace(/[^0-9]/g, ""))}
            placeholder="e.g. 480" className={inputCls} />
        </L>
        <L label="Vehicle type">
          <select value={vehicleType} onChange={(e) => setVehicleType(e.target.value)} className={inputCls}>
            <option value="regular">Regular</option>
            <option value="over_dimensional">Over Dimensional Cargo</option>
          </select>
        </L>
        <L label="Transport mode">
          <select value={transportMode} onChange={(e) => setTransportMode(e.target.value)} className={inputCls}>
            <option value="road">Road</option>
            <option value="rail">Rail</option>
            <option value="air">Air</option>
            <option value="ship">Ship</option>
          </select>
        </L>
      </div>
      <p className="text-[10px] text-[#94A3B8]">
        Distance decides how long the bill is valid — one day per 200 km, or per 20 km
        for Over Dimensional Cargo (CGST Rule 138(10)). Leave it blank and the expiry
        has to be read off the portal.
      </p>
      <Actions onClose={onClose} onSubmit={() => ok && onSubmit({ dispatch_from: from, ship_to: to, goods_description: goods, hsn_code: hsn, distance_km: distance, vehicle_type: vehicleType, transport_mode: transportMode })} busy={busy} disabled={!ok} label="Prepare record" />
    </ModalShell>
  );
}

function RecordEwayModal({ busy, recordId, onClose, onSubmit }: { busy: boolean; recordId: string; onClose: () => void; onSubmit: (f: { ewb_number: string; ewb_date: string; ewb_valid_upto: string }) => void }) {
  const today = todayLocalISO();
  const [num, setNum] = useState(""); const [date, setDate] = useState(today); const [valid, setValid] = useState(today);
  // WHAT RULE 138(10) SAYS THIS BILL IS VALID UNTIL, from the distance recorded
  // when the record was prepared. "Valid upto" used to default to TODAY, which
  // is wrong for every bill that has ever existed — a bill is valid for at
  // least one day past its date — so the CA re-keyed the portal's date into a
  // box whose default was a trap (SALES-28).
  //
  // The server computes it; this renders it. It is a PRE-FILL and a
  // cross-check, never a substitute: the portal is authoritative, and the
  // `source`/`caveat` strings say so at the point of display.
  const [computed, setComputed] = useState<{ valid_upto: string | null; days: number | null;
    slab_km: number | null; source: string | null; caveat: string | null; gap: string | null } | null>(null);
  const [validTouched, setValidTouched] = useState(false);
  useEffect(() => {
    if (!recordId || !date) return;
    let cancelled = false;
    (async () => {
      try {
        const token = await getAuthToken();
        const r = await apiGet(`/api/eway-bill/records/${recordId}/validity?ewb_date=${encodeURIComponent(date)}`, token);
        if (cancelled || !r.success) return;
        const d = r.data as NonNullable<typeof computed>;
        setComputed(d);
        if (d.valid_upto && !validTouched) setValid(d.valid_upto);
      } catch {
        // Best-effort: the CA can always type the portal's own date.
      }
    })();
    return () => { cancelled = true; };
  }, [recordId, date, validTouched]);
  const disagrees = Boolean(computed?.valid_upto && valid && computed.valid_upto !== valid);
  return (
    <ModalShell title="Record E-Way Bill" note="Enter the EWB details from the NIC portal." onClose={onClose}>
      <L label="E-Way Bill number"><input value={num} onChange={(e) => setNum(e.target.value)} placeholder="12-digit EWB no." className={inputCls} /></L>
      <div className="grid grid-cols-2 gap-2">
        <L label="EWB date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} /></L>
        <L label="Valid upto">
          <input type="date" value={valid}
            onChange={(e) => { setValidTouched(true); setValid(e.target.value); }}
            className={inputCls} />
        </L>
      </div>
      {computed?.gap && <p className="text-[10px] text-amber-700">{computed.gap}</p>}
      {computed?.valid_upto && (
        <p className="text-[10px] text-[#94A3B8]">
          {computed.days} day{computed.days === 1 ? "" : "s"} at one per {computed.slab_km} km — {computed.source}.
          The portal&apos;s own date is what counts; correct this if it differs.
        </p>
      )}
      {computed?.caveat && <p className="text-[10px] text-amber-700">{computed.caveat}</p>}
      {disagrees && (
        <p className="text-[10px] text-amber-700">
          This differs from the {computed?.valid_upto} that Rule 138(10) gives for the recorded
          distance. Recording the portal&apos;s date is right — but check the distance too, since
          it is what every later expiry warning is worked out from.
        </p>
      )}
      <Actions onClose={onClose} onSubmit={() => num.trim() && onSubmit({ ewb_number: num, ewb_date: date, ewb_valid_upto: valid })} busy={busy} disabled={!num.trim()} label="Record E-Way Bill" />
    </ModalShell>
  );
}

function CancelModal({ title, note, busy, onClose, onSubmit }: { title: string; note: string; busy: boolean; onClose: () => void; onSubmit: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <ModalShell title={title} note={note} onClose={onClose}>
      <L label="Cancellation reason"><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" className={inputCls} /></L>
      <Actions onClose={onClose} onSubmit={() => reason.trim() && onSubmit(reason)} busy={busy} disabled={!reason.trim()} label={title} />
    </ModalShell>
  );
}
