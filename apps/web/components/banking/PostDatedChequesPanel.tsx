"use client";

/**
 * The post-dated cheque register (accounting-21).
 *
 * A POST-DATED CHEQUE IS A MEMORANDUM, AND THIS SCREEN SAYS SO. Recording,
 * editing and cancelling a cheque posts nothing: the books are the same the day
 * a cheque is recorded as they were the day before. The one act that reaches
 * them is "Convert", on a cheque that is DUE, and the server does it through the
 * ordinary receipt (cheque received) or vendor-payment (cheque issued) engine —
 * so the journal, the invoice settlement, the closed-year check and the GST
 * advance rules are exactly those of a receipt typed on the Receipts screen.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Whether a cheque is due or stale is
 * the server's answer (`state`, `is_due`, `is_stale`), worked out against the
 * firm's own IST day: a browser comparing a cheque's date with its own clock
 * would be reading somebody else's day. What is typed is turned into integers
 * by `lib/money/rupeeInput`; every bound, and every refusal, is the server's and
 * arrives as its own sentence.
 *
 * THE ALLOCATIONS ARE INTENT, NOT A CLAIM. They name the invoices (or bills) the
 * cheque is meant for. Nothing is reserved against them; the server re-checks
 * each against what the document still owes on the day the cheque is converted.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Plus, RefreshCw, X } from "lucide-react";
import {
  api,
  type PostDatedCheque,
  type PostDatedChequeConversion,
  type PostDatedChequeDirection,
  type PostDatedChequeOptions,
  type PostDatedChequeRegister,
} from "@/lib/api";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { dayLabel } from "@/lib/dates/dayLabel";
import { formatPaise } from "@/lib/money/format";
import { paiseFromRupeeInput, rupeeInputFromPaise } from "@/lib/money/rupeeInput";
import { Button } from "@/components/ui/button";
import { Callout, StatutoryNotes } from "@/components/ui/callout";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { useSingleFlight } from "@/lib/async/useSingleFlight";
import { CustomerLookup } from "@/components/lookups/CustomerLookup";
import { VendorLookup } from "@/components/lookups/VendorLookup";

type Msg = { type: "ok" | "err"; text: string } | null;

const WORDS = {
  received: {
    title: "Post-dated cheques received",
    party: "Customer", docs: "Invoices", docKey: "sales_invoice_id" as const,
    convert: "Convert to receipt", made: "Receipt",
    lead: "Cheques your customers have handed over, dated ahead.",
  },
  issued: {
    title: "Post-dated cheques issued",
    party: "Supplier", docs: "Bills", docKey: "purchase_bill_id" as const,
    convert: "Convert to payment", made: "Payment",
    lead: "Cheques you have given to your suppliers, dated ahead.",
  },
};

const STATE_LABEL: Record<string, string> = {
  due: "Due", not_due: "Not yet due", converted: "Converted", cancelled: "Cancelled",
};

interface FormState {
  partyId: string;
  chequeNo: string;
  chequeDate: string;
  amount: string;
  drawee: string;
  bankAccountId: string;
  notes: string;
  /** document id -> the amount typed against it */
  alloc: Record<string, string>;
}

const BLANK: FormState = {
  partyId: "", chequeNo: "", chequeDate: "", amount: "", drawee: "",
  bankAccountId: "", notes: "", alloc: {},
};

function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "Something went wrong. Please try again.";
}

