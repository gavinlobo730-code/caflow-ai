"use client";

/**
 * Interest on an overdue customer balance (accounting-22).
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Which invoices are late, from which
 * date, for how many days, at what figure and which are left out are
 * `domain/sales/late_interest.py`'s answers, served by the preview with the
 * day-count convention stated on every one. What lives here is a date box, a
 * table of what the server returned, a terms form that turns typed text into
 * two integers (`lib/sales/lateInterest`), and one button.
 *
 * NOTHING IS POSTED, ISSUED OR EMAILED FROM HERE. "Prepare draft invoice" makes
 * an ordinary DRAFT sales invoice through the sales engine; it changes no ledger
 * until somebody issues it from the Sales Invoices tab, and the CA still has to
 * type the real invoice number. The preview is a worklist, not a bill.
 *
 * A BLANK RATE IS NOT A ZERO RATE. A customer with overdue invoices and no rate
 * is LISTED, with the balance the rate would apply to and no figure — a nil that
 * means "nobody can tell" must not look like a nil that means "none".
 */
import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Loader2, RefreshCw } from "lucide-react";
import {
  api,
  type LateInterestDocument,
  type LateInterestDrafts,
  type LateInterestParty,
  type LateInterestPreview,
  type LateInterestTerms,
} from "@/lib/api";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { todayLocalISO } from "@/lib/dateMath";
import { dayLabel } from "@/lib/dates/dayLabel";
import { formatPaise } from "@/lib/money/format";
import { BASIS_CHOICES, ratePercentText, termsPayload, type TermsText } from "@/lib/sales/lateInterest";
import { Button } from "@/components/ui/button";
import { Callout, StatutoryNotes } from "@/components/ui/callout";
import { EmptyStateAction, EmptyStateActions } from "@/components/ui/empty-state-action";
import { EmptyState } from "@/components/ui/states";
import type { SingleFlight } from "@/lib/async/singleFlight";
import { useSingleFlight } from "@/lib/async/useSingleFlight";

type Msg = { type: "ok" | "err"; text: string } | null;

/** The server's status words, for the eye. A status this build has not heard of
 *  is shown as the server sent it rather than hidden. */
const STATUS_LABEL: Record<string, string> = {
  charge: "Interest due",
  covered: "Already drafted to this date",
  rounds_to_nil: "Under half a paisa",
  waived: "Waived (rate 0)",
  no_terms: "No rate on record",
  interest_invoice: "Interest invoice (not a base)",
  undated: "No date to count from",
  not_overdue: "Not overdue",
};

function statusLabel(s: string): string {
  return STATUS_LABEL[s] ?? s.replace(/_/g, " ");
}

function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "Something went wrong. Please try again.";
}

function termsText(t: LateInterestTerms): TermsText {
  return { rate: ratePercentText(t.rate_bps), grace: String(t.grace_days), basis: t.basis };
}

