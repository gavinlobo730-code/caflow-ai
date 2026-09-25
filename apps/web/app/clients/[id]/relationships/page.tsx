"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, X, Network, Trash2, FileText } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Callout, StatutoryNotes } from "@/components/ui/callout";
import { TableSkeleton } from "@/components/ui/skeleton";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { formatDate as formatDateShared } from "@/lib/services/formatting";
import { formatPaise, NO_FIGURE } from "@/lib/money/format";
import { api } from "@/lib/api";
import type {
  ClientEntityRole,
  RelatedParty,
  RelatedPartyDisclosure,
  RelationshipEntity,
} from "@/lib/api";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";

/**
 * Related parties — the AS 18 note, and the roles it is built from.
 *
 * WHAT WAS WRONG, AND IT WAS FOUR THINGS.
 *
 *  1. `roles` was declared, rendered as "Associated Entities (0)" and NEVER
 *     FETCHED — `loadAll` read only `cross_client_matches`. A CA who linked a
 *     director saw the row until they refreshed, and then it was gone. There
 *     was no endpoint to fetch from either; `GET /api/relationships/roles`
 *     is new.
 *  2. The role form asked for a UUID: *"Enter the Entity ID from the Entity
 *     Registry."* It is a picker now, served from the firm's own register.
 *  3. A newly added role rendered blank — the API returns the database row,
 *     which carries `role`, and this file read `role_type`.
 *  4. `GET /related-party-report` — the AS 18 disclosure, Companies Act s.188
 *     transactions, s.185 loans to directors and the s.92 transfer-pricing
 *     flags — had NO CALLER anywhere in this app. It is the one output that
 *     makes this screen worth opening, and nothing rendered it.
 *
 * THE SCREEN DECIDES NOTHING. Who is a related party, what the note must say
 * and what cannot be derived are all
 * `apps/api/domain/related_party/disclosure.py`. This renders what it is
 * given, including its gaps — a note that quietly omits a related party is a
 * WRONG disclosure, which is worse than none, so the sentences travel with
 * the figures rather than being summarised here.
 */
const ROLE_TYPES = [
  "Director", "Shareholder", "Partner", "Trustee", "Proprietor",
  "Guarantor", "Authorized Signatory", "Karta (HUF)", "Beneficiary",
  "Manager", "Other",
];

interface CrossClientMatch {
  id: string;
  /** The column is `match_value`, and it is NOT always a PAN: migration 059
   *  CHECKs `match_type` to ('pan','gstin','name','email') and the value is
   *  whatever that type says it is. This interface said `pan`, so the cell was
   *  permanently undefined under the old `select("*")` — and once the select
   *  was narrowed to a column list it named a column that does not exist,
   *  which PostgREST rejects for the WHOLE select, taking the screen's load()
   *  with it. Nullable, because the column is. */
  match_value: string | null;
  client_id_a: string;
  client_id_b: string;
  /** One of 'pan' | 'gstin' | 'name' | 'email' (migration 059's CHECK). */
  match_type: string;
  /** The column is `reviewed`, not `is_reviewed` — this file's old interface
   *  said otherwise and read a field that is always undefined. */
  reviewed: boolean;
  is_confirmed?: boolean;
}

function formatDate(d?: string | null) {
  if (!d) return "—";
  try { return formatDateShared(d); } catch { return d; }
}

const STANDING_STYLE: Record<string, string> = {
  included: "bg-state-ready-surface text-state-ready",
  excluded: "bg-gray-100 text-gray-600",
  undetermined: "bg-state-attention-surface text-state-attention",
};

