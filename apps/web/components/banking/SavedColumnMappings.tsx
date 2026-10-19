"use client";

/**
 * What the product has been taught about each bank's statement layout, beside the statement import.
 *
 * When a bank's export is not one of the layouts the importer recognises, a CA maps its columns once and the mapping is saved
 * for that account and that exact header row (so the next export of the same layout imports without asking). The list had no
 * screen, so a mapping that had gone wrong, or one for a layout the bank has since changed, could be neither seen nor taken
 * back: the only way to correct it was to import under it again. This shows each saved layout as "Date <- Txn Date" using the
 * labels the CA saw, and lets a person with banking write access forget one (the next upload of that layout asks again).
 *
 * Three states stay apart: it could not be read, nothing has been saved, and the rows.
 */
import { useCallback, useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Can } from "@/components/Can";
import { Callout } from "@/components/ui/callout";
import { EmptyState } from "@/components/ui/states";
import { Button } from "@/components/ui/button";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { ListWindowNotice } from "@/components/lists/ListWindowNotice";
import { windowDescription } from "@/lib/lists/window";
import { formatDate } from "@/lib/dates/format";
import { describeMapping, readSavedMappings, type SavedColumnMapping } from "@/lib/banking/savedColumnMappings";

const INITIAL_LIMIT = 100;

type Loaded =
  | { kind: "loading" }
  | { kind: "unreadable" }
  | { kind: "ready"; rows: SavedColumnMapping[]; hasMore: boolean; limit: number; maxLimit: number };

export function SavedColumnMappings({
  clientId, accounts, refreshKey,
}: {
  clientId: string;
  accounts: { id: string; bank_name: string; account_no: string }[];
  /** Bumped by the host after an import, which may have saved a layout. */
  refreshKey?: number;
}) {
  const [limit, setLimit] = useState(INITIAL_LIMIT);
  const [state, setState] = useState<Loaded>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => { setLimit(INITIAL_LIMIT); }, [clientId]);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    (async () => {
      try {
        const res = await api.banking.listColumnMappings({ client_id: clientId, limit: String(limit) }) as
          { success: boolean; data: unknown };
        if (cancelled) return;
        const window = res.success ? readSavedMappings(res.data, limit) : null;
        setState(window
          ? { kind: "ready", rows: window.rows, hasMore: window.hasMore, limit: window.limit, maxLimit: window.maxLimit }
          : { kind: "unreadable" });
      } catch {
        if (!cancelled) setState({ kind: "unreadable" });
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => { cancelled = true; };
  }, [clientId, limit, refreshKey, reload]);

  const accountName = useCallback((id: string) => {
    const a = accounts.find((x) => x.id === id);
    return a ? `${a.bank_name} (····${a.account_no.slice(-4)})` : "A bank account no longer listed";
  }, [accounts]);

  async function forget(m: SavedColumnMapping) {
    if (busy) return;
    if (!(await confirmDialog({
      message: `Forget the saved layout for ${accountName(m.bank_account_id)}?\n\nThe next statement with this layout will ask you to map its columns again. Statements already imported are not changed.`,
      confirmLabel: "Forget",
      danger: true,
    }))) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.banking.deleteColumnMapping(m.id) as { success: boolean; error: string | null };
      if (!res.success) { setMsg({ type: "err", text: res.error ?? "Could not forget the layout." }); return; }
      setMsg({ type: "ok", text: "Layout forgotten." });
      setReload((k) => k + 1);
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Could not forget the layout." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white rounded-xl border border-ps-border p-4" aria-label="Saved statement layouts">
      <h3 className="text-sm font-semibold text-ps-ink">Statement layouts saved for this client</h3>
      <p className="mt-0.5 text-xs text-ps-hint">
        When a bank&apos;s file is mapped by hand, the mapping is kept for that account and that exact set of column headings.
      </p>
      {msg && <Callout tone={msg.type === "ok" ? "note" : "problem"} className="mt-2">{msg.text}</Callout>}
      {state.kind === "loading" && <p className="mt-2 text-xs text-ps-hint">Loading the saved layouts…</p>}
      {state.kind === "unreadable" && (
        <Callout tone="problem" className="mt-2">The saved layouts could not be loaded. This is not the same as none having been saved.</Callout>
      )}
      {state.kind === "ready" && state.rows.length === 0 && (
        <EmptyState
          className="py-6"
          title="No statement layout has been saved yet"
          description="A layout is saved when you map a statement's columns by hand and import it. Banks the importer already recognises need none."
        />
      )}
      {state.kind === "ready" && state.rows.length > 0 && (
        <>
          <ul className="mt-2 divide-y divide-ps-border">
            {state.rows.map((m) => (
              <li key={m.id} className="py-2 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs font-medium text-ps-body">{accountName(m.bank_account_id)}</p>
                  <p className="mt-0.5 text-xs text-ps-label">
                    {describeMapping(m.mapping, m.header_labels).map((f) => `${f.label} ← ${f.column}`).join(" · ") || "No columns recorded"}
                  </p>
                  <p className="mt-0.5 text-3xs text-ps-hint">Saved {formatDate(m.updated_at ?? m.created_at)}</p>
                </div>
                <Can resource="banking" action="write">
                  <Button variant="plain" size="none" disabled={busy} onClick={() => forget(m)}
                    className="shrink-0 flex items-center gap-1 text-3xs px-2 py-1 border border-ps-border rounded hover:bg-ps-bg text-ps-label disabled:opacity-40"
                    aria-label={`Forget the saved layout for ${accountName(m.bank_account_id)}`}>
                    <Trash2 size={11} /> Forget
                  </Button>
                </Can>
              </li>
            ))}
          </ul>
          <ListWindowNotice
            hasMore={state.hasMore}
            what={windowDescription(state.rows.length, "saved layouts", "latest")}
            limit={state.limit}
            maxLimit={state.maxLimit}
            onShowMore={(next) => setLimit(next)}
            busy={busy}
          />
        </>
      )}
    </section>
  );
}
