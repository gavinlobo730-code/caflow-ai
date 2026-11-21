"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { failureSentence } from "@/lib/api/failureSentence";
import { formatDate } from "@/lib/dates/format";
import { NOTE_MAX, readMine, standingOf, type Standing } from "@/lib/access/accessRequest";

/**
 * "Request access", on the notice a person sees at a screen they hold no permission for (POST-A-543, the owner's addition of
 * 21-11-2026).
 *
 * Pressing it raises a request to the firm's Partners for the ONE permission the notice named. A Partner decides it in
 * Approvals; an approval switches that permission on for this person, exactly as the Team screen would have. Nothing here
 * decides anything: the server says what may be asked for, by whom, and that nobody approves their own.
 *
 * WHAT THE PERSON IS TOLD, AND NEVER MORE THAN IS KNOWN. Their own requests are read first, so somebody who already asked
 * sees that it is waiting (and since when) and is not offered a second request the server would refuse; somebody a Partner
 * declined sees that, with the Partner's reason, and may ask again. If their requests could not be read, the button is still
 * offered and the server answers a repeat in words. A refusal from the server is shown as the server worded it.
 */
export default function RequestAccess({ resource, action, askedFrom }: { resource: string; action: string; askedFrom: string }) {
  // null: not read yet, or could not be read. The button is offered either way.
  const [standing, setStanding] = useState<Standing | null>(null);
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const noteId = useId();

  const read = useCallback(async () => {
    try {
      const res = await api.approvals.myAccessRequests();
      const rows = res?.success ? readMine(res.data) : null;
      setStanding(rows ? standingOf(rows, resource, action) : null);
    } catch {
      setStanding(null);
    }
  }, [resource, action]);

  useEffect(() => { void read(); }, [read]);

  async function ask() {
    if (sending) return;
    setSending(true);
    setProblem(null);
    try {
      const res = await api.approvals.requestAccess({ resource, action, asked_from: askedFrom, note: note.trim() || undefined });
      if (!res?.success) throw new Error(res?.error ?? "The request could not be sent.");
      setStanding({ kind: "waiting", askedAt: res.data?.asked_at ?? null });
      setNote("");
    } catch (e) {
      setProblem(failureSentence(e, "The request could not be sent."));
      // The commonest refusal is "you have already asked": show what the server holds now.
      void read();
    } finally {
      setSending(false);
    }
  }

  if (standing?.kind === "waiting") {
    return (
      <p className="mt-4 text-sm text-ps-body" role="status" data-access-request="waiting">
        You asked for this{standing.askedAt ? ` on ${formatDate(standing.askedAt)}` : ""}. A Partner has not decided yet;
        you will get a notification when they do.
      </p>
    );
  }

  return (
    <div className="mt-4" data-access-request={standing?.kind === "declined" ? "declined" : "none"}>
      {standing?.kind === "declined" && (
        <p className="text-sm text-ps-body mb-3" role="status">
          A Partner declined your last request for this{standing.decidedAt ? ` on ${formatDate(standing.decidedAt)}` : ""}.
          {standing.reason ? ` Reason given: ${standing.reason}` : ""} You can ask again.
        </p>
      )}
      <label htmlFor={noteId} className="block text-xs font-medium text-ps-label mb-1">
        Why you need it (optional; your Partner reads this)
      </label>
      <textarea
        id={noteId}
        value={note}
        maxLength={NOTE_MAX}
        onChange={(e) => setNote(e.target.value)}
        rows={2}
        className="w-full rounded-md border border-ps-border px-3 py-2 text-sm text-ps-ink"
      />
      <div className="mt-3 flex items-center gap-3">
        <Button onClick={ask} disabled={sending}>{sending ? "Sending…" : "Request access"}</Button>
        <span className="text-xs text-ps-hint">Your firm&apos;s Partners are asked. One of them approves or declines it.</span>
      </div>
      {problem && <p role="alert" className="mt-2 text-sm text-state-problem">{problem}</p>}
    </div>
  );
}
