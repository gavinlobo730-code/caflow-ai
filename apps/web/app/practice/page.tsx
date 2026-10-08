"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Building2, RefreshCw, Loader2 } from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { objectOrNull } from "@/lib/api/shape";
import { formatPaise } from "@/lib/services/formatting";
import { PartnerGuard } from "@/components/practice/PartnerGuard";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { EmptyStateAction } from "@/components/ui/empty-state-action";

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

function PracticeOverview() {
  const [provisioned, setProvisioned] = useState<boolean | null>(null);
  const [identity, setIdentity] = useState<PracticeIdentity | null>(null);
  const [dash, setDash] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [provisioning, setProvisioning] = useState(false);
  // What the server said about WHETHER the Practice can be set up now
  // (`can_provision`: the firm has a PAN and nothing is provisioned yet). `null`
  // is "the server did not say" (an API not yet redeployed) and is not "no":
  // only an explicit `false` disables the button.
  const [canProvision, setCanProvision] = useState<boolean | null>(null);
  // The server's own sentence for why the last attempt did not provision, and
  // whether the attempt was refused (answered, but nothing provisioned) as
  // opposed to failing to get an answer at all.
  const [provisionNotice, setProvisionNotice] = useState<string | null>(null);
  const [provisionRefused, setProvisionRefused] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const p = await api.practice.get() as ApiResp<unknown>;
      // This router answers a refusal as HTTP 200 with {success: false}; an
      // unchecked read would fall through to the "Set up your Practice" screen
      // below for a request the server declined.
      if (!p?.success) { setError(p?.error ?? "Failed to load Practice"); return; }
      const status = objectOrNull<{
        provisioned?: boolean; can_provision?: boolean; identity?: PracticeIdentity | null;
      }>(p.data);
      setProvisioned(status?.provisioned ?? false);
      setCanProvision(typeof status?.can_provision === "boolean" ? status.can_provision : null);
      setIdentity(status?.identity ?? null);
      if (status?.provisioned) {
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
    setProvisionNotice(null);
    setProvisionRefused(false);
    try {
      const r = await api.practice.provision() as ApiResp<unknown>;
      // THE RESPONSE IS READ. `POST /api/practice/provision` answers a firm with
      // no valid PAN as success with `provisioned: false` and a sentence saying
      // what to do; awaiting the call and reloading showed the "Set up your
      // Practice" screen again with no word of why (PRE-A-003). Nothing is
      // decided here: the sentence is the server's, shown as it came.
      if (!r?.success) {
        setProvisionNotice(r?.error ?? "Couldn't set up the Practice.");
        return;
      }
      const result = objectOrNull<{ provisioned?: boolean; message?: string | null }>(r.data);
      if (!result?.provisioned) {
        setProvisionRefused(true);
        setProvisionNotice(result?.message ?? "The Practice could not be set up.");
        return;
      }
      await load();
    } catch (e) {
      setProvisionNotice(e instanceof Error ? e.message : "Provisioning failed");
    } finally {
      setProvisioning(false);
    }
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
        {provisionNotice ? (
          <p role="alert" className="mt-3 max-w-sm text-sm text-state-problem">{provisionNotice}</p>
        ) : canProvision === false ? (
          // The server's own `can_provision` is false on this screen only when the
          // firm has no PAN (nothing is provisioned here), and sign-up does not
          // collect one. Said before the click rather than after a refusal.
          <p role="status" className="mt-3 max-w-sm text-sm text-ps-body">
            Your firm has no PAN on record yet, and the Practice is set up under
            it. Set the firm PAN in Settings, then come back.
          </p>
        ) : null}
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <Button variant="plain" size="none" onClick={() => provision()}
            disabled={canProvision === false}
            className="px-4 py-2 rounded-lg bg-brand text-white text-sm font-medium disabled:opacity-50">
            {provisioning ? "Setting up…" : "Set up Practice"}
          </Button>
          {(canProvision === false || provisionRefused) && (
            <EmptyStateAction href="/settings" requires={["firm", "write"]}
              variant="secondary" label="Set the firm PAN in Settings" />
          )}
        </div>
      </div>
    );
  }

  // The four Total Receivable / Overdue / TDS Receivable / Collected tiles
  // used to be repeated here in full — identical to the ones on the Revenue
  // page (/practice/revenue), reading the same api.billing.dashboard() call.
  // This screen's own job is Practice SETUP and tax identity; the figures
  // belong on Revenue, so here they are one summary line with a link across.
  const overdueCount = dash?.overdue_count ?? 0;
  return (
    <div className="p-6 max-w-5xl">
      <PageHeader
        icon={<Building2 size={18} className="text-brand" />}
        title="Practice Overview"
        actions={
          <button onClick={load} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand">
            <RefreshCw size={13} /> Refresh
          </button>
        }
        className="mb-5"
      />
      <div className="flex items-center justify-between gap-3 rounded-xl border border-ps-border bg-white p-4 mb-5">
        <p className="text-sm text-ps-body">
          Total receivable{" "}
          <span className="font-semibold text-ps-ink tabular-nums">
            {formatPaise(dash?.total_receivable_paise ?? 0)}
          </span>
          {overdueCount > 0 && (
            <span className="text-state-problem">
              {" "}· {overdueCount} overdue ({formatPaise(dash?.overdue_paise ?? 0)})
            </span>
          )}
        </p>
        <Link href="/practice/revenue" className="text-sm font-medium text-brand hover:underline shrink-0">
          Revenue dashboard →
        </Link>
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
