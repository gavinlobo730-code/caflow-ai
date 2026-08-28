"use client";

/**
 * Journal entry page — client view. Handles BOTH create and edit:
 * entryId === "new" is the create-mode sentinel, exactly as sales invoices and
 * purchase bills do it. That is not a stylistic choice — a separate static
 * /journal/new route sitting beside this dynamic [entryId] one would need its
 * own shadow-splat rule, and _redirects is capped at 100 dynamic rules by
 * Cloudflare Pages (see scripts/generate-redirects.js). One route costs three
 * rules; two would cost six.
 *
 * Ids come from window.location.pathname, NOT useParams(): under
 * `output: export` plus Cloudflare's rewrite-to-_placeholder hosting the App
 * Router's FlightRouterState is permanently anchored to the build-time
 * "_placeholder" param, so useParams() never resolves to the real ids (see
 * ClientNavContext.tsx). The client id comes from the shared useClientNav()
 * hook, and entryId is read the same way locally.
 */
import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { getFirmId } from "@/lib/data/getFirmId";
import { writeTimelineEvent } from "@/lib/services/timeline";
import { clearReports } from "@/lib/accounting/reportCache";
import { useClientNav, getCurrentFinancialYear } from "@/lib/workspace/ClientNavContext";
import { api, type ApiResp, type JournalEntryDetail, type JournalLineIO } from "@/lib/api";
import { JournalEditor, type EditorAccount, type JournalSaveMode } from "@/components/journal/JournalEditor";
import { ErrorState } from "@/components/ui/states";
import { TableSkeleton } from "@/components/ui/skeleton";

function getEntryIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  const m = window.location.pathname.match(/\/accounting\/journal\/([^/]+)\/edit/);
  return m ? decodeURIComponent(m[1]) : "";
}

/** Where the Journal list lives — a tab on the accounting page, not a route. */
function journalListHref(clientId: string): string {
  return `/clients/${clientId}/accounting?tab=journal`;
}

export default function JournalEntryPageClient() {
  const { clientId } = useClientNav();
  // Only used to stamp the timeline event below. An edit happened when it
  // happened, so the year is the current one — not whichever year a selector
  // elsewhere on the screen was left on.
  // usePathname() is only a re-run trigger (its own value is the build-time
  // placeholder segment) — the real id always comes from window.location.
  const pathname = usePathname();
  const [entryId, setEntryId] = useState<string>(() => getEntryIdFromLocation());
  useEffect(() => { setEntryId(getEntryIdFromLocation()); }, [pathname]);
  const isNew = entryId === "new";
  const router = useRouter();

  const [accounts, setAccounts] = useState<EditorAccount[] | null>(null);
  const [entry, setEntry] = useState<JournalEntryDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const ready = accounts !== null && (isNew || entry !== null);

  useEffect(() => {
    // Never query the static-export placeholder ids.
    if (!clientId || clientId === "_placeholder" || !entryId || entryId === "_placeholder") return;
    let cancelled = false;
    setAccounts(null); setEntry(null); setLoadError(null); setSaveError(null);

    const supabase = getSupabaseClient();
    const loadAccounts = selectAll(() => supabase
      .from("chart_of_accounts")
      .select("id, account_code, account_name, account_type, is_active, client_id")
      .or(`client_id.eq.${clientId},client_id.is.null`)
      .eq("is_active", true)
      .order("account_code")
      .order("id"))
      .then(({ data, error }) => {
        if (error) throw error;
        return (data ?? []) as unknown as EditorAccount[];
      });

    if (isNew) {
      loadAccounts
        .then((a) => { if (!cancelled) setAccounts(a); })
        .catch(() => { if (!cancelled) setLoadError("Couldn't load the chart of accounts."); });
      return () => { cancelled = true; };
    }

    Promise.all([
      loadAccounts,
      api.accounting.getJournalEntry(entryId) as Promise<ApiResp<JournalEntryDetail>>,
    ])
      .then(([a, res]) => {
        if (cancelled) return;
        if (!res?.success || !res.data) { setLoadError("Journal entry not found."); return; }
        setAccounts(a); setEntry(res.data);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : "Couldn't load this journal entry.");
      });
    return () => { cancelled = true; };
  }, [clientId, entryId, isNew, reloadKey]);

  const done = useCallback((eventType: string, title: string, description: string, id: string) => {
    // Non-blocking: the entry is already saved by the time this runs, and a
    // failed timeline write must never look like a failed post.
    void (async () => {
      try {
        const firmId = await getFirmId();
        await writeTimelineEvent({
          client_id: clientId, firm_id: firmId, financial_year: getCurrentFinancialYear(),
          category: "accounting", event_type: eventType, severity: "info",
          title, description, entity_type: "journal_entry", entity_id: id, actor_type: "user",
        });
      } catch { /* non-blocking */ }
    })();
    // Reports read the ledger this just changed.
    clearReports(clientId);
    router.push(journalListHref(clientId));
  }, [clientId, router]);

  async function handleSave(mode: JournalSaveMode, payload: {
    entry_date: string; entry_type: string; reference_no: string;
    narration: string; lines: JournalLineIO[];
  }) {
    setSaving(true); setSaveError(null);
    try {
      if (isNew) {
        // Through the single posting kernel (manual_journal_service →
        // phase2_journal_service._create_journal), which writes the header and
        // every line in one transaction and enforces the FY lock server-side.
        const res = await api.accounting.createJournalEntry({
          client_id: clientId,
          entry_date: payload.entry_date,
          reference_no: payload.reference_no || undefined,
          narration: payload.narration,
          entry_type: payload.entry_type,
          status: mode === "post" ? "posted" : "draft",
          lines: payload.lines,
        }) as ApiResp<{ id: string }>;
        done(
          mode === "post" ? "journal_entry_posted" : "journal_entry_saved",
          mode === "post" ? "Journal entry posted" : "Journal entry saved (draft)",
          payload.narration, res.data.id,
        );
        return;
      }

      // A posted entry must send its FULL line set — edit_posted_journal
      // rewrites them wholesale rather than diffing.
      await api.accounting.updateJournalEntry(entryId, {
        entry_date: payload.entry_date,
        entry_type: payload.entry_type,
        reference_no: payload.reference_no || null,
        narration: payload.narration,
        lines: payload.lines,
      });

      // Posting a DRAFT goes through the approval endpoint, which is the
      // production path (journal_posting_service.post_draft). The legacy
      // PATCH /journal/{id}/post is backed by the in-memory engine and would
      // not touch this client's ledger at all.
      if (mode === "post") await api.accounting.postDraftJournal(entryId);

      done(
        mode === "post" ? "journal_entry_posted" : "journal_entry_updated",
        mode === "post" ? "Journal entry posted" : "Journal entry corrected",
        payload.narration, entryId,
      );
    } catch (e) {
      // The backend's message is written for the CA — a locked year, a filed
      // return, an unbalanced entry — so it is shown rather than replaced.
      setSaveError(e instanceof Error ? e.message : "Couldn't save this entry.");
    } finally {
      setSaving(false);
    }
  }

  if (loadError) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <ErrorState message={loadError} onRetry={() => setReloadKey((k) => k + 1)} />
      </div>
    );
  }

  if (!ready) {
    return <div className="p-6 max-w-3xl mx-auto"><TableSkeleton rows={6} /></div>;
  }

  return (
    <div className="p-6">
      <JournalEditor
        accounts={accounts ?? []}
        existing={isNew ? null : entry}
        saving={saving}
        serverError={saveError}
        onSave={handleSave}
        onCancel={() => router.push(journalListHref(clientId))}
      />
    </div>
  );
}
