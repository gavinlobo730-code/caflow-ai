"use client";

/**
 * The sales cycle BEFORE the tax invoice (SALES-21).
 *
 * WHAT THE PRODUCT COULD NOT DO
 *   The cycle started at the invoice. A client quotes, takes an order,
 *   delivers against it and bills afterwards — and none of the first three
 *   documents existed, so the CA either raised the tax invoice EARLY
 *   (declaring a supply that had not happened) or kept the quotation in a
 *   spreadsheet and re-typed every line when it converted.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Which of CGST Rule 55's movements
 * a challan covers, what that document must contain, whether its lines carry
 * tax, and which deemed-supply clock is running are all
 * `domain/gst/delivery_challan.py`'s answers, served through
 * `GET /api/sales-cycle/vocabulary` so no label lives here.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { AlertTriangle, Clock, FileText, Info, Plus, Truck, X } from "lucide-react";
import {
  api,
  type ChallanParticulars,
  type DeliveryChallan,
  type OrderPosition,
  type SalesCycleVocabulary,
  type SalesOrder,
  type SalesQuotation,
} from "@/lib/api";
import { paiseFromRupeeInput, parseQuantity } from "@/lib/money/rupeeInput";

type Tab = "quotations" | "orders" | "challans";
type Msg = { type: "ok" | "err"; text: string } | null;

interface Customer { id: string; name?: string; customer_name?: string }

const BLANK_LINE = { description: "", hsn_sac: "", quantity: "1", unit: "NOS",
                     rate: "", gst_rate_percent: "18" };

function rupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function SalesCycleTab({ clientId }: { clientId: string }) {
  const [tab, setTab] = useState<Tab>("quotations");
  const [vocab, setVocab] = useState<SalesCycleVocabulary | null>(null);
  const [quotations, setQuotations] = useState<SalesQuotation[]>([]);
  const [orders, setOrders] = useState<SalesOrder[]>([]);
  const [challans, setChallans] = useState<DeliveryChallan[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState<ChallanParticulars | null>(null);
  const [position, setPosition] = useState<OrderPosition | null>(null);

  const [form, setForm] = useState({
    kind: "quotation",
    customer_id: "",
    document_no: "",
    document_date: "",
    valid_until: "",
    customer_po_no: "",
    expected_delivery_date: "",
    reason: "job_work",
    goods_kind: "",
    consignee_name: "",
    consignee_gstin: "",
    consignee_address: "",
    transporter_name: "",
    vehicle_no: "",
    is_inter_state: false,
    notes: "",
  });
  const [lines, setLines] = useState([{ ...BLANK_LINE }]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const [v, q, o, c, cust] = await Promise.all([
        api.salesCycle.vocabulary(),
        api.salesCycle.quotations(clientId),
        api.salesCycle.orders(clientId),
        api.salesCycle.challans(clientId),
        api.customers.list(clientId),
      ]);
      if (v.success && v.data) setVocab(objectWithLists<SalesCycleVocabulary>(v.data, "challan_reasons", "goods_kinds", "quote_kinds"));
      if (q.success && q.data) setQuotations(arrayOrEmpty(q.data));
      if (o.success && o.data) setOrders(arrayOrEmpty(o.data));
      if (c.success && c.data) setChallans(arrayOrEmpty(c.data));
      if (cust.success && cust.data) setCustomers(arrayOrEmpty<Customer>(cust.data));
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { void load(); }, [load]);

  /** Every challan whose s.143 or s.31(7) period has run out and whose goods
   *  are not back. This is the figure the whole feature exists for: nothing in
   *  a ledger shows it, because no journal was ever posted. */
  const overdue = useMemo(
    () => challans.filter((c) => c.clock?.overdue === true && !c.received_back_on),
    [challans]);

  /** Challans whose clock cannot be run because the kind of goods was never
   *  recorded. NOT counted as safe — s.143's periods differ by a factor of
   *  three and the module refuses to pick one. */
  const undecided = useMemo(
    () => challans.filter((c) => (c.clock?.gaps || []).length > 0), [challans]);

  const buildLines = () => lines
    .filter((l) => l.description.trim())
    .map((l) => ({
      description: l.description.trim(),
      hsn_sac: l.hsn_sac.trim() || null,
      quantity: parseQuantity(l.quantity) ?? 1,
      unit: l.unit.trim() || "NOS",
      rate_paise: paiseFromRupeeInput(l.rate) ?? 0,
      gst_rate_percent: Number(l.gst_rate_percent) || 0,
    }));

  async function save() {
    const body = buildLines();
    if (!body.length) {
      setMsg({ type: "err", text: "Add at least one line." });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      let res;
      if (tab === "quotations") {
        res = await api.salesCycle.createQuotation({
          client_id: clientId, customer_id: form.customer_id,
          kind: form.kind, document_no: form.document_no,
          document_date: form.document_date,
          valid_until: form.valid_until || null,
          is_inter_state: form.is_inter_state,
          notes: form.notes || null, lines: body,
        });
      } else if (tab === "orders") {
        res = await api.salesCycle.createOrder({
          client_id: clientId, customer_id: form.customer_id,
          document_no: form.document_no, document_date: form.document_date,
          customer_po_no: form.customer_po_no || null,
          expected_delivery_date: form.expected_delivery_date || null,
          is_inter_state: form.is_inter_state,
          notes: form.notes || null, lines: body,
        });
      } else {
        res = await api.salesCycle.createChallan({
          client_id: clientId,
          customer_id: form.customer_id || null,
          document_no: form.document_no, document_date: form.document_date,
          reason: form.reason,
          goods_kind: form.reason === "job_work" && form.goods_kind
            ? form.goods_kind : null,
          consignee_name: form.consignee_name || null,
          consignee_gstin: form.consignee_gstin || null,
          consignee_address: form.consignee_address || null,
          transporter_name: form.transporter_name || null,
          vehicle_no: form.vehicle_no || null,
          is_inter_state: form.is_inter_state,
          notes: form.notes || null, lines: body,
        });
      }
      if (!res.success) {
        setMsg({ type: "err", text: res.error || "That was refused." });
        return;
      }
      setShowForm(false);
      setLines([{ ...BLANK_LINE }]);
      setMsg({ type: "ok", text: "Saved." });
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Failed." });
    } finally {
      setSaving(false);
    }
  }

  async function markBack(challan: DeliveryChallan, on: string) {
    const res = await api.salesCycle.updateChallan(challan.id, clientId,
      { received_back_on: on });
    if (!res.success) {
      setMsg({ type: "err", text: res.error || "That was refused." });
      return;
    }
    await load();
  }

  if (loading) {
    return <div className="p-6 text-sm text-ps-hint">Loading…</div>;
  }
  if (loadFailed) {
    return (
      <div className="p-6">
        <div className="rounded border border-state-problem-border bg-state-problem-surface p-4 text-sm text-state-problem">
          The sales cycle could not be loaded.{" "}
          <button onClick={() => void load()} className="underline">Try again</button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-1">
      {/* Nothing here is a tax invoice, and the server says so once. */}
      {vocab && (
        <div className="flex items-start gap-2 rounded border border-ps-border bg-ps-muted p-3 text-sm text-ps-body">
          <Info size={16} className="mt-0.5 shrink-0" />
          <span>{vocab.not_a_tax_invoice}</span>
        </div>
      )}

      {overdue.length > 0 && (
        <div className="rounded border border-state-problem bg-state-problem-surface p-3 text-sm text-state-problem">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle size={16} />
            {overdue.length} challan{overdue.length === 1 ? "" : "s"} past the
            statutory period with the goods not back
          </div>
          <ul className="mt-2 space-y-1">
            {overdue.map((c) => (
              <li key={c.id}>
                <span className="font-mono">{c.document_no}</span> — due back{" "}
                {c.clock.due_back_by}. {c.clock.consequence}
              </li>
            ))}
          </ul>
        </div>
      )}

      {undecided.length > 0 && (
        <div className="rounded border border-state-attention-border bg-state-attention-surface p-3 text-sm text-state-attention">
          <div className="flex items-center gap-2 font-medium">
            <Clock size={16} />
            {undecided.length} challan{undecided.length === 1 ? "" : "s"} cannot
            be timed yet
          </div>
          <ul className="mt-2 space-y-1">
            {undecided.map((c) => (
              <li key={c.id}>
                <span className="font-mono">{c.document_no}</span> —{" "}
                {c.clock.gaps.join(" ")}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {([
          ["quotations", "Quotations & Proforma", FileText],
          ["orders", "Sales Orders", FileText],
          ["challans", "Delivery Challans", Truck],
        ] as const).map(([id, label, Icon]) => (
          <button
            key={id}
            onClick={() => { setTab(id); setShowForm(false); setDetail(null); }}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm ${
              tab === id ? "bg-brand text-white" : "bg-ps-muted text-ps-body"
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
        <button
          onClick={() => setShowForm((v) => !v)}
          className="ml-auto flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-sm text-white"
        >
          <Plus size={14} /> New
        </button>
      </div>

      {msg && (
        <div className={`rounded p-2 text-sm ${
          msg.type === "ok" ? "bg-state-ready-surface text-state-ready" : "bg-state-problem-surface text-state-problem"
        }`}>{msg.text}</div>
      )}

      {showForm && vocab && (
        <div className="rounded border border-ps-border bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">
              New {tab === "quotations" ? "quotation or proforma"
                : tab === "orders" ? "sales order" : "delivery challan"}
            </h3>
            <button onClick={() => setShowForm(false)}><X size={16} /></button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {tab === "quotations" && (
              <label className="text-sm">
                <span className="mb-1 block text-ps-label">Document</span>
                <select
                  value={form.kind}
                  onChange={(e) => setForm({ ...form, kind: e.target.value })}
                  className="w-full rounded border border-ps-border px-2 py-1.5"
                >
                  {vocab.quote_kinds.map((k) => (
                    <option key={k.value} value={k.value}>{k.label}</option>
                  ))}
                </select>
              </label>
            )}

            {tab === "challans" && (
              <label className="text-sm sm:col-span-2">
                <span className="mb-1 block text-ps-label">
                  Why the goods are moving (CGST Rule 55)
                </span>
                <select
                  value={form.reason}
                  onChange={(e) => setForm({ ...form, reason: e.target.value })}
                  className="w-full rounded border border-ps-border px-2 py-1.5"
                >
                  {vocab.challan_reasons.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </label>
            )}

            {tab === "challans" && form.reason === "job_work" && (
              <label className="text-sm">
                <span className="mb-1 block text-ps-label">
                  What is being sent (CGST s.143)
                </span>
                <select
                  value={form.goods_kind}
                  onChange={(e) => setForm({ ...form, goods_kind: e.target.value })}
                  className="w-full rounded border border-ps-border px-2 py-1.5"
                >
                  <option value="">Not recorded</option>
                  {vocab.goods_kinds.map((g) => (
                    <option key={g.value} value={g.value}>{g.label}</option>
                  ))}
                </select>
              </label>
            )}

            <label className="text-sm">
              <span className="mb-1 block text-ps-label">
                {tab === "challans" ? "Consignee (customer)" : "Customer"}
              </span>
              <select
                value={form.customer_id}
                onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
                className="w-full rounded border border-ps-border px-2 py-1.5"
              >
                <option value="">Select…</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name || c.customer_name || c.id}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-sm">
              <span className="mb-1 block text-ps-label">Number</span>
              <input
                value={form.document_no}
                onChange={(e) => setForm({ ...form, document_no: e.target.value })}
                placeholder="QT/2026-27/0001"
                className="w-full rounded border border-ps-border px-2 py-1.5"
              />
            </label>

            <label className="text-sm">
              <span className="mb-1 block text-ps-label">Date</span>
              <input
                type="date"
                value={form.document_date}
                onChange={(e) => setForm({ ...form, document_date: e.target.value })}
                className="w-full rounded border border-ps-border px-2 py-1.5"
              />
            </label>

            {tab === "quotations" && (
              <label className="text-sm">
                <span className="mb-1 block text-ps-label">Valid until</span>
                <input
                  type="date"
                  value={form.valid_until}
                  onChange={(e) => setForm({ ...form, valid_until: e.target.value })}
                  className="w-full rounded border border-ps-border px-2 py-1.5"
                />
              </label>
            )}

            {tab === "orders" && (
              <>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">
                    Customer&apos;s PO number
                  </span>
                  <input
                    value={form.customer_po_no}
                    onChange={(e) => setForm({ ...form, customer_po_no: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">Expected delivery</span>
                  <input
                    type="date"
                    value={form.expected_delivery_date}
                    onChange={(e) => setForm({ ...form, expected_delivery_date: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
              </>
            )}

            {tab === "challans" && (
              <>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">Consignee name</span>
                  <input
                    value={form.consignee_name}
                    onChange={(e) => setForm({ ...form, consignee_name: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">
                    Consignee GSTIN (if registered)
                  </span>
                  <input
                    value={form.consignee_gstin}
                    onChange={(e) => setForm({ ...form, consignee_gstin: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5 font-mono"
                  />
                </label>
                <label className="text-sm sm:col-span-2">
                  <span className="mb-1 block text-ps-label">Consignee address</span>
                  <input
                    value={form.consignee_address}
                    onChange={(e) => setForm({ ...form, consignee_address: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">Transporter</span>
                  <input
                    value={form.transporter_name}
                    onChange={(e) => setForm({ ...form, transporter_name: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">Vehicle number</span>
                  <input
                    value={form.vehicle_no}
                    onChange={(e) => setForm({ ...form, vehicle_no: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
              </>
            )}

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_inter_state}
                onChange={(e) => setForm({ ...form, is_inter_state: e.target.checked })}
              />
              Inter-state movement
            </label>
          </div>

          <div className="mt-4">
            <div className="mb-2 text-sm font-medium text-ps-body">Lines</div>
            <div className="space-y-2">
              {lines.map((l, i) => (
                <div key={i} className="grid gap-2 sm:grid-cols-6">
                  <input
                    value={l.description}
                    placeholder="Description"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, description: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-ps-border px-2 py-1.5 text-sm sm:col-span-2"
                  />
                  <input
                    value={l.hsn_sac}
                    placeholder="HSN"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, hsn_sac: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-ps-border px-2 py-1.5 text-sm font-mono"
                  />
                  <input
                    value={l.quantity}
                    placeholder="Qty"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, quantity: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-ps-border px-2 py-1.5 text-sm"
                  />
                  <input
                    value={l.rate}
                    placeholder="Rate ₹"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, rate: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-ps-border px-2 py-1.5 text-sm"
                  />
                  <input
                    value={l.gst_rate_percent}
                    placeholder="GST %"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, gst_rate_percent: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-ps-border px-2 py-1.5 text-sm"
                  />
                </div>
              ))}
            </div>
            <button
              onClick={() => setLines([...lines, { ...BLANK_LINE }])}
              className="mt-2 text-sm text-blue-600"
            >
              + Add line
            </button>
          </div>

          {tab === "challans"
            && vocab.challan_reasons.find((r) => r.value === form.reason)
              ?.is_a_supply === false && (
            <p className="mt-3 text-xs text-ps-label">
              {vocab.no_tax_on_a_non_supply}
            </p>
          )}

          <div className="mt-4 flex gap-2">
            <button
              disabled={saving}
              onClick={() => void save()}
              className="rounded bg-brand px-4 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="rounded border border-ps-border px-4 py-1.5 text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {tab === "quotations" && (
        <Table
          head={["Kind", "Number", "Date", "Valid until", "Status", "Total"]}
          rows={quotations.map((q) => [
            q.title || q.kind,
            q.document_no,
            q.document_date,
            q.is_expired === true
              ? `${q.valid_until} (expired)`
              : q.valid_until || "—",
            q.status,
            rupees(q.total_paise),
          ])}
          empty="No quotations or proforma invoices yet."
        />
      )}

      {tab === "orders" && (
        <div className="space-y-3">
          <Table
            head={["Number", "Date", "Customer PO", "Expected", "Status", "Total"]}
            rows={orders.map((o) => [
              o.document_no, o.document_date, o.customer_po_no || "—",
              o.expected_delivery_date || "—", o.status, rupees(o.total_paise),
            ])}
            empty="No sales orders yet."
            onRow={(i) => {
              void api.salesCycle.orderPosition(orders[i].id, clientId)
                .then((r) => { if (r.success && r.data) setPosition(objectWithLists<OrderPosition>(r.data, "gaps", "lines")); });
            }}
          />
          {position && (
            <div className="rounded border border-ps-border bg-white p-4">
              <div className="mb-2 flex items-center justify-between">
                <h4 className="text-sm font-semibold">What is still open</h4>
                <button onClick={() => setPosition(null)}><X size={14} /></button>
              </div>
              <Table
                head={["Line", "Ordered", "Delivered", "Undelivered", "Invoiced", "Unbilled"]}
                rows={position.lines.map((l) => [
                  l.description, l.ordered_qty, l.delivered_qty,
                  l.undelivered_qty, l.invoiced_qty, l.unbilled_qty,
                ])}
                empty="This order has no lines."
              />
              {position.gaps.map((g) => (
                <p key={g} className="mt-2 text-xs text-state-attention">{g}</p>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "challans" && (
        <div className="space-y-3">
          <Table
            head={["Number", "Date", "Why", "Due back", "Status", "Value"]}
            rows={challans.map((c) => [
              c.document_no,
              c.document_date,
              c.reason_label || c.reason,
              c.clock?.due_back_by
                ? `${c.clock.due_back_by}${c.clock.overdue ? " — OVERDUE" : ""}`
                : "—",
              c.received_back_on ? `back ${c.received_back_on}` : c.status,
              rupees(c.total_paise),
            ])}
            empty="No delivery challans yet."
            onRow={(i) => {
              void api.salesCycle.challan(challans[i].id, clientId)
                .then((r) => { if (r.success && r.data) setDetail(objectWithLists<ChallanParticulars>(r.data, "copies", "missing", "particulars")); });
            }}
          />

          {challans.some((c) => c.clock?.applies && !c.received_back_on) && (
            <div className="rounded border border-ps-border bg-white p-4">
              <h4 className="mb-2 text-sm font-semibold">
                Record goods coming back
              </h4>
              <div className="space-y-2">
                {challans.filter((c) => c.clock?.applies && !c.received_back_on)
                  .map((c) => (
                    <div key={c.id} className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="font-mono">{c.document_no}</span>
                      <input
                        type="date"
                        onChange={(e) => {
                          if (e.target.value) void markBack(c, e.target.value);
                        }}
                        className="rounded border border-ps-border px-2 py-1"
                      />
                    </div>
                  ))}
              </div>
            </div>
          )}

          {detail && (
            <div className="rounded border border-ps-border bg-white p-4">
              <div className="mb-2 flex items-center justify-between">
                <h4 className="text-sm font-semibold">
                  {detail.rule} — {detail.reason_label}
                </h4>
                <button onClick={() => setDetail(null)}><X size={14} /></button>
              </div>
              <Table
                head={["Clause", "Particular", "On the document"]}
                rows={detail.particulars.map((p) => [
                  p.clause,
                  p.required ? p.label : `${p.label} (not required here)`,
                  p.value || "—",
                ])}
                empty=""
              />
              {detail.missing.length > 0 && (
                <div className="mt-3 rounded border border-state-attention-border bg-state-attention-surface p-3 text-sm text-state-attention">
                  <div className="font-medium">Still to be recorded</div>
                  <ul className="mt-1 list-disc pl-5">
                    {detail.missing.map((m) => <li key={m}>{m}</li>)}
                  </ul>
                </div>
              )}
              <div className="mt-3 text-xs text-ps-label">
                <div className="font-medium text-ps-body">
                  Three copies (Rule 55(2))
                </div>
                <ul className="mt-1">
                  {detail.copies.map((c) => <li key={c.copy}>{c.legend}</li>)}
                </ul>
              </div>
              {detail.clock.applies && (
                <p className="mt-3 text-xs text-ps-body">{detail.clock.consequence}</p>
              )}
              {detail.rule_55_5.gaps.map((g) => (
                <p key={g} className="mt-2 text-xs text-state-attention">{g}</p>
              ))}
              {detail.clock.statute.includes("s.143") && (
                <p className="mt-2 text-xs text-ps-label">
                  {detail.itc_04.refusal}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Table({ head, rows, empty, onRow }: {
  head: string[];
  rows: (string | number)[][];
  empty: string;
  onRow?: (index: number) => void;
}) {
  if (!rows.length) {
    return <p className="p-4 text-sm text-ps-hint">{empty}</p>;
  }
  return (
    <div className="overflow-x-auto rounded border border-ps-border">
      <table className="w-full text-sm">
        <thead className="bg-ps-muted text-left text-xs uppercase text-ps-hint">
          <tr>{head.map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              onClick={onRow ? () => onRow(i) : undefined}
              className={`border-t border-ps-border ${onRow ? "cursor-pointer hover:bg-ps-hover" : ""}`}
            >
              {r.map((cell, j) => (
                <td key={j} className="px-3 py-2 tabular-nums">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
