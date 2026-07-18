"use client";

// Phase 4.5.2 — Customer Portal dashboard with data surfaces.
// Auth is the client's own Supabase session, resolved server-side via
// get_current_portal_client. Every surface here is the firm↔client fee
// relationship (invoices, canonical dues, statement, payment reminders) plus
// the client's own compliance status — served by /api/portal/self/*. The active
// client is selected EXPLICITLY via X-Portal-Client-Id (no implicit switching).
// All amounts are integer paise from the server; the frontend only formats them.

import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import {
  FileText, FolderOpen, MessageSquare, Receipt, ScrollText, BellRing, ShieldCheck,
  Download, AlertCircle, CreditCard, type LucideIcon,
} from "lucide-react";
import { api, type ApiResp } from "@/lib/api";
import { getSupabaseClient } from "@/lib/supabase/client";
import { formatPaise, formatDate } from "@/lib/services/formatting";
import { PageLoader } from "@/components/ui/skeleton";

interface Section { key: string; label: string; available: boolean }
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

// The fee-relationship surfaces this page renders inline (the RLS-direct
// documents/messages/requests live on their own pages and are not loaded here).
const DATA_SECTIONS = new Set(["invoices", "statements", "reminders", "compliance"]);

function StatusBadge({ status, danger }: { status: string | null; danger?: boolean }) {
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium ${
      danger ? "bg-red-100 text-red-700" : "bg-gray-100 text-gray-600"}`}>
      {status ?? "—"}
    </span>
  );
}

export default function PortalDashboardPage() {
  const searchParams = useSearchParams();
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
  const [stmtStart, setStmtStart] = useState<string>("");
  const [stmtEnd, setStmtEnd] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

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
        setStatement(r.data);
      }
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Unable to load this section");
    }
  }, [invoices, reminders, compliance, statement, stmtStart, stmtEnd]);

  useEffect(() => {
    if (activeClient && DATA_SECTIONS.has(active)) loadSection(active, activeClient);
  }, [active, activeClient, loadSection]);

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
      setStatement(r.data);
    } catch (e) { setNotice(e instanceof Error ? e.message : "Could not load statement"); }
    finally { setBusy(false); }
  };

  if (loading) return <div className="p-8 text-sm text-gray-500">Loading your portal…</div>;
  if (error) {
    return (
      <div className="p-8 max-w-md">
        <p className="text-sm text-red-600">{error}</p>
        <p className="text-xs text-gray-400 mt-2">If you believe you should have access, ask your accountant to invite you.</p>
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
      <div className="p-8 max-w-md">
        <p className="text-sm text-gray-600">You don&apos;t have access to a client portal right now.</p>
        <p className="text-xs text-gray-400 mt-2">If you believe you should have access, ask your accountant to invite you.</p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-[#182350]">Your Portal</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Welcome{dash?.contact.name ? `, ${dash.contact.name}` : ""}. Your secure workspace with your accountant.
          </p>
        </div>
        {memberships.length > 1 && (
          <label className="text-xs text-gray-600">
            <span className="block text-[11px] text-gray-400 mb-0.5">Client</span>
            <select
              value={activeClient ?? ""}
              onChange={(e) => { setActiveClient(e.target.value || null); }}
              className="border border-gray-200 rounded-lg px-2 py-1 text-xs text-[#182350]">
              <option value="">Select a client…</option>
              {memberships.map((m) => <option key={m.client_id} value={m.client_id}>{m.name ?? m.client_id}</option>)}
            </select>
          </label>
        )}
      </div>

      {memberships.length > 1 && !activeClient ? (
        <div className="bg-[#F8FAFC] border border-dashed border-gray-200 rounded-xl p-8 text-center text-sm text-gray-500">
          You have access to {memberships.length} clients. Choose one above to continue.
        </div>
      ) : !dash ? (
        <PageLoader />
      ) : (
        <>
          {/* Dues summary — the headline "what do I owe the firm" figure. */}
          {dues && (
            <div className="mb-5 grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-[11px] uppercase tracking-wide text-gray-400">Total Outstanding</p>
                <p className="mt-1 text-xl font-semibold text-[#182350]">{formatPaise(dues.total_outstanding_paise)}</p>
              </div>
              <div className={`rounded-xl border p-4 ${dues.overdue_paise > 0 ? "border-red-200 bg-red-50" : "border-gray-200 bg-white"}`}>
                <p className="text-[11px] uppercase tracking-wide text-gray-400">Overdue</p>
                <p className={`mt-1 text-xl font-semibold ${dues.overdue_paise > 0 ? "text-red-700" : "text-[#182350]"}`}>{formatPaise(dues.overdue_paise)}</p>
              </div>
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-[11px] uppercase tracking-wide text-gray-400">Overdue Invoices</p>
                <p className="mt-1 text-xl font-semibold text-[#182350]">{dues.overdue_count}</p>
              </div>
            </div>
          )}

          {/* Section navigation. */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-5">
            {(dash.sections ?? []).filter((s) => DATA_SECTIONS.has(s.key)).map((s) => {
              const Icon = ICONS[s.key] ?? FileText;
              const on = active === s.key;
              return (
                <button key={s.key} onClick={() => setActive(s.key)}
                  className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm transition ${
                    on ? "border-[#182350] bg-[#182350] text-white" : "border-gray-200 bg-white text-[#182350] hover:border-gray-300"}`}>
                  <Icon size={16} className={on ? "text-white" : "text-gray-400"} />
                  <span className="font-medium">{s.label}</span>
                </button>
              );
            })}
          </div>

          {notice && (
            <div className="mb-3 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              <AlertCircle size={14} /> {notice}
            </div>
          )}

          {/* ── Invoices ── */}
          {active === "invoices" && (
            <Panel title="Invoices">
              {invoices === null ? <Loading /> : invoices.length === 0 ? <Empty label="No invoices yet." /> : (
                <Table head={["Invoice", "Date", "Due", "Total", "Outstanding", "Status", ""]}>
                  {invoices.map((i) => (
                    <tr key={i.id} className="border-t border-gray-100">
                      <td className="px-3 py-2 font-medium text-[#182350]">{i.invoice_no ?? "—"}</td>
                      <td className="px-3 py-2 text-gray-500">{i.invoice_date ? formatDate(i.invoice_date) : "—"}</td>
                      <td className="px-3 py-2 text-gray-500">{i.due_date ? formatDate(i.due_date) : "—"}</td>
                      <td className="px-3 py-2 tabular-nums">{formatPaise(i.total_paise)}</td>
                      <td className="px-3 py-2 tabular-nums">{formatPaise(i.outstanding_paise)}</td>
                      <td className="px-3 py-2"><StatusBadge status={i.is_overdue ? `overdue ${i.days_overdue}d` : i.status} danger={i.is_overdue} /></td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        {i.outstanding_paise > 0 && (
                          <button disabled={busy} onClick={() => payInvoice(i.id)}
                            className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:underline disabled:opacity-40 mr-3">
                            <CreditCard size={13} /> Pay Now
                          </button>
                        )}
                        <button disabled={busy} onClick={() => downloadInvoice(i.id)}
                          className="inline-flex items-center gap-1 text-xs text-[#182350] hover:underline disabled:opacity-40">
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
                <label className="text-xs text-gray-500">From
                  <input type="date" value={stmtStart} onChange={(e) => setStmtStart(e.target.value)}
                    className="ml-1 block sm:inline border border-gray-200 rounded px-2 py-1 text-xs" />
                </label>
                <label className="text-xs text-gray-500">To
                  <input type="date" value={stmtEnd} onChange={(e) => setStmtEnd(e.target.value)}
                    className="ml-1 block sm:inline border border-gray-200 rounded px-2 py-1 text-xs" />
                </label>
                <button disabled={busy} onClick={reloadStatement}
                  className="rounded-lg border border-gray-200 px-3 py-1 text-xs text-[#182350] hover:border-gray-300 disabled:opacity-40">Apply</button>
                <button disabled={busy} onClick={downloadStatement}
                  className="inline-flex items-center gap-1 rounded-lg bg-[#182350] px-3 py-1 text-xs text-white disabled:opacity-40">
                  <Download size={13} /> Download PDF
                </button>
                <span className="text-[11px] text-gray-400">Defaults to the current financial year.</span>
              </div>
              {statement === null ? <Loading /> : statement.available === false ? (
                <Empty label="No statement is available for this client yet." />
              ) : (
                <>
                  <div className="mb-2 flex gap-6 text-xs text-gray-500">
                    <span>Opening: <span className="font-medium text-[#182350]">{formatPaise(statement.opening_balance_paise)}</span></span>
                    <span>Closing: <span className="font-medium text-[#182350]">{formatPaise(statement.closing_balance_paise)}</span></span>
                  </div>
                  {statement.transactions.length === 0 ? <Empty label="No transactions in this period." /> : (
                    <Table head={["Date", "Particulars", "Debit", "Credit", "Balance"]}>
                      {statement.transactions.map((t, idx) => (
                        <tr key={idx} className="border-t border-gray-100">
                          <td className="px-3 py-2 text-gray-500">{formatDate(t.date)}</td>
                          <td className="px-3 py-2 text-[#182350]">{t.particulars}</td>
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
              {reminders === null ? <Loading /> : reminders.length === 0 ? <Empty label="No reminders have been sent." /> : (
                <Table head={["Invoice", "Status", "Sent"]}>
                  {reminders.map((r, idx) => (
                    <tr key={idx} className="border-t border-gray-100">
                      <td className="px-3 py-2 font-medium text-[#182350]">{r.invoice_no ?? "—"}</td>
                      <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                      <td className="px-3 py-2 text-gray-500">{r.sent_at ? formatDate(r.sent_at) : (r.created_at ? formatDate(r.created_at) : "—")}</td>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
          )}

          {/* ── Compliance Status ── */}
          {active === "compliance" && (
            <Panel title="Compliance Status">
              {compliance === null ? <Loading /> : compliance.length === 0 ? <Empty label="No compliance items to show." /> : (
                <Table head={["Type", "Obligation", "Period", "Due", "Status"]}>
                  {compliance.map((c, idx) => (
                    <tr key={idx} className="border-t border-gray-100">
                      <td className="px-3 py-2 font-medium text-[#182350]">{c.compliance_type ?? "—"}</td>
                      <td className="px-3 py-2 text-gray-600">{c.obligation_type ?? "—"}</td>
                      <td className="px-3 py-2 text-gray-500">{c.period_label ?? "—"}</td>
                      <td className="px-3 py-2 text-gray-500">{c.due_date ? formatDate(c.due_date) : "—"}</td>
                      <td className="px-3 py-2"><StatusBadge status={c.status} /></td>
                    </tr>
                  ))}
                </Table>
              )}
            </Panel>
          )}
        </>
      )}

      <p className="text-[11px] text-gray-400 mt-6">
        Figures reflect your account with your accountant. For anything that looks off, message your accountant.
      </p>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      <div className="border-b border-gray-100 px-4 py-2.5 text-sm font-semibold text-[#182350]">{title}</div>
      <div className="p-3 overflow-x-auto">{children}</div>
    </div>
  );
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="text-[11px] uppercase tracking-wide text-gray-400">
          {head.map((h, i) => <th key={i} className="px-3 py-1.5 font-medium">{h}</th>)}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

function Loading() { return <PageLoader className="min-h-[20vh]" />; }
function Empty({ label }: { label: string }) { return <div className="p-4 text-sm text-gray-400">{label}</div>; }