export default function ClientRelatedPartiesPage() {
  const { clientId } = useClientNav();
  const [roles, setRoles] = useState<ClientEntityRole[]>([]);
  const [note, setNote] = useState<RelatedPartyDisclosure | null>(null);
  const [matches, setMatches] = useState<CrossClientMatch[]>([]);
  const [entities, setEntities] = useState<RelationshipEntity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addRoleModal, setAddRoleModal] = useState(false);
  const [roleForm, setRoleForm] = useState({ entity_id: "", role_type: "Director", ownership_percent: "" });
  const [savingRole, setSavingRole] = useState(false);
  const [detectLoading, setDetectLoading] = useState(false);
  // The row being removed, or null. Per-ROW rather than one boolean: a shared
  // flag would disable every trash icon while one is in flight, which reads as
  // the screen having frozen.
  const [removingRoleId, setRemovingRoleId] = useState<string | null>(null);
  // One action at a time: every button that starts work waits for whichever is
  // already running, or the second can act on what the first is still changing.
  const actionInFlight = detectLoading || savingRole || removingRoleId !== null;

  const loadAll = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    setError(null);
    try {
      const [rolesRes, noteRes] = await Promise.all([
        api.relatedParties.roles(clientId),
        api.relatedParties.disclosure(clientId),
      ]);
      // The envelope before the payload, and the payload before it is treated
      // as a list — several routers answer a refusal as HTTP 200.
      if (!rolesRes?.success) throw new Error(rolesRes?.error || "Could not load the roles.");
      setRoles(arrayOrEmpty<ClientEntityRole>(rolesRes.data));
      setNote(
        noteRes?.success
          ? objectWithLists<RelatedPartyDisclosure>(
              noteRes.data,
              "parties", "section_185_loans", "transfer_pricing_flags",
              "entity_relationships", "gaps", "notes",
            )
          : null
      );

      // Cross-client matches stay a direct read: a plain filtered select with
      // no server-side computation, scoped to THIS client on either end —
      // `cross_client_matches` names two clients and either may be this one.
      const db = getSupabaseClient();
      const { data, error: matchesError } = await db
        .from("cross_client_matches")
        .select("id, match_value, client_id_a, client_id_b, match_type, reviewed, is_confirmed")
        .eq("reviewed", false)
        .or(`client_id_a.eq.${clientId},client_id_b.eq.${clientId}`)
        .order("created_at", { ascending: false });
      if (matchesError) throw matchesError;
      setMatches((data as CrossClientMatch[]) ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { loadAll(); }, [loadAll]);

  // The register is fetched when the picker opens, not on every page load: a
  // firm's entity list has nothing to do with rendering this client's note.
  useEffect(() => {
    if (!addRoleModal || entities.length) return;
    api.relatedParties.entities()
      .then((r) => { if (r?.success) setEntities(arrayOrEmpty<RelationshipEntity>(r.data)); })
      .catch(() => { /* the picker falls back to its empty state */ });
  }, [addRoleModal, entities.length]);

  async function handleDetectMatches() {
    if (actionInFlight) return;
    setDetectLoading(true);
    try {
      await api.relatedParties.detectMatches();
      await loadAll();
    } catch { /* non-fatal — the list simply does not change */ }
    finally { setDetectLoading(false); }
  }

  async function handleAddRole() {
    if (actionInFlight || !roleForm.entity_id || !roleForm.role_type) return;
    setSavingRole(true);
    try {
      const res = await api.relatedParties.addRole(roleForm.entity_id, {
        client_id: clientId,
        role_type: roleForm.role_type,
        ownership_percent: roleForm.ownership_percent
          ? Number(roleForm.ownership_percent)
          : null,
      });
      if (!res?.success) throw new Error(res?.error ?? "Failed to add role");
      setAddRoleModal(false);
      setRoleForm({ entity_id: "", role_type: "Director", ownership_percent: "" });
      // Reload rather than prepending the response: adding a director CHANGES
      // THE NOTE, and a screen showing a new row beside a stale disclosure is
      // the more confusing of the two states.
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add role");
    } finally {
      setSavingRole(false);
    }
  }

  async function handleRemoveRole(roleId: string) {
    // A second click on the same trash icon deletes a role that is already gone
    // and then reloads over the answer to the first — so the button is out of
    // action from the moment it is pressed, not from when the request returns.
    if (actionInFlight) return;
    setRemovingRoleId(roleId);
    try {
      const res = await api.relatedParties.removeRole(roleId);
      if (!res?.success) throw new Error(res?.error ?? "Failed to remove role");
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove role");
    } finally {
      setRemovingRoleId(null);
    }
  }

  const included = useMemo(
    () => (note?.parties ?? []).filter((p) => p.standing === "included"),
    [note]
  );
  const undetermined = useMemo(
    () => (note?.parties ?? []).filter((p) => p.standing === "undetermined"),
    [note]
  );

  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <TableSkeleton cols={5} rows={4} />
        <TableSkeleton cols={4} rows={3} />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-base font-semibold text-brand">Related Parties</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Directors, shareholders and related parties, and the AS 18 note built from them
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={handleDetectMatches}
            disabled={actionInFlight}
            className="flex items-center gap-1 text-xs text-state-attention border border-state-attention-border px-2.5 py-1.5 rounded hover:bg-state-attention-hover disabled:opacity-50"
          >
            <Network size={12} /> Detect Matches
          </button>
          <button
            onClick={() => setAddRoleModal(true)}
            className="flex items-center gap-1 text-xs bg-brand text-white px-3 py-1.5 rounded-md hover:bg-brand-dark"
          >
            <Plus size={12} /> Link Entity
          </button>
        </div>
      </div>

      {error && <Callout tone="problem">{error}</Callout>}

      {/* ── The disclosure ─────────────────────────────────────────────── */}
      <Card>
        <CardContent className="p-5 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-brand">
              <FileText size={13} /> AS 18 related party disclosure
            </h2>
            {note && (
              <Badge className={note.disclosure_required
                ? "bg-state-attention-surface text-state-attention text-3xs"
                : "bg-gray-100 text-gray-600 text-3xs"}>
                {note.disclosure_required ? "Disclosure required" : "No related party identified"}
              </Badge>
            )}
          </div>

          {!note ? (
            <p className="text-xs text-ps-hint">
              The disclosure could not be loaded. The roles below are still current.
            </p>
          ) : included.length === 0 ? (
            <p className="text-xs text-ps-hint">
              No related party has been identified for this client yet. Link the
              directors, partners or shareholders above and the note builds itself.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-3xs uppercase tracking-wide text-ps-hint border-b border-ps-border">
                    <th className="pb-2 pr-3 font-medium">Party</th>
                    <th className="pb-2 pr-3 font-medium">Relationship</th>
                    <th className="pb-2 pr-3 font-medium text-right">Sales</th>
                    <th className="pb-2 pr-3 font-medium text-right">Purchases</th>
                    <th className="pb-2 pr-3 font-medium text-right">Receivable</th>
                    <th className="pb-2 font-medium text-right">Payable</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-border">
                  {included.map((p) => <PartyRow key={p.entity_id + p.role} party={p} />)}
                </tbody>
              </table>
            </div>
          )}

          {undetermined.length > 0 && (
            <div className="rounded-lg border border-state-attention-border bg-state-attention-surface p-3">
              <p className="text-3xs font-semibold uppercase tracking-wide text-state-attention mb-1.5">
                Not decided — held out of the note above
              </p>
              <ul className="space-y-1">
                {undetermined.map((p) => (
                  <li key={p.entity_id + p.role} className="text-2xs text-ps-label">
                    <span className="font-medium text-ps-ink">{p.name}</span>
                    {" · "}{p.role}{" — "}{p.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {note && (note.section_185_loans.length > 0 || note.transfer_pricing_flags.length > 0) && (
            <div className="flex flex-wrap gap-2">
              {note.section_185_loans.length > 0 && (
                <Badge className="bg-state-problem-surface text-state-problem text-3xs">
                  {note.section_185_loans.length} loan(s) flagged under Companies Act s.185
                </Badge>
              )}
              {note.transfer_pricing_flags.length > 0 && (
                <Badge className="bg-state-attention-surface text-state-attention text-3xs">
                  {note.transfer_pricing_count} inter-company loan(s) above the s.92 threshold
                </Badge>
              )}
            </div>
          )}

          {note && <StatutoryNotes gaps={note.gaps} caveats={note.notes} />}
        </CardContent>
      </Card>

      {/* ── The roles the note is built from ───────────────────────────── */}
      <div>
        <h2 className="text-sm font-semibold text-brand mb-3">
          Associated entities
          <span className="ml-2 text-xs text-gray-500 font-normal">({roles.length})</span>
        </h2>
        <Card>
          <CardContent className="p-0">
            {roles.length === 0 ? (
              <p className="p-5 text-xs text-ps-hint">
                No entity is linked to this client yet.
              </p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-3xs uppercase tracking-wide text-ps-hint border-b border-ps-border">
                    <th className="px-5 py-2.5 font-medium">Entity</th>
                    <th className="px-3 py-2.5 font-medium">PAN</th>
                    <th className="px-3 py-2.5 font-medium">Role</th>
                    <th className="px-3 py-2.5 font-medium text-right">Holding</th>
                    <th className="px-3 py-2.5 font-medium">From</th>
                    <th className="px-3 py-2.5 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-border">
                  {roles.map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3 text-ps-ink font-medium">
                        {r.entity_name ?? "(unnamed entity)"}
                        {r.entity_type && (
                          <span className="ml-2 text-3xs text-gray-500">{r.entity_type}</span>
                        )}
                      </td>
                      <td className="px-3 py-3 font-mono text-gray-600">{r.pan ?? "—"}</td>
                      <td className="px-3 py-3">
                        <Badge className="bg-gray-100 text-gray-700 text-3xs">{r.role}</Badge>
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums text-gray-700">
                        {r.ownership_percent === null ? "—" : `${r.ownership_percent}%`}
                      </td>
                      <td className="px-3 py-3 text-gray-500">{formatDate(r.effective_from)}</td>
                      <td className="px-3 py-3 text-right">
                        <button
                          onClick={() => handleRemoveRole(r.id)}
                          disabled={actionInFlight}
                          title="Remove this role"
                          aria-label={`Remove ${r.entity_name ?? "entity"} as ${r.role}`}
                          className="text-ps-hint hover:text-state-problem transition-colors disabled:opacity-40"
                        >
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Cross-client matches ───────────────────────────────────────── */}
      {matches.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-brand mb-3">
            Shared with other clients
            <span className="ml-2 text-xs text-gray-500 font-normal">({matches.length})</span>
          </h2>
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-3xs uppercase tracking-wide text-ps-hint border-b border-ps-border">
                    <th className="px-5 py-2.5 font-medium">Match</th>
                    {/* Not "PAN": the match may be on a GSTIN, a name or an
                        email, and the Match column beside it says which. */}
                    <th className="px-3 py-2.5 font-medium">Matched on</th>
                    <th className="px-3 py-2.5 font-medium">Other client</th>
                    <th className="px-3 py-2.5 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-border">
                  {matches.map((m) => (
                    <tr key={m.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3">
                        <Badge className="bg-state-attention-surface text-state-attention text-3xs">
                          {m.match_type.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 text-gray-700 font-mono">{m.match_value ?? "—"}</td>
                      <td className="px-3 py-3 text-gray-500">
                        {(m.client_id_a === clientId ? m.client_id_b : m.client_id_a).slice(0, 8)}…
                      </td>
                      <td className="px-3 py-3">
                        <Badge className="bg-state-attention-surface text-state-attention text-3xs">
                          {m.reviewed ? (m.is_confirmed ? "Confirmed" : "Dismissed") : "Pending"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── Link an entity ─────────────────────────────────────────────── */}
      {addRoleModal && (
        <div className="fixed inset-0 bg-gray-900/60 flex items-center justify-center z-50 px-4">
          <div className="bg-white border border-gray-200 rounded-xl shadow-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold text-brand">Link an entity to this client</h2>
              <button onClick={() => setAddRoleModal(false)} className="text-gray-400 hover:text-gray-700">
                <X size={16} />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label htmlFor="rp-entity" className="text-xs text-gray-600">Entity *</label>
                <select
                  id="rp-entity"
                  value={roleForm.entity_id}
                  onChange={(e) => setRoleForm({ ...roleForm, entity_id: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-brand"
                >
                  <option value="">
                    {entities.length ? "Choose an entity…" : "Loading the entity register…"}
                  </option>
                  {entities.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.full_name}{e.pan ? ` · ${e.pan}` : ""}
                    </option>
                  ))}
                </select>
                {entities.length === 0 && (
                  <p className="mt-1 text-3xs text-ps-hint">
                    No entity is registered yet — add one in the firm&apos;s Entity Registry first.
                  </p>
                )}
              </div>
              <div>
                <label htmlFor="rp-role" className="text-xs text-gray-600">Role *</label>
                <select
                  id="rp-role"
                  value={roleForm.role_type}
                  onChange={(e) => setRoleForm({ ...roleForm, role_type: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-brand"
                >
                  {ROLE_TYPES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="rp-holding" className="text-xs text-gray-600">
                  Holding % (optional)
                </label>
                <input
                  id="rp-holding"
                  type="number" min="0" max="100"
                  value={roleForm.ownership_percent}
                  onChange={(e) => setRoleForm({ ...roleForm, ownership_percent: e.target.value })}
                  className="w-full mt-1 px-3 py-2 text-sm bg-white border border-gray-300 rounded-md text-gray-900 focus:outline-none focus:ring-2 focus:ring-brand"
                  placeholder="e.g. 51"
                />
                {/* AS 18 reaches a shareholder whose interest gives control or
                    significant influence, not everybody on the register — so
                    for a shareholder this box is what decides the note. */}
                {roleForm.role_type === "Shareholder" && (
                  <p className="mt-1 text-3xs text-ps-hint">
                    A shareholder is only a related party where their holding
                    gives control or significant influence, so without this
                    figure the note cannot decide.
                  </p>
                )}
              </div>
            </div>
            <div className="flex gap-2 mt-5">
              <button
                onClick={() => setAddRoleModal(false)}
                className="flex-1 text-sm text-gray-600 border border-gray-200 py-2 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleAddRole}
                disabled={actionInFlight || !roleForm.entity_id}
                className="flex-1 text-sm bg-brand text-white py-2 rounded-md hover:bg-brand-dark disabled:opacity-50"
              >
                {savingRole ? "Linking…" : "Link entity"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PartyRow({ party }: { party: RelatedParty }) {
  const d = party.dealings;
  // NULL dealings means the party carries no PAN, so nothing could be matched
  // — that is UNKNOWN, not nil, and a zero here would read as "no dealings".
  const cell = (v: number | undefined) =>
    d ? formatPaise(v ?? 0) : NO_FIGURE;
  return (
    <tr className="hover:bg-gray-50">
      <td className="py-2.5 pr-3">
        <span className="font-medium text-ps-ink">{party.name}</span>
        {party.pan && <span className="ml-2 font-mono text-3xs text-gray-500">{party.pan}</span>}
      </td>
      <td className="py-2.5 pr-3">
        <Badge className={`${STANDING_STYLE[party.standing] ?? "bg-gray-100 text-gray-600"} text-3xs`}>
          {party.role}
        </Badge>
        {party.ownership_percent !== null && (
          <span className="ml-2 text-3xs text-gray-500">{party.ownership_percent}%</span>
        )}
      </td>
      <td className="py-2.5 pr-3 text-right tabular-nums text-gray-700">{cell(d?.sales_paise)}</td>
      <td className="py-2.5 pr-3 text-right tabular-nums text-gray-700">{cell(d?.purchases_paise)}</td>
      <td className="py-2.5 pr-3 text-right tabular-nums text-gray-700">{cell(d?.receivable_paise)}</td>
      <td className="py-2.5 text-right tabular-nums text-gray-700">{cell(d?.payable_paise)}</td>
    </tr>
  );
}
