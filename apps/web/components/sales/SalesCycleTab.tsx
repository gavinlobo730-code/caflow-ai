"use client";

/**
 * The sales cycle BEFORE the tax invoice (SALES-21).
 *
 * WHAT THE PRODUCT COULD NOT DO
 *   The cycle started at the invoice. A client quotes, takes an order,
 *   delivers against it and bills afterwards — and none of the first three
 *   documents existed, so the CA either raised the tax invoice EARLY
 *   (declaring a supply that had not happened) or kept the quotation in a
 *   spreadsheet and re-typed every line when it converted.
 *
 * THIS SCREEN DECIDES NOTHING (CLAUDE.md). Which of CGST Rule 55's movements
 * a challan covers, what that document must contain, whether its lines carry
 * tax, and which deemed-supply clock is running are all
 * `domain/gst/delivery_challan.py`'s answers, served through
 * `GET /api/sales-cycle/vocabulary` so no label lives here.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";
import { AlertTriangle, Clock, FileText, Info, Plus, Truck, X } from "lucide-react";
import {
  api,
  type ChallanParticulars,
  type DeliveryChallan,
  type OrderPosition,
  type SalesCycleVocabulary,
  type SalesOrder,
  type SalesQuotation,
} from "@/lib/api";
import { paiseFromRupeeInput, parseQuantity } from "@/lib/money/rupeeInput";
import { Itc04Panel } from "@/components/gst/Itc04Panel";
import { StateLookup } from "@/components/lookups/StateLookup";
import { Button } from "@/components/ui/button";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { DraftChallanEditor } from "@/components/sales/DraftChallanEditor";
import { DateInput } from "@/components/ui/date-input";
import { useDateProblems, useDateRefusal } from "@/lib/dates/useDateProblems";
import { formatDate, todayIstISO } from "@/lib/dates/format";

type Tab = "quotations" | "orders" | "challans";
type Msg = { type: "ok" | "err"; text: string } | null;

interface Customer { id: string; name?: string; customer_name?: string }

const BLANK_LINE = { description: "", hsn_sac: "", quantity: "1", unit: "NOS",
                     rate: "", gst_rate_percent: "18" };

function rupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function SalesCycleTab({ clientId }: { clientId: string }) {
  const [tab, setTab] = useState<Tab>("quotations");
  const [vocab, setVocab] = useState<SalesCycleVocabulary | null>(null);
  const [quotations, setQuotations] = useState<SalesQuotation[]>([]);
  const [orders, setOrders] = useState<SalesOrder[]>([]);
  const [challans, setChallans] = useState<DeliveryChallan[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  // Text that is not a date reads as blank to the form (frontend_ux-19).
  const dates = useDateProblems();
  // The date each open challan was recorded back on, typed and not yet sent, and the unreadable ones: a box of its own for each challan, so
  // one challan's unreadable date holds that challan's button and nothing else.
  const [backOn, setBackOn] = useState<Record<string, string>>({});
  const backDates = useDateProblems();
  // The challan whose "Record goods back" was pressed last, and what the server answered that press with, for WHICH challan (the answer to an attempt: cleared by the next
  // press). Each is said in its own challan's row, beside the button that raised it: with many challans open the block's end is out of sight of the button, and a late answer
  // to one challan must not stand in another's row.
  const [backTried, setBackTried] = useState<string | null>(null);
  const [backAnswer, setBackAnswer] = useState<{ id: string; text: string } | null>(null);
  const backNo = challans.find((c) => c.id === backTried)?.document_no;
  const backProblem = backTried === null ? null
    : (backDates.problems[`back-${backTried}`] ?? ((backOn[backTried] ?? "") ? null : `Enter the date the goods on ${backNo ?? "the challan"} came back.`));
  const backRefusal = useDateRefusal(backProblem);
  /** What is said in one challan's row: the server's answer to the press on THAT challan (named, because the server's sentence names no challan), or else the sentence about its box. */
  const backSaid = (c: DeliveryChallan): string | null =>
    (backAnswer && backAnswer.id === c.id ? `${c.document_no}: ${backAnswer.text}` : null) || (backTried === c.id ? backRefusal.shown : null);
  const [detail, setDetail] = useState<ChallanParticulars | null>(null);
  // What the server answered the last press of "Issue challan" with, for WHICH challan: said beside the button that raised it, in the open detail (POST-A-398).
  const [issueAnswer, setIssueAnswer] = useState<{ id: string; text: string } | null>(null);
  // The same for "Cancel draft" (POST-A-417), and whether the draft's correction form is open (it is the open detail's, and closes with it).
  const [cancelAnswer, setCancelAnswer] = useState<{ id: string; text: string } | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const [position, setPosition] = useState<OrderPosition | null>(null);

  const [form, setForm] = useState({
    kind: "quotation",
    customer_id: "",
    document_no: "",
    document_date: "",
    valid_until: "",
    customer_po_no: "",
    expected_delivery_date: "",
    reason: "job_work",
    goods_kind: "",
    consignee_name: "",
    consignee_gstin: "",
    consignee_address: "",
    transporter_name: "",
    vehicle_no: "",
    is_inter_state: false,
    place_of_supply: "",
    notes: "",
  });
  const [lines, setLines] = useState([{ ...BLANK_LINE }]);

  // The tab shows "Loading…" for the FIRST read of a client's lists and keeps itself drawn for every read after it (POST-A-385). A reload replaced the whole tab with "Loading…", which unmounted the
  // FORM GST ITC-04 panel inside it: recording a lot calls `onChanged` (this reload), so the panel's "Recorded. That was the last lot — … its s.143 clock has stopped." line, the year and window it had
  // chosen and any other open lot form were lost, and the person saw the list change without being told it had worked. Keyed by the client, because a tab reused for another client must not show
  // the last client's lists while the new ones load.
  const loadedFor = useRef<string | null>(null);
  // Which read is the latest: a reload can be asked for while an earlier one is in flight (the panel does not wait for it), and the last ANSWER must not win over the last QUESTION.
  const latestRead = useRef(0);
  // Bumped when a reload has landed, so the ITC-04 panel inside the tab reads its statement again: it is derived from the challans this tab changes ("Record goods back", a new
  // job-work challan), and before POST-A-385 it was re-read only because the reload unmounted and remounted it. A prop, not a key, so the panel keeps what it has said.
  const [itc04Refresh, setItc04Refresh] = useState(0);
  const load = useCallback(async () => {
    const mine = ++latestRead.current;
    if (loadedFor.current !== clientId) setLoading(true);
    setLoadFailed(false);
    try {
      const [v, q, o, c, cust] = await Promise.all([
        api.salesCycle.vocabulary(),
        api.salesCycle.quotations(clientId),
        api.salesCycle.orders(clientId),
        api.salesCycle.challans(clientId),
        api.customers.list(clientId),
      ]);
      if (mine !== latestRead.current) return;   // a later read has been asked for: its answer is the one to show
      if (v.success && v.data) setVocab(objectWithLists<SalesCycleVocabulary>(v.data, "challan_reasons", "goods_kinds", "quote_kinds"));
      if (q.success && q.data) setQuotations(arrayOrEmpty(q.data));
      if (o.success && o.data) setOrders(arrayOrEmpty(o.data));
      if (c.success && c.data) setChallans(arrayOrEmpty(c.data));
      if (cust.success && cust.data) setCustomers(arrayOrEmpty<Customer>(cust.data));
      // Only a read that CAME BACK counts as the first: "Try again" after a failed first read blocks with "Loading…" again, and does not show lists that were never read as empty ones.
      loadedFor.current = clientId;
      setItc04Refresh((n) => n + 1);
    } catch {
      if (mine !== latestRead.current) return;
      // A failed read, first or later, is answered with the could-not-be-loaded box; "Try again" is then a first read again and blocks with "Loading…" until it answers.
      loadedFor.current = null;
      setLoadFailed(true);
    } finally {
      if (mine === latestRead.current) setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { void load(); }, [load]);

  /** Every challan whose s.143 or s.31(7) period has run out and whose goods
   *  are not back. This is the figure the whole feature exists for: nothing in
   *  a ledger shows it, because no journal was ever posted. */
  const overdue = useMemo(
    () => challans.filter((c) => c.clock?.overdue === true && !c.received_back_on),
    [challans]);

  /** Challans whose clock cannot be run because the kind of goods was never
   *  recorded. NOT counted as safe — s.143's periods differ by a factor of
   *  three and the module refuses to pick one. */
  const undecided = useMemo(
    () => challans.filter((c) => (c.clock?.gaps || []).length > 0), [challans]);

  const buildLines = () => lines
    .filter((l) => l.description.trim())
    .map((l) => ({
      description: l.description.trim(),
      hsn_sac: l.hsn_sac.trim() || null,
      quantity: parseQuantity(l.quantity) ?? 1,
      unit: l.unit.trim() || "NOS",
      rate_paise: paiseFromRupeeInput(l.rate) ?? 0,
      gst_rate_percent: Number(l.gst_rate_percent) || 0,
    }));

  async function save() {
    if (dates.first) { setMsg({ type: "err", text: dates.first }); return; }
    const body = buildLines();
    if (!body.length) {
      setMsg({ type: "err", text: "Add at least one line." });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      let res;
      if (tab === "quotations") {
        res = await api.salesCycle.createQuotation({
          client_id: clientId, customer_id: form.customer_id,
          kind: form.kind, document_no: form.document_no,
          document_date: form.document_date,
          valid_until: form.valid_until || null,
          is_inter_state: form.is_inter_state,
          notes: form.notes || null, lines: body,
        });
      } else if (tab === "orders") {
        res = await api.salesCycle.createOrder({
          client_id: clientId, customer_id: form.customer_id,
          document_no: form.document_no, document_date: form.document_date,
          customer_po_no: form.customer_po_no || null,
          expected_delivery_date: form.expected_delivery_date || null,
          is_inter_state: form.is_inter_state,
          notes: form.notes || null, lines: body,
        });
      } else {
        res = await api.salesCycle.createChallan({
          client_id: clientId,
          customer_id: form.customer_id || null,
          document_no: form.document_no, document_date: form.document_date,
          reason: form.reason,
          goods_kind: form.reason === "job_work" && form.goods_kind
            ? form.goods_kind : null,
          consignee_name: form.consignee_name || null,
          consignee_gstin: form.consignee_gstin || null,
          consignee_address: form.consignee_address || null,
          transporter_name: form.transporter_name || null,
          vehicle_no: form.vehicle_no || null,
          is_inter_state: form.is_inter_state,
          place_of_supply: form.is_inter_state && form.place_of_supply ? form.place_of_supply : null,
          notes: form.notes || null, lines: body,
        });
      }
      if (!res.success) {
        setMsg({ type: "err", text: res.error || "That was refused." });
        return;
      }
      setShowForm(false);
      setLines([{ ...BLANK_LINE }]);
      setMsg({ type: "ok", text: "Saved." });
      await load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Failed." });
    } finally {
      setSaving(false);
    }
  }

  async function markBack(challan: DeliveryChallan) {
    // Recording goods back stops the s.143 clock for the whole challan, so it is a button the person presses on a date they can read, and
    // not the act of picking a date (the box used to write the moment a date was chosen, and a half-typed one was a write).
    // A new press begins, so what the last one was answered with is no longer true; a sentence about THE BOX is derived from it (`backProblem`) and said
    // through the latch, and is not copied into the answer, where it would stay after the date is right.
    setBackAnswer(null);
    setBackTried(challan.id);
    if (backDates.problems[`back-${challan.id}`] || !(backOn[challan.id] ?? "")) { backRefusal.refuse(); return; }
    const on = backOn[challan.id] ?? "";
    // A refusal arrives as a thrown sentence (the API answers it with an error status), and it used to escape here unshown: the person pressed
    // the box, nothing happened and nothing said why. `save()` above has always caught it; this did not. It is said beside the button, in the block
    // the button is in: the page's message line is above the whole tab, out of sight of a long list of challans.
    try {
      const res = await api.salesCycle.updateChallan(challan.id, clientId,
        { received_back_on: on });
      if (!res.success) {
        setBackAnswer({ id: challan.id, text: res.error || "That was refused." });
        return;
      }
    } catch (e) {
      setBackAnswer({ id: challan.id, text: e instanceof Error ? e.message : "That was refused." });
      return;
    }
    setBackOn((prev) => {
      const next = { ...prev };
      delete next[challan.id];
      return next;
    });
    setBackTried(null);
    backRefusal.clear();
    await load();
  }

  /** Issue a draft challan: the goods leave on it (POST-A-398). The server asks what a challan must hold when it leaves (goods on it, a date that has come, Rule 55(1)'s particulars, what a job-work
   *  challan sends) and answers a refusal in a sentence, which is said beside the button. This screen decides none of it. */
  async function issue(challan: DeliveryChallan) {
    setIssueAnswer(null);
    try {
      const res = await api.salesCycle.issueChallan(challan.id, clientId);
      if (!res.success) {
        setIssueAnswer({ id: challan.id, text: res.error || "That was refused." });
        return;
      }
    } catch (e) {
      setIssueAnswer({ id: challan.id, text: e instanceof Error ? e.message : "That was refused." });
      return;
    }
    setMsg({ type: "ok", text: `Challan ${challan.document_no} issued.` });
    await load();
    // The open detail is the draft's; read it again so it shows the challan as issued. If that read fails the list already shows the new status, so the stale detail is closed. Only the detail of THIS
    // challan is replaced: the person may have opened another while the press was answered, and that one is not written over (nor one they closed opened again).
    await reopen(challan.id);
  }

  /** Read the open detail again (after a correction or an issue), replacing it only if it is still the same challan's. If that read fails the stale detail is closed rather than left standing. */
  async function reopen(challanId: string) {
    const fresh = await api.salesCycle.challan(challanId, clientId).then(
      (r) => (r.success && r.data ? objectWithLists<ChallanParticulars>(r.data, "copies", "missing", "particulars", "lines") : null),
      () => null);
    setDetail((open) => (open && open.challan?.id === challanId ? fresh : open));
  }

  /** A correction was taken by the server (POST-A-417): the lists and the open detail are read again, so the draft shows what it now holds and what is still to be recorded. */
  async function corrected(challanId: string) {
    setCorrecting(false);
    setMsg({ type: "ok", text: "The draft was corrected." });
    await load();
    await reopen(challanId);
  }

  /** Cancel a draft challan (POST-A-417): a draft whose goods did not leave keeps its number and is cancelled, not deleted. Asked first, in the shared dialog, because it cannot be undone; the server's
   *  status table decides whether it may be (a refusal is its sentence, said beside the button). This screen decides none of it. */
  async function cancelDraft(challan: DeliveryChallan) {
    setCancelAnswer(null);
    const ok = await confirmDialog({
      title: `Cancel draft ${challan.document_no}?`,
      message: `Challan ${challan.document_no} keeps its number and is not a document the goods left on. A cancelled challan cannot be issued and its status cannot change again; this cannot be undone.`,
      confirmLabel: "Cancel the draft",
      cancelLabel: "Keep it",
      danger: true,
    });
    if (!ok) return;
    try {
      const res = await api.salesCycle.cancelChallan(challan.id, clientId);
      if (!res.success) {
        setCancelAnswer({ id: challan.id, text: res.error || "That was refused." });
        return;
      }
    } catch (e) {
      setCancelAnswer({ id: challan.id, text: e instanceof Error ? e.message : "That was refused." });
      return;
    }
    setMsg({ type: "ok", text: `Challan ${challan.document_no} cancelled.` });
    setDetail((open) => (open && open.challan?.id === challan.id ? null : open));
    await load();
  }

  if (loading) {
    return <div className="p-6 text-sm text-ps-hint">Loading…</div>;
  }
  if (loadFailed) {
    return (
      <div className="p-6">
        <div className="rounded border border-state-problem-border bg-state-problem-surface p-4 text-sm text-state-problem">
          The sales cycle could not be loaded.{" "}
          <button onClick={() => void load()} className="underline">Try again</button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-1">
      {/* Nothing here is a tax invoice, and the server says so once. */}
      {vocab && (
        <div className="flex items-start gap-2 rounded border border-ps-border bg-ps-muted p-3 text-sm text-ps-body">
          <Info size={16} className="mt-0.5 shrink-0" />
          <span>{vocab.not_a_tax_invoice}</span>
        </div>
      )}

      {overdue.length > 0 && (
        <div className="rounded border border-state-problem bg-state-problem-surface p-3 text-sm text-state-problem">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle size={16} />
            {overdue.length} challan{overdue.length === 1 ? "" : "s"} past the
            statutory period with the goods not back
          </div>
          <ul className="mt-2 space-y-1">
            {overdue.map((c) => (
              <li key={c.id}>
                <span className="font-mono">{c.document_no}</span> — due back{" "}
                {c.clock.due_back_by}. {c.clock.consequence}
              </li>
            ))}
          </ul>
        </div>
      )}

      {undecided.length > 0 && (
        <div className="rounded border border-state-attention-border bg-state-attention-surface p-3 text-sm text-state-attention">
          <div className="flex items-center gap-2 font-medium">
            <Clock size={16} />
            {undecided.length} challan{undecided.length === 1 ? "" : "s"} cannot
            be timed yet
          </div>
          <ul className="mt-2 space-y-1">
            {undecided.map((c) => (
              <li key={c.id}>
                <span className="font-mono">{c.document_no}</span> —{" "}
                {c.clock.gaps.join(" ")}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {([
          ["quotations", "Quotations & Proforma", FileText],
          ["orders", "Sales Orders", FileText],
          ["challans", "Delivery Challans", Truck],
        ] as const).map(([id, label, Icon]) => (
          <button
            key={id}
            onClick={() => { setTab(id); setShowForm(false); setDetail(null); setIssueAnswer(null); setCancelAnswer(null); setCorrecting(false); setBackTried(null); setBackAnswer(null); backRefusal.clear(); }}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm ${
              tab === id ? "bg-brand text-white" : "bg-ps-muted text-ps-body"
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
        <button
          onClick={() => setShowForm((v) => !v)}
          className="ml-auto flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-sm text-white"
        >
          <Plus size={14} /> New
        </button>
      </div>

      {msg && (
        <div role={msg.type === "ok" ? "status" : "alert"} className={`rounded p-2 text-sm ${
          msg.type === "ok" ? "bg-state-ready-surface text-state-ready" : "bg-state-problem-surface text-state-problem"
        }`}>{msg.text}</div>
      )}

      {showForm && vocab && (
        <div className="rounded border border-ps-border bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">
              New {tab === "quotations" ? "quotation or proforma"
                : tab === "orders" ? "sales order" : "delivery challan"}
            </h3>
            <button onClick={() => setShowForm(false)}><X size={16} /></button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {tab === "quotations" && (
              <label className="text-sm">
                <span className="mb-1 block text-ps-label">Document</span>
                <select
                  value={form.kind}
                  onChange={(e) => setForm({ ...form, kind: e.target.value })}
                  className="w-full rounded border border-ps-border px-2 py-1.5"
                >
                  {vocab.quote_kinds.map((k) => (
                    <option key={k.value} value={k.value}>{k.label}</option>
                  ))}
                </select>
              </label>
            )}

            {tab === "challans" && (
              <label className="text-sm sm:col-span-2">
                <span className="mb-1 block text-ps-label">
                  Why the goods are moving (CGST Rule 55)
                </span>
                <select
                  value={form.reason}
                  onChange={(e) => setForm({ ...form, reason: e.target.value })}
                  className="w-full rounded border border-ps-border px-2 py-1.5"
                >
                  {vocab.challan_reasons.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </label>
            )}

            {tab === "challans" && form.reason === "job_work" && (
              <label className="text-sm">
                <span className="mb-1 block text-ps-label">
                  What is being sent (CGST s.143)
                </span>
                <select
                  value={form.goods_kind}
                  onChange={(e) => setForm({ ...form, goods_kind: e.target.value })}
                  className="w-full rounded border border-ps-border px-2 py-1.5"
                >
                  <option value="">Not recorded</option>
                  {vocab.goods_kinds.map((g) => (
                    <option key={g.value} value={g.value}>{g.label}</option>
                  ))}
                </select>
              </label>
            )}

            <label className="text-sm">
              <span className="mb-1 block text-ps-label">
                {tab === "challans" ? "Consignee (customer)" : "Customer"}
              </span>
              <select
                value={form.customer_id}
                onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
                className="w-full rounded border border-ps-border px-2 py-1.5"
              >
                <option value="">Select…</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name || c.customer_name || c.id}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-sm">
              <span className="mb-1 block text-ps-label">Number</span>
              <input
                value={form.document_no}
                onChange={(e) => setForm({ ...form, document_no: e.target.value })}
                placeholder="QT/2026-27/0001"
                className="w-full rounded border border-ps-border px-2 py-1.5"
              />
            </label>

            <label className="text-sm">
              <span className="mb-1 block text-ps-label">Date</span>
              <DateInput
                id="sc-date"
                value={form.document_date}
                onChange={(v) => setForm({ ...form, document_date: v })}
                onStateChange={dates.watch("document_date", "Date")}
                className="w-full rounded border border-ps-border px-2 py-1.5"
              />
            </label>

            {tab === "quotations" && (
              <label className="text-sm">
                <span className="mb-1 block text-ps-label">Valid until</span>
                <DateInput
                  id="sc-valid-until"
                  anchor={form.document_date || null} notBefore={form.document_date || null}
                  value={form.valid_until}
                  onChange={(v) => setForm({ ...form, valid_until: v })}
                  onStateChange={dates.watch("valid_until", "Valid until")}
                  className="w-full rounded border border-ps-border px-2 py-1.5"
                />
              </label>
            )}

            {tab === "orders" && (
              <>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">
                    Customer&apos;s PO number
                  </span>
                  <input
                    value={form.customer_po_no}
                    onChange={(e) => setForm({ ...form, customer_po_no: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">Expected delivery</span>
                  <DateInput
                    id="sc-expected-delivery"
                    anchor={form.document_date || null} notBefore={form.document_date || null}
                    value={form.expected_delivery_date}
                    onChange={(v) => setForm({ ...form, expected_delivery_date: v })}
                    onStateChange={dates.watch("expected_delivery_date", "Expected delivery")}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
              </>
            )}

            {tab === "challans" && (
              <>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">Consignee name</span>
                  <input
                    value={form.consignee_name}
                    onChange={(e) => setForm({ ...form, consignee_name: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">
                    Consignee GSTIN (if registered)
                  </span>
                  <input
                    value={form.consignee_gstin}
                    onChange={(e) => setForm({ ...form, consignee_gstin: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5 font-mono"
                  />
                </label>
                <label className="text-sm sm:col-span-2">
                  <span className="mb-1 block text-ps-label">Consignee address</span>
                  <input
                    value={form.consignee_address}
                    onChange={(e) => setForm({ ...form, consignee_address: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">Transporter</span>
                  <input
                    value={form.transporter_name}
                    onChange={(e) => setForm({ ...form, transporter_name: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block text-ps-label">Vehicle number</span>
                  <input
                    value={form.vehicle_no}
                    onChange={(e) => setForm({ ...form, vehicle_no: e.target.value })}
                    className="w-full rounded border border-ps-border px-2 py-1.5"
                  />
                </label>
              </>
            )}

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_inter_state}
                onChange={(e) => setForm({ ...form, is_inter_state: e.target.checked })}
              />
              Inter-state movement
            </label>

            {tab === "challans" && form.is_inter_state && (
              <div className="text-sm">
                <span className="mb-1 block text-ps-label">Place of supply (CGST Rule 55(1)(viii))</span>
                <StateLookup placeOfSupply value={form.place_of_supply} onChange={(code) => setForm({ ...form, place_of_supply: code })}
                  placeholder="— Select —" ariaLabel="Place of supply" clearable />
              </div>
            )}
          </div>

          <div className="mt-4">
            <div className="mb-2 text-sm font-medium text-ps-body">Lines</div>
            <div className="space-y-2">
              {lines.map((l, i) => (
                <div key={i} className="grid gap-2 sm:grid-cols-6">
                  <input aria-label={`Line ${i + 1} description`}
                    value={l.description}
                    placeholder="Description"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, description: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-ps-border px-2 py-1.5 text-sm sm:col-span-2"
                  />
                  <input aria-label={`Line ${i + 1} HSN or SAC code`}
                    value={l.hsn_sac}
                    placeholder="HSN"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, hsn_sac: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-ps-border px-2 py-1.5 text-sm font-mono"
                  />
                  <input aria-label={`Line ${i + 1} quantity`}
                    value={l.quantity}
                    placeholder="Qty"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, quantity: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-ps-border px-2 py-1.5 text-sm"
                  />
                  <input aria-label={`Line ${i + 1} rate (₹)`}
                    value={l.rate}
                    placeholder="Rate ₹"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, rate: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-ps-border px-2 py-1.5 text-sm"
                  />
                  <input aria-label={`Line ${i + 1} GST rate (%)`}
                    value={l.gst_rate_percent}
                    placeholder="GST %"
                    onChange={(e) => {
                      const next = [...lines];
                      next[i] = { ...l, gst_rate_percent: e.target.value };
                      setLines(next);
                    }}
                    className="rounded border border-ps-border px-2 py-1.5 text-sm"
                  />
                </div>
              ))}
            </div>
            <button
              onClick={() => setLines([...lines, { ...BLANK_LINE }])}
              className="mt-2 text-sm text-blue-600"
            >
              + Add line
            </button>
          </div>

          {tab === "challans"
            && vocab.challan_reasons.find((r) => r.value === form.reason)
              ?.is_a_supply === false && (
            <p className="mt-3 text-xs text-ps-label">
              {vocab.no_tax_on_a_non_supply}
            </p>
          )}

          {tab === "challans" && (
            <p className="mt-3 text-xs text-ps-label">
              CGST Rule 55(1) asks for the HSN code of every line, the consignee and, for an inter-State movement, the place of supply. A job-work challan also says what it sends, because the period under
              s.143 depends on it. A challan is saved as a draft and issued when its goods leave; a draft saved without one of these is corrected from its panel (open it from the list) before it is issued.
            </p>
          )}

          <div className="mt-4 flex gap-2">
            <Button variant="plain" size="none"
              disabled={saving}
              onClick={() => save()}
              className="rounded bg-brand px-4 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </Button>
            <button
              onClick={() => setShowForm(false)}
              className="rounded border border-ps-border px-4 py-1.5 text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {tab === "quotations" && (
        <Table
          head={["Kind", "Number", "Date", "Valid until", "Status", "Total"]}
          rows={quotations.map((q) => [
            q.title || q.kind,
            q.document_no,
            q.document_date,
            q.is_expired === true
              ? `${q.valid_until} (expired)`
              : q.valid_until || "—",
            q.status,
            rupees(q.total_paise),
          ])}
          empty="No quotations or proforma invoices yet."
        />
      )}

      {tab === "orders" && (
        <div className="space-y-3">
          <Table
            head={["Number", "Date", "Customer PO", "Expected", "Status", "Total"]}
            rows={orders.map((o) => [
              o.document_no, o.document_date, o.customer_po_no || "—",
              o.expected_delivery_date || "—", o.status, rupees(o.total_paise),
            ])}
            empty="No sales orders yet."
            onRow={(i) => {
              void api.salesCycle.orderPosition(orders[i].id, clientId)
                .then((r) => { if (r.success && r.data) setPosition(objectWithLists<OrderPosition>(r.data, "gaps", "lines")); });
            }}
          />
          {position && (
            <div className="rounded border border-ps-border bg-white p-4">
              <div className="mb-2 flex items-center justify-between">
                <h4 className="text-sm font-semibold">What is still open</h4>
                <button onClick={() => setPosition(null)}><X size={14} /></button>
              </div>
              <Table
                head={["Line", "Ordered", "Delivered", "Undelivered", "Invoiced", "Unbilled"]}
                rows={position.lines.map((l) => [
                  l.description, l.ordered_qty, l.delivered_qty,
                  l.undelivered_qty, l.invoiced_qty, l.unbilled_qty,
                ])}
                empty="This order has no lines."
              />
              {position.gaps.map((g) => (
                <p key={g} className="mt-2 text-xs text-state-attention">{g}</p>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "challans" && (
        <div className="space-y-3">
          <Table
            head={["Number", "Date", "Why", "Due back", "Status", "Value"]}
            rows={challans.map((c) => [
              c.document_no,
              c.document_date,
              c.reason_label || c.reason,
              c.clock?.due_back_by
                ? `${c.clock.due_back_by}${c.clock.overdue ? " — OVERDUE" : ""}`
                : "—",
              c.received_back_on ? `back ${c.received_back_on}` : c.status,
              rupees(c.total_paise),
            ])}
            empty="No delivery challans yet."
            onRow={(i) => {
              setIssueAnswer(null);       // an answer to an earlier press is not the answer to a challan opened now
              setCancelAnswer(null);
              setCorrecting(false);
              void api.salesCycle.challan(challans[i].id, clientId)
                .then((r) => { if (r.success && r.data) setDetail(objectWithLists<ChallanParticulars>(r.data, "copies", "missing", "particulars", "lines")); });
            }}
          />

          {challans.some((c) => c.status === "draft") && (
            <p className="text-xs text-ps-label">
              {challans.filter((c) => c.status === "draft").length} in draft. A draft is not recorded as issued: no period runs on it here and it is not on FORM GST ITC-04. If the goods on a
              draft have left, open it and issue it.
            </p>
          )}

          {challans.some((c) => (c.status === "issued" || c.status === "received_back") && c.clock?.applies && !c.received_back_on) && (
            <div className="rounded border border-ps-border bg-white p-4">
              <h4 className="mb-1 text-sm font-semibold">
                Mark a whole challan back at once
              </h4>
              <p className="mb-2 text-xs text-ps-label">
                This stops the s.143 clock for every line on the challan. Goods that
                come back in lots are recorded lot by lot under ITC-04 below, which
                keeps what is still outstanding.
              </p>
              <div className="space-y-2">
                {challans.filter((c) => (c.status === "issued" || c.status === "received_back") && c.clock?.applies && !c.received_back_on)
                  .map((c) => (
                    <div key={c.id} className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="font-mono">{c.document_no}</span>
                      <DateInput
                        aria-label={`Date the goods came back, challan ${c.document_no}`}
                        value={backOn[c.id] ?? ""}
                        onChange={(v) => setBackOn((prev) => ({ ...prev, [c.id]: v }))}
                        onStateChange={backDates.watch(`back-${c.id}`, `Date back, ${c.document_no}`, { afterMax: true })}
                        anchor={c.document_date}
                        notBefore={c.document_date}
                        notAfter={todayIstISO()}
                        className="rounded border border-ps-border px-2 py-1"
                      />
                      <Button variant="plain" size="none"
                        onClick={() => markBack(c)}
                        className="rounded bg-brand px-3 py-1 text-xs text-white disabled:opacity-50"
                      >
                        Record goods back
                      </Button>
                      {/* In the row of the challan it is about, beside its button. The newest answer is shown: the server's answer to a press clears with the next press, so one that is here came after the date's sentence. */}
                      {backSaid(c) && <p role="alert" className="basis-full text-xs text-state-problem">{backSaid(c)}</p>}
                    </div>
                  ))}
              </div>
            </div>
          )}

          {correcting && vocab && detail?.challan && detail.challan.status === "draft" && (
            <DraftChallanEditor detail={detail} clientId={clientId} goodsKinds={vocab.goods_kinds}
              onSaved={corrected} onClose={() => setCorrecting(false)} />
          )}

          {detail && (
            <div className="rounded border border-ps-border bg-white p-4">
              <div className="mb-2 flex items-center justify-between">
                <h4 className="text-sm font-semibold">
                  {detail.rule} — {detail.reason_label}
                </h4>
                <button aria-label="Close the challan" onClick={() => { setDetail(null); setIssueAnswer(null); setCancelAnswer(null); setCorrecting(false); }}><X size={14} /></button>
              </div>
              {detail.challan && detail.challan.status === "draft" && (
                <div className="mb-3 rounded border border-ps-border bg-ps-muted p-3 text-sm">
                  <div className="font-medium text-ps-ink">Challan {detail.challan.document_no} is a draft</div>
                  <p className="mt-1 text-xs text-ps-body">
                    A draft is not recorded as issued. Issuing records that the goods left on {formatDate(detail.challan.document_date)}, the challan&apos;s date: any period under the Act is run from that day, a job-work
                    challan is listed on FORM GST ITC-04, and goods can be recorded as back on it only once it is issued. Nothing is sent to any portal.
                  </p>
                  {detail.clock.consequence && <p className="mt-1 text-xs text-ps-body">{detail.clock.consequence}</p>}
                  {detail.missing.length > 0 && (
                    <p className="mt-1 text-xs text-state-attention">
                      Rule 55(1) asks for what is listed under &ldquo;Still to be recorded&rdquo; below, and the server will not issue the challan without it. Correct draft records the consignee, what a job-work challan sends, the place of supply and the HSN code of each line; the consigner is the client&apos;s own details, read from the client&apos;s profile.
                    </p>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Button variant="plain" size="none" onClick={() => issue(detail.challan as DeliveryChallan)}
                      className="rounded bg-brand px-3 py-1 text-xs text-white disabled:opacity-50">
                      Issue challan
                    </Button>
                    <Button variant="plain" size="none" onClick={() => setCorrecting(true)}
                      className="rounded border border-ps-border px-3 py-1 text-xs">
                      Correct draft
                    </Button>
                    <Button variant="plain" size="none" onClick={() => cancelDraft(detail.challan as DeliveryChallan)}
                      className="rounded border border-state-problem-border px-3 py-1 text-xs text-state-problem">
                      Cancel draft
                    </Button>
                  </div>
                  {issueAnswer && issueAnswer.id === detail.challan.id && (
                    <p role="alert" className="mt-2 text-xs text-state-problem">{issueAnswer.text}</p>
                  )}
                  {cancelAnswer && cancelAnswer.id === detail.challan.id && (
                    <p role="alert" className="mt-2 text-xs text-state-problem">{cancelAnswer.text}</p>
                  )}
                </div>
              )}
              <Table
                head={["Clause", "Particular", "On the document"]}
                rows={detail.particulars.map((p) => [
                  p.clause,
                  p.required ? p.label : `${p.label} (not required here)`,
                  p.value || "—",
                ])}
                empty=""
              />
              {detail.missing.length > 0 && (
                <div className="mt-3 rounded border border-state-attention-border bg-state-attention-surface p-3 text-sm text-state-attention">
                  <div className="font-medium">Still to be recorded</div>
                  <ul className="mt-1 list-disc pl-5">
                    {detail.missing.map((m) => <li key={m}>{m}</li>)}
                  </ul>
                </div>
              )}
              <div className="mt-3 text-xs text-ps-label">
                <div className="font-medium text-ps-body">
                  Three copies (Rule 55(2))
                </div>
                <ul className="mt-1">
                  {detail.copies.map((c) => <li key={c.copy}>{c.legend}</li>)}
                </ul>
              </div>
              {detail.clock.applies && (
                <p className="mt-3 text-xs text-ps-body">{detail.clock.consequence}</p>
              )}
              {detail.rule_55_5.gaps.map((g) => (
                <p key={g} className="mt-2 text-xs text-state-attention">{g}</p>
              ))}
              {detail.clock.statute.includes("s.143") && (
                <p className="mt-2 text-xs text-ps-label">
                  {detail.itc_04.refusal}
                </p>
              )}
            </div>
          )}

          {/* The challan that was opened is above this panel, so the card a row opens (and the Issue challan in it) is next to the list and not under a form that can be a screen long. */}
          <Itc04Panel clientId={clientId} onChanged={() => void load()} refreshToken={itc04Refresh} />
        </div>
      )}
    </div>
  );
}

function Table({ head, rows, empty, onRow }: {
  head: string[];
  rows: (string | number)[][];
  empty: string;
  onRow?: (index: number) => void;
}) {
  if (!rows.length) {
    return <p className="p-4 text-sm text-ps-hint">{empty}</p>;
  }
  return (
    <div className="overflow-x-auto rounded border border-ps-border">
      <table className="w-full text-sm">
        <thead className="bg-ps-muted text-left text-xs uppercase text-ps-hint">
          <tr>{head.map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              onClick={onRow ? () => onRow(i) : undefined}
              className={`border-t border-ps-border ${onRow ? "cursor-pointer hover:bg-ps-hover" : ""}`}
            >
              {r.map((cell, j) => (
                <td key={j} className="px-3 py-2 tabular-nums">
                  {onRow && j === 0 ? (
                    // A click anywhere in the row opens it; its first cell is also a button, so the keyboard reaches what is inside the row (the draft's Issue challan is only there).
                    <button type="button" className="text-left underline-offset-2 hover:underline focus-visible:underline" onClick={(e) => { e.stopPropagation(); onRow(i); }}>{cell}</button>
                  ) : cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
