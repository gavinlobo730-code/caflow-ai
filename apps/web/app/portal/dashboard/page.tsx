"use client";

// Phase 4.5.2 — Customer Portal dashboard with data surfaces.
// Auth is the client's own Supabase session, resolved server-side via
// get_current_portal_client. Every surface here is the firm↔client fee
// relationship (invoices, canonical dues, statement, payment reminders) plus
// the client's own compliance status — served by /api/portal/self/*. The active
// client is selected EXPLICITLY via X-Portal-Client-Id (no implicit switching).
// All amounts are integer paise from the server; the frontend only formats them.

import { useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  FileText, FolderOpen, MessageSquare, Receipt, ScrollText, BellRing, ShieldCheck,
  Download, CreditCard, Send, type LucideIcon,
} from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import type {
  PortalDocument, PortalDocumentRequest, PortalMessage,
} from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase/client";
import { hasEmployeePortalAccess } from "@/lib/portal/employeeAccess";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import { PageLoader } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import {
  PortalShell, PortalPanel, PortalTable, PortalRow, PortalEmpty,
} from "@/components/portal/PortalShell";
import { arrayOrEmpty, objectWithLists } from "@/lib/api/shape";

interface Section {
  key: string;
  label: string;
  available: boolean;
  /** Something the client has to be told about this section — today, that
   *  fulfilling a document request by uploading here is not available. A
   *  THIRD state beside present and absent, and the reason the dashboard can
   *  stop hiding sections it does not fully implement. */
  note?: string | null;
}
interface Dashboard { client_id: string; contact: { email: string | null; name: string | null }; sections: Section[] }
interface Membership { client_id: string; name: string | null }

interface PortalInvoice {
  id: string; invoice_no: string | null; invoice_date: string | null; due_date: string | null;
  total_paise: number; paid_paise: number; outstanding_paise: number; status: string | null;
  is_overdue: boolean; days_overdue: number;
}
interface PortalDues {
  dues: PortalInvoice[]; total_outstanding_paise: number; overdue_paise: number; overdue_count: number;
}
interface PortalReminder { invoice_no: string | null; status: string | null; sent_at: string | null; created_at: string | null }
interface PortalCompliance {
  compliance_type: string | null; obligation_type: string | null; period_label: string | null;
  period_start: string | null; period_end: string | null; due_date: string | null;
  status: string | null; filed_date: string | null; acknowledgement_no: string | null;
}
interface StatementTxn {
  date: string; type: string; reference: string | null; particulars: string;
  debit_paise: number; credit_paise: number; running_balance_paise: number;
}
interface PortalStatement {
  customer: { name: string | null } | null;
  period?: { start_date: string; end_date: string };
  opening_balance_paise: number; transactions: StatementTxn[]; closing_balance_paise: number;
  available?: boolean;
}

const ICONS: Record<string, LucideIcon> = {
  documents: FolderOpen, requests: FileText, messages: MessageSquare,
  invoices: Receipt, statements: ScrollText, reminders: BellRing, compliance: ShieldCheck,
};

// ⚠️ THERE USED TO BE A `DATA_SECTIONS` SET HERE AND IT WAS THE DEFECT.
// `_DASHBOARD_SECTIONS` serves seven sections, all `available: true`, and this
// file kept its own set of the four it knew how to load — then filtered the
// other three out of its own tab row. So the API told a client Documents,
// Document Requests and Messages existed and the screen silently disagreed, on
// the one surface the outside world sees. The three are served now and this
// renders WHAT THE SERVER SENDS; a section the loader does not recognise shows
// its own empty state rather than vanishing, which is the Schedule III caption
// rule applied to the portal.

