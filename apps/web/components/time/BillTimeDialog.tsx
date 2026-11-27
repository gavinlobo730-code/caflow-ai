"use client";

/**
 * Bill a client's unbilled time (POST-B-194, hourly billing).
 *
 * A Partner opens this from the Unbilled Work panel for one client, ticks the entries to bill, chooses how they are laid
 * out on the invoice, names the practice's service and the rate of GST, sees the lines the draft would carry, and makes ONE
 * draft invoice in the firm's own books. The draft is not issued here: it opens in the practice's invoices to be reviewed,
 * numbered and issued.
 *
 * NOTHING IS WORKED OUT HERE. What an hour is worth, which entries may be billed, the lines and their total are the
 * server's (`/api/billing/unbilled-work/entries`, `/time-invoices/preview`, `/time-invoices`). The dialog sends what was
 * ticked and typed and shows what comes back; an entry the server says cannot be billed yet is listed with the server's
 * reason and has no tick. A total is shown only when the server has previewed THESE ticks: after a tick changes, the old
 * preview is not shown as if it were the new one.
 *
 * NO RATE OF GST IS ASSUMED. The box starts from the rate recorded against the chosen service in the practice's own
 * catalogue, when one is; otherwise it starts empty, and the draft cannot be made until a rate is typed.
 */
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { LoadingRegion, SkeletonText } from "@/components/ui/skeleton";
import { formatPaise } from "@/lib/money/format";
import { formatDate } from "@/lib/dates/format";
import { formatDuration } from "@/lib/data/timeTracking";
import { failureSentence } from "@/lib/api/failureSentence";
import { practiceSalesHref } from "@/lib/invoices/workspaceNav";
import { gstRateToPercent } from "@/lib/invoices/gst";
import {
  GROUPINGS, GROUPING_LABELS, billableIds, gstPercentTyped, readMade, readPreview, readServices, readUnbilledEntries,
  type Grouping, type PracticeService, type TimeInvoiceMade, type TimeInvoicePreview, type UnbilledEntries,
} from "@/lib/billing/timeInvoice";