export default function OverdueInterestPanel({
  clientId,
  onOpenInvoice,
}: {
  clientId: string;
  /** Opens a draft on the Sales Invoices tab. Supplied by the page, which owns
   *  the tab state and the address bar. */
  onOpenInvoice?: (invoiceId: string) => void;
}) {
  const [asOf, setAsOf] = useState(todayLocalISO());
  const [preview, setPreview] = useState<LateInterestPreview | null>(null);
  const [terms, setTerms] = useState<LateInterestTerms[]>([]);
  const [edits, setEdits] = useState<Record<string, TermsText>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState<string | null>(null);
  // One guard over the panel's two writes: saving a customer's terms and preparing a
  // draft interest invoice (which is read against those very terms). `busy` alone takes
  // a render to reach the DOM, and a second click in that gap makes a second draft.
  const { flight } = useSingleFlight();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [showTerms, setShowTerms] = useState(false);
  const [drafted, setDrafted] = useState<LateInterestDrafts | null>(null);

  const load = useCallback(async () => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(asOf)) return;
    setLoading(true);
    setLoadError(null);
    try {
      const [p, t] = await Promise.all([
        api.lateInterest.preview(clientId, asOf),
        api.lateInterest.terms(clientId),
      ]);
      if (p.success && p.data) {
        setPreview(objectWithLists<LateInterestPreview>(p.data, "parties", "caveats", "gaps"));
      } else {
        setLoadError(p.error || "Interest could not be worked out.");
      }
      if (t.success && t.data) {
        const loaded = objectWithLists<{ customers: LateInterestTerms[] }>(t.data, "customers");
        const list = loaded ? loaded.customers : [];
        setTerms(list);
        // A box the CA is typing in must not be overwritten by a refresh.
        setEdits((prev) => {
          const next: Record<string, TermsText> = {};
          for (const row of list) next[row.customer_id] = prev[row.customer_id] ?? termsText(row);
          return next;
        });
      }
    } catch (e) {
      setLoadError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [clientId, asOf]);

  useEffect(() => { void load(); }, [load]);

  async function saveTerms(customerId: string) {
    const edit = edits[customerId];
    if (!edit) return;
    const payload = termsPayload(edit);
    if (!payload.ok) { setMsg({ type: "err", text: payload.error }); return; }
    setBusy(`terms:${customerId}`);
    setMsg(null);
    try {
      const r = await api.lateInterest.setTerms({
        client_id: clientId, customer_id: customerId,
        rate_bps: payload.rate_bps, grace_days: payload.grace_days, basis: payload.basis,
      });
      if (!r.success) throw new Error(r.error || "The terms were not saved.");
      setMsg({ type: "ok", text: "Interest terms saved." });
      setEdits((prev) => { const next = { ...prev }; delete next[customerId]; return next; });
      await load();
    } catch (e) {
      setMsg({ type: "err", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function prepare(party: LateInterestParty) {
    setBusy(`draft:${party.customer_id}`);
    setMsg(null);
    setDrafted(null);
    try {
      const r = await api.lateInterest.prepareDrafts({
        client_id: clientId, customer_id: party.customer_id, as_of_date: asOf,
      });
      if (!r.success || !r.data) throw new Error(r.error || "No draft was made.");
      const data = r.data;
      setDrafted({
        ...data,
        drafts: arrayOrEmpty(data.drafts),
        not_drafted: arrayOrEmpty(data.not_drafted),
        failed: arrayOrEmpty(data.failed),
        caveats: arrayOrEmpty(data.caveats),
      });
      await load();
    } catch (e) {
      setMsg({ type: "err", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  const parties = preview ? preview.parties : [];
  const gaps = preview ? preview.gaps : [];
  const caveats = preview ? preview.caveats : [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink">Interest on overdue balances</h2>
          <p className="mt-0.5 max-w-2xl text-xs text-ps-label">
            What each customer owes in interest on invoices still open past their due date,
            as at a date. Nothing is posted or invoiced from this screen.
          </p>
        </div>
        <div className="ml-auto flex items-end gap-2">
          <label className="text-2xs text-ps-label">
            As at
            <input
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="mt-0.5 block rounded-lg border border-ps-border px-2 py-1.5 text-xs"
            />
          </label>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-1 rounded-lg border border-ps-border px-2 py-1.5 text-xs text-ps-label hover:bg-ps-bg disabled:opacity-50"
          >
            {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            Refresh
          </button>
        </div>
      </div>

      {msg && (
        <Callout tone={msg.type === "ok" ? "note" : "problem"}>{msg.text}</Callout>
      )}
      {loadError && <Callout tone="problem">{loadError}</Callout>}

      {preview && (
        <Callout tone="note" title="How this is worked out">
          <p>{preview.convention?.statement}</p>
          {preview.statutory_reading && (
            <p className="mt-1.5">
              <span className="font-medium">{preview.statutory_reading.section}</span>{" "}
              <span className="font-mono">{preview.statutory_reading.grade}</span>{" "}
              {preview.statutory_reading.text}
            </p>
          )}
        </Callout>
      )}

      <StatutoryNotes gaps={gaps} caveats={caveats} title="Not worked out" bulleted />

      {drafted && (
        <div className="space-y-2 rounded-lg border border-ps-border p-3">
          <h3 className="text-xs font-semibold text-ps-ink">
            {drafted.drafts.length === 1 ? "1 draft invoice prepared" : `${drafted.drafts.length} draft invoices prepared`}
          </h3>
          <ul className="space-y-1 text-xs">
            {drafted.drafts.map((d) => (
              <li key={d.invoice_id} className="flex flex-wrap items-center gap-2">
                <FileText size={12} className="text-ps-label" aria-hidden />
                <span className="font-mono">{d.invoice_no ?? "Draft"}</span>
                <span>
                  {formatPaise(d.interest_paise)} interest
                  {d.invoice_nos.length > 0 && <> on {d.invoice_nos.join(", ")}</>}
                </span>
                {onOpenInvoice && (
                  <button
                    type="button"
                    onClick={() => onOpenInvoice(d.invoice_id)}
                    className="font-medium text-brand underline"
                  >
                    Review draft
                  </button>
                )}
              </li>
            ))}
          </ul>
          <p className="text-xs text-ps-label">
            These are drafts. They post nothing until you issue them, and each needs its real
            invoice number first.
          </p>
          {drafted.not_drafted.length > 0 && (
            <Callout tone="attention" title="Not drafted — raise these by hand">
              <ul className="list-disc space-y-1 pl-4">
                {drafted.not_drafted.map((b) => <li key={b.invoice_id}>{b.reason}</li>)}
              </ul>
            </Callout>
          )}
          {drafted.failed.length > 0 && (
            <Callout tone="problem" title="Not drafted">
              <ul className="list-disc space-y-1 pl-4">
                {drafted.failed.map((f, i) => <li key={i}>{f.reason}</li>)}
              </ul>
            </Callout>
          )}
        </div>
      )}

      {loading && !preview ? (
        <p className="p-4 text-sm text-ps-hint">Working out interest…</p>
      ) : parties.length === 0 ? (
        <p className="p-4 text-sm text-ps-hint">
          Nothing is overdue as at {dayLabel(asOf)}.
        </p>
      ) : (
        <div className="overflow-x-auto rounded border border-ps-border">
          <table className="w-full text-sm">
            <thead className="bg-ps-muted text-left text-xs uppercase text-ps-hint">
              <tr>
                <th className="px-3 py-2" aria-label="Invoices" />
                <th className="px-3 py-2">Customer</th>
                <th className="px-3 py-2">Rate</th>
                <th className="px-3 py-2 text-right">Overdue balance</th>
                <th className="px-3 py-2 text-right">Interest</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {parties.map((p) => {
                const docs: LateInterestDocument[] = arrayOrEmpty(p.documents);
                const isOpen = !!open[p.customer_id];
                return (
                  <PartyRows
                    key={p.customer_id}
                    party={p}
                    docs={docs}
                    isOpen={isOpen}
                    onToggle={() => setOpen((o) => ({ ...o, [p.customer_id]: !isOpen }))}
                    busy={busy === `draft:${p.customer_id}`}
                    anyBusy={busy !== null}
                    flight={flight}
                    onPrepare={() => prepare(p)}
                  />
                );
              })}
            </tbody>
            {preview && (
              <tfoot>
                <tr className="border-t border-ps-border bg-ps-muted text-xs font-medium">
                  <td className="px-3 py-2" />
                  <td className="px-3 py-2">Total</td>
                  <td className="px-3 py-2" />
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatPaise(preview.totals?.overdue_outstanding_paise)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatPaise(preview.totals?.interest_paise)}
                  </td>
                  <td className="px-3 py-2" />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}

      <div>
        <button
          type="button"
          onClick={() => setShowTerms((v) => !v)}
          className="inline-flex items-center gap-1 text-xs font-medium text-ps-body hover:text-ps-ink"
          aria-expanded={showTerms}
        >
          {showTerms ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          Interest terms for each customer
        </button>
        {showTerms && (
          <div className="mt-2 overflow-x-auto rounded border border-ps-border">
            <table className="w-full text-sm">
              <thead className="bg-ps-muted text-left text-xs uppercase text-ps-hint">
                <tr>
                  <th className="px-3 py-2">Customer</th>
                  <th className="px-3 py-2">Rate a year (%)</th>
                  <th className="px-3 py-2">Grace (days)</th>
                  <th className="px-3 py-2">Count</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {terms.length === 0 && (
                  <tr><td colSpan={5}>
                    <EmptyState
                      className="py-8"
                      title="No customers yet"
                      description="Interest is worked out per customer, from the rate and grace period recorded for each. Add this client's customers first, then set their terms here."
                      action={
                        <EmptyStateActions>
                          {/* The Customers tab of this same screen: ?tab= is the one deep-link convention
                              (decision D10: no new route under /clients/[id]), and a customer is added by
                              whoever may write the client's records. */}
                          <EmptyStateAction requires={["client", "write"]} label="Add Customers"
                            href={`/clients/${clientId}/sales?tab=customers`} />
                        </EmptyStateActions>
                      }
                    />
                  </td></tr>
                )}
                {terms.map((t) => {
                  const edit = edits[t.customer_id] ?? termsText(t);
                  const set = (patch: Partial<TermsText>) =>
                    setEdits((prev) => ({ ...prev, [t.customer_id]: { ...edit, ...patch } }));
                  return (
                    <tr key={t.customer_id} className="border-t border-ps-border">
                      <td className="px-3 py-2">{t.customer_name ?? "—"}</td>
                      <td className="px-3 py-2">
                        <input
                          inputMode="decimal"
                          value={edit.rate}
                          onChange={(e) => set({ rate: e.target.value })}
                          placeholder="none"
                          aria-label={`Annual interest rate for ${t.customer_name ?? "customer"}`}
                          className="w-20 rounded border border-ps-border px-2 py-1 text-xs"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <input
                          inputMode="numeric"
                          value={edit.grace}
                          onChange={(e) => set({ grace: e.target.value })}
                          aria-label={`Grace days for ${t.customer_name ?? "customer"}`}
                          className="w-16 rounded border border-ps-border px-2 py-1 text-xs"
                        />
                      </td>
                      <td className="px-3 py-2">
                        <select
                          value={edit.basis}
                          onChange={(e) => set({ basis: e.target.value })}
                          aria-label={`Count interest from, for ${t.customer_name ?? "customer"}`}
                          className="rounded border border-ps-border px-2 py-1 text-xs"
                        >
                          {BASIS_CHOICES.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
                        </select>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Button
                          variant="plain" size="none" spinner={false} flight={flight}
                          type="button"
                          onClick={() => saveTerms(t.customer_id)}
                          disabled={busy !== null}
                          className="rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50"
                        >
                          {busy === `terms:${t.customer_id}` ? "Saving…" : "Save"}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="border-t border-ps-border p-2 text-2xs text-ps-hint">
              Leave the rate empty if no interest is agreed. Type 0 to record that interest is
              waived for this customer — the two are different.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function PartyRows({
  party, docs, isOpen, onToggle, busy, anyBusy, onPrepare, flight,
}: {
  party: LateInterestParty;
  docs: LateInterestDocument[];
  isOpen: boolean;
  onToggle: () => void;
  busy: boolean;
  anyBusy: boolean;
  /** Handed back to the Button, which holds the promise it returns: a second click
   *  while the draft is being made is ignored, not queued. */
  onPrepare: () => unknown;
  /** The panel's shared guard, so Save terms and Prepare cannot run together. */
  flight: SingleFlight;
}) {
  const hasInterest = party.interest_paise > 0;
  return (
    <>
      <tr className="border-t border-ps-border">
        <td className="px-3 py-2">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={isOpen}
            aria-label={`${isOpen ? "Hide" : "Show"} the overdue invoices of ${party.customer_name ?? "this customer"}`}
            className="text-ps-label hover:text-ps-ink"
          >
            {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        </td>
        <td className="px-3 py-2">{party.customer_name ?? "—"}</td>
        <td className="px-3 py-2 text-xs">
          {party.terms_set && party.terms
            ? `${ratePercentText(party.terms.rate_bps)}% a year${party.terms.grace_days ? `, ${party.terms.grace_days} days grace` : ""}`
            : <span className="text-state-attention">No rate on record</span>}
        </td>
        <td className="px-3 py-2 text-right tabular-nums">{formatPaise(party.overdue_outstanding_paise)}</td>
        <td className="px-3 py-2 text-right tabular-nums">
          {party.terms_set ? formatPaise(party.interest_paise) : "—"}
        </td>
        <td className="px-3 py-2 text-right">
          <Button
            variant="plain" size="none" spinner={false} flight={flight}
            type="button"
            onClick={() => onPrepare()}
            disabled={!hasInterest || anyBusy}
            title={hasInterest
              ? "Make a draft sales invoice for this interest. Nothing is posted until it is issued."
              : "There is no interest to draft as at this date."}
            className="inline-flex items-center gap-1 rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />}
            Prepare draft invoice
          </Button>
        </td>
      </tr>
      {isOpen && (
        <tr className="bg-ps-bg/40">
          <td />
          <td colSpan={5} className="px-3 py-2">
            <table className="w-full text-xs">
              <thead className="text-left text-2xs uppercase text-ps-hint">
                <tr>
                  <th className="py-1 pr-3">Invoice</th>
                  <th className="py-1 pr-3">Due</th>
                  <th className="py-1 pr-3 text-right">Open balance</th>
                  <th className="py-1 pr-3 text-right">Days late</th>
                  <th className="py-1 pr-3 text-right">Days charged</th>
                  <th className="py-1 pr-3 text-right">Interest</th>
                  <th className="py-1">Status</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.invoice_id} className="border-t border-ps-border align-top">
                    <td className="py-1 pr-3 font-mono">{d.invoice_no ?? "—"}</td>
                    <td className="py-1 pr-3">{dayLabel(d.due_date ?? d.invoice_date)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatPaise(d.outstanding_paise)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{d.days_late}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{d.days_charged}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{formatPaise(d.interest_paise)}</td>
                    <td className="py-1">
                      {statusLabel(d.status)}
                      {d.period_from && d.period_to && d.status === "charge" && (
                        <span className="block text-ps-hint">
                          after {dayLabel(d.period_from)} to {dayLabel(d.period_to)}
                        </span>
                      )}
                      {d.already_charged_through && (
                        <span className="block text-ps-hint">
                          drafted through {dayLabel(d.already_charged_through)}
                        </span>
                      )}
                      {d.start_note && <span className="block text-ps-hint">{d.start_note}</span>}
                      {d.note && <span className="block text-ps-hint">{d.note}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </>
  );
}
