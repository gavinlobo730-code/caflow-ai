"use client";

/**
 * The purchase cycle BEFORE the bill (PUR-25).
 *
 * WHAT THE PRODUCT COULD NOT DO
 *   The cycle started at the bill. A client raises a purchase order, receives
 *   the goods against it and only then books the supplier's invoice; neither
 *   of the first two documents existed, so there was nothing to check the bill
 *   against — and no record at all of WHEN the goods arrived.
 *
 *   That second absence is statutory twice over: CGST s.16(2)(b) allows the
 *   input tax credit only where the goods have been RECEIVED, and MSMED s.15
 *   runs its fifteen days from the day of ACCEPTANCE, which s.2(b)'s
 *   Explanation makes the day of actual delivery.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Both statutory sentences, the
 * status vocabularies and the no-tolerance rule are served by
 * `GET /api/purchase-cycle/vocabulary`; the differences, the gaps and the
 * acceptance date are `domain/purchases/three_way_match.py`'s answers.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { AlertTriangle, ClipboardList, Info, PackageCheck, Plus, X } from "lucide-react";
import {
  api,
  type GoodsReceipt,
  type PurchaseCycleVocabulary,
  type PurchaseOrder,
  type PurchaseOrderPosition,
  type ThreeWayMatch,
} from "@/lib/api";
import { paiseFromRupeeInput, parseQuantity } from "@/lib/money/rupeeInput";

type Tab = "orders" | "receipts";
type Msg = { type: "ok" | "err"; text: string } | null;

interface Vendor { id: string; name?: string; vendor_name?: string }

const BLANK_LINE = { description: "", hsn_sac: "", quantity: "1", unit: "NOS",
                     rate: "", gst_rate_percent: "18" };

function rupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function PurchaseCycleTab({ clientId }: { clientId: string }) {
  const [tab, setTab] = useState<Tab>("orders");
  const [vocab, setVocab] = useState<PurchaseCycleVocabulary | null>(null);
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [receipts, setReceipts] = useState<GoodsReceipt[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [position, setPosition] = useState<PurchaseOrderPosition | null>(null);
  const [matchBillId, setMatchBillId] = useState("");
  const [matched, setMatched] = useState<ThreeWayMatch | null>(null);

  const [form, setForm] = useState({
    vendor_id: "",
    document_no: "",
    document_date: "",
    expected_date: "",
    received_on: "",
    order_id: "",
    vendor_challan_no: "",
    vehicle_no: "",
    is_inter_state: false,
    notes: "",
  });
  const [lines, setLines] = useState([{ ...BLANK_LINE }]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const [v, o, g, ven] = await Promise.all([
        api.purchaseCycle.vocabulary(),
        api.purchaseCycle.orders(clientId),
        api.purchaseCycle.receipts(clientId),
        api.vendors.list(clientId),
      ]);
      if (v.success && v.data) setVocab(v.data);
      if (o.success && o.data) setOrders(arrayOrEmpty(o.data));
      if (g.success && g.data) setReceipts(arrayOrEmpty(g.data));
      if (ven.success && ven.data) setVendors(arrayOrEmpty<Vendor>(ven.data));
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { void load(); }, [load]);

  /** Orders that are live work: approved or part-received. */
  const open = useMemo(
    () => orders.filter((o) => (vocab?.order_open_statuses || [])
      .includes(o.status)), [orders, vocab]);

  /** Receipts where an objection was raised and not yet removed. The MSMED
   *  s.2(b) clock has not started on these, so nothing can be said yet about
   *  when payment falls due. */
  const openObjections = useMemo(
    () => receipts.filter((g) => g.objection_raised_on && !g.objection_removed_on),
    [receipts]);

  function buildLines() {
    return lines.filter((l) => l.description.trim()).map((l) => ({
      description: l.description.trim(),
      hsn_sac: l.hsn_sac.trim() || null,
      quantity: parseQuantity(l.quantity) ?? 1,
      unit: l.unit.trim() || "NOS",
      rate_paise: paiseFromRupeeInput(l.rate) ?? 0,
      gst_rate_percent: Number(l.gst_rate_percent) || 0,
    }));
  }

  async function save() {
    const body = buildLines();
    if (!body.length) {
      setMsg({ type: "err", text: "Add at least one line." });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const res = tab === "orders"
        ? await api.purchaseCycle.createOrder({
            client_id: clientId, vendor_id: form.vendor_id,
            document_no: form.document_no, document_date: form.document_date,
            expected_date: form.expected_date || null,
            is_inter_state: form.is_inter_state,
            notes: form.notes || null, lines: body,
          })
        : await api.purchaseCycle.createReceipt({
            client_id: clientId, vendor_id: form.vendor_id,
            document_no: form.document_no, received_on: form.received_on,
            order_id: form.order_id || null,
            vendor_challan_no: form.vendor_challan_no || null,
            vehicle_no: form.vehicle_no || null,
            notes: form.notes || null,
            lines: body.map((l) => ({ ...l, rejected_qty: 0 })),
          });
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

  async function runMatch() {
    if (!matchBillId.trim()) return;
    const res = await api.purchaseCycle.matchBill(matchBillId.trim(), clientId);
    if (!res.success) {
      setMsg({ type: "err", text: res.error || "That bill was not found." });
      return;
    }
    setMatched(objectWithLists<ThreeWayMatch>(res.data, "caveats", "differences", "gaps", "lines") ?? null);
  }

  if (loading) return <div className="p-6 text-sm text-gray-500">Loading…</div>;
  if (loadFailed) {
    return (
      <div className="p-6">
        <div className="rounded border border-state-problem-border bg-state-problem-surface p-4 text-sm text-red-800">
          The purchase cycle could not be loaded.{" "}
          <button onClick={() => void load()} className="underline">Try again</button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-1">
      {vocab && (
        <div className="flex items-start gap-2 rounded border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
          <Info size={16} className="mt-0.5 shrink-0" />
          <span>{vocab.posts_nothing}</span>
        </div>
      )}

      {openObjections.length > 0 && (
        <div className="rounded border border-amber-300 bg-state-attention-surface p-3 text-sm text-amber-900">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle size={16} />
            {openObjections.length} goods receipt
            {openObjections.length === 1 ? "" : "s"} with an objection still open
          </div>
          {vocab && <p className="mt-1">{vocab.msmed_acceptance}</p>}
          <ul className="mt-2 space-y-1">
            {openObjections.map((g) => (
              <li key={g.id}>
                <span className="font-mono">{g.document_no}</span> — objected{" "}
                {g.objection_raised_on}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {([
          ["orders", "Purchase Orders", ClipboardList],
          ["receipts", "Goods Receipts", PackageCheck],
        ] as const).map(([id, label, Icon]) => (
          <button
            key={id}
            onClick={() => { setTab(id); setShowForm(false); setPosition(null); }}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm ${
              tab === id ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-700"
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
        <span className="ml-3 text-xs text-gray-500">
          {open.length} order{open.length === 1 ? "" : "s"} still open
        </span>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="ml-auto flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-sm text-white"
        >
          <Plus size={14} /> New
        </button>
      </div>

      {msg && (
        <div className={`rounded p-2 text-sm ${
          msg.type === "ok" ? "bg-green-50 text-green-800" : "bg-state-problem-surface text-red-800"
        }`}>{msg.text}</div>
      )}

      {showForm && (
        <div className="rounded border border-gray-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">
              New {tab === "orders" ? "purchase order" : "goods receipt"}
            </h3>
            <button onClick={() => setShowForm(false)}><X size={16} /></button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <label className="text-sm">
              <span className="mb-1 block text-gray-600">Supplier</span>
              <select
                value={form.vendor_id}
                onChange={(e) => setForm({ ...form, vendor_id: e.target.value })}
                className="w-full rounded border border-gray-300 px-2 py-1.5"
              >
                <option value="">Select…</option>
                {vendors.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name || v.vendor_name || v.id}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-sm">
              <span className="mb-1 block text-gray-600">Number</span>
              <input
                value={form.document_no}
                onChange={(e) => setForm({ ...form, document_no: e.target.value })}
                placeholder={tab === "orders" ? "PO/2026-27/0001" : "GRN/2026-27/0001"}
                className="w-full rounded border border-gray-300 px-2 py-1.5"
              />
            </label>

            {tab === "orders" ? (
              <>
                <label className="text-sm">
                  <span className="mb-1 block text-gray-600">Order date</span>
                  <input
                    type="date"
                    value={form.document_date}
                    onChange={(e) => setForm({ ...form, document_date: e.target.value })}
                    className="w-full rounded border border-gray-300 px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-gray-600">Expected by</span>
                  <input
                    type="date"
                    value={form.expected_date}
                    onChange={(e) => setForm({ ...form, expected_date: e.target.value })}
                    className="w-full rounded border border-gray-300 px-2 py-1.5"
                  />
                </label>
              </>
            ) : (
              <>
                <label className="text-sm">
                  <span className="mb-1 block text-gray-600">
                    Goods arrived on
                  </span>
                  <input
                    type="date"
                    value={form.received_on}
                    onChange={(e) => setForm({ ...form, received_on: e.target.value })}
                    className="w-full rounded border border-gray-300 px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-gray-600">Against order</span>
                  <select
                    value={form.order_id}
                    onChange={(e) => setForm({ ...form, order_id: e.target.value })}
                    className="w-full rounded border border-gray-300 px-2 py-1.5"
                  >
                    <option value="">No order</option>
                    {open.map((o) => (
                      <option key={o.id} value={o.id}>{o.document_no}</option>
                    ))}
                  </select>
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-gray-600">
                    Supplier&apos;s challan number
                  </span>
                  <input
                    value={form.vendor_challan_no}
                    onChange={(e) => setForm({ ...form, vendor_challan_no: e.target.value })}
                    className="w-full rounded border border-gray-300 px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-gray-600">Vehicle number</span>
                  <input
                    value={form.vehicle_no}
                    onChange={(e) => setForm({ ...form, vehicle_no: e.target.value })}
                    className="w-full rounded border border-gray-300 px-2 py-1.5"
                  />
                </label>
              </>
            )}

            {tab === "orders" && (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.is_inter_state}
                  onChange={(e) => setForm({ ...form, is_inter_state: e.target.checked })}
                />
                Inter-state supply
              </label>
            )}
          </div>

          <div className="mt-4">
            <div className="mb-2 text-sm font-medium text-gray-700">Lines</div>
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
                    className="rounded border border-gray-300 px-2 py-1.5 text-sm sm:col-span-2"
                  />
                  <input
                    value={l.hsn_sac}
                    placeholder="HSN"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, hsn_sac: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-gray-300 px-2 py-1.5 text-sm font-mono"
                  />
                  <input
                    value={l.quantity}
                    placeholder="Qty"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, quantity: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-gray-300 px-2 py-1.5 text-sm"
                  />
                  <input
                    value={l.rate}
                    placeholder="Rate ₹"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, rate: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-gray-300 px-2 py-1.5 text-sm"
                  />
                  <input
                    value={l.gst_rate_percent}
                    placeholder="GST %"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, gst_rate_percent: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-gray-300 px-2 py-1.5 text-sm"
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
              className="rounded border border-gray-300 px-4 py-1.5 text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {tab === "orders" && (
        <div className="space-y-3">
          <Table
            head={["Number", "Date", "Expected", "Status", "Value"]}
            rows={orders.map((o) => [
              o.document_no, o.document_date, o.expected_date || "—",
              o.status, rupees(o.total_paise),
            ])}
            empty="No purchase orders yet."
            onRow={(i) => {
              void api.purchaseCycle.orderPosition(orders[i].id, clientId)
                .then((r) => { if (r.success && r.data) setPosition(objectWithLists<PurchaseOrderPosition>(r.data, "lines")); });
            }}
          />
          {position && (
            <div className="rounded border border-gray-200 bg-white p-4">
              <div className="mb-2 flex items-center justify-between">
                <h4 className="text-sm font-semibold">What is still open</h4>
                <button onClick={() => setPosition(null)}><X size={14} /></button>
              </div>
              <Table
                head={["Line", "Ordered", "Received", "Outstanding", "Billed", "Unbilled"]}
                rows={position.lines.map((l) => [
                  l.description, l.ordered_qty, l.received_qty,
                  l.unreceived_qty, l.billed_qty, l.unbilled_qty,
                ])}
                empty="This order has no lines."
              />
              <p className="mt-2 text-xs text-gray-600">{position.posts_nothing}</p>
            </div>
          )}
        </div>
      )}

      {tab === "receipts" && (
        <Table
          head={["Number", "Arrived", "Against order", "Objection", "Status"]}
          rows={receipts.map((g) => [
            g.document_no,
            g.received_on,
            orders.find((o) => o.id === g.order_id)?.document_no || "—",
            g.objection_raised_on
              ? `${g.objection_raised_on}${g.objection_removed_on
                  ? ` → removed ${g.objection_removed_on}` : " (open)"}`
              : "—",
            g.status,
          ])}
          empty="No goods receipts yet."
        />
      )}

      {/* The three-way match, against a bill the CA names. */}
      <div className="rounded border border-gray-200 bg-white p-4">
        <h4 className="mb-2 text-sm font-semibold">
          Match a bill against its order and its receipts
        </h4>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={matchBillId}
            onChange={(e) => setMatchBillId(e.target.value)}
            placeholder="Purchase bill id"
            className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          />
          <button
            onClick={() => void runMatch()}
            className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white"
          >
            Match
          </button>
        </div>
        {matched && (
          <div className="mt-3 space-y-2 text-sm">
            <Table
              head={["Line", "Ordered", "Received", "Billed", "Rate difference"]}
              rows={matched.lines.map((l) => [
                l.description,
                l.ordered_qty ?? "—",
                l.received_qty ?? "—",
                l.billed_qty,
                l.rate_difference_paise === null
                  ? "—" : rupees(l.rate_difference_paise),
              ])}
              empty="This bill has no lines."
            />
            {matched.differences.map((d) => (
              <p key={d} className="rounded bg-state-problem-surface p-2 text-red-900">{d}</p>
            ))}
            {matched.gaps.map((g) => (
              <p key={g} className="rounded bg-state-attention-surface p-2 text-amber-900">{g}</p>
            ))}
            {matched.acceptance_date && (
              <p className="text-gray-700">
                Day of acceptance: {matched.acceptance_date}.{" "}
                {matched.acceptance_source}
              </p>
            )}
            {matched.caveats.map((c) => (
              <p key={c} className="text-xs text-ps-label">{c}</p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Table({ head, rows, empty, onRow }: {
  head: string[];
  rows: (string | number)[][];
  empty: string;
  onRow?: (index: number) => void;
}) {
  if (!rows.length) return <p className="p-4 text-sm text-gray-500">{empty}</p>;
  return (
    <div className="overflow-x-auto rounded border border-gray-200">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
          <tr>{head.map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              onClick={onRow ? () => onRow(i) : undefined}
              className={`border-t border-gray-100 ${onRow ? "cursor-pointer hover:bg-gray-50" : ""}`}
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
