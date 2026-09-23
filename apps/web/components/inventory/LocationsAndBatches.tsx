"use client";

/**
 * Where the stock is, and which lot it came from (INV-03a, migration 398).
 *
 * THREE THINGS THIS SCREEN RENDERS AND DECIDES NONE OF
 *
 *   Whether a transfer between two godowns is a SUPPLY. CGST s.25(4) makes two
 *   registrations of one entity distinct persons and Schedule I paragraph 2
 *   treats a movement between them as a supply even without consideration —
 *   so it needs a tax invoice. The browser asks /transfer-preview and renders
 *   the answer; it never compares two GSTINs itself, and it never mints the
 *   invoice, because Rule 28's valuation option is the client's.
 *
 *   WHICH BUCKET a batch's expiry falls in. "Expires within 30 days" is a
 *   boundary the server owns, including the part that is easy to get wrong:
 *   stock is still good ON its expiry date.
 *
 *   What "unallocated" means. Every movement recorded before this feature has
 *   no godown, nothing was back-filled, and the sentence explaining that is
 *   the server's.
 */
import { useCallback, useEffect, useState } from "react";
import { Plus, AlertCircle, Info, Warehouse, ArrowRightLeft, Trash2, Boxes } from "lucide-react";
import { request } from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { todayLocalISO } from "@/lib/dateMath";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Callout } from "@/components/ui/callout";

interface Godown {
  id: string;
  name: string;
  code: string | null;
  state_code: string | null;
  gstin: string | null;
  is_default: boolean;
  is_active: boolean;
}

interface DetailRow {
  service_catalogue_id: string;
  item_name: string;
  unit: string | null;
  godown_id: string | null;
  godown_name: string | null;
  batch_id: string | null;
  batch_no: string | null;
  expiry_date: string | null;
  qty_units: string;
  value_paise: number;
}

interface Batch {
  id: string;
  service_catalogue_id: string;
  batch_no: string;
  manufactured_on: string | null;
  expiry_date: string | null;
}

interface StockItem { id: string; name: string }

interface Expiry {
  bucket_order: string[];
  bucket_labels: Record<string, string>;
  buckets: Record<string, { quantity: string; value_paise: number; batches: number }>;
  rows: Array<{
    batch_no: string | null; item_name: string; godown_name: string | null;
    quantity: string; value_paise: number; expiry_date: string | null;
    bucket: string; days_to_expiry: number | null;
  }>;
  notes: string[];
}

const INPUT = "w-full px-2.5 py-1.5 border border-ps-border rounded-lg text-xs";

