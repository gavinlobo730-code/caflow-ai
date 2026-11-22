"use client";

/**
 * Whether a Partner approves every manual journal (POST-A-456, migration 681).
 *
 * WHAT WAS WRONG
 *   Two doors put a manual journal on the books and they asked different people: a new entry sent as posted asked `accounting`
 *   `write` (a Manager), and posting a saved draft asked `accounting` `approve` (a Partner). A Manager went around the Approvals tab by
 *   typing the entry again as new, and a firm that wanted every manual journal approved had no way to say so.
 *
 * WHAT THIS PAGE IS
 *   The firm's one switch. Off (the default): anyone who may write the books posts a manual journal, as a new entry or from a draft.
 *   On: only someone who may approve posts one, posts a draft, or corrects or deletes one on the books; everyone else saves a draft,
 *   which waits in Approvals. The server holds every door to it (`services/journal_approval_rule`); this page shows the server's
 *   answer and sends the Partner's choice, and decides nothing.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, ClipboardCheck } from "lucide-react";
import { ReadOnlyNotice } from "@/components/settings/ChangePart";
import { api, type JournalApprovalRule } from "@/lib/api/index";
import { readJournalApprovalRule } from "@/lib/accounting/journalApprovalRule";
import { FormSkeleton } from "@/components/ui/skeleton";
import { Callout } from "@/components/ui/callout";
import { PageHeader } from "@/components/ui/page-header";

export default function JournalApprovalPage() {
  const [rule, setRule] = useState<JournalApprovalRule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.accounting.journalApproval();
      const read = res?.success ? readJournalApprovalRule(res.data) : null;
      if (!read) throw new Error(res?.error || "Couldn't read this firm's setting.");
      setRule(read);
      setError("");
    } catch (e) {
      setRule(null);
      setError(e instanceof Error ? e.message : "Couldn't read this firm's setting.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function change(next: boolean) {
    setSaving(true); setError("");
    try {
      const res = await api.accounting.setJournalApproval(next);
      const read = res?.success ? readJournalApprovalRule(res.data) : null;
      if (!read) throw new Error(res?.error || "The setting was not changed.");
      setRule(read);
    } catch (e) {
      // The server's refusal is written for the Partner; it is shown as it came.
      setError(e instanceof Error ? e.message : "The setting was not changed.");
    } finally {
      setSaving(false);
    }
  }

  const on = rule?.approval_required ?? false;
  return (
    <>
      <div className="max-w-2xl mx-auto space-y-4 p-6">
        <Link href="/settings" className="inline-flex items-center gap-1 text-xs text-ps-label hover:text-ps-body">
          <ChevronLeft size={13} /> Settings
        </Link>

        <PageHeader
          icon={<ClipboardCheck size={17} className="text-brand" />}
          title="Journal approval"
          subtitle="Whether a Partner approves every manual journal before it reaches a client's books."
        />

        {/* The box below is switched off by the server's own answer (`may_change_setting`, the same pair); this says why. */}
        <ReadOnlyNotice resource="settings" action="write" page="Journal approval" />

        {error && (
          <Callout tone="problem">
            {error}{" "}
            {!rule && <button onClick={load} className="underline">Try again</button>}
          </Callout>
        )}

        {loading ? <FormSkeleton /> : rule && (
          <div className="bg-white rounded-xl border border-ps-border px-5 py-4 space-y-3">
            <label className="flex items-start gap-3 text-sm text-ps-ink">
              <input type="checkbox" className="mt-1" checked={on} disabled={saving || !rule.may_change_setting}
                     onChange={(e) => change(e.target.checked)} />
              <span>
                <span className="font-medium">A Partner approves every manual journal</span>
                <span className="block text-xs text-ps-label mt-1">
                  {on
                    ? "On. Only someone who may approve journal entries posts a manual journal, posts a saved draft, or corrects or deletes an entry on the books. Everyone else saves a draft, which waits in each client's Approvals tab."
                    : "Off. Anyone who may write a client's books posts a manual journal, as a new entry or from a saved draft. Drafts still wait in the Approvals tab until someone posts them."}
                </span>
              </span>
            </label>
            <p className="text-xs text-ps-hint">
              Who may approve is a Partner, and anyone the Team page gives approval of accounting. Reversing a posted entry needs
              approval whichever way this is set. Postings made by invoices, bills, receipts and bank lines are not manual journals
              and are not affected.
            </p>
          </div>
        )}
      </div>
    </>
  );
}