export default function BillTimeDialog({ clientId, clientName, onClose, onBilled }: {
  clientId: string;
  clientName: string;
  onClose: () => void;
  /** Called once a draft has been made, so the panel behind re-reads what is still unbilled. */
  onBilled: () => void;
}) {
  const [work, setWork] = useState<UnbilledEntries | null>(null);
  const [services, setServices] = useState<PracticeService[] | null>(null);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [grouping, setGrouping] = useState<Grouping>("by_task");
  const [serviceId, setServiceId] = useState("");
  const [gst, setGst] = useState("");
  const [preview, setPreview] = useState<{ forKey: string; lines: TimeInvoicePreview } | null>(null);
  const [previewProblem, setPreviewProblem] = useState<string | null>(null);
  // Two flags, because they hold different things: while the DRAFT is being made the dialog cannot be closed (a person who
  // closed it would not learn whether their time was billed); while a preview is being read it can.
  const [previewing, setPreviewing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [made, setMade] = useState<TimeInvoiceMade | null>(null);
  const groupingId = useId(), serviceBoxId = useId(), gstId = useId();

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [entries, options] = await Promise.all([api.billing.unbilledEntries(clientId), api.billing.serviceOptions()]);
        if (!live) return;
        const read = entries.success ? readUnbilledEntries(entries.data) : null;
        if (!read) { setLoadProblem(entries.error ?? "This client's unbilled time could not be read."); return; }
        setWork(read);
        setTicked(new Set(billableIds(read.entries ?? [])));
        const list = options.success ? readServices(options.data) : null;
        setServices(list);
        if (list && list.length === 1) choose(list[0]);
      } catch (e) {
        if (live) setLoadProblem(failureSentence(e, "This client's unbilled time could not be read.", "read"));
      }
    })();
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- read once when the dialog opens for this client
  }, [clientId]);

  function choose(service: PracticeService | undefined) {
    setServiceId(service?.id ?? "");
    // The rate recorded against the service is a starting figure the Partner can change; none recorded leaves the box empty.
    setGst(service && service.gstRateBps !== null ? String(gstRateToPercent(service.gstRateBps)) : "");
  }

  const entries = useMemo(() => work?.entries ?? [], [work]);
  const ids = useMemo(() => entries.filter((e) => ticked.has(e.id)).map((e) => e.id), [entries, ticked]);
  // What a preview is OF: the ticks and the layout. A preview of anything else is not shown.
  const key = `${grouping}|${ids.join(",")}`;
  const shown = preview && preview.forKey === key ? preview.lines : null;

  const readPreviewNow = useCallback(async () => {
    if (ids.length === 0) return;
    setPreviewing(true); setPreviewProblem(null);
    try {
      const res = await api.billing.previewTimeInvoice({ client_id: clientId, entry_ids: ids, group_by: grouping });
      const lines = res.success ? readPreview(res.data) : null;
      if (!lines) throw new Error(res.error ?? "The lines could not be worked out.");
      setPreview({ forKey: key, lines });
    } catch (e) {
      setPreview(null);
      setPreviewProblem(failureSentence(e, "The lines could not be worked out.", "read"));
    } finally {
      setPreviewing(false);
    }
  }, [clientId, grouping, ids, key]);

  // The preview follows the ticks and the layout, a moment after the last change.
  useEffect(() => {
    if (!work || ids.length === 0 || made) return;
    const timer = setTimeout(() => { void readPreviewNow(); }, 350);
    return () => clearTimeout(timer);
  }, [work, ids.length, key, made, readPreviewNow]);

  const rate = gstPercentTyped(gst);

  async function create() {
    if (creating || ids.length === 0 || !serviceId || rate === null) return;
    setCreating(true); setProblem(null);
    try {
      const res = await api.billing.createTimeInvoice({ client_id: clientId, entry_ids: ids, group_by: grouping, service_id: serviceId, gst_rate_percent: rate });
      const done = res.success ? readMade(res.data) : null;
      if (!done) throw new Error(res.error ?? "The draft invoice could not be made.");
      setMade(done);
      onBilled();
    } catch (e) {
      setProblem(failureSentence(e, "The draft invoice could not be made."));
    } finally {
      setCreating(false);
    }
  }

  const draftHref = made ? practiceSalesHref(made.practiceClientId, { invoiceId: made.invoiceId }) : null;

  return (
    <Modal
      title={`Bill time: ${clientName}`}
      note="Makes one draft invoice in your firm's own books. Nothing is issued or sent from here."
      onClose={() => { if (!creating) onClose(); }}
      maxWidthClass="max-w-3xl"
      footer={made ? (
        <Button variant="outline" onClick={onClose} disabled={creating}>Close</Button>
      ) : (
        <>
          <Button variant="outline" onClick={onClose} disabled={creating}>Cancel</Button>
          <Button onClick={create} disabled={creating || previewing || !work || ids.length === 0 || !serviceId || rate === null || !shown}>
            {creating ? "Making the draft…" : "Make the draft invoice"}
          </Button>
        </>
      )}
    >
      <div data-bill-time>
        {loadProblem ? (
          <p role="alert" className="text-sm text-state-problem">{loadProblem}</p>
        ) : !work ? (
          <LoadingRegion label="Reading this client's unbilled time"><SkeletonText lines={3} /></LoadingRegion>
        ) : made ? (
          <div role="status" data-bill-time-made>
            <p className="text-sm text-ps-ink font-medium">
              A draft invoice was made for {formatPaise(made.valuePaise)} before GST, billing {made.entriesBilled} time entr{made.entriesBilled === 1 ? "y" : "ies"}.
            </p>
            <p className="text-sm text-ps-body mt-2">
              It is a draft: give it its invoice number, check it and issue it from your practice&apos;s invoices. Deleting the
              draft puts this time back on the unbilled list.
            </p>
            {draftHref && <p className="mt-3"><Link href={draftHref} className="text-sm text-blue-700 hover:underline">Open the draft invoice</Link></p>}
          </div>
        ) : entries.length === 0 ? (
          <p className="text-sm text-ps-hint">This client has no unbilled billable time.</p>
        ) : (
          <div className="space-y-5">
            <div>
              <p className="text-xs font-semibold text-ps-ink mb-2">Time to bill ({ids.length} of {entries.length} ticked)</p>
              <div className="border border-ps-border rounded-lg divide-y max-h-64 overflow-y-auto">
                {entries.map((e) => (
                  <label key={e.id} data-entry={e.id} className="flex items-start gap-3 px-3 py-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={ticked.has(e.id)}
                      disabled={e.blocked !== null}
                      onChange={(ev) => setTicked((old) => { const next = new Set(old); if (ev.target.checked) next.add(e.id); else next.delete(e.id); return next; })}
                    />
                    <span className="flex-1 min-w-0">
                      <span className="block text-gray-800 truncate">
                        {e.day ? formatDate(e.day) : "No date"}{e.userName ? ` · ${e.userName}` : ""}{e.taskTitle ? ` · ${e.taskTitle}` : ""}
                      </span>
                      {e.description && <span className="block text-2xs text-ps-hint truncate">{e.description}</span>}
                      {e.blocked && <span className="block text-2xs text-state-attention">{e.blocked}</span>}
                    </span>
                    <span className="text-xs text-ps-label whitespace-nowrap">{formatDuration(e.minutes)}</span>
                    <span className="text-sm text-gray-800 w-24 text-right whitespace-nowrap">{e.valuePaise === null ? "—" : formatPaise(e.valuePaise)}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="grid sm:grid-cols-3 gap-3">
              <div>
                <label htmlFor={groupingId} className="block text-xs font-medium text-ps-label mb-1">On the invoice</label>
                <select id={groupingId} value={grouping} onChange={(e) => setGrouping(e.target.value as Grouping)} className="w-full border rounded-lg px-2 py-1.5 text-sm">
                  {GROUPINGS.map((g) => <option key={g} value={g}>{GROUPING_LABELS[g]}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor={serviceBoxId} className="block text-xs font-medium text-ps-label mb-1">Billed as (your practice&apos;s service)</label>
                {services === null ? (
                  <p className="text-xs text-state-problem">Your practice&apos;s services could not be read.</p>
                ) : services.length === 0 ? (
                  <p className="text-xs text-ps-hint">Your practice has no services yet. Add one in My practice, under Products and services, then come back.</p>
                ) : (
                  <select id={serviceBoxId} value={serviceId} onChange={(e) => choose(services.find((s) => s.id === e.target.value))} className="w-full border rounded-lg px-2 py-1.5 text-sm">
                    <option value="">Choose a service</option>
                    {services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                )}
              </div>
              <div>
                <label htmlFor={gstId} className="block text-xs font-medium text-ps-label mb-1">GST rate (%)</label>
                <input id={gstId} inputMode="decimal" value={gst} onChange={(e) => setGst(e.target.value)}
                  aria-invalid={gst.trim() !== "" && rate === null} className="w-full border rounded-lg px-2 py-1.5 text-sm" />
                {gst.trim() !== "" && rate === null && <p className="text-2xs text-state-problem mt-1">Enter the rate as a number between 0 and 100.</p>}
              </div>
            </div>

            <div data-bill-time-preview>
              <p className="text-xs font-semibold text-ps-ink mb-2">The draft&apos;s lines</p>
              {ids.length === 0 ? (
                <p className="text-sm text-ps-hint">Tick at least one entry.</p>
              ) : previewProblem ? (
                <p role="alert" className="text-sm text-state-problem">{previewProblem}</p>
              ) : !shown ? (
                <LoadingRegion label="Working out the lines" className="text-sm text-ps-hint">Working out the lines…</LoadingRegion>
              ) : (
                <div className="border border-ps-border rounded-lg divide-y">
                  {shown.lines.map((line, i) => (
                    <div key={i} className="flex items-center gap-3 px-3 py-2 text-sm">
                      <span className="flex-1 min-w-0 text-gray-800">{line.description}</span>
                      <span className="w-28 text-right whitespace-nowrap">{formatPaise(line.valuePaise)}</span>
                    </div>
                  ))}
                  <div className="flex items-center gap-3 px-3 py-2 text-sm font-semibold">
                    <span className="flex-1">Before GST, for {formatDuration(shown.minutes)}</span>
                    <span className="w-28 text-right whitespace-nowrap" data-bill-time-total>{formatPaise(shown.valuePaise)}</span>
                  </div>
                </div>
              )}
              <p className="text-2xs text-ps-hint mt-2">
                Each line is the worth of its time as it was recorded, added up. GST is charged on the draft at the rate above
                and can still be changed on the draft before it is issued.
              </p>
            </div>

            {problem && <p role="alert" className="text-sm text-state-problem">{problem}</p>}
          </div>
        )}
      </div>
    </Modal>
  );
}