export function LocationsAndBatches({ clientId, asOf }: { clientId: string; asOf: string }) {
  const [godowns, setGodowns] = useState<Godown[]>([]);
  const [unallocatedMeans, setUnallocatedMeans] = useState("");
  const [detail, setDetail] = useState<DetailRow[]>([]);
  const [expiry, setExpiry] = useState<Expiry | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [items, setItems] = useState<StockItem[]>([]);
  const [addingBatch, setAddingBatch] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [g, d, e, b, it] = await Promise.all([
        request<{ success: boolean; data: { godowns: Godown[]; unallocated_means: string }; error: string | null }>(
          `/api/inventory/godowns?client_id=${encodeURIComponent(clientId)}`),
        request<{ success: boolean; data: { rows: DetailRow[] }; error: string | null }>(
          `/api/inventory/position-detail?client_id=${encodeURIComponent(clientId)}&as_of=${asOf}`),
        request<{ success: boolean; data: Expiry; error: string | null }>(
          `/api/inventory/expiry?client_id=${encodeURIComponent(clientId)}&as_of=${asOf}`),
        request<{ success: boolean; data: Batch[]; error: string | null }>(
          `/api/inventory/batches?client_id=${encodeURIComponent(clientId)}`),
        request<{ success: boolean; data: StockItem[]; error: string | null }>(
          `/api/inventory/items?client_id=${encodeURIComponent(clientId)}`),
      ]);
      if (!g.success || !d.success || !e.success || !b.success) {
        throw new Error(g.error ?? d.error ?? e.error ?? b.error ?? "Couldn't load.");
      }
      setGodowns(g.data.godowns ?? []);
      setUnallocatedMeans(g.data.unallocated_means ?? "");
      setDetail(d.data.rows ?? []);
      setExpiry(e.data);
      setBatches(b.data ?? []);
      setItems(it.success ? (it.data ?? []) : []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load stock locations.");
    } finally {
      setLoading(false);
    }
  }, [clientId, asOf]);

  useEffect(() => { load(); }, [load]);

  async function closeGodown(g: Godown) {
    try {
      await request(`/api/inventory/godowns/${g.id}?client_id=${encodeURIComponent(clientId)}`,
        { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't close the godown.");
    }
  }

  if (loading) return <TableSkeleton />;

  const unallocated = detail.filter((r) => !r.godown_id);

  return (
    <div className="space-y-5">
      {error && (
        <div role="alert" className="bg-state-problem-surface border border-state-problem-border rounded-lg px-3 py-2 text-xs text-state-problem flex gap-2">
          <AlertCircle size={13} className="shrink-0 mt-0.5" /><span>{error}</span>
        </div>
      )}

      {/* ── godowns ──────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-50 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ps-ink flex items-center gap-2">
            <Warehouse size={15} className="text-blue-600" /> Godowns
          </h3>
          <button onClick={() => setAdding(true)}
            className="text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white flex items-center gap-1">
            <Plus size={12} /> Add godown
          </button>
        </div>
        {godowns.length === 0 ? (
          <p className="px-5 py-6 text-xs text-ps-hint">
            No godowns recorded. Stock is tracked in one undifferentiated pile until
            you add one.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ps-muted text-ps-hint">
                  <th className="px-5 py-2 text-left font-semibold">Godown</th>
                  <th className="px-5 py-2 text-left font-semibold">State</th>
                  <th className="px-5 py-2 text-left font-semibold">Registration</th>
                  <th className="px-5 py-2 text-right font-semibold">Value held</th>
                  <th className="px-5 py-2 text-right font-semibold"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-bg">
                {godowns.map((g) => (
                  <tr key={g.id} className={g.is_active ? "" : "opacity-50"}>
                    <td className="px-5 py-2 text-ps-ink">
                      {g.name}
                      {g.is_default && (
                        <span className="ml-1.5 text-3xs px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">
                          default
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-2 text-ps-label">{g.state_code ?? "—"}</td>
                    <td className="px-5 py-2 font-mono text-2xs text-ps-label">
                      {/* Not recorded is its own answer: whether a transfer is a
                          supply cannot be determined without it. */}
                      {g.gstin ?? <span className="font-sans text-state-attention">Not recorded</span>}
                    </td>
                    <td className="px-5 py-2 text-right tabular-nums">
                      {formatPaise(detail
                        .filter((r) => r.godown_id === g.id)
                        .reduce((t, r) => t + r.value_paise, 0))}
                    </td>
                    <td className="px-5 py-2 text-right">
                      {g.is_active && (
                        <button onClick={() => closeGodown(g)} aria-label={`Close ${g.name}`}
                          className="p-1 rounded hover:bg-state-problem-surface text-red-600">
                          <Trash2 size={12} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {unallocated.length > 0 && unallocatedMeans && (
          <div className="px-5 py-3 border-t border-ps-muted bg-ps-bg flex gap-2">
            <Info size={13} className="shrink-0 mt-0.5 text-ps-hint" />
            <span className="text-2xs text-ps-label">{unallocatedMeans}</span>
          </div>
        )}
      </div>

      {/* ── the position, per godown per batch ───────────────────────── */}
      <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-50">
          <h3 className="text-sm font-semibold text-ps-ink">Stock by godown and lot</h3>
          <p className="text-2xs text-ps-hint mt-0.5">As at {asOf}</p>
        </div>
        {detail.length === 0 ? (
          <p className="px-5 py-6 text-xs text-ps-hint">No stock movements yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ps-muted text-ps-hint">
                  <th className="px-5 py-2 text-left font-semibold">Item</th>
                  <th className="px-5 py-2 text-left font-semibold">Godown</th>
                  <th className="px-5 py-2 text-left font-semibold">Lot</th>
                  <th className="px-5 py-2 text-left font-semibold">Expires</th>
                  <th className="px-5 py-2 text-right font-semibold">Qty</th>
                  <th className="px-5 py-2 text-right font-semibold">Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-bg">
                {detail.map((r, i) => (
                  <tr key={i}>
                    <td className="px-5 py-2 text-ps-ink">{r.item_name}</td>
                    <td className="px-5 py-2 text-ps-label">
                      {r.godown_name ?? <span className="text-ps-hint">Unallocated</span>}
                    </td>
                    <td className="px-5 py-2 text-ps-label">{r.batch_no ?? "—"}</td>
                    <td className="px-5 py-2 text-ps-label">{r.expiry_date ?? "—"}</td>
                    <td className="px-5 py-2 text-right tabular-nums">{r.qty_units}</td>
                    <td className="px-5 py-2 text-right tabular-nums">{formatPaise(r.value_paise)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── lots ─────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-50 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ps-ink flex items-center gap-2">
            <Boxes size={15} className="text-blue-600" /> Lots
          </h3>
          <button onClick={() => setAddingBatch(true)}
            className="text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white flex items-center gap-1">
            <Plus size={12} /> Add lot
          </button>
        </div>
        {batches.length === 0 ? (
          <p className="px-5 py-6 text-xs text-ps-hint">
            No lots recorded. Add one to track expiry or to trace a recall.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ps-muted text-ps-hint">
                  <th className="px-5 py-2 text-left font-semibold">Lot</th>
                  <th className="px-5 py-2 text-left font-semibold">Item</th>
                  <th className="px-5 py-2 text-left font-semibold">Manufactured</th>
                  <th className="px-5 py-2 text-left font-semibold">Expires</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-bg">
                {batches.map((b) => (
                  <tr key={b.id}>
                    <td className="px-5 py-2 text-ps-ink">{b.batch_no}</td>
                    <td className="px-5 py-2 text-ps-label">
                      {items.find((i) => i.id === b.service_catalogue_id)?.name ?? "—"}
                    </td>
                    <td className="px-5 py-2 text-ps-label">{b.manufactured_on ?? "—"}</td>
                    <td className="px-5 py-2 text-ps-label">
                      {/* Not recorded is its own answer: it is not the same as
                          stock that does not expire, and the server says so on
                          the expiry report below. */}
                      {b.expiry_date ?? <span className="text-state-attention">Not recorded</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── expiry ───────────────────────────────────────────────────── */}
      {expiry && (
        <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-50">
            <h3 className="text-sm font-semibold text-ps-ink">Expiry</h3>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-px bg-ps-muted">
            {expiry.bucket_order.map((b) => (
              <div key={b} className="bg-white px-4 py-3">
                <p className="text-2xs text-ps-hint">{expiry.bucket_labels[b]}</p>
                <p className="text-sm font-semibold text-ps-ink tabular-nums mt-0.5">
                  {formatPaise(expiry.buckets[b]?.value_paise ?? 0)}
                </p>
                <p className="text-3xs text-ps-hint">
                  {expiry.buckets[b]?.batches ?? 0} lot(s)
                </p>
              </div>
            ))}
          </div>
          {expiry.rows.length > 0 && (
            <div className="overflow-x-auto border-t border-ps-muted">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-ps-muted text-ps-hint">
                    <th className="px-5 py-2 text-left font-semibold">Lot</th>
                    <th className="px-5 py-2 text-left font-semibold">Item</th>
                    <th className="px-5 py-2 text-left font-semibold">Godown</th>
                    <th className="px-5 py-2 text-right font-semibold">Qty</th>
                    <th className="px-5 py-2 text-right font-semibold">Value</th>
                    <th className="px-5 py-2 text-left font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-bg">
                  {expiry.rows.map((r, i) => (
                    <tr key={i}>
                      <td className="px-5 py-2 text-ps-ink">{r.batch_no ?? "—"}</td>
                      <td className="px-5 py-2 text-ps-label">{r.item_name}</td>
                      <td className="px-5 py-2 text-ps-label">{r.godown_name ?? "—"}</td>
                      <td className="px-5 py-2 text-right tabular-nums">{r.quantity}</td>
                      <td className="px-5 py-2 text-right tabular-nums">{formatPaise(r.value_paise)}</td>
                      <td className="px-5 py-2">
                        {/* The BUCKET is the server's; the colour is the only
                            thing decided here, and it is decided from the
                            bucket rather than from the date. */}
                        <span className={`text-2xs px-1.5 py-0.5 rounded ${
                          r.bucket === "expired" ? "bg-state-problem-surface text-state-problem"
                          : r.bucket === "within_30_days" ? "bg-state-attention-surface text-state-attention"
                          : r.bucket === "no_expiry_recorded" ? "bg-ps-muted text-ps-label"
                          : "bg-emerald-50 text-emerald-700"}`}>
                          {expiry.bucket_labels[r.bucket]}
                        </span>
                        {r.expiry_date && (
                          <span className="ml-1.5 text-3xs text-ps-hint">{r.expiry_date}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {expiry.notes.length > 0 && (
            <div className="px-5 py-3 border-t border-ps-muted space-y-1">
              {expiry.notes.map((n, i) => (
                <p key={i} className="text-2xs text-ps-label">{n}</p>
              ))}
            </div>
          )}
        </div>
      )}

      {godowns.filter((g) => g.is_active).length >= 2 && (
        <TransferPanel clientId={clientId} godowns={godowns.filter((g) => g.is_active)}
          detail={detail} onDone={load} />
      )}

      {adding && (
        <GodownModal clientId={clientId} onClose={() => setAdding(false)}
          onSaved={() => { setAdding(false); load(); }} />
      )}

      {addingBatch && (
        <BatchModal clientId={clientId} items={items}
          onClose={() => setAddingBatch(false)}
          onSaved={() => { setAddingBatch(false); load(); }} />
      )}
    </div>
  );
}


function TransferPanel({ clientId, godowns, detail, onDone }: {
  clientId: string; godowns: Godown[]; detail: DetailRow[]; onDone: () => void;
}) {
  const [from, setFrom] = useState(godowns[0]?.id ?? "");
  const [to, setTo] = useState(godowns[1]?.id ?? "");
  const [item, setItem] = useState("");
  const [quantity, setQuantity] = useState("");
  const [when, setWhen] = useState(todayLocalISO());
  const [decision, setDecision] = useState<{ is_supply: boolean | null; reason: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // WHETHER IT IS A SUPPLY IS ASKED OF THE SERVER, on every change of either
  // godown. Comparing the two GSTINs here would be a second implementation of
  // s.25(4) with Schedule I paragraph 2 — and it is the answer that decides
  // whether a tax invoice is owed.
  useEffect(() => {
    if (!from || !to || from === to) { setDecision(null); return; }
    let live = true;
    request<{ success: boolean; data: { is_supply: boolean | null; reason: string } }>(
      `/api/inventory/transfer-preview?client_id=${encodeURIComponent(clientId)}` +
      `&from_godown_id=${encodeURIComponent(from)}&to_godown_id=${encodeURIComponent(to)}`)
      .then((r) => { if (live && r.success) setDecision(r.data); })
      .catch(() => { if (live) setDecision(null); });
    return () => { live = false; };
  }, [clientId, from, to]);

  const items = Array.from(new Map(
    detail.filter((r) => r.godown_id === from)
      .map((r) => [r.service_catalogue_id, r.item_name])).entries());

  async function move() {
    setSaving(true); setError("");
    try {
      await request("/api/inventory/transfer", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId, service_catalogue_id: item,
          from_godown_id: from, to_godown_id: to,
          quantity, movement_date: when,
        }),
      });
      setQuantity("");
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't move the stock.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-50">
        <h3 className="text-sm font-semibold text-ps-ink flex items-center gap-2">
          <ArrowRightLeft size={15} className="text-blue-600" /> Move stock between godowns
        </h3>
      </div>
      <div className="px-5 py-4 space-y-3">
        {error && <Callout tone="problem">{error}</Callout>}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          <label className="text-xs">
            <span className="block text-ps-hint mb-1">From</span>
            <select value={from} onChange={(e) => setFrom(e.target.value)} className={INPUT}>
              {godowns.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </label>
          <label className="text-xs">
            <span className="block text-ps-hint mb-1">To</span>
            <select value={to} onChange={(e) => setTo(e.target.value)} className={INPUT}>
              {godowns.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </label>
          <label className="text-xs">
            <span className="block text-ps-hint mb-1">Item</span>
            <select value={item} onChange={(e) => setItem(e.target.value)} className={INPUT}>
              <option value="">Choose…</option>
              {items.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
          </label>
          <label className="text-xs">
            <span className="block text-ps-hint mb-1">Quantity</span>
            <input value={quantity} inputMode="decimal" onChange={(e) => setQuantity(e.target.value)}
              className={`${INPUT} text-right tabular-nums`} />
          </label>
          <label className="text-xs">
            <span className="block text-ps-hint mb-1">Date</span>
            <input type="date" value={when} onChange={(e) => setWhen(e.target.value)} className={INPUT} />
          </label>
        </div>

        {/* THE ANSWER THE CA HAS TO SEE BEFORE MOVING ANYTHING. */}
        {decision && (
          <div className={`rounded-lg px-3 py-2 text-xs flex gap-2 ${
            decision.is_supply === true ? "bg-state-attention-surface border border-state-attention-border text-amber-900"
            : decision.is_supply === false ? "bg-ps-bg border border-ps-border text-ps-body"
            : "bg-state-attention-surface border border-state-attention-border text-amber-900"}`}>
            <Info size={13} className="shrink-0 mt-0.5" />
            <span>{decision.reason}</span>
          </div>
        )}

        <div className="flex justify-end">
          <button onClick={move} disabled={saving || !item || !quantity || from === to}
            className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs disabled:opacity-40">
            Move stock
          </button>
        </div>
      </div>
    </div>
  );
}


function GodownModal({ clientId, onClose, onSaved }: {
  clientId: string; onClose: () => void; onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [address, setAddress] = useState("");
  const [stateCode, setStateCode] = useState("");
  const [gstin, setGstin] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true); setError("");
    try {
      await request("/api/inventory/godowns", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId, name: name.trim(), code: code.trim() || null,
          address: address.trim() || null, state_code: stateCode.trim() || null,
          gstin: gstin.trim().toUpperCase() || null, is_default: isDefault,
        }),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the godown.");
    } finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="bg-white rounded-xl w-full max-w-lg shadow-xl">
        <div className="px-5 py-4 border-b border-ps-muted">
          <h3 className="text-sm font-semibold text-ps-ink">New godown</h3>
        </div>
        <div className="px-5 py-4 space-y-3">
          {error && <Callout tone="problem">{error}</Callout>}
          <label className="block text-xs">
            <span className="block text-ps-hint mb-1">Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className={INPUT} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs">
              <span className="block text-ps-hint mb-1">Reference (optional)</span>
              <input value={code} onChange={(e) => setCode(e.target.value)} className={INPUT} />
            </label>
            <label className="block text-xs">
              <span className="block text-ps-hint mb-1">State code</span>
              <input value={stateCode} onChange={(e) => setStateCode(e.target.value)}
                placeholder="27" maxLength={2} className={INPUT} />
            </label>
          </div>
          <label className="block text-xs">
            <span className="block text-ps-hint mb-1">Address (optional)</span>
            <input value={address} onChange={(e) => setAddress(e.target.value)} className={INPUT} />
          </label>
          {/* WHICH REGISTRATION IT OPERATES UNDER. Needed only where the client
              holds several — and it is what decides whether a transfer out of
              this godown is a supply between distinct persons. */}
          <label className="block text-xs">
            <span className="block text-ps-hint mb-1">GST registration (optional)</span>
            <input value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())}
              className={`${INPUT} font-mono`} maxLength={15} />
            <span className="block text-3xs text-ps-hint mt-1">
              Only needed where this client holds more than one. Whether moving
              stock out of here is a supply depends on it.
            </span>
          </label>
          <label className="flex items-center gap-2 text-xs text-ps-body">
            <input type="checkbox" checked={isDefault}
              onChange={(e) => setIsDefault(e.target.checked)} />
            Stock movements default to this godown
          </label>
        </div>
        <div className="px-5 py-3 border-t border-ps-muted flex justify-end gap-2">
          <button onClick={onClose}
            className="px-3 py-1.5 rounded-lg border border-ps-border text-xs text-ps-label">
            Cancel
          </button>
          <button onClick={save} disabled={saving || !name.trim()}
            className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs disabled:opacity-40">
            Create
          </button>
        </div>
      </div>
    </div>
  );
}


function BatchModal({ clientId, items, onClose, onSaved }: {
  clientId: string; items: StockItem[]; onClose: () => void; onSaved: () => void;
}) {
  const [item, setItem] = useState("");
  const [batchNo, setBatchNo] = useState("");
  const [made, setMade] = useState("");
  const [expires, setExpires] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true); setError("");
    try {
      await request("/api/inventory/batches", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId, service_catalogue_id: item,
          batch_no: batchNo.trim(),
          manufactured_on: made || null,
          // LEFT NULL WHERE NOT TYPED, never defaulted: a batch with no date
          // is reported as having none, which is a different fact from stock
          // that does not expire.
          expiry_date: expires || null,
        }),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the lot.");
    } finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="bg-white rounded-xl w-full max-w-lg shadow-xl">
        <div className="px-5 py-4 border-b border-ps-muted">
          <h3 className="text-sm font-semibold text-ps-ink">New lot</h3>
        </div>
        <div className="px-5 py-4 space-y-3">
          {error && <Callout tone="problem">{error}</Callout>}
          <label className="block text-xs">
            <span className="block text-ps-hint mb-1">Item</span>
            <select value={item} onChange={(e) => setItem(e.target.value)} className={INPUT}>
              <option value="">Choose…</option>
              {items.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
            </select>
          </label>
          <label className="block text-xs">
            <span className="block text-ps-hint mb-1">Lot number</span>
            <input value={batchNo} onChange={(e) => setBatchNo(e.target.value)}
              placeholder="As printed on the carton" className={INPUT} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs">
              <span className="block text-ps-hint mb-1">Manufactured (optional)</span>
              <input type="date" value={made} onChange={(e) => setMade(e.target.value)} className={INPUT} />
            </label>
            <label className="block text-xs">
              <span className="block text-ps-hint mb-1">Expires (optional)</span>
              <input type="date" value={expires} onChange={(e) => setExpires(e.target.value)} className={INPUT} />
              <span className="block text-3xs text-ps-hint mt-1">
                Leave blank if this item does not expire.
              </span>
            </label>
          </div>
        </div>
        <div className="px-5 py-3 border-t border-ps-muted flex justify-end gap-2">
          <button onClick={onClose}
            className="px-3 py-1.5 rounded-lg border border-ps-border text-xs text-ps-label">
            Cancel
          </button>
          <button onClick={save} disabled={saving || !item || !batchNo.trim()}
            className="px-3 py-1.5 rounded-lg bg-blue-600 text-white text-xs disabled:opacity-40">
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
