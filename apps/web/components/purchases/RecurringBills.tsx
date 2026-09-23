"use client";

/**
 * Recurring purchase bills (PUR-26).
 *
 * The AP twin of the Sales tab's Recurring section. A template generates DRAFT
 * bills through the ordinary bill engine and never RECEIVES one — receiving is
 * what posts Dr Expense / Dr GST Input / Cr Trade Payables, withholds the TDS
 * and claims the credit, and that stays the CA's act.
 *
 * ZERO BUSINESS LOGIC HERE. The cadence, the catch-up, the idempotency and
 * every rupee are the server's (`services/recurring_purchase_bill_service.py`
 * over `domain/recurrence.py`). This screen collects what the CA decided and
 * renders what the server answered — including the "next dates" list, which is
 * fetched rather than computed, so the browser can never disagree with the job
 * that actually runs.
 */

import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, Clock, X, Trash2 } from "lucide-react";

import { apiCall, apiGet, getAuthToken } from "@/lib/invoices/shared";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { paiseFromRupeeInput, bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { formatPaise } from "@/lib/services/formatting";
import { TableSkeleton } from "@/components/ui/skeleton";
import { VendorLookup } from "@/components/lookups/VendorLookup";
import { EntityLookup } from "@/components/lookups/EntityLookup";
import { todayLocalISO } from "@/lib/dateMath";
import { Callout } from "@/components/ui/callout";

const FREQUENCIES = ["weekly", "monthly", "quarterly", "half_yearly", "yearly"] as const;
type Frequency = (typeof FREQUENCIES)[number];

const FREQUENCY_LABEL: Record<Frequency, string> = {
  weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly",
  half_yearly: "Half-yearly", yearly: "Yearly",
};

const STATUS_CHIP: Record<string, string> = {
  active: "bg-green-50 text-green-700",
  paused: "bg-state-attention-surface text-state-attention",
  archived: "bg-ps-muted text-ps-label",
};

export interface RecurringBillLine {
  id?: string;
  service_catalogue_id: string;
  description: string;
  hsn_sac: string | null;
  unit: string | null;
  quantity: number;
  rate_paise: number;
  gst_rate_bps: number;
  is_service: boolean;
  itc_eligible: boolean;
  blocked_credit_reason: string | null;
  tds_applicable: boolean;
  expense_account_id: string | null;
}

export interface RecurringBillTemplate {
  id: string;
  client_id: string;
  vendor_id: string;
  title: string;
  description: string | null;
  frequency: Frequency;
  start_date: string;
  end_date: string | null;
  next_run_date: string | null;
  notes: string | null;
  is_inter_state: boolean;
  is_reverse_charge: boolean;
  status: string;
  lines: RecurringBillLine[];
}

interface Vendor { id: string; name: string }
interface CatalogueItem { id: string; name: string; kind?: string | null }

/** Taxable value of a template, before tax — what the bill engine will charge on. */
function templateBase(lines: RecurringBillLine[]): number {
  return lines.reduce(
    (s, l) => s + Math.round((l.rate_paise || 0) * (l.quantity || 0)), 0);
}

function fmt(paise: number): string {
  return paise === 0 ? "—" : formatPaise(paise);
}

// ── The tab ──────────────────────────────────────────────────────────────────

export function RecurringBills({ clientId }: { clientId: string }) {
  const [templates, setTemplates] = useState<RecurringBillTemplate[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [catalogue, setCatalogue] = useState<CatalogueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [editor, setEditor] = useState<RecurringBillTemplate | "new" | null>(null);
  const [historyFor, setHistoryFor] = useState<RecurringBillTemplate | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const say = (type: "ok" | "err", text: string) => {
    setMsg({ type, text });
    setTimeout(() => setMsg(null), 6000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const token = await getAuthToken();
      const supabase = getSupabaseClient();
      const [tplRes, vendRes, catRes] = await Promise.all([
        apiGet(`/api/recurring-purchase-bills?client_id=${encodeURIComponent(clientId)}`, token),
        selectAll(() => supabase.from("vendors").select("id, name")
          .eq("client_id", clientId).eq("is_active", true).order("name").order("id")),
        selectAll(() => supabase.from("service_catalogue").select("id, name, kind")
          .eq("client_id", clientId).order("name").order("id")),
      ]);
      if (!tplRes.success) throw new Error(tplRes.error ?? "Could not load templates");
      setTemplates((tplRes.data as RecurringBillTemplate[]) ?? []);
      setVendors((vendRes.data as Vendor[]) ?? []);
      setCatalogue((catRes.data as CatalogueItem[]) ?? []);
    } catch {
      // A failed fetch must read as retryable, not as "no templates" — the
      // same rule the bills and payments tabs carry (audit M17).
      setTemplates([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  const vendorName = (id: string) => vendors.find((v) => v.id === id)?.name ?? "—";

  async function runNow(t: RecurringBillTemplate) {
    setBusy(t.id);
    try {
      const token = await getAuthToken();
      const res = await apiCall(`/api/recurring-purchase-bills/${t.id}/run`, "POST", undefined, token);
      if (!res.success) throw new Error(res.error ?? "Run failed");
      const d = res.data as { generated_count: number; skipped_count: number; failed_count: number };
      const parts = [`${d.generated_count} draft${d.generated_count === 1 ? "" : "s"} generated`];
      if (d.skipped_count) parts.push(`${d.skipped_count} already existed`);
      if (d.failed_count) parts.push(`${d.failed_count} failed — see History`);
      say(d.failed_count ? "err" : "ok", parts.join(", ")
        + ". Enter the supplier's own bill number on each draft before receiving it.");
      load();
    } catch (e) {
      say("err", e instanceof Error ? e.message : "Run failed");
    } finally {
      setBusy(null);
    }
  }

  /** Catch every template up at once — the same job the daily sweep runs, and
   *  what a CA opening this tab after a fortnight away actually wants. Scoped
   *  to this client; the server confines it further to the caller's own book. */
  async function runAllDue() {
    setBusy("all");
    try {
      const token = await getAuthToken();
      const res = await apiCall(
        `/api/recurring-purchase-bills/run?client_id=${encodeURIComponent(clientId)}`,
        "POST", undefined, token);
      if (!res.success) throw new Error(res.error ?? "Run failed");
      const d = res.data as { generated_count: number; skipped_count: number; failed_count: number };
      const parts = [`${d.generated_count} draft${d.generated_count === 1 ? "" : "s"} generated`];
      if (d.skipped_count) parts.push(`${d.skipped_count} already existed`);
      if (d.failed_count) parts.push(`${d.failed_count} failed — see History`);
      say(d.failed_count ? "err" : "ok", parts.join(", "));
      load();
    } catch (e) {
      say("err", e instanceof Error ? e.message : "Run failed");
    } finally {
      setBusy(null);
    }
  }

  async function changeStatus(t: RecurringBillTemplate, action: "pause" | "resume" | "archive") {
    setBusy(t.id);
    try {
      const token = await getAuthToken();
      // Each URL spelled out rather than built from `action`. It is one line
      // longer and it makes the three endpoints GREPPABLE — which is what
      // tests/test_every_mounted_endpoint_has_a_way_in.py can see, and its own
      // docstring names a verb held in a variable as the blind spot it cannot
      // cover. An endpoint that looks unreachable to that scan is one nobody
      // can prove a screen calls.
      const url =
        action === "pause" ? `/api/recurring-purchase-bills/${t.id}/pause`
        : action === "resume" ? `/api/recurring-purchase-bills/${t.id}/resume`
        : `/api/recurring-purchase-bills/${t.id}/archive`;
      const res = await apiCall(url, "POST", undefined, token);
      if (!res.success) throw new Error(res.error ?? "Update failed");
      say("ok", `Template ${action === "resume" ? "resumed" : `${action}d`}`);
      load();
    } catch (e) {
      say("err", e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {msg && (
        <div className={`rounded-lg px-3 py-2 text-xs ${msg.type === "ok"
          ? "bg-green-50 text-green-700 border border-green-200"
          : "bg-state-problem-surface text-state-problem border border-state-problem-border"}`}>
          {msg.text}
        </div>
      )}

      {editor && (
        <RecurringBillEditor
          clientId={clientId}
          vendors={vendors}
          catalogue={catalogue}
          existing={editor === "new" ? null : editor}
          onClose={() => setEditor(null)}
          onSaved={(text) => { setEditor(null); say("ok", text); load(); }}
        />
      )}
      {historyFor && (
        <RecurringBillHistory
          template={historyFor}
          vendorName={vendorName(historyFor.vendor_id)}
          onClose={() => setHistoryFor(null)}
        />
      )}

      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-ps-body">
            {templates.length} template{templates.length !== 1 ? "s" : ""}
          </p>
          <p className="text-2xs text-ps-hint mt-0.5">
            Rent, retainers, utilities. Each generates a <strong>draft</strong> bill for
            review — never received, never posted. The supplier&apos;s own bill number is
            left blank for you to enter.
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <button onClick={load} aria-label="Reload templates"
            className="p-1.5 rounded border border-ps-border hover:bg-ps-bg text-ps-label">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          {templates.some((t) => t.status === "active") && (
            <button onClick={runAllDue} disabled={busy === "all"}
              className="text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg disabled:opacity-40">
              {busy === "all" ? "Generating…" : "Generate all due"}
            </button>
          )}
          <button onClick={() => setEditor("new")}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
            <Plus size={12} /> New Template
          </button>
        </div>
      </div>

      {loading ? (
        <TableSkeleton cols={7} rows={3} />
      ) : loadFailed ? (
        <div className="bg-white rounded-xl border border-state-problem-border text-center py-12">
          <p className="text-sm text-state-problem">Could not load recurring templates.</p>
          <button onClick={load} className="mt-2 text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg">
            Try again
          </button>
        </div>
      ) : templates.length === 0 ? (
        <div className="bg-white rounded-xl border border-ps-muted text-center py-16">
          <Clock size={32} className="text-gray-200 mx-auto mb-3" />
          <p className="text-sm text-ps-label">No recurring bills yet</p>
          <p className="text-xs text-ps-hint mt-1">
            Set one up for the rent or a monthly retainer and the draft appears on schedule.
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-ps-bg text-3xs uppercase tracking-wide text-ps-hint">
                <tr>
                  <th className="text-left font-medium px-3 py-2">Template</th>
                  <th className="text-left font-medium px-3 py-2">Vendor</th>
                  <th className="text-left font-medium px-3 py-2">Every</th>
                  <th className="text-left font-medium px-3 py-2">Next</th>
                  <th className="text-right font-medium px-3 py-2">Taxable</th>
                  <th className="text-left font-medium px-3 py-2">Status</th>
                  <th className="text-right font-medium px-3 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {templates.map((t) => (
                  <tr key={t.id} className="border-t border-ps-bg">
                    <td className="px-3 py-2">
                      <p className="font-medium text-ps-ink">{t.title}</p>
                      {t.description && <p className="text-3xs text-ps-hint">{t.description}</p>}
                    </td>
                    <td className="px-3 py-2 text-ps-label">{vendorName(t.vendor_id)}</td>
                    <td className="px-3 py-2 text-ps-label">{FREQUENCY_LABEL[t.frequency] ?? t.frequency}</td>
                    <td className="px-3 py-2 text-ps-label tabular-nums">
                      {t.status === "active" ? (t.next_run_date ?? "—") : "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-ps-ink">
                      {fmt(templateBase(t.lines ?? []))}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`px-2 py-0.5 rounded-full text-3xs font-medium ${STATUS_CHIP[t.status] ?? ""}`}>
                        {t.status}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-1.5 flex-wrap">
                        {t.status === "active" && (
                          <button onClick={() => runNow(t)} disabled={busy === t.id}
                            className="text-2xs px-2 py-1 border border-ps-border rounded-md hover:bg-ps-bg disabled:opacity-40">
                            Generate now
                          </button>
                        )}
                        <button onClick={() => setHistoryFor(t)}
                          className="text-2xs px-2 py-1 border border-ps-border rounded-md hover:bg-ps-bg">
                          History
                        </button>
                        {t.status !== "archived" && (
                          <button onClick={() => setEditor(t)}
                            className="text-2xs px-2 py-1 border border-ps-border rounded-md hover:bg-ps-bg">
                            Edit
                          </button>
                        )}
                        {t.status === "active" && (
                          <button onClick={() => changeStatus(t, "pause")} disabled={busy === t.id}
                            className="text-2xs px-2 py-1 border border-ps-border rounded-md hover:bg-ps-bg disabled:opacity-40">
                            Pause
                          </button>
                        )}
                        {t.status === "paused" && (
                          <button onClick={() => changeStatus(t, "resume")} disabled={busy === t.id}
                            className="text-2xs px-2 py-1 border border-ps-border rounded-md hover:bg-ps-bg disabled:opacity-40">
                            Resume
                          </button>
                        )}
                        {t.status !== "archived" && (
                          <button onClick={() => changeStatus(t, "archive")} disabled={busy === t.id}
                            className="text-2xs px-2 py-1 border border-state-problem-border text-red-600 rounded-md hover:bg-state-problem-surface disabled:opacity-40">
                            Archive
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Editor ───────────────────────────────────────────────────────────────────

interface DraftLine {
  service_catalogue_id: string;
  description: string;
  hsn_sac: string;
  unit: string;
  quantity: string;
  rate: string;              // rupees, as typed
  gst_rate: string;          // percent, as typed
  is_service: boolean;
  itc_eligible: boolean;
  blocked_credit_reason: string;
  tds_applicable: boolean;
}

function blankLine(): DraftLine {
  return {
    service_catalogue_id: "", description: "", hsn_sac: "", unit: "",
    quantity: "1", rate: "", gst_rate: "18", is_service: false,
    itc_eligible: true, blocked_credit_reason: "", tds_applicable: false,
  };
}

function paiseToRupeeText(paise: number): string {
  // Integer division and remainder, never a float divide — see
  // lib/money/rupeeInput for why a rupee amount is never round-tripped
  // through a float.
  const n = Math.abs(Math.trunc(paise));
  return `${paise < 0 ? "-" : ""}${Math.trunc(n / 100)}.${String(n % 100).padStart(2, "0")}`;
}

function RecurringBillEditor({
  clientId, vendors, catalogue, existing, onClose, onSaved,
}: {
  clientId: string;
  vendors: Vendor[];
  catalogue: CatalogueItem[];
  existing: RecurringBillTemplate | null;
  onClose: () => void;
  onSaved: (msg: string) => void;
}) {
  const [vendorId, setVendorId] = useState(existing?.vendor_id ?? "");
  const [title, setTitle] = useState(existing?.title ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [frequency, setFrequency] = useState<Frequency>(existing?.frequency ?? "monthly");
  const [startDate, setStartDate] = useState(existing?.start_date ?? todayLocalISO());
  const [endDate, setEndDate] = useState(existing?.end_date ?? "");
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [interState, setInterState] = useState(Boolean(existing?.is_inter_state));
  const [reverseCharge, setReverseCharge] = useState(Boolean(existing?.is_reverse_charge));
  const [lines, setLines] = useState<DraftLine[]>(
    existing?.lines?.length
      ? existing.lines.map((l) => ({
          service_catalogue_id: l.service_catalogue_id ?? "",
          description: l.description ?? "",
          hsn_sac: l.hsn_sac ?? "",
          unit: l.unit ?? "",
          quantity: String(l.quantity ?? 1),
          rate: paiseToRupeeText(l.rate_paise ?? 0),
          gst_rate: String((l.gst_rate_bps ?? 1800) / 100),
          is_service: Boolean(l.is_service),
          itc_eligible: l.itc_eligible !== false,
          blocked_credit_reason: l.blocked_credit_reason ?? "",
          tds_applicable: Boolean(l.tds_applicable),
        }))
      : [blankLine()]
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function setLine(i: number, patch: Partial<DraftLine>) {
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  }

  async function save() {
    setErr(null);
    if (!vendorId) { setErr("Choose the vendor this bill comes from."); return; }
    if (!title.trim()) { setErr("Give the template a name — you will pick it out of a list."); return; }
    if (endDate && endDate < startDate) { setErr("The end date cannot be before the start date."); return; }

    const payloadLines = [];
    // Indexed loop rather than `.entries()`: the tsconfig target predates
    // downlevelIteration and an iterator over a tuple will not compile.
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (!l.service_catalogue_id) {
        setErr(`Line ${i + 1}: choose the product or service. A bill the engine `
          + `would refuse cannot be generated unattended.`);
        return;
      }
      const ratePaise = paiseFromRupeeInput(l.rate || "0");
      if (ratePaise === null) {
        setErr(`Line ${i + 1}: the rate must be a number of rupees, e.g. 50000 or 50000.50 — without commas.`);
        return;
      }
      const gstBps = bpsFromPercentInput(l.gst_rate || "0");
      if (gstBps === null) {
        setErr(`Line ${i + 1}: the GST rate must be a percentage, e.g. 18 or 12.5.`);
        return;
      }
      const qty = Number(l.quantity);
      if (!Number.isFinite(qty) || qty <= 0) {
        setErr(`Line ${i + 1}: quantity must be a positive number.`);
        return;
      }
      payloadLines.push({
        service_catalogue_id: l.service_catalogue_id,
        description: l.description || "",
        hsn_sac: l.hsn_sac || undefined,
        unit: l.unit || undefined,
        quantity: qty,
        rate_paise: ratePaise,
        gst_rate_percent: gstBps / 100,
        is_service: l.is_service,
        itc_eligible: l.itc_eligible,
        blocked_credit_reason: l.itc_eligible ? undefined : (l.blocked_credit_reason || undefined),
        tds_applicable: l.tds_applicable,
      });
    }

    setSaving(true);
    try {
      const token = await getAuthToken();
      const body = {
        client_id: clientId,
        vendor_id: vendorId,
        title: title.trim(),
        description: description || undefined,
        frequency,
        start_date: startDate,
        end_date: endDate || undefined,
        notes: notes || undefined,
        is_inter_state: interState,
        is_reverse_charge: reverseCharge,
        lines: payloadLines,
      };
      const res = existing
        ? await apiCall(`/api/recurring-purchase-bills/${existing.id}`, "PUT", body, token)
        : await apiCall(`/api/recurring-purchase-bills`, "POST", body, token);
      if (!res.success) throw new Error(res.error ?? "Save failed");
      onSaved(existing ? "Template updated" : "Template created");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-start justify-center overflow-y-auto p-4">
      <div className="bg-white rounded-xl w-full max-w-4xl my-8 shadow-xl">
        <div className="flex items-center justify-between px-5 py-3 border-b border-ps-muted">
          <h3 className="text-sm font-semibold text-ps-ink">
            {existing ? "Edit recurring bill" : "New recurring bill"}
          </h3>
          <button onClick={onClose} aria-label="Close"><X size={16} className="text-ps-hint" /></button>
        </div>

        <div className="p-5 space-y-4">
          {err && <Callout tone="problem">{err}</Callout>}

          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            <div className="col-span-2 lg:col-span-1">
              <label className="block text-xs font-medium text-ps-label mb-1">Vendor *</label>
              <VendorLookup vendors={vendors} value={vendorId} onChange={setVendorId} ariaLabel="Vendor" />
            </div>
            <div className="col-span-2 lg:col-span-2">
              <label className="block text-xs font-medium text-ps-label mb-1">Name *</label>
              <input value={title} onChange={(e) => setTitle(e.target.value)}
                placeholder="Office rent — Andheri"
                className="w-full px-3 py-1.5 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Every *</label>
              <select value={frequency} onChange={(e) => setFrequency(e.target.value as Frequency)}
                className="w-full px-3 py-1.5 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                {FREQUENCIES.map((f) => <option key={f} value={f}>{FREQUENCY_LABEL[f]}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">First bill on *</label>
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
                className="w-full px-3 py-1.5 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-ps-label mb-1">Stop after (optional)</label>
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
                className="w-full px-3 py-1.5 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div className="col-span-2 lg:col-span-3 flex flex-wrap gap-4 pt-1">
              <label className="flex items-center gap-2 text-xs text-ps-label">
                <input type="checkbox" checked={interState} onChange={(e) => setInterState(e.target.checked)} />
                Inter-state supply (IGST)
              </label>
              <label className="flex items-center gap-2 text-xs text-ps-label">
                <input type="checkbox" checked={reverseCharge} onChange={(e) => setReverseCharge(e.target.checked)} />
                Reverse charge — CGST §9(3)/(4)
              </label>
            </div>
          </div>

          <div className="border border-ps-muted rounded-lg">
            <div className="flex items-center justify-between px-3 py-2 border-b border-ps-muted bg-ps-bg rounded-t-lg">
              <p className="text-xs font-semibold text-ps-body">Lines</p>
              <button type="button" onClick={() => setLines((ls) => [...ls, blankLine()])}
                className="text-2xs px-2.5 py-1 border border-ps-border bg-white rounded-md hover:bg-ps-muted">
                <Plus size={11} className="inline mr-1" />Add line
              </button>
            </div>
            <div className="divide-y divide-ps-bg">
              {lines.map((l, i) => (
                <div key={i} className="p-3 space-y-2">
                  <div className="grid grid-cols-2 lg:grid-cols-6 gap-2">
                    <div className="col-span-2">
                      <label className="block text-3xs text-ps-hint mb-1">Product / Service *</label>
                      <EntityLookup
                        items={catalogue}
                        value={l.service_catalogue_id}
                        onChange={(id) => setLine(i, { service_catalogue_id: id })}
                        getId={(c) => c.id}
                        getLabel={(c) => c.name}
                        getSearchFields={(c) => [c.name]}
                        placeholder="— Choose —"
                        ariaLabel={`Product or service for line ${i + 1}`}
                      />
                    </div>
                    <div className="col-span-2">
                      <label className="block text-3xs text-ps-hint mb-1">Description</label>
                      <input value={l.description} onChange={(e) => setLine(i, { description: e.target.value })}
                        className="w-full px-2 py-1 text-xs border border-ps-border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                    <div>
                      <label className="block text-3xs text-ps-hint mb-1">Qty</label>
                      <input value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })}
                        inputMode="decimal"
                        className="w-full px-2 py-1 text-xs border border-ps-border rounded-md text-right font-mono focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                    <div>
                      <label className="block text-3xs text-ps-hint mb-1">Rate (₹)</label>
                      <input value={l.rate} onChange={(e) => setLine(i, { rate: e.target.value })}
                        inputMode="decimal" placeholder="0.00"
                        className="w-full px-2 py-1 text-xs border border-ps-border rounded-md text-right font-mono focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                    <div>
                      <label className="block text-3xs text-ps-hint mb-1">GST %</label>
                      <input value={l.gst_rate} onChange={(e) => setLine(i, { gst_rate: e.target.value })}
                        inputMode="decimal"
                        className="w-full px-2 py-1 text-xs border border-ps-border rounded-md text-right font-mono focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                    <div>
                      <label className="block text-3xs text-ps-hint mb-1">HSN / SAC</label>
                      <input value={l.hsn_sac} onChange={(e) => setLine(i, { hsn_sac: e.target.value })}
                        className="w-full px-2 py-1 text-xs border border-ps-border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                    <div>
                      <label className="block text-3xs text-ps-hint mb-1">Unit</label>
                      <input value={l.unit} onChange={(e) => setLine(i, { unit: e.target.value })}
                        placeholder="NOS"
                        className="w-full px-2 py-1 text-xs border border-ps-border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-4">
                    <label className="flex items-center gap-2 text-2xs text-ps-label">
                      <input type="checkbox" checked={l.is_service}
                        onChange={(e) => setLine(i, { is_service: e.target.checked })} />
                      Service
                    </label>
                    <label className="flex items-center gap-2 text-2xs text-ps-label">
                      <input type="checkbox" checked={l.tds_applicable}
                        onChange={(e) => setLine(i, { tds_applicable: e.target.checked })} />
                      TDS applies
                    </label>
                    <label className="flex items-center gap-2 text-2xs text-ps-label">
                      <input type="checkbox" checked={!l.itc_eligible}
                        onChange={(e) => setLine(i, { itc_eligible: !e.target.checked })} />
                      Credit blocked — CGST §17(5)
                    </label>
                    {!l.itc_eligible && (
                      <input value={l.blocked_credit_reason}
                        onChange={(e) => setLine(i, { blocked_credit_reason: e.target.value })}
                        placeholder="Which clause of §17(5)?"
                        className="flex-1 min-w-[12rem] px-2 py-1 text-xs border border-ps-border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    )}
                    {lines.length > 1 && (
                      <button type="button" aria-label={`Remove line ${i + 1}`}
                        onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
                        className="ml-auto text-red-500 hover:text-state-problem">
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-ps-label mb-1">Description</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder="What this template is for — shown in the list, not on the bill"
              className="w-full px-3 py-1.5 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <div>
            <label className="block text-xs font-medium text-ps-label mb-1">Notes on every generated bill</label>
            <input value={notes} onChange={(e) => setNotes(e.target.value)}
              placeholder="Left on each draft — e.g. the lease reference"
              className="w-full px-3 py-1.5 text-sm border border-ps-border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <p className="text-2xs text-ps-hint">
            Generated bills are <strong>drafts</strong>. The supplier&apos;s own bill number is
            left blank — enter it before you receive the bill, because receiving is what posts
            the journal, withholds the TDS and claims the credit.
          </p>
        </div>

        <div className="flex gap-3 justify-end px-5 py-3 border-t border-ps-muted">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-ps-border rounded-lg hover:bg-ps-bg">
            Cancel
          </button>
          <button onClick={save} disabled={saving}
            className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Saving…" : existing ? "Save changes" : "Create template"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── History ──────────────────────────────────────────────────────────────────

interface RunRow {
  id: string;
  occurrence_date: string;
  status: string;
  detail: unknown;
  bill: { id?: string; bill_no?: string | null; our_reference?: string | null;
          status?: string | null; total_paise?: number | null } | null;
}

function RecurringBillHistory({
  template, vendorName, onClose,
}: { template: RecurringBillTemplate; vendorName: string; onClose: () => void }) {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [upcoming, setUpcoming] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = await getAuthToken();
        const [h, p] = await Promise.all([
          apiGet(`/api/recurring-purchase-bills/${template.id}/history`, token),
          // FETCHED, never computed here: the browser must not hold a second
          // opinion about which dates the job will pick.
          apiGet(`/api/recurring-purchase-bills/${template.id}/preview?count=5`, token),
        ]);
        if (cancelled) return;
        setRuns((h.data as RunRow[]) ?? []);
        setUpcoming(((p.data as { occurrences?: string[] } | null)?.occurrences) ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [template.id]);

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-start justify-end">
      <div className="bg-white h-full w-full max-w-lg shadow-xl overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b border-ps-muted sticky top-0 bg-white">
          <div>
            <h3 className="text-sm font-semibold text-ps-ink">{template.title}</h3>
            <p className="text-2xs text-ps-hint">{vendorName}</p>
          </div>
          <button onClick={onClose} aria-label="Close"><X size={16} className="text-ps-hint" /></button>
        </div>

        <div className="p-5 space-y-5">
          <div>
            <p className="text-xs font-semibold text-ps-body mb-2">Next dates</p>
            {upcoming.length === 0 ? (
              <p className="text-2xs text-ps-hint">Nothing further scheduled.</p>
            ) : (
              <ul className="text-xs text-ps-label space-y-1">
                {upcoming.map((d) => <li key={d} className="tabular-nums">{d}</li>)}
              </ul>
            )}
          </div>

          <div>
            <p className="text-xs font-semibold text-ps-body mb-2">Generated so far</p>
            {loading ? (
              <TableSkeleton cols={3} rows={3} />
            ) : runs.length === 0 ? (
              <p className="text-2xs text-ps-hint">Nothing generated yet.</p>
            ) : (
              <table className="w-full text-xs">
                <thead className="text-3xs uppercase tracking-wide text-ps-hint">
                  <tr>
                    <th className="text-left font-medium py-1">Occurrence</th>
                    <th className="text-left font-medium py-1">Bill</th>
                    <th className="text-right font-medium py-1">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.id} className="border-t border-ps-bg">
                      <td className="py-1.5 tabular-nums text-ps-label">{r.occurrence_date}</td>
                      <td className="py-1.5 text-ps-ink">
                        {r.status === "failed" ? (
                          <span className="text-red-600">
                            Failed{r.detail ? ` — ${String((r.detail as { error?: string })?.error ?? "")}` : ""}
                          </span>
                        ) : (
                          <>
                            {r.bill?.bill_no || r.bill?.our_reference || "—"}
                            <span className="ml-1 text-3xs text-ps-hint">{r.bill?.status ?? ""}</span>
                          </>
                        )}
                      </td>
                      <td className="py-1.5 text-right tabular-nums text-ps-label">
                        {r.bill?.total_paise ? fmt(Number(r.bill.total_paise)) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
