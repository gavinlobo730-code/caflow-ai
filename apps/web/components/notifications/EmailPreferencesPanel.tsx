"use client";

/**
 * Which of the practice's own mail THIS person gets (practice_management-03).
 *
 * The product mails staff about an assigned task, an overdue task, a deadline
 * that has reached its 7/3/1-day point or gone overdue, a task escalated to a
 * manager, and a client writing on the portal. Mail nobody can switch off is the
 * mail a practice learns to filter away, so each kind has a switch here.
 *
 * NOTHING IS DECIDED IN THIS FILE. The vocabulary, the sentences and the
 * defaults are served by `GET /api/notifications/email-preferences`
 * (`domain/practice_notices`), and the browser holds none of them — the
 * Schedule III caption lesson. What it adds is what the server cannot know:
 * the switch is optimistic only in the sense that it asks first and renders the
 * server's answer, never its own.
 *
 * It says which switches the person CHOSE and which are simply the default,
 * because showing only the effect makes an inherited default and a deliberate
 * choice look identical.
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, Mail } from "lucide-react";
import { api } from "@/lib/api";
import type { EmailLogRow, EmailPreferenceEvent } from "@/lib/api";
import { arrayOrEmpty, objectOrNull } from "@/lib/api/shape";
import { Callout } from "@/components/ui/callout";

/** `true` or `false` only when the server said so; anything else is "not told". */
function readMailEnabled(data: unknown): boolean | null {
  const v = objectOrNull<{ mail_enabled?: unknown }>(data)?.mail_enabled;
  return typeof v === "boolean" ? v : null;
}

export function EmailPreferencesPanel() {
  const [events, setEvents] = useState<EmailPreferenceEvent[]>([]);
  // Whether this deployment sends the practice's own mail at all. `null` is "the
  // server did not say" (a backend older than this field) and is NEVER rendered
  // as off: only an explicit `false` shows the notice.
  const [mailEnabled, setMailEnabled] = useState<boolean | null>(null);
  // The mails the product actually sent this person: "why did I not get it?" is
  // answered by a row being there or not.
  const [sent, setSent] = useState<EmailLogRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.notifications.emailPreferences();
      if (!res.success) throw new Error(res.error ?? "Could not load your email settings");
      setEvents(arrayOrEmpty<EmailPreferenceEvent>(
        objectOrNull<{ events?: unknown }>(res.data)?.events));
      setMailEnabled(readMailEnabled(res.data));
      // The record is a convenience beside the switches: its failure must not
      // blank them, and must not read as "nothing was sent".
      api.notifications.emailLog(10)
        .then((log) => setSent(log.success
          ? arrayOrEmpty<EmailLogRow>(objectOrNull<{ sent?: unknown }>(log.data)?.sent) : []))
        .catch(() => setSent([]));
    } catch (e) {
      setEvents([]);
      setError(e instanceof Error ? e.message : "Could not load your email settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function toggle(ev: EmailPreferenceEvent) {
    setSaving(ev.event_type);
    setError(null);
    try {
      const res = await api.notifications.setEmailPreference(ev.event_type, !ev.email_enabled);
      if (!res.success) throw new Error(res.error ?? "Could not save that");
      setEvents(arrayOrEmpty<EmailPreferenceEvent>(
        objectOrNull<{ events?: unknown }>(res.data)?.events));
      setMailEnabled(readMailEnabled(res.data));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save that");
    } finally {
      setSaving(null);
    }
  }

  return (
    <section aria-labelledby="email-prefs-h" className="rounded-xl border border-ps-border bg-white p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Mail size={15} className="text-ps-body" />
        <h2 id="email-prefs-h" className="text-sm font-semibold text-ps-ink">Email me when</h2>
      </div>
      <p className="text-xs text-ps-label">
        These switch the email only. The notification in the app is always there.
      </p>
      {error && <Callout tone="problem">{error}</Callout>}
      {!loading && mailEnabled === false && (
        <Callout tone="attention" title="Email is switched off for this deployment">
          Nothing below will be emailed yet. Your choices are saved and apply once the practice
          switches email on; the notifications in the app are not affected.
        </Callout>
      )}
      {loading ? (
        <p className="flex items-center gap-2 text-xs text-ps-hint"><Loader2 className="animate-spin" size={12} /> Loading…</p>
      ) : (
        <ul className="divide-y divide-ps-border">
          {events.map((ev) => (
            <li key={ev.event_type} className="flex items-start justify-between gap-4 py-2.5">
              <div className="min-w-0">
                <p className="text-sm text-ps-ink">{ev.label}</p>
                <p className="text-xs text-ps-hint mt-0.5">
                  {ev.description}{" "}
                  <span className="text-ps-disabled">
                    {ev.is_default ? "(the default)" : "(your choice)"}
                  </span>
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={ev.email_enabled}
                aria-label={`Email me when: ${ev.label}`}
                disabled={saving === ev.event_type}
                onClick={() => toggle(ev)}
                className={`shrink-0 mt-0.5 inline-flex h-5 w-9 items-center rounded-full border transition-colors disabled:opacity-60 ${
                  ev.email_enabled ? "bg-brand border-brand" : "bg-ps-muted border-ps-border"
                }`}
              >
                <span
                  className={`h-4 w-4 rounded-full bg-white shadow transition-transform ${
                    ev.email_enabled ? "translate-x-4" : "translate-x-0.5"
                  }`}
                />
              </button>
            </li>
          ))}
          {events.length === 0 && !error && (
            <li className="py-3 text-xs text-ps-hint">No email settings are available right now.</li>
          )}
        </ul>
      )}
      {!loading && (
        <div className="border-t border-ps-border pt-3">
          <h3 className="text-xs font-semibold text-ps-body">Sent to you recently</h3>
          {sent.length === 0 ? (
            <p className="mt-1 text-xs text-ps-hint">Nothing yet.</p>
          ) : (
            <ul className="mt-1 space-y-0.5">
              {sent.map((row) => (
                <li key={row.id} className="flex justify-between gap-3 text-xs text-ps-label">
                  <span>{row.event_type.replace(/_/g, " ")}</span>
                  <span className={row.status === "failed" ? "text-state-problem" : "text-ps-hint"}>
                    {row.status === "failed" ? "could not be delivered" : "sent"} · {row.sent_for_date}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
