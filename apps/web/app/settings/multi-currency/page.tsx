"use client";

/**
 * Turning multi-currency on — the switch that did not exist (ACC-19).
 *
 * WHAT WAS WRONG
 *   All five multi-currency phases are BUILT: foreign documents, realized and
 *   unrealized FX, five /api/fx-reports endpoints, foreign bank accounts. None
 *   of it could be switched on. `resolve_currency_policy` is
 *   `active = L1 AND L2 AND L3`; L2 (`firms.multi_currency_entitled`) and L3
 *   (`clients.multi_currency_enabled`) are read by six routers and were
 *   WRITTEN BY NOTHING — no endpoint, no field, no screen, no seed. Only a
 *   manual UPDATE against the database could activate any of it.
 *
 * WHY THE GATES ARE SHOWN AND NOT JUST THE ANSWER
 *   `active: false` is what made this unusable. A Partner needs to see WHICH
 *   switch is down, or the next thing they do is tick something and watch
 *   nothing happen. The server sends all three, and the one they cannot change
 *   — the environment kill switch — says so rather than rendering as a
 *   checkbox that refuses.
 *
 * Zero business logic here (CLAUDE.md). The server decides what may be turned
 * on: turning a client on while the firm is off, or while its books are kept
 * in a currency the product does not support, is REFUSED with a sentence, and
 * this page renders that sentence.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, Globe, Check } from "lucide-react";
import { RoleGuard } from "@/components/RoleGuard";
import { api, type CurrencyPolicy } from "@/lib/api/index";
import { arrayOrEmpty, objectOrNull } from "@/lib/api/shape";
import { TableSkeleton } from "@/components/ui/skeleton";
import { FxRatesPanel } from "@/components/currency/FxRatesPanel";
import { Callout } from "@/components/ui/callout";

type ClientRow = { id: string; name?: string; client_name?: string };
type Row = { client: ClientRow; policy: CurrencyPolicy | null };
type FirmGates = { platform: { on: boolean; why?: string }; firm: { on: boolean } };

function label(c: ClientRow): string {
  return c.name || c.client_name || c.id;
}

export default function MultiCurrencyPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [firmGates, setFirmGates] = useState<FirmGates | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // The firm gate comes from its own endpoint rather than off the first
      // client's policy: a firm with no clients yet has no policy to read it
      // from, and that is the firm this is being switched on for. Both answers
      // are built by the same `_gates` on the server, so there is still one
      // implementation.
      const ent = await api.currencies.entitlement();
      // `?? null` is not enough and this screen proved it: the envelope's
      // `data` is `[]` wherever the answer is absent, and `[] ?? null` is
      // `[]` — truthy, so `firmGates?.platform.on` then read `.on` off
      // undefined and the whole Settings module went to its error boundary.
      // objectOrNull is the one place that knows an array is not an object.
      setFirmGates(ent.success ? objectOrNull<FirmGates>(ent.data) : null);

      // `GET /api/clients` answers `{clients, total}`, NOT a bare array. The
      // cast that used to sit here asserted the array, so `arrayOrEmpty` was
      // handed an OBJECT and answered `[]` — correctly, by its own rule — and
      // this screen listed no clients at all, for every firm, permanently.
      // Following the payload rule is not enough on its own; it has to be
      // applied to the right FIELD, which is what typing `api.clients.list()`
      // now makes the compiler check.
      const cl = await api.clients.list();
      const clients = cl.success ? arrayOrEmpty<ClientRow>(cl.data?.clients) : [];
      const settled = await Promise.all(clients.map(async (c) => {
        try {
          const p = await api.currencies.policy({ client_id: c.id });
          return { client: c, policy: p.success ? objectOrNull<CurrencyPolicy>(p.data) : null };
        } catch {
          return { client: c, policy: null };
        }
      }));
      setRows(settled);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load the currency settings.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const platformOn = firmGates?.platform?.on ?? false;
  const firmOn = firmGates?.firm?.on ?? false;

  async function setFirm(enabled: boolean) {
    setSaving("firm"); setError("");
    try {
      const r = await api.currencies.setEntitlement(enabled);
      if (!r.success) throw new Error(r.error ?? "Failed");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't change the firm setting.");
    }
    setSaving("");
  }

  async function setClient(clientId: string, enabled: boolean) {
    setSaving(clientId); setError("");
    try {
      const r = await api.currencies.setClientPolicy(clientId, enabled);
      if (!r.success) throw new Error(r.error ?? "Failed");
      await load();
    } catch (e) {
      // The server's refusal is a SENTENCE — "the firm is off", "this client's
      // books are kept in USD" — and it is the whole value of the refusal.
      setError(e instanceof Error ? e.message : "Couldn't change this client.");
    }
    setSaving("");
  }

  return (
    <RoleGuard allowed={["Partner"]}>
      <div className="max-w-ps-data mx-auto space-y-4 p-6">
        <Link href="/settings" className="inline-flex items-center gap-1 text-xs text-ps-label hover:text-ps-body">
          <ChevronLeft size={13} /> Settings
        </Link>

        <div className="flex items-center gap-2.5">
          <Globe size={17} className="text-blue-600" />
          <h1 className="text-lg font-semibold text-ps-ink">Multi-currency</h1>
        </div>
        <p className="text-xs text-ps-label max-w-2xl">
          Lets a client raise invoices, receive payments and hold bank accounts in a
          foreign currency, with the realized and unrealized exchange difference
          computed and posted. The books stay in rupees.
        </p>

        {error && <Callout tone="problem">{error}</Callout>}

        {loading ? <TableSkeleton cols={4} rows={4} /> : (
          <>
            {/* THE PLATFORM GATE — shown, never offered. It is an environment
                variable so it can be turned off without a database. */}
            {!platformOn && (
              <div className="bg-state-attention-surface border border-state-attention-border rounded-xl px-4 py-3 text-xs text-amber-900 space-y-1 max-w-2xl">
                <p className="font-semibold">Multi-currency is off for this deployment.</p>
                <p>{firmGates?.platform.why ?? "MULTI_CURRENCY_ENABLED is not set."}</p>
                <p>Nothing below takes effect until it is switched on in the environment.</p>
              </div>
            )}

            {/* L2 — the firm. */}
            {/* The CLIENTS table below is the data and takes the page's width;
                these two are a notice and a single switch, so they keep the
                reading measure the paragraph above already uses. Without it the
                switch sits a screen away from the label it governs — D11's own
                second half, on the one page where the two shapes sit together. */}
            <div className="bg-white rounded-xl border border-ps-muted px-5 py-4 flex items-center justify-between max-w-2xl">
              <div>
                <p className="text-sm font-medium text-ps-ink">This firm</p>
                <p className="text-xs text-ps-hint mt-0.5">
                  Turn it off here and no client of the firm can transact in a foreign currency.
                </p>
              </div>
              <label className="flex items-center gap-2 text-xs text-ps-body">
                <input type="checkbox" checked={firmOn} disabled={saving === "firm"}
                       onChange={e => setFirm(e.target.checked)} />
                {firmOn ? "On" : "Off"}
              </label>
            </div>

            {/* L3 — per client. */}
            <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-50">
                <p className="text-sm font-semibold text-ps-ink">Clients</p>
              </div>
              {rows.length === 0 ? (
                <p className="px-5 py-8 text-center text-sm text-ps-label">No clients yet.</p>
              ) : (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-ps-muted text-ps-hint">
                      <th className="px-5 py-2.5 text-left font-semibold">Client</th>
                      <th className="px-3 py-2.5 text-left font-semibold">Books kept in</th>
                      <th className="px-3 py-2.5 text-left font-semibold">Foreign currency</th>
                      <th className="px-3 py-2.5 text-left font-semibold">Effect</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ps-bg">
                    {rows.map(({ client, policy }) => {
                      const on = policy?.gates?.client?.on ?? false;
                      const supported = policy?.gates.functional_currency_supported ?? true;
                      return (
                        <tr key={client.id} className="hover:bg-ps-bg">
                          <td className="px-5 py-2.5 font-medium text-ps-ink">{label(client)}</td>
                          <td className="px-3 py-2.5 font-mono text-ps-label">
                            {policy?.gates.functional_currency ?? "—"}
                          </td>
                          <td className="px-3 py-2.5">
                            <label className="flex items-center gap-2 text-ps-body">
                              <input type="checkbox" checked={on}
                                     disabled={saving === client.id || (!on && !supported)}
                                     onChange={e => setClient(client.id, e.target.checked)} />
                              {on ? "On" : "Off"}
                            </label>
                          </td>
                          <td className="px-3 py-2.5">
                            {/* The RESOLVED answer, not the checkbox. A client
                                ticked on under a firm that is off is exactly the
                                inert control this screen exists to end. */}
                            {policy?.active ? (
                              <span className="inline-flex items-center gap-1 text-emerald-700">
                                <Check size={12} /> Active
                              </span>
                            ) : !supported ? (
                              <span className="text-state-attention">
                                Books kept in {policy?.gates.functional_currency} — not supported
                              </span>
                            ) : (
                              <span className="text-ps-hint">
                                {!platformOn ? "Off for this deployment"
                                  : !firmOn ? "Off for the firm"
                                  : "Off for this client"}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
            {/* The rate the whole feature runs on. `fx_rates` was read by the
                booking path and written by nothing, so switching the gates on
                above left a Partner with no way to record one. */}
            <FxRatesPanel />
          </>
        )}
      </div>
    </RoleGuard>
  );
}
