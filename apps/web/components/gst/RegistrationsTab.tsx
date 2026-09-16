"use client";

/**
 * The GST registrations a client holds (GST-20).
 *
 * WHAT WAS MISSING
 *   `clients.gstin` held exactly one, and both return tables were
 *   UNIQUE (client_id, period) — so a client registered in more than one state
 *   could not hold both registrations' returns whatever the code did. CGST Act
 *   s.25(1) requires registration in EVERY State or Union territory from which
 *   a taxable supply is made and s.25(2)'s proviso allows one per place of
 *   business, so a manufacturer with a depot, a services firm with two offices
 *   or an e-commerce seller holding warehouse-state registrations is an
 *   ordinary client, not an edge case. The CA's only route was a second fake
 *   "client" per GSTIN, which splits ONE entity's accounting across two
 *   ledgers and breaks every client-scoped report.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Whether a GSTIN is well formed,
 * which state it belongs to, whether the client already holds it and which
 * registration types file GSTR-1 and GSTR-3B at all are
 * `domain/gst/registrations.py`'s answers, served by
 * /api/client-gst-registrations.
 */
import { useCallback, useEffect, useState } from "react";
import { Plus, AlertTriangle, X, Info } from "lucide-react";
import { api, type ClientGstRegistration, type GstRegistrationKinds } from "@/lib/api";
import { confirmDialog } from "@/components/ui/confirm-dialog";

type Msg = { type: "ok" | "err"; text: string } | null;

const BLANK = {
  gstin: "",
  registration_type: "regular",
  filing_frequency: "monthly",
  trade_name: "",
  effective_from: "",
};

/** Underscores out, first letter up — the same derivation the day book uses on
 *  a journal source, rather than a label map that would be a second copy of
 *  the server's list. */
function pretty(value: string): string {
  const spaced = value.replace(/_/g, " ").trim();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : value;
}