function StatusBadge({ status, danger }: { status: string | null; danger?: boolean }) {
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-2xs font-medium ${
      danger ? "bg-state-problem-surface text-state-problem" : "bg-ps-muted text-ps-label"}`}>
      {status ?? "—"}
    </span>
  );
}

export default function PortalDashboardPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const inviteToken = searchParams.get("invite");

  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [activeClient, setActiveClient] = useState<string | null>(null);
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [active, setActive] = useState<string>("invoices");
  const [dues, setDues] = useState<PortalDues | null>(null);
  const [invoices, setInvoices] = useState<PortalInvoice[] | null>(null);
  const [reminders, setReminders] = useState<PortalReminder[] | null>(null);
  const [compliance, setCompliance] = useState<PortalCompliance[] | null>(null);
  const [statement, setStatement] = useState<PortalStatement | null>(null);
  const [documents, setDocuments] = useState<PortalDocument[] | null>(null);
  const [requests, setRequests] = useState<PortalDocumentRequest[] | null>(null);
  const [messages, setMessages] = useState<PortalMessage[] | null>(null);
  const [draft, setDraft] = useState("");
  const [stmtStart, setStmtStart] = useState<string>("");
  const [stmtEnd, setStmtEnd] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // A failed loadSection() left the section's own state at null forever —
  // the panel's own `xxx === null` guard reads that as "still loading," so
  // it kept spinning underneath the (correctly firing) `notice` banner
  // instead of resolving to a retryable error state.
  const [sectionFailed, setSectionFailed] = useState<Record<string, boolean>>({});
  // True once we know this identity belongs in the EMPLOYEE portal and the
  // navigation there has been asked for but not yet happened. Keeps the loading
  // state up across that gap; see the redirect below.
  const [redirecting, setRedirecting] = useState(false);

  // 1. Accept a pending invite (F22 fix — a single-use token, not an auto-bind
  // on email/URL match), then resolve the identity's client memberships (one
  // identity → many clients). The magic-link session may still be hydrating
  // when this page first mounts, so wait for it rather than firing a doomed,
  // unauthenticated request.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const supabase = getSupabaseClient();
      for (let attempt = 0; attempt < 10; attempt++) {
        const { data } = await supabase.auth.getSession();
        if (data?.session) break;
        await new Promise((r) => setTimeout(r, 500));
      }
      if (cancelled) return;
      try {
        if (inviteToken) {
          // Best-effort: an already-accepted/expired token here just means the
          // invitee reloaded this page after accepting once — memberships load
          // below already reflects that; only a genuinely failed acceptance
          // needs surfacing, and even then we still try to show what's active.
          await api.portalSelf.acceptInvite(inviteToken).catch(() => null);
        }
        const res = await api.portalSelf.memberships() as ApiResp<{ memberships: Membership[] }>;
        const ms = res.data?.memberships ?? [];
        // No CLIENT memberships is not the same as no access. /portal/login
        // pushes every portal sign-in here, and an employee of a client is a
        // portal user with no client membership at all — so this branch used to
        // tell an activated employee "ask your accountant to invite you" and
        // leave them with no route to their own payslips but the original
        // invite link. Send them to the portal that is actually theirs.
        if (ms.length === 0 && await hasEmployeePortalAccess()) {
          if (!cancelled) {
            // Stays true through the navigation. `finally` below clears
            // `loading`, and without this the zero-memberships branch would
            // paint "you don't have access" for a frame or two on the way out —
            // the exact message this redirect exists to stop them seeing.
            setRedirecting(true);
            router.replace("/portal/employee");
          }
          return;
        }
        if (cancelled) return;
        setMemberships(ms);
        if (ms.length === 1) setActiveClient(ms[0].client_id);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unable to load your portal");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2. Load the dashboard shell + the dues summary for the selected client.
  useEffect(() => {
    if (!activeClient) return;
    setDash(null); setDues(null);
    setInvoices(null); setReminders(null); setCompliance(null); setStatement(null);
    setDocuments(null); setRequests(null); setMessages(null);
    (async () => {
      try {
        const [d, du] = await Promise.all([
          api.portalSelf.dashboard(activeClient) as Promise<ApiResp<Dashboard>>,
          api.portalSelf.dues(activeClient) as Promise<ApiResp<PortalDues>>,
        ]);
        setDash(d.data);
        setDues(du.data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unable to load your portal");
      }
    })();
  }, [activeClient]);

  // 3. Lazy-load the active section's data the first time it is opened.
  const loadSection = useCallback(async (key: string, client: string) => {
    setNotice(null);
    setSectionFailed((f) => ({ ...f, [key]: false }));
    try {
      if (key === "invoices" && invoices === null) {
        const r = await api.portalSelf.invoices(client) as ApiResp<{ invoices: PortalInvoice[] }>;
        setInvoices(r.data?.invoices ?? []);
      } else if (key === "reminders" && reminders === null) {
        const r = await api.portalSelf.reminders(client) as ApiResp<{ reminders: PortalReminder[] }>;
        setReminders(r.data?.reminders ?? []);
      } else if (key === "compliance" && compliance === null) {
        const r = await api.portalSelf.compliance(client) as ApiResp<{ compliance: PortalCompliance[] }>;
        setCompliance(r.data?.compliance ?? []);
      } else if (key === "statements" && statement === null) {
        const r = await api.portalSelf.statement(client, stmtStart || undefined, stmtEnd || undefined) as ApiResp<PortalStatement>;
        setStatement(objectWithLists<PortalStatement>(r.data, "transactions"));
      } else if (key === "documents" && documents === null) {
        const r = await api.portalSelf.documents(client);
        setDocuments(arrayOrEmpty<PortalDocument>(r.data?.documents));
      } else if (key === "requests" && requests === null) {
        const r = await api.portalSelf.documentRequests(client);
        setRequests(arrayOrEmpty<PortalDocumentRequest>(r.data?.requests));
      } else if (key === "messages" && messages === null) {
        const r = await api.portalSelf.messages(client);
        setMessages(arrayOrEmpty<PortalMessage>(r.data?.messages));
      }
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Unable to load this section");
      setSectionFailed((f) => ({ ...f, [key]: true }));
    }
  }, [invoices, reminders, compliance, statement, documents, requests, messages,
      stmtStart, stmtEnd]);

  useEffect(() => {
    if (activeClient) loadSection(active, activeClient);
  }, [active, activeClient, loadSection]);

  /** Post to the thread and append the server's own row, never a local echo:
   *  `id`, `created_at` and `sender_type` are the server's, and a fabricated
   *  row would show a client a message stamped differently from the one their
   *  accountant will read. */
  const sendMessage = async () => {
    const text = draft.trim();
    if (!text || !activeClient || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      const r = await api.portalSelf.postMessage(text, activeClient);
      if (!r?.success) throw new Error(r?.error ?? "Your message was not sent.");
      const sent = r.data?.message;
      if (sent) setMessages((prev) => [...(prev ?? []), sent]);
      setDraft("");
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Your message was not sent.");
    } finally {
      setBusy(false);
    }
  };

  /** A 60-second signed URL from the server, opened directly — the file never
   *  comes through Singapore. */
  const openDocument = async (id: string) => {
    if (!activeClient || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      const r = await api.portalSelf.documentDownload(id, activeClient);
      if (!r?.success || !r.data?.url) throw new Error(r?.error ?? "Could not open that document.");
      window.open(r.data.url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Could not open that document.");
    } finally {
      setBusy(false);
    }
  };

  const downloadInvoice = async (id: string) => {
    if (!activeClient) return;
    setBusy(true); setNotice(null);
    try { await api.portalSelf.invoicePdf(id, activeClient); }
    catch (e) { setNotice(e instanceof Error ? e.message : "Could not download invoice"); }
    finally { setBusy(false); }
  };

  // Pay Now (Phase 4.6) — create/reuse a payment link for this invoice and open
  // the hosted gateway checkout. The payment flows back through the standard
  // receipt → AR pipeline server-side; nothing here touches accounting.
  const payInvoice = async (id: string) => {
    if (!activeClient) return;
    setBusy(true); setNotice(null);
    try {
      const res = await api.portalSelf.payInvoice(id, activeClient) as ApiResp<{ short_url: string | null }>;
      const url = res.data?.short_url;
      if (url) window.open(url, "_blank", "noopener");
      else setNotice("A payment link could not be created. Please contact your accountant.");
    } catch (e) { setNotice(e instanceof Error ? e.message : "Could not start the payment"); }
    finally { setBusy(false); }
  };

  const downloadStatement = async () => {
    if (!activeClient) return;
    setBusy(true); setNotice(null);
    try { await api.portalSelf.statementPdf(activeClient, stmtStart || undefined, stmtEnd || undefined); }
    catch (e) { setNotice(e instanceof Error ? e.message : "Could not download statement"); }
    finally { setBusy(false); }
  };

  const reloadStatement = async () => {
    if (!activeClient) return;
    setBusy(true); setNotice(null);
    try {
      const r = await api.portalSelf.statement(activeClient, stmtStart || undefined, stmtEnd || undefined) as ApiResp<PortalStatement>;
      setStatement(objectWithLists<PortalStatement>(r.data, "transactions"));
    } catch (e) { setNotice(e instanceof Error ? e.message : "Could not load statement"); }
    finally { setBusy(false); }
  };

  if (loading || redirecting) return <div className="p-8 text-sm text-ps-label">Loading your portal…</div>;
  if (error) {
    return (
      <div className="p-8 max-w-md">
        <p className="text-sm text-state-problem">{error}</p>
        <p className="text-xs text-ps-hint mt-2">If you believe you should have access, ask your accountant to invite you.</p>
      </div>
    );
  }
  // A successful memberships() call with zero results (deactivated access, or
  // an invite that was never accepted) isn't a fetch `error` — but with no
  // memberships, activeClient never gets set and the branch below falls
  // through to `!dash ? <PageLoader />`, spinning forever with nothing to load
  // it out of that state. Show the same "ask your accountant" message instead.
  if (memberships.length === 0) {
    return (
      <PortalShell title="Your Portal">
        <p className="text-sm text-ps-body">
          You don&apos;t have access to a client portal right now.
        </p>
        <p className="mt-2 text-xs text-ps-hint">
          If you believe you should have access, ask your accountant to invite you.
        </p>
      </PortalShell>
    );
  }

  const activeSection = (dash?.sections ?? []).find((s) => s.key === active);

  return (
    <PortalShell
      title="Your Portal"
      subtitle="Your secure workspace with your accountant"
      identity={dash?.contact.name ?? dash?.contact.email ?? null}
      actions={memberships.length > 1 ? (
        <label className="text-xs text-ps-label">
          <span className="sr-only">Client</span>
          <select
            value={activeClient ?? ""}
            onChange={(e) => { setActiveClient(e.target.value || null); }}
            className="rounded-lg border border-ps-border px-2 py-1 text-xs text-ps-ink">
            <option value="">Select a client…</option>
            {memberships.map((m) => <option key={m.client_id} value={m.client_id}>{m.name ?? m.client_id}</option>)}
          </select>
        </label>
      ) : undefined}
    >
      {memberships.length > 1 && !activeClient ? (
        <div className="rounded-xl border border-dashed border-ps-border bg-white p-8 text-center text-sm text-ps-label">
          You have access to {memberships.length} clients. Choose one above to continue.
        </div>
      ) : !dash ? (
        <PageLoader />
      ) : (
        <>
          {/* Dues summary — the headline "what do I owe the firm" figure. */}
          {dues && (
            <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-ps-border bg-white p-4">
                <p className="text-2xs uppercase tracking-wide text-ps-hint">Total Outstanding</p>
                <p className="mt-1 text-xl font-semibold tabular-nums text-ps-ink">{formatPaise(dues.total_outstanding_paise)}</p>
              </div>
              <div className={`rounded-xl border p-4 ${dues.overdue_paise > 0 ? "border-state-problem-border bg-state-problem-surface" : "border-ps-border bg-white"}`}>
                <p className="text-2xs uppercase tracking-wide text-ps-hint">Overdue</p>
                <p className={`mt-1 text-xl font-semibold tabular-nums ${dues.overdue_paise > 0 ? "text-state-problem" : "text-ps-ink"}`}>{formatPaise(dues.overdue_paise)}</p>
              </div>
              <div className="rounded-xl border border-ps-border bg-white p-4">
                <p className="text-2xs uppercase tracking-wide text-ps-hint">Overdue Invoices</p>
                <p className="mt-1 text-xl font-semibold tabular-nums text-ps-ink">{dues.overdue_count}</p>
              </div>
            </div>
          )}

          {/* Section navigation. */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-5">
            {(dash.sections ?? []).map((s) => {
              const Icon = ICONS[s.key] ?? FileText;
              const on = active === s.key;
              return (
                <button key={s.key} onClick={() => setActive(s.key)}
                  className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm transition ${
                    on ? "border-brand-dark bg-brand-dark text-white" : "border-ps-border bg-white text-ps-ink hover:border-ps-hint"}`}>
                  <Icon size={16} className={on ? "text-white" : "text-ps-hint"} />
                  <span className="font-medium">{s.label}</span>
                </button>
              );
            })}
          </div>

          {notice && <div className="mb-3"><Callout tone="problem">{notice}</Callout></div>}

          {/* The section's own caveat, SERVED. `_DASHBOARD_SECTIONS` carries a
              `note` per section — a third state beside present and absent —
              and today the one that has one is Document Requests, where
              uploading is not available. Saying so beats a button that fails
              and beats hiding the section, which is what this screen used to
              do to all three of them. */}
          {activeSection?.note && (
            <div className="mb-3"><Callout tone="note">{activeSection.note}</Callout></div>
          )}

          {/* ── Invoices ── */}
          {active === "invoices" && (
            <Panel title="Invoices">
              {invoices === null ? (sectionFailed["invoices"] ? <ErrorRetry onRetry={() => loadSection("invoices", activeClient!)} /> : <Loading />) : invoices.length === 0 ? <Empty label="No invoices yet." /> : (
                <Table head={["Invoice", "Date", "Due", "Total", "Outstanding", "Status", ""]}>
                  {invoices.map((i) => (
                    <tr key={i.id} className="border-t border-ps-border">
                      <td className="px-3 py-2 font-medium text-ps-ink">{i.invoice_no ?? "—"}</td>
                      <td className="px-3 py-2 text-ps-label">{i.invoice_date ? formatDate(i.invoice_date) : "—"}</td>
                      <td className="px-3 py-2 text-ps-label">{i.due_date ? formatDate(i.due_date) : "—"}</td>
                      <td className="px-3 py-2 tabular-nums">{formatPaise(i.total_paise)}</td>
                      <td className="px-3 py-2 tabular-nums">{formatPaise(i.outstanding_paise)}</td>
                      <td className="px-3 py-2"><StatusBadge status={i.is_overdue ? `overdue ${i.days_overdue}d` : i.status} danger={i.is_overdue} /></td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        {i.outstanding_paise > 0 && (
                          <button disabled={busy} onClick={() => payInvoice(i.id)}
                            className="inline-flex items-center gap-1 text-xs text-brand-dark hover:underline disabled:opacity-40 mr-3">
                            <CreditCard size={13} /> Pay Now
                          </button>
                        )}
                        <button disabled={busy} onClick={() => downloadInvoice(i.id)}
                          className="inline-flex items-center gap-1 text-xs text-brand hover:underline disabled:opacity-40">
                          <Download size={13} /> PDF
                        </button>
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
          )}

          {/* ── Statements ── */}
          {active === "statements" && (
            <Panel title="Account Statement">
              <div className="flex flex-wrap items-end gap-2 mb-3">
                <label className="text-xs text-ps-label">From
                  <input type="date" value={stmtStart} onChange={(e) => setStmtStart(e.target.value)}
                    className="ml-1 block sm:inline border border-ps-border rounded px-2 py-1 text-xs" />
                </label>
                <label className="text-xs text-ps-label">To
                  <input type="date" value={stmtEnd} onChange={(e) => setStmtEnd(e.target.value)}
                    className="ml-1 block sm:inline border border-ps-border rounded px-2 py-1 text-xs" />
                </label>
                <button disabled={busy} onClick={reloadStatement}
                  className="rounded-lg border border-ps-border px-3 py-1 text-xs text-ps-ink hover:border-ps-hint disabled:opacity-40">Apply</button>
                <button disabled={busy} onClick={downloadStatement}
                  className="inline-flex items-center gap-1 rounded-lg bg-brand px-3 py-1 text-xs text-white disabled:opacity-40">
                  <Download size={13} /> Download PDF
                </button>
                <span className="text-2xs text-ps-hint">Defaults to the current financial year.</span>
              </div>
              {statement === null ? (sectionFailed["statements"] ? <ErrorRetry onRetry={() => loadSection("statements", activeClient!)} /> : <Loading />) : statement.available === false ? (
                <Empty label="No statement is available for this client yet." />
              ) : (
                <>
                  <div className="mb-2 flex gap-6 text-xs text-ps-label">
                    <span>Opening: <span className="font-medium text-ps-ink">{formatPaise(statement.opening_balance_paise)}</span></span>
                    <span>Closing: <span className="font-medium text-ps-ink">{formatPaise(statement.closing_balance_paise)}</span></span>
                  </div>
                  {statement.transactions.length === 0 ? <Empty label="No transactions in this period." /> : (
                    <Table head={["Date", "Particulars", "Debit", "Credit", "Balance"]}>
                      {statement.transactions.map((t, idx) => (
                        <tr key={idx} className="border-t border-ps-border">
                          <td className="px-3 py-2 text-ps-label">{formatDate(t.date)}</td>
                          <td className="px-3 py-2 text-ps-ink">{t.particulars}</td>
                          <td className="px-3 py-2 tabular-nums">{t.debit_paise ? formatPaise(t.debit_paise) : "—"}</td>
                          <td className="px-3 py-2 tabular-nums">{t.credit_paise ? formatPaise(t.credit_paise) : "—"}</td>
                          <td className="px-3 py-2 tabular-nums font-medium">{formatPaise(t.running_balance_paise)}</td>
                        </tr>
                      ))}
                    </Table>
                  )}
                </>
              )}
            </Panel>
          )}

          {/* ── Payment Reminders ── */}
          {active === "reminders" && (
            <Panel title="Payment Reminders">
              {reminders === null ? (sectionFailed["reminders"] ? <ErrorRetry onRetry={() => loadSection("reminders", activeClient!)} /> : <Loading />) : reminders.length === 0 ? <Empty label="No reminders have been sent." /> : (
                <Table head={["Invoice", "Status", "Sent"]}>
                  {reminders.map((r, idx) => (
                    <tr key={idx} className="border-t border-ps-border">
                      <td className="px-3 py-2 font-medium text-ps-ink">{r.invoice_no ?? "—"}</td>
                      <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                      <td className="px-3 py-2 text-ps-label">{r.sent_at ? formatDate(r.sent_at) : (r.created_at ? formatDate(r.created_at) : "—")}</td>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
          )}

          {/* ── Compliance Status ── */}
          {active === "compliance" && (
            <Panel title="Compliance Status">
              {compliance === null ? (sectionFailed["compliance"] ? <ErrorRetry onRetry={() => loadSection("compliance", activeClient!)} /> : <Loading />) : compliance.length === 0 ? <Empty label="No compliance items to show." /> : (
                <Table head={["Type", "Obligation", "Period", "Due", "Status"]}>
                  {compliance.map((c, idx) => (
                    <tr key={idx} className="border-t border-ps-border">
                      <td className="px-3 py-2 font-medium text-ps-ink">{c.compliance_type ?? "—"}</td>
                      <td className="px-3 py-2 text-ps-label">{c.obligation_type ?? "—"}</td>
                      <td className="px-3 py-2 text-ps-label">{c.period_label ?? "—"}</td>
                      <td className="px-3 py-2 text-ps-label">{c.due_date ? formatDate(c.due_date) : "—"}</td>
                      <td className="px-3 py-2"><StatusBadge status={c.status} /></td>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
          )}

          {/* ── Documents (2.4) ── */}
          {active === "documents" && (
            <PortalPanel title="Documents">
              {documents === null ? (sectionFailed["documents"] ? <ErrorRetry onRetry={() => loadSection("documents", activeClient!)} /> : <Loading />) : documents.length === 0 ? (
                <PortalEmpty label="Your accountant has not filed any documents against your account yet." />
              ) : (
                <PortalTable head={["Document", "Filed", "Size", ""]}>
                  {documents.map((d) => (
                    <PortalRow key={d.id}>
                      <td className="px-3 py-2">
                        <span className="font-medium text-ps-ink">{d.description || d.file_name}</span>
                        {d.description && d.description !== d.file_name && (
                          <span className="block text-2xs text-ps-hint">{d.file_name}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-ps-label">{d.created_at ? formatDate(d.created_at) : "—"}</td>
                      <td className="px-3 py-2 tabular-nums text-ps-label">{fileSize(d.file_size)}</td>
                      <td className="px-3 py-2 text-right">
                        <Button variant="ghost" size="sm" disabled={busy}
                          onClick={() => openDocument(d.id)} className="gap-1 text-xs">
                          <Download size={13} /> Open
                        </Button>
                      </td>
                    </PortalRow>
                  ))}
                </PortalTable>
              )}
            </PortalPanel>
          )}

          {/* ── Document Requests (2.4) ── */}
          {active === "requests" && (
            <PortalPanel title="Document Requests">
              {requests === null ? (sectionFailed["requests"] ? <ErrorRetry onRetry={() => loadSection("requests", activeClient!)} /> : <Loading />) : requests.length === 0 ? (
                <PortalEmpty label="Your accountant has not asked you for anything." />
              ) : (
                <PortalTable head={["What is needed", "Asked", "Status"]}>
                  {requests.map((r) => (
                    <PortalRow key={r.id}>
                      <td className="px-3 py-2">
                        <span className="font-medium text-ps-ink">{r.title}</span>
                        {r.is_urgent && r.status !== "fulfilled" && (
                          <span className="ml-2 rounded-full border border-state-problem-border bg-state-problem-surface px-1.5 py-0.5 text-3xs font-medium text-state-problem">
                            urgent
                          </span>
                        )}
                        {r.description && (
                          <span className="block text-2xs text-ps-hint">{r.description}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-ps-label">{r.created_at ? formatDate(r.created_at) : "—"}</td>
                      <td className="px-3 py-2">
                        <StatusBadge
                          status={r.status === "fulfilled"
                            ? (r.fulfilled_at ? `received ${formatDate(r.fulfilled_at)}` : "received")
                            : "still needed"}
                          danger={r.status !== "fulfilled" && !!r.is_urgent}
                        />
                      </td>
                    </PortalRow>
                  ))}
                </PortalTable>
              )}
            </PortalPanel>
          )}

          {/* ── Messages (2.4) ── */}
          {active === "messages" && (
            <PortalPanel title="Messages">
              {messages === null ? (sectionFailed["messages"] ? <ErrorRetry onRetry={() => loadSection("messages", activeClient!)} /> : <Loading />) : (
                <div className="space-y-3">
                  {messages.length === 0 ? (
                    <PortalEmpty label="No messages yet. Write below and your accountant will see it." />
                  ) : (
                    <ol className="space-y-2">
                      {messages.map((m) => {
                        const mine = m.sender_type === "client";
                        return (
                          <li key={m.id} className={mine ? "flex justify-end" : "flex justify-start"}>
                            <div className={`max-w-[85%] rounded-xl border px-3 py-2 ${
                              mine ? "border-brand-dark/20 bg-brand-dark/5" : "border-ps-border bg-white"}`}>
                              <p className="text-3xs text-ps-hint">
                                {mine ? "You" : (m.sender_name || "Your accountant")}
                                {m.created_at && ` · ${formatDate(m.created_at)}`}
                              </p>
                              <p className="mt-0.5 whitespace-pre-wrap text-sm text-ps-body">{m.body}</p>
                            </div>
                          </li>
                        );
                      })}
                    </ol>
                  )}
                  <form
                    className="flex items-end gap-2 border-t border-ps-border pt-3"
                    onSubmit={(e) => { e.preventDefault(); sendMessage(); }}
                  >
                    <label className="flex-1">
                      <span className="sr-only">Your message</span>
                      <textarea
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        rows={2}
                        maxLength={4000}
                        placeholder="Write to your accountant…"
                        className="w-full resize-y rounded-lg border border-ps-border px-3 py-2 text-sm text-ps-ink focus:outline-none focus:ring-1 focus:ring-brand-dark"
                      />
                    </label>
                    <Button type="submit" size="sm" disabled={busy || !draft.trim()} className="gap-1.5">
                      <Send size={13} /> Send
                    </Button>
                  </form>
                </div>
              )}
            </PortalPanel>
          )}
        </>
      )}
    </PortalShell>
  );
}

/** A file size a client reads, not a byte count. */
function fileSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// The local `Panel` and `Table` this file used to declare were the shared
// `PortalPanel` and `PortalTable` written twice, in raw `gray-*`. They are
// gone; these three aliases keep the seven call sites below reading the same
// and are the only local chrome left.
const Panel = PortalPanel;
const Table = PortalTable;
const Empty = PortalEmpty;

function Loading() { return <PageLoader className="min-h-[20vh]" />; }

function ErrorRetry({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="space-y-2 p-6 text-center">
      <p className="text-sm text-state-problem">Couldn&apos;t load this section.</p>
      <Button variant="outline" size="sm" onClick={onRetry}>Retry</Button>
    </div>
  );
}
