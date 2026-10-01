"use client";

/**
 * Which engagement a recorded hour belongs to (practice_management-11).
 *
 * The picker holds NO rule. It shows what `GET /api/time-entries/engagement-choices`
 * served: the client's live engagements and the one the server will default to.
 * An empty value means "let the server default" — the client's single active
 * engagement — and when the server cannot default (none live, or several) it says
 * why in its own words, because a wrong guess would price the hour under another
 * engagement's rate.
 *
 * The engagement's billing-rate OVERRIDE is not shown here: it is fee economics
 * (`billing:write`) and the person choosing where an hour goes does not need it.
 */
import { useEffect, useState } from "react";
import { getEngagementChoices, type EngagementChoices } from "@/lib/data/timeTracking";

export function EngagementPicker({
  clientId, value, onChange, id,
}: {
  clientId: string;
  value: string;
  onChange: (engagementId: string) => void;
  id: string;
}) {
  const [choices, setChoices] = useState<EngagementChoices | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    onChange("");
    setChoices(null);
    setFailed(false);
    if (!clientId) return;
    let stale = false;
    getEngagementChoices(clientId)
      .then((c) => { if (!stale) setChoices(c); })
      .catch(() => { if (!stale) setFailed(true); });
    return () => { stale = true; };
    // `onChange` is a state setter from the caller; the client is what re-asks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  if (!clientId) return null;
  if (failed) {
    return (
      <p className="text-2xs text-ps-hint">
        The client&apos;s engagements could not be loaded, so none will be recorded on this entry.
      </p>
    );
  }
  if (!choices) return <p className="text-2xs text-ps-hint">Loading engagements…</p>;
  if (choices.engagements.length === 0 && !choices.reason) return null;

  const byId = new Map(choices.engagements.map((e) => [e.id, e]));
  const label = (e: { service_type: string | null; status: string | null }) =>
    `${e.service_type ?? "Engagement"}${e.status ? ` (${e.status})` : ""}`;
  const defaultEngagement = choices.default_engagement_id
    ? byId.get(choices.default_engagement_id)
    : undefined;

  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-ps-body mb-1">Engagement</label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
      >
        <option value="">
          {defaultEngagement ? `${label(defaultEngagement)} — the client's active engagement` : "No engagement chosen"}
        </option>
        {choices.engagements
          .filter((e) => e.id !== choices.default_engagement_id)
          .map((e) => <option key={e.id} value={e.id}>{label(e)}</option>)}
      </select>
      {choices.reason && !value && (
        <p className="text-2xs text-ps-label mt-1">{choices.reason}</p>
      )}
    </div>
  );
}
