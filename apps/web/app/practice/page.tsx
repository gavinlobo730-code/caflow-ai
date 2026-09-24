"use client";

import { useState, useEffect, useCallback } from "react";
import { Building2, RefreshCw, IndianRupee, AlertTriangle, Wallet, ReceiptText, Loader2 } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { PartnerGuard } from "@/components/practice/PartnerGuard";

/** What the practice client's own tax identity is, as the server holds it. */
interface PracticeIdentity {
  pan: string | null;
  gstin: string | null;
  state: string | null;
  state_code: string | null;
}

/**
 * The firm's OWN tax identity, on the client it raises its own fee invoices
 * from.
 *
 * `PATCH /api/practice/identity` has existed since Phase 3.3A — Partner-only,
 * validating PAN and GSTIN, deriving the state code, audit-logged — and NO
 * SCREEN CALLED IT, so the practice client's identifiers were frozen at
 * whatever provisioning copied off `firms` at the moment it ran. A firm that
 * corrected its GSTIN in Settings afterwards (which writes `firms`, migration
 * 399) left this one carrying the old number, and CGST Rule 46(a) puts the
 * SUPPLIER's GSTIN on every fee invoice raised from it.
 *
 * IT DECIDES NOTHING. The PAN and GSTIN formats, the check digit and the
 * state-code derivation are all `models/client.PracticeIdentityUpdate` and
 * `core/validators`; this sends what was typed and renders what comes back.
 * Fields left blank are left ALONE — the endpoint treats `None` as unchanged,
 * which is what lets a Partner correct one identifier without re-typing the
 * others.
 */