export default function RegistrationsTab({ clientId }: { clientId: string }) {
  const [rows, setRows] = useState<ClientGstRegistration[]>([]);
  const [kinds, setKinds] = useState<GstRegistrationKinds | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  /** Which registration is having its s.29 end date recorded, and the date so
   *  far. A real date control rather than a text prompt: the column is a DATE
   *  and a typed "31/03/2027" reaches the server as a 400 the CA cannot act on. */
  const [closing, setClosing] = useState<{ id: string; on: string } | null>(null);
  const [msg, setMsg] = useState<Msg>(null);

  const busy = saving || busyId !== null;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.clientGstRegistrations.list(clientId);
      if (!res.success || !res.data) throw new Error(res.error ?? "Couldn't read the registrations.");
      setRows(res.data);
      setLoadFailed(false);
    } catch {
      // Not swallowed into an empty list: on this tab "none" reads as an
      // invitation to add the primary a second time.
      setRows([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    let alive = true;
    api.clientGstRegistrations.kinds()
      .then((r) => { if (alive && r.success && r.data) setKinds(r.data); })
      .catch(() => { /* the pickers fall back to what is already selected */ });
    return () => { alive = false; };
  }, []);

  async function handleSave() {
    setSaving(true);
    setMsg(null);
    try {
      const res = await api.clientGstRegistrations.create({
        client_id: clientId,
        gstin: form.gstin.trim().toUpperCase(),
        registration_type: form.registration_type,
        filing_frequency: form.filing_frequency,
        trade_name: form.trade_name.trim() || null,
        effective_from: form.effective_from || null,
      });
      if (!res.success) throw new Error(res.error ?? "Couldn't add the registration.");
      setShowForm(false);
      setForm(BLANK);
      setMsg({ type: "ok", text: "Registration added. Its returns are prepared separately." });
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't add the registration." });
    } finally {
      setSaving(false);
    }
  }

  async function handleClose(r: ClientGstRegistration, on: string) {
    if (!on) return;
    setBusyId(r.id ?? null);
    setMsg(null);
    try {
      const res = await api.clientGstRegistrations.close(r.id as string, clientId, on);
      if (!res.success) throw new Error(res.error ?? "Couldn't record the cancellation.");
      setClosing(null);
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't record the cancellation." });
    } finally {
      setBusyId(null);
    }
  }

  async function handleWithdraw(r: ClientGstRegistration) {
    const ok = await confirmDialog({
      title: `Remove ${r.gstin}?`,
      message: "Only for a registration recorded in error. If it was real and has "
             + "ended, record the cancellation date instead — the returns for the "
             + "periods it was live are still owed.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    setBusyId(r.id ?? null);
    setMsg(null);
    try {
      const res = await api.clientGstRegistrations.remove(r.id as string, clientId);
      if (!res.success) throw new Error(res.error ?? "Couldn't remove the registration.");
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Couldn't remove the registration." });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-[#0F172A]">GST registrations</h2>
          <p className="text-[11px] text-[#64748B] mt-1 max-w-2xl">
            One client, one legal person — and as many GSTINs as it is registered
            under. CGST Act s.25(1) makes registration state-wise and s.25(2)
            allows one per place of business, so each registration prepares and
            files its own GSTR-1 and GSTR-3B. The primary is the GSTIN on the
            client record; add the rest here.
          </p>
        </div>
        <button onClick={() => { setForm(BLANK); setShowForm(true); }} disabled={busy}
          className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5">
          <Plus size={13} /> Add a registration
        </button>
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
          <span>The registrations could not be read, so this list is not the whole of them. Reload before adding one.</span>
        </div>
      )}

      {loading ? (
        <p className="text-xs text-[#94A3B8]">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-[#94A3B8]">
          No GSTIN is recorded for this client. Record it on the client record first —
          a GST return cannot be prepared without one.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-left">
                <th className="py-2 font-semibold">GSTIN</th>
                <th className="py-2 font-semibold">State</th>
                <th className="py-2 font-semibold">Type</th>
                <th className="py-2 font-semibold">Frequency</th>
                <th className="py-2 font-semibold">Status</th>
                <th className="py-2 font-semibold" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {rows.map((r) => (
                <tr key={r.gstin} className="align-top">
                  <td className="py-2">
                    <span className="font-mono text-[#1E293B]">{r.gstin}</span>
                    {r.trade_name && (
                      <span className="block text-[10px] text-[#64748B]">{r.trade_name}</span>
                    )}
                    {/* The primary is the client record's own GSTIN, so it is
                        shown and never editable here. */}
                    {r.is_primary && (
                      <span className="inline-block mt-0.5 px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 text-[10px]">
                        Primary
                      </span>
                    )}
                  </td>
                  <td className="py-2 font-mono text-[#64748B]">{r.state_code}</td>
                  <td className="py-2">
                    {pretty(r.registration_type)}
                    {/* A registration that files a DIFFERENT form says which
                        one — offering it a GSTR-3B screen offers a return it
                        must not file. */}
                    {r.other_return_form && (
                      <span className="block text-[10px] text-amber-800 max-w-xs flex gap-1 mt-0.5">
                        <Info size={10} className="shrink-0 mt-0.5" />{r.other_return_form}
                      </span>
                    )}
                  </td>
                  <td className="py-2">{pretty(r.filing_frequency)}</td>
                  <td className="py-2">
                    {r.effective_to
                      ? <span className="text-[#64748B]">
                          Cancelled {String(r.effective_to).slice(0, 10)}
                          {/* s.29: a cancelled registration still owes the returns
                              for every period it was live, so it stays listed. */}
                          <span className="block text-[10px] text-[#94A3B8]">
                            Returns for the periods it was live are still owed
                          </span>
                        </span>
                      : <span className="text-emerald-700">Active</span>}
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">
                    {!r.is_primary && (
                      <>
                        {!r.effective_to && closing?.id !== r.id && (
                          <button onClick={() => setClosing({ id: r.id as string, on: "" })}
                            disabled={busy}
                            className="px-2 py-1 text-[11px] border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] disabled:opacity-40">
                            Cancelled…
                          </button>
                        )}
                        {closing?.id === r.id && (
                          <span className="inline-flex items-center gap-1">
                            <input type="date" value={closing.on} autoFocus
                              aria-label={`Date ${r.gstin} was cancelled or surrendered`}
                              onChange={(e) => setClosing({ id: r.id as string, on: e.target.value })}
                              className="px-1.5 py-1 text-[11px] border border-[#E2E8F0] rounded" />
                            <button onClick={() => handleClose(r, closing.on)}
                              disabled={busy || !closing.on}
                              className="px-2 py-1 text-[11px] bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-40">
                              Record
                            </button>
                            <button onClick={() => setClosing(null)} disabled={busy}
                              className="px-1.5 py-1 text-[11px] text-[#94A3B8] hover:text-[#334155]">
                              Cancel
                            </button>
                          </span>
                        )}
                        <button onClick={() => handleWithdraw(r)} disabled={busy}
                          className="ml-1 px-2 py-1 text-[11px] text-[#94A3B8] hover:text-red-600 disabled:opacity-40">
                          Remove
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/20">
          <div className="w-full max-w-md h-full bg-white shadow-xl flex flex-col">
            <div className="px-5 py-4 border-b border-[#F1F5F9] flex items-center justify-between">
              <p className="text-sm font-semibold text-[#0F172A]">Add a GST registration</p>
              <button onClick={() => setShowForm(false)} aria-label="Close"
                className="p-1 rounded hover:bg-[#F1F5F9] text-[#64748B]"><X size={16} /></button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              <label className="text-xs block">
                <span className="block text-[#334155] font-medium mb-1">GSTIN *</span>
                <input value={form.gstin} maxLength={15}
                  onChange={(e) => setForm(f => ({ ...f, gstin: e.target.value.toUpperCase() }))}
                  placeholder="29AABCU9603R1ZJ"
                  className="w-full px-2.5 py-1.5 border border-[#E2E8F0] rounded-lg font-mono" />
                <span className="block text-[10px] text-[#94A3B8] mt-1 leading-tight">
                  The state is the GSTIN&apos;s own first two characters and is not asked
                  for separately — a registration is state-wise.
                </span>
              </label>

              <label className="text-xs block">
                <span className="block text-[#334155] font-medium mb-1">Registration type</span>
                <select value={form.registration_type}
                  onChange={(e) => setForm(f => ({ ...f, registration_type: e.target.value }))}
                  className="w-full px-2.5 py-1.5 border border-[#E2E8F0] rounded-lg">
                  {(kinds?.registration_types ?? [{ value: form.registration_type, files_gstr1_and_3b: true, other_return_form: null }])
                    .map((t) => (
                      <option key={t.value} value={t.value}>{pretty(t.value)}</option>
                    ))}
                </select>
                {(() => {
                  const chosen = kinds?.registration_types?.find(t => t.value === form.registration_type);
                  return chosen?.other_return_form ? (
                    <span className="block text-[10px] text-amber-800 mt-1 leading-tight">
                      {chosen.other_return_form} — which this product does not build, so
                      no GSTR-1 or GSTR-3B will be prepared for it.
                    </span>
                  ) : null;
                })()}
              </label>

              <label className="text-xs block">
                <span className="block text-[#334155] font-medium mb-1">Filing frequency</span>
                <select value={form.filing_frequency}
                  onChange={(e) => setForm(f => ({ ...f, filing_frequency: e.target.value }))}
                  className="w-full px-2.5 py-1.5 border border-[#E2E8F0] rounded-lg">
                  {(kinds?.filing_frequencies ?? [form.filing_frequency]).map((v) => (
                    <option key={v} value={v}>{pretty(v)}</option>
                  ))}
                </select>
              </label>

              <label className="text-xs block">
                <span className="block text-[#334155] font-medium mb-1">Trade name</span>
                <input value={form.trade_name}
                  onChange={(e) => setForm(f => ({ ...f, trade_name: e.target.value }))}
                  placeholder="Bengaluru depot"
                  className="w-full px-2.5 py-1.5 border border-[#E2E8F0] rounded-lg" />
                <span className="block text-[10px] text-[#94A3B8] mt-1 leading-tight">
                  Two registrations in one state are told apart only by this.
                </span>
              </label>

              <label className="text-xs block">
                <span className="block text-[#334155] font-medium mb-1">Registered from</span>
                <input type="date" value={form.effective_from}
                  onChange={(e) => setForm(f => ({ ...f, effective_from: e.target.value }))}
                  className="w-full px-2.5 py-1.5 border border-[#E2E8F0] rounded-lg" />
              </label>
            </div>

            <div className="px-5 py-3 border-t border-[#F1F5F9] flex justify-end gap-2">
              <button onClick={() => setShowForm(false)}
                className="px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">
                Cancel
              </button>
              <button onClick={handleSave} disabled={saving || !form.gstin.trim()}
                className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                {saving ? "Adding…" : "Add"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