export default function PostDatedChequesPanel({
  clientId,
  direction,
}: {
  clientId: string;
  direction: PostDatedChequeDirection;
}) {
  const words = WORDS[direction];
  const [register, setRegister] = useState<PostDatedChequeRegister | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const [converted, setConverted] = useState<PostDatedChequeConversion | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  // One guard over every write this panel makes (record, convert, cancel). Converting
  // POSTS a receipt or a vendor payment, so a second click that lands before React has
  // re-rendered `busy` would be a second voucher; `busy` alone cannot stop that.
  const { flight } = useSingleFlight();
  const [showFinished, setShowFinished] = useState(false);
  const [presentedOn, setPresentedOn] = useState("");

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<PostDatedCheque | null>(null);
  const [form, setForm] = useState<FormState>(BLANK);
  const [options, setOptions] = useState<PostDatedChequeOptions | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const r = await api.postDatedCheques.list(clientId, direction, showFinished);
      if (r.success && r.data) {
        setRegister(objectWithLists<PostDatedChequeRegister>(r.data, "cheques", "notes"));
      } else {
        setLoadError(r.error || "The cheque register could not be read.");
      }
    } catch (e) {
      setLoadError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [clientId, direction, showFinished]);

  useEffect(() => { void load(); }, [load]);

  const loadOptions = useCallback(async (partyId?: string) => {
    try {
      const r = await api.postDatedCheques.options(clientId, direction, partyId);
      if (r.success && r.data) {
        setOptions(objectWithLists<PostDatedChequeOptions>(
          r.data, "parties", "bank_accounts", "documents"));
      }
    } catch (e) {
      setMsg({ type: "err", text: errorText(e) });
    }
  }, [clientId, direction]);

  function openNew() {
    setEditing(null);
    setForm(BLANK);
    setFormOpen(true);
    setMsg(null);
    void loadOptions();
  }

  function openEdit(c: PostDatedCheque) {
    const alloc: Record<string, string> = {};
    for (const a of arrayOrEmpty<PostDatedCheque["allocations"][number]>(c.allocations)) {
      const id = a[words.docKey];
      if (id) alloc[id] = rupeeInputFromPaise(a.allocated_paise);
    }
    setEditing(c);
    setForm({
      partyId: (direction === "received" ? c.customer_id : c.vendor_id) ?? "",
      chequeNo: c.cheque_no, chequeDate: c.cheque_date,
      amount: rupeeInputFromPaise(c.amount_paise), drawee: c.drawee_bank ?? "",
      bankAccountId: c.bank_account_id ?? "", notes: c.notes ?? "", alloc,
    });
    setFormOpen(true);
    setMsg(null);
    void loadOptions((direction === "received" ? c.customer_id : c.vendor_id) ?? undefined);
  }

  function closeForm() {
    setFormOpen(false);
    setEditing(null);
    setForm(BLANK);
  }

  function pickParty(partyId: string) {
    setForm((f) => ({ ...f, partyId, alloc: {} }));
    void loadOptions(partyId || undefined);
  }

  const documents = options ? options.documents : [];
  const amountPaise = paiseFromRupeeInput(form.amount);
  const allocatedPaise = useMemo(() => {
    let total = 0;
    for (const text of Object.values(form.alloc)) {
      const p = text.trim() === "" ? 0 : paiseFromRupeeInput(text);
      if (p !== null) total += p;
    }
    return total;
  }, [form.alloc]);

  async function submit() {
    if (!form.partyId && !editing) {
      setMsg({ type: "err", text: `Choose the ${words.party.toLowerCase()} first.` });
      return;
    }
    if (amountPaise === null || amountPaise <= 0) {
      setMsg({ type: "err", text: "The amount is not a valid rupee amount." });
      return;
    }
    const allocations: { sales_invoice_id?: string; purchase_bill_id?: string; allocated_paise: number }[] = [];
    for (const [docId, text] of Object.entries(form.alloc)) {
      if (text.trim() === "") continue;
      const p = paiseFromRupeeInput(text);
      if (p === null || p <= 0) {
        setMsg({ type: "err", text: "An allocation is not a valid rupee amount." });
        return;
      }
      allocations.push({ [words.docKey]: docId, allocated_paise: p });
    }
    setBusy("save");
    setMsg(null);
    try {
      const common = {
        cheque_no: form.chequeNo, cheque_date: form.chequeDate, amount_paise: amountPaise,
        drawee_bank: form.drawee || null, bank_account_id: form.bankAccountId || null,
        notes: form.notes || null, allocations,
      };
      const r = editing
        ? await api.postDatedCheques.update(editing.id, clientId, common)
        : await api.postDatedCheques.create({
            ...common, client_id: clientId, direction,
            ...(direction === "received" ? { customer_id: form.partyId } : { vendor_id: form.partyId }),
          });
      if (!r.success) throw new Error(r.error || "The cheque was not saved.");
      setMsg({ type: "ok", text: editing ? "Cheque updated." : "Cheque recorded. Nothing is posted until it is converted." });
      closeForm();
      await load();
    } catch (e) {
      setMsg({ type: "err", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function convert(c: PostDatedCheque) {
    const ok = await confirmDialog({
      title: words.convert,
      message:
        `Convert cheque ${c.cheque_no} for ${formatPaise(c.amount_paise)} into a ` +
        `${words.made.toLowerCase()}? This posts to the books, dated the day it was presented` +
        `${presentedOn ? ` (${dayLabel(presentedOn)})` : " (today)"}.`,
      confirmLabel: words.convert,
    });
    if (!ok) return;
    setBusy(`convert:${c.id}`);
    setMsg(null);
    setConverted(null);
    try {
      const r = await api.postDatedCheques.convert(c.id, clientId, presentedOn || undefined);
      if (!r.success || !r.data) throw new Error(r.error || "The cheque was not converted.");
      setConverted(r.data);
      await load();
    } catch (e) {
      setMsg({ type: "err", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  async function cancel(c: PostDatedCheque) {
    const ok = await confirmDialog({
      title: "Cancel this cheque?",
      message: `Cheque ${c.cheque_no} for ${formatPaise(c.amount_paise)} comes off the register. ` +
        "Nothing was posted for it, so nothing is reversed.",
      confirmLabel: "Cancel cheque",
      danger: true,
    });
    if (!ok) return;
    setBusy(`cancel:${c.id}`);
    setMsg(null);
    try {
      const r = await api.postDatedCheques.cancel(c.id, clientId);
      if (!r.success) throw new Error(r.error || "The cheque was not cancelled.");
      await load();
    } catch (e) {
      setMsg({ type: "err", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  const cheques = register ? register.cheques : [];
  const notes = register ? register.notes : [];
  const mine = register?.summary?.[direction];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ps-ink">{words.title}</h2>
          <p className="mt-0.5 max-w-2xl text-xs text-ps-label">
            {words.lead} A post-dated cheque is a memorandum: it is not in the books until
            you convert it on or after its date.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-end gap-2">
          <label className="text-2xs text-ps-label">
            Presented on (blank = today)
            <input
              type="date"
              value={presentedOn}
              onChange={(e) => setPresentedOn(e.target.value)}
              className="mt-0.5 block rounded-lg border border-ps-border px-2 py-1.5 text-xs"
            />
          </label>
          <label className="flex items-center gap-1 text-2xs text-ps-label">
            <input
              type="checkbox"
              checked={showFinished}
              onChange={(e) => setShowFinished(e.target.checked)}
            />
            Show converted and cancelled
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
          <button
            type="button"
            onClick={openNew}
            className="inline-flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark"
          >
            <Plus size={12} /> Record a cheque
          </button>
        </div>
      </div>

      {msg && <Callout tone={msg.type === "ok" ? "note" : "problem"}>{msg.text}</Callout>}
      {loadError && <Callout tone="problem">{loadError}</Callout>}

      {converted && (
        <Callout tone="note" title={`${converted.document.kind === "receipt" ? "Receipt" : "Payment"} recorded`}>
          <p>
            {words.made} <span className="font-mono">{converted.document.number ?? ""}</span> for{" "}
            {formatPaise(converted.document.amount_paise)}, dated {dayLabel(converted.document.date)}.
            {converted.document.unallocated_paise
              ? ` ${formatPaise(converted.document.unallocated_paise)} is not allocated to any document.`
              : ""}
          </p>
          {converted.document.posting_account_notice && (
            <p className="mt-1">{converted.document.posting_account_notice}</p>
          )}
          {converted.stale_note && <p className="mt-1">{converted.stale_note}</p>}
        </Callout>
      )}

      {mine && (
        <div className="flex flex-wrap gap-4 text-xs">
          <span>
            <span className="font-medium text-ps-ink">Due now:</span>{" "}
            {mine.due?.count ?? 0} · {formatPaise(mine.due?.amount_paise ?? 0)}
          </span>
          <span>
            <span className="font-medium text-ps-ink">Still to come:</span>{" "}
            {mine.not_due?.count ?? 0} · {formatPaise(mine.not_due?.amount_paise ?? 0)}
          </span>
        </div>
      )}

      <StatutoryNotes caveats={notes} />

      {formOpen && (
        <div className="space-y-3 rounded-lg border border-ps-border p-3">
          <div className="flex items-center">
            <h3 className="text-xs font-semibold text-ps-ink">
              {editing ? `Edit cheque ${editing.cheque_no}` : "Record a cheque"}
            </h3>
            <button type="button" onClick={closeForm} aria-label="Close" className="ml-auto text-ps-label hover:text-ps-ink">
              <X size={14} />
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <span className="text-2xs text-ps-label">{words.party}</span>
              {direction === "received" ? (
                <CustomerLookup
                  customers={(options ? options.parties : []).map((p) => ({ id: p.id, name: p.name ?? "", gstin: p.gstin }))}
                  value={form.partyId}
                  onChange={pickParty}
                  disabled={!!editing}
                  size="sm"
                  ariaLabel="Customer"
                />
              ) : (
                <VendorLookup
                  vendors={(options ? options.parties : []).map((p) => ({ id: p.id, name: p.name ?? "", gstin: p.gstin }))}
                  value={form.partyId}
                  onChange={pickParty}
                  disabled={!!editing}
                  size="sm"
                  ariaLabel="Supplier"
                />
              )}
            </div>
            <label className="text-2xs text-ps-label">
              Cheque number
              <input value={form.chequeNo} onChange={(e) => setForm({ ...form, chequeNo: e.target.value })}
                className="mt-0.5 block w-full rounded-lg border border-ps-border px-2 py-1.5 text-xs" />
            </label>
            <label className="text-2xs text-ps-label">
              Cheque date
              <input type="date" value={form.chequeDate} onChange={(e) => setForm({ ...form, chequeDate: e.target.value })}
                className="mt-0.5 block w-full rounded-lg border border-ps-border px-2 py-1.5 text-xs" />
            </label>
            <label className="text-2xs text-ps-label">
              Amount (₹)
              <input inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })}
                className="mt-0.5 block w-full rounded-lg border border-ps-border px-2 py-1.5 text-xs tabular-nums" />
            </label>
            <label className="text-2xs text-ps-label">
              Drawee bank (as written on the cheque)
              <input value={form.drawee} onChange={(e) => setForm({ ...form, drawee: e.target.value })}
                className="mt-0.5 block w-full rounded-lg border border-ps-border px-2 py-1.5 text-xs" />
            </label>
            <label className="text-2xs text-ps-label">
              {direction === "received" ? "Banked into" : "Drawn on"} (your bank account)
              <select value={form.bankAccountId} onChange={(e) => setForm({ ...form, bankAccountId: e.target.value })}
                className="mt-0.5 block w-full rounded-lg border border-ps-border px-2 py-1.5 text-xs">
                <option value="">Not named</option>
                {(options ? options.bank_accounts : []).map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </select>
            </label>
          </div>
          <label className="block text-2xs text-ps-label">
            Notes
            <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="mt-0.5 block w-full rounded-lg border border-ps-border px-2 py-1.5 text-xs" />
          </label>

          {form.partyId && (
            <div>
              <h4 className="text-2xs font-semibold uppercase text-ps-hint">
                {words.docs} this cheque is meant for (optional)
              </h4>
              {documents.length === 0 ? (
                <p className="mt-1 text-xs text-ps-hint">Nothing is open for this {words.party.toLowerCase()}.</p>
              ) : (
                <table className="mt-1 w-full text-xs">
                  <thead className="text-left text-2xs uppercase text-ps-hint">
                    <tr>
                      <th className="py-1 pr-3">Number</th>
                      <th className="py-1 pr-3">Due</th>
                      <th className="py-1 pr-3 text-right">Still owed</th>
                      <th className="py-1 text-right">This cheque settles (₹)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documents.map((d) => (
                      <tr key={d.id} className="border-t border-ps-border">
                        <td className="py-1 pr-3 font-mono">{d.number ?? "—"}</td>
                        <td className="py-1 pr-3">{dayLabel(d.due_date ?? d.date)}</td>
                        <td className="py-1 pr-3 text-right tabular-nums">{formatPaise(d.outstanding_paise)}</td>
                        <td className="py-1 text-right">
                          <input
                            inputMode="decimal"
                            value={form.alloc[d.id] ?? ""}
                            onChange={(e) => setForm({ ...form, alloc: { ...form.alloc, [d.id]: e.target.value } })}
                            aria-label={`Amount this cheque settles on ${d.number ?? "this document"}`}
                            className="w-28 rounded border border-ps-border px-2 py-1 text-right text-xs tabular-nums"
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="mt-1 text-2xs text-ps-hint">
                Allocated {formatPaise(allocatedPaise)}
                {amountPaise !== null ? ` of ${formatPaise(amountPaise)}` : ""}. This is a note of
                intent: nothing is held against the document, and it is checked against what is
                owed on the day the cheque is converted.
              </p>
            </div>
          )}

          <div className="flex gap-2">
            <Button
              variant="plain" size="none" spinner={false} flight={flight}
              type="button"
              onClick={() => submit()}
              disabled={busy !== null}
              className="inline-flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-dark disabled:opacity-50"
            >
              {busy === "save" && <Loader2 size={12} className="animate-spin" />}
              {editing ? "Save changes" : "Record cheque"}
            </Button>
            <button type="button" onClick={closeForm}
              className="rounded-lg border border-ps-border px-3 py-1.5 text-xs text-ps-label hover:bg-ps-bg">
              Close
            </button>
          </div>
        </div>
      )}

      {loading && !register ? (
        <p className="p-4 text-sm text-ps-hint">Reading the register…</p>
      ) : cheques.length === 0 ? (
        <p className="p-4 text-sm text-ps-hint">
          No post-dated cheques on the register.
        </p>
      ) : (
        <div className="overflow-x-auto rounded border border-ps-border">
          <table className="w-full text-sm">
            <thead className="bg-ps-muted text-left text-xs uppercase text-ps-hint">
              <tr>
                <th className="px-3 py-2">Cheque</th>
                <th className="px-3 py-2">{words.party}</th>
                <th className="px-3 py-2">Drawee bank</th>
                <th className="px-3 py-2">Cheque date</th>
                <th className="px-3 py-2 text-right">Amount</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {cheques.map((c) => (
                <tr key={c.id} className="border-t border-ps-border align-top">
                  <td className="px-3 py-2 font-mono">{c.cheque_no}</td>
                  <td className="px-3 py-2">{c.party_name ?? "—"}</td>
                  <td className="px-3 py-2">{c.drawee_bank ?? "—"}</td>
                  <td className="px-3 py-2">{dayLabel(c.cheque_date)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatPaise(c.amount_paise)}</td>
                  <td className="px-3 py-2 text-xs">
                    <span className={c.is_due ? "font-medium text-state-attention" : ""}>
                      {STATE_LABEL[c.state] ?? c.state}
                    </span>
                    {c.is_stale && c.stale_note && (
                      <span className="block max-w-xs text-state-attention">{c.stale_note}</span>
                    )}
                    {c.status === "held" && c.posting_account_notice && (
                      <span className="block max-w-xs text-ps-hint">{c.posting_account_notice}</span>
                    )}
                    {c.cancel_reason && <span className="block text-ps-hint">{c.cancel_reason}</span>}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {c.status === "held" && (
                      <span className="inline-flex flex-wrap justify-end gap-1">
                        <Button
                          variant="plain" size="none" spinner={false} flight={flight}
                          type="button"
                          onClick={() => convert(c)}
                          disabled={!c.is_due || busy !== null}
                          title={c.is_due
                            ? `Make this an ordinary ${words.made.toLowerCase()}`
                            : "Not due yet: a post-dated cheque is a memorandum until its date."}
                          className="inline-flex items-center gap-1 rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50"
                        >
                          {busy === `convert:${c.id}` && <Loader2 size={12} className="animate-spin" />}
                          {words.convert}
                        </Button>
                        <button type="button" onClick={() => openEdit(c)} disabled={busy !== null}
                          className="rounded-lg border border-ps-border px-2 py-1 text-2xs hover:bg-ps-bg disabled:opacity-50">
                          Edit
                        </button>
                        <Button variant="plain" size="none" spinner={false} flight={flight}
                          type="button" onClick={() => cancel(c)} disabled={busy !== null}
                          className="rounded-lg border border-ps-border px-2 py-1 text-2xs text-state-problem hover:bg-ps-bg disabled:opacity-50">
                          Cancel
                        </Button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