function TaxIdentity({ identity, onSaved }: {
  identity: PracticeIdentity | null; onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [pan, setPan] = useState("");
  const [gstin, setGstin] = useState("");
  const [state, setState] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function start() {
    setPan(identity?.pan ?? "");
    setGstin(identity?.gstin ?? "");
    setState(identity?.state ?? "");
    setError(null);
    setOpen(true);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      // Only what CHANGED. The endpoint reads an omitted field as unchanged,
      // so sending the untouched ones back would re-validate values nobody
      // edited and turn a PAN correction into a GSTIN rewrite.
      const body: Record<string, string> = {};
      if (pan.trim() && pan.trim() !== (identity?.pan ?? "")) body.pan = pan.trim();
      if (gstin.trim() && gstin.trim() !== (identity?.gstin ?? "")) body.gstin = gstin.trim();
      if (state.trim() && state.trim() !== (identity?.state ?? "")) body.state = state.trim();
      if (Object.keys(body).length === 0) { setOpen(false); return; }
      const r = await api.practice.updateIdentity(body) as ApiResp<unknown>;
      // This router answers a refusal as HTTP 200 with {success: false} — an
      // unchecked call shows "saved" for a request the server declined.
      if (!r?.success) { setError(r?.error ?? "Couldn't save the identity."); return; }
      setOpen(false);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the identity.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 mt-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-brand">Your firm&apos;s tax identity</h2>
          <p className="text-2xs text-gray-500 mt-0.5">
            What goes on the fee invoices you raise to your own clients — CGST
            Rule 46(a). Separate from the firm profile in Settings, which is
            what the product itself is registered under.
          </p>
        </div>
        {!open && (
          <button onClick={start}
            className="shrink-0 text-2xs px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">
            Edit
          </button>
        )}
      </div>

      {!open ? (
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3 text-2xs">
          <div><dt className="text-gray-400">PAN</dt>
            <dd className="text-brand font-mono">{identity?.pan || "Not recorded"}</dd></div>
          <div><dt className="text-gray-400">GSTIN</dt>
            <dd className="text-brand font-mono">{identity?.gstin || "Not recorded"}</dd></div>
          <div><dt className="text-gray-400">State</dt>
            <dd className="text-brand">{identity?.state || "Not recorded"}</dd></div>
          <div><dt className="text-gray-400">State code</dt>
            <dd className="text-brand font-mono">{identity?.state_code || "—"}</dd></div>
        </dl>
      ) : (
        <div className="mt-3 space-y-2">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <label className="block">
              <span className="text-2xs text-gray-400">PAN</span>
              <input value={pan} onChange={(e) => setPan(e.target.value.toUpperCase())}
                placeholder="AAAAA9999A" maxLength={10}
                className="w-full text-2xs font-mono px-2 py-1 rounded-md border border-gray-200" />
            </label>
            <label className="block">
              <span className="text-2xs text-gray-400">GSTIN</span>
              <input value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())}
                placeholder="27AAAAA9999A1ZK" maxLength={15}
                className="w-full text-2xs font-mono px-2 py-1 rounded-md border border-gray-200" />
            </label>
            <label className="block">
              <span className="text-2xs text-gray-400">State</span>
              <input value={state} onChange={(e) => setState(e.target.value)}
                placeholder="Maharashtra"
                className="w-full text-2xs px-2 py-1 rounded-md border border-gray-200" />
            </label>
          </div>
          <p className="text-2xs text-gray-400">
            The state code is derived from the GSTIN or the state; leave a field
            blank to leave it as it is.
          </p>
          {error && <p className="text-2xs text-red-600">{error}</p>}
          <div className="flex gap-2">
            <button onClick={save} disabled={saving}
              className="text-2xs px-3 py-1 rounded-md bg-brand text-white font-medium disabled:opacity-50 inline-flex items-center gap-1">
              {saving && <Loader2 size={11} className="animate-spin" />}Save
            </button>
            <button onClick={() => { setOpen(false); setError(null); }}
              className="text-2xs px-3 py-1 rounded-md border border-gray-200 text-gray-600">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

interface DashboardData {
  total_receivable_paise: number;
  overdue_paise: number;
  overdue_count: number;
  tds_receivable_paise: number;
  collected_cash_paise: number;
}

function KpiCard({ label, value, icon: Icon, tone }: {
  label: string; value: string; icon: typeof IndianRupee; tone?: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center justify-between">
        <p className="text-2xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
        <Icon size={15} className={tone ?? "text-gray-400"} />
      </div>
      <p className="text-xl font-semibold text-brand mt-2 tabular-nums">{value}</p>
    </div>
  );
}

function PracticeOverview() {
  const [provisioned, setProvisioned] = useState<boolean | null>(null);
  const [identity, setIdentity] = useState<PracticeIdentity | null>(null);
  const [dash, setDash] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [provisioning, setProvisioning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const p = await api.practice.get() as ApiResp<{
        provisioned: boolean; identity?: PracticeIdentity | null;
      }>;
      setProvisioned(p.data?.provisioned ?? false);
      setIdentity(p.data?.identity ?? null);
      if (p.data?.provisioned) {
        const d = await api.billing.dashboard() as ApiResp<DashboardData>;
        setDash(d.data);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load Practice");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function provision() {
    setProvisioning(true);
    try { await api.practice.provision(); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Provisioning failed"); }
    finally { setProvisioning(false); }
  }

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading Practice…</div>;
  if (error) return <div className="p-8 text-sm text-red-600">{error}</div>;

  if (provisioned === false) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-12 text-center">
        <div className="w-12 h-12 rounded-full bg-brand/10 flex items-center justify-center mb-4">
          <Building2 size={20} className="text-brand" />
        </div>
        <h2 className="text-base font-semibold text-brand">Set up your Practice</h2>
        <p className="text-sm text-gray-500 mt-1 max-w-sm">
          Provision the firm-as-internal-client to start Revenue Operations
          (billing, collections, AR) for your own firm.
        </p>
        <button onClick={provision} disabled={provisioning}
          className="mt-4 px-4 py-2 rounded-lg bg-brand text-white text-sm font-medium disabled:opacity-50">
          {provisioning ? "Setting up…" : "Set up Practice"}
        </button>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <Building2 size={18} className="text-brand" />
          <h1 className="text-lg font-semibold text-brand">Practice — Revenue Overview</h1>
        </div>
        <button onClick={load} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <KpiCard label="Total Receivable" value={formatPaise(dash?.total_receivable_paise ?? 0)} icon={IndianRupee} tone="text-blue-500" />
        <KpiCard label="Overdue" value={`${formatPaise(dash?.overdue_paise ?? 0)} (${dash?.overdue_count ?? 0})`} icon={AlertTriangle} tone="text-state-problem" />
        <KpiCard label="TDS Receivable" value={formatPaise(dash?.tds_receivable_paise ?? 0)} icon={ReceiptText} tone="text-amber-500" />
        <KpiCard label="Collected (cash)" value={formatPaise(dash?.collected_cash_paise ?? 0)} icon={Wallet} tone="text-green-600" />
      </div>
      <TaxIdentity identity={identity} onSaved={load} />
      <p className="text-2xs text-gray-400 mt-4">
        All figures computed server-side from the internal client&apos;s books. Partner-only.
      </p>
    </div>
  );
}

export default function PracticePage() {
  return <PartnerGuard><PracticeOverview /></PartnerGuard>;
}
