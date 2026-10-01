"use client";

/**
 * Compliance Calendar — the month's obligations, across the clients the caller
 * may see (practice_management-17).
 *
 * EVERY DATE ON THIS SCREEN IS THE SERVER'S. It reads
 * `GET /api/compliance/obligations/calendar`: the same `compliance_records` the
 * Deadlines screen and a client's Compliance tab track, each with a due date
 * computed by `services/compliance_engine` — the 22nd or 24th for a QRMP client's
 * GSTR-3B, the state-group rule, an extension a notification granted — and each
 * with a status that survives a reload. This file states no due date, computes
 * none and holds no table of them.
 *
 * It used to. It built fourteen deadlines in the browser (the 11th and the 20th
 * for EVERY client, advance-tax dates, TDS returns, AOC-4 and MGT-7 a day off the
 * engine), attached every one to ALL clients, and kept its done tick in component
 * state — so a tick was gone on refresh and recorded nowhere, and a QRMP client
 * was shown a date that was not theirs. `scripts/a-statutory-due-date-is-never-a-
 * literal.test.ts` listed it as a KNOWN DEFECT.
 *
 * ONE CHIP PER (DUE DATE, OBLIGATION, PERIOD), NOT ONE PER CLIENT: a hundred
 * clients' GSTR-3B fall on the same day and a hundred chips are unreadable. A chip
 * says how many clients it covers and how many are done; the day panel lists them,
 * each with its own tick. A tick goes through the SAME prompt as the Deadlines
 * screen (`MarkFiledModal`), which asks for the date the return was filed on the
 * portal — recording a GSTR-1 or GSTR-3B as filed locks that period, and the lock
 * quotes the date. Nothing is filed by this screen: it records what the CA has
 * already done on the portal. CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.
 *
 * THE MCA ANNUAL FORMS COME FROM THE MCA WORKSPACE, NOT FROM THE OBLIGATION ROWS.
 * AOC-4 and MGT-7 are counted from each company's own AGM date, which that
 * endpoint reads (`mca_companies.last_agm_date`) and NAMES a company without,
 * where the generated rows fall back to the latest date the Act allows an AGM —
 * a date nobody chose. They carry nothing to tick here (the filing is recorded
 * in the company's own MCA workspace), and a company with no AGM date recorded is
 * named in the notice at the top rather than given a plausible one.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import Link from "next/link";
import {
  ChevronLeft, ChevronRight, Calendar, CheckCircle, Circle, AlertTriangle,
} from "lucide-react";
import { api } from "@/lib/api";
import { arrayOrEmpty, objectOrNull } from "@/lib/api/shape";
import { getClients } from "@/lib/data/clients";
import {
  getObligationCalendar, markFiled as markObligationFiled,
} from "@/lib/data/compliance";
import type { ComplianceEntry, ObligationCalendar } from "@/lib/data/compliance";
import {
  categoryOf, groupObligations, groupsOnDay, overdueGroups, upcomingGroups,
} from "@/lib/compliance/calendarGroups";
import type { CalendarCategory, ObligationGroup } from "@/lib/compliance/calendarGroups";
import { describeFilingOutcome } from "@/lib/compliance/filingOutcome";
import { MarkFiledModal } from "@/components/compliance/MarkFiledModal";
import { useToast } from "@/components/ui/use-toast";
import type { Client } from "@/lib/types";
import { todayLocalISO, toLocalISO, fromLocalISO, daysBetweenLocalISO } from "@/lib/dateMath";
import { formatDate } from "@/lib/services/formatting";

// ─── COLOUR SCHEME ────────────────────────────────────────────────────────────

const CATEGORY_STYLES: Record<CalendarCategory, { chip: string; badge: string }> = {
  GST:       { chip: "bg-state-problem-surface text-state-problem border-state-problem-border", badge: "bg-red-500" },
  IncomeTax: { chip: "bg-blue-100 text-blue-700 border-blue-200", badge: "bg-blue-500" },
  TDS:       { chip: "bg-orange-100 text-orange-700 border-orange-200", badge: "bg-orange-500" },
  MCA:       { chip: "bg-purple-100 text-purple-700 border-purple-200", badge: "bg-purple-500" },
  Payroll:   { chip: "bg-teal-100 text-teal-700 border-teal-200", badge: "bg-teal-500" },
  Other:     { chip: "bg-green-100 text-green-700 border-green-200", badge: "bg-green-500" },
};

const CATEGORY_LABELS: Record<CalendarCategory, string> = {
  GST: "GST", IncomeTax: "Income Tax", TDS: "TDS", MCA: "MCA", Payroll: "Payroll deposits", Other: "Other",
};

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** How far ahead the "Upcoming" panel looks. A panel, not a statutory figure. */
const UPCOMING_WINDOW_DAYS = 45;

function pad(n: number): string { return String(n).padStart(2, "0"); }
function isoOf(y: number, m: number, d: number): string { return `${y}-${pad(m + 1)}-${pad(d)}`; }
function monthBounds(y: number, m: number): { from: string; to: string } {
  return { from: toLocalISO(new Date(y, m, 1)), to: toLocalISO(new Date(y, m + 1, 0)) };
}
function addDaysISO(iso: string, days: number): string {
  const d = fromLocalISO(iso) ?? new Date();
  d.setDate(d.getDate() + days);
  return toLocalISO(d);
}

/** An MCA annual form, counted from the company's own AGM (not an obligation row). */
interface McaDeadline {
  client_id: string; company_name: string; form_type: string; due_date: string; description: string;
}

// ─── MAIN PAGE ────────────────────────────────────────────────────────────────

export default function CalendarPage() {
  const todayISO = todayLocalISO();
  const todayDate = fromLocalISO(todayISO) ?? new Date();
  const { toast } = useToast();

  const [viewYear, setViewYear] = useState(todayDate.getFullYear());
  const [viewMonth, setViewMonth] = useState(todayDate.getMonth());
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [month, setMonth] = useState<ObligationCalendar | null>(null);
  const [ahead, setAhead] = useState<ObligationCalendar | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [mca, setMca] = useState<McaDeadline[]>([]);
  const [agmGaps, setAgmGaps] = useState<{ company_name: string }[]>([]);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  const [marking, setMarking] = useState<{ entry: ComplianceEntry; label: string } | null>(null);
  const [filingBusy, setFilingBusy] = useState(false);
  const [filingError, setFilingError] = useState<string | null>(null);

  // A response for a month the person has already navigated away from must not
  // overwrite the one they are looking at.
  const latest = useRef(0);

  const clientMap = useMemo(() => new Map(clients.map((c) => [c.id, c.client_name])), [clients]);

  useEffect(() => {
    let live = true;
    getClients()
      .then((list) => { if (live) setClients(arrayOrEmpty<Client>(list)); })
      .catch(() => { /* the calendar still shows; rows just lack a client name */ });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await api.mca.firmCalendar() as {
          success: boolean;
          data?: { deadlines?: unknown; without_agm_date?: unknown };
        };
        if (!live || !res?.success) return;
        const d = objectOrNull<{ deadlines?: unknown; without_agm_date?: unknown }>(res.data);
        setMca(arrayOrEmpty<McaDeadline>(d?.deadlines));
        setAgmGaps(arrayOrEmpty<{ company_name: string }>(d?.without_agm_date));
      } catch {
        // The obligations still stand; the MCA forms are simply absent, which is the
        // honest degradation — better than dates nobody computed.
      }
    })();
    return () => { live = false; };
  }, []);

  const loadMonth = useCallback(async () => {
    const mine = ++latest.current;
    setLoading(true);
    try {
      const { from, to } = monthBounds(viewYear, viewMonth);
      const cal = await getObligationCalendar({ dateFrom: from, dateTo: to, clientId: clientId || undefined });
      if (mine !== latest.current) return;
      setMonth(cal);
      setError(null);
    } catch (e: unknown) {
      if (mine !== latest.current) return;
      // A failed read is NOT an empty month, and the screen says which it is.
      setMonth(null);
      setError(e instanceof Error ? e.message : "The calendar could not be loaded.");
    } finally {
      if (mine === latest.current) setLoading(false);
    }
  }, [viewYear, viewMonth, clientId]);

  const loadAhead = useCallback(async () => {
    try {
      const cal = await getObligationCalendar({
        dateFrom: todayISO, dateTo: addDaysISO(todayISO, UPCOMING_WINDOW_DAYS),
        clientId: clientId || undefined,
      });
      setAhead(cal);
    } catch {
      setAhead(null); // the side panels simply do not appear; the month grid says why
    }
  }, [todayISO, clientId]);

  useEffect(() => { void loadMonth(); }, [loadMonth]);
  useEffect(() => { void loadAhead(); }, [loadAhead]);

  // ── what the screen shows ──────────────────────────────────────────────────

  // The obligation rows, with the MCA annual forms taken out: the generated rows
  // carry a date counted from an AGM nobody recorded, and the MCA workspace's own
  // rows (below) count from the real one.
  const recordRows = (cal: ObligationCalendar | null): ComplianceEntry[] =>
    cal ? [...cal.upcoming, ...cal.overdue, ...cal.completed]
      .filter((e) => categoryOf(e.compliance_type) !== "MCA") : [];

  const mcaItems = (from: string, to: string) => mca
    .filter((d) => (!clientId || d.client_id === clientId) && d.due_date >= from && d.due_date <= to)
    .map((d) => ({
      client_id: d.client_id, company_name: d.company_name, description: d.description,
      due_date: d.due_date, label: d.form_type,
    }));

  const { from: monthFrom, to: monthTo } = monthBounds(viewYear, viewMonth);
  const monthGroups: ObligationGroup[] = useMemo(
    () => groupObligations(
      recordRows(month).filter((e) => e.due_date >= monthFrom && e.due_date <= monthTo),
      todayISO, mcaItems(monthFrom, monthTo)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [month, mca, clientId, monthFrom, monthTo, todayISO]);

  const aheadGroups: ObligationGroup[] = useMemo(
    () => groupObligations(recordRows(ahead), todayISO,
      mcaItems("0000-01-01", addDaysISO(todayISO, UPCOMING_WINDOW_DAYS))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ahead, mca, clientId, todayISO]);

  const upcoming = upcomingGroups(aheadGroups, todayISO, 10);
  const late = overdueGroups(aheadGroups);
  const lateCount = late.reduce((n, g) => n + g.overdue, 0);

  const totalDays = new Date(viewYear, viewMonth + 1, 0).getDate();
  const startDow = new Date(viewYear, viewMonth, 1).getDay();
  const cells: Array<number | null> = [];
  for (let i = 0; i < startDow; i++) cells.push(null);
  for (let d = 1; d <= totalDays; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  const selectedGroups = selectedDay ? groupsOnDay(monthGroups, selectedDay) : [];

  function prevMonth() {
    if (viewMonth === 0) { setViewYear((y) => y - 1); setViewMonth(11); } else setViewMonth((m) => m - 1);
  }
  function nextMonth() {
    if (viewMonth === 11) { setViewYear((y) => y + 1); setViewMonth(0); } else setViewMonth((m) => m + 1);
  }
  function goToday() {
    setViewYear(todayDate.getFullYear());
    setViewMonth(todayDate.getMonth());
    setSelectedDay(todayISO);
  }

  async function confirmFiled(v: { filedDate: string; arn: string }) {
    if (!marking) return;
    setFilingBusy(true);
    setFilingError(null);
    try {
      const result = await markObligationFiled(marking.entry.id, {
        arn: v.arn || undefined, filedDate: v.filedDate,
      });
      // What the server did about the period — a tick that closed nothing must
      // not read like one that closed the month.
      const outcome = describeFilingOutcome(result, marking.label);
      toast({ title: outcome.title, description: outcome.description });
      setMarking(null);
      // Re-read rather than patch in place: the tick is shown because the server
      // holds it, and a reload shows the same.
      await Promise.all([loadMonth(), loadAhead()]);
    } catch (e: unknown) {
      setFilingError(e instanceof Error ? e.message : "Couldn't mark this filed.");
    } finally {
      setFilingBusy(false);
    }
  }

  const nameOf = (id: string) => clientMap.get(id) ?? "Unknown client";

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* A company with no AGM date recorded has no AOC-4 or MGT-7 here, and
          silence looks exactly like "nothing due". Named, for the same reason a
          payroll run names its statutory gaps. */}
      {agmGaps.length > 0 && (
        <div className="bg-state-attention-surface border border-state-attention-border rounded-xl px-4 py-3">
          <p className="text-xs font-medium text-amber-800">
            {agmGaps.length} compan{agmGaps.length === 1 ? "y has" : "ies have"} no AGM date
            recorded, so their AOC-4 and MGT-7 are not shown
          </p>
          <p className="text-xs text-state-attention mt-0.5">
            Both are counted from the AGM, so there is no date to show — record it on the
            client&apos;s MCA tab.{" "}
            {agmGaps.map((g) => g.company_name).filter(Boolean).join(", ")}
          </p>
        </div>
      )}

      {error && (
        <div role="alert" className="bg-state-problem-surface border border-state-problem-border rounded-xl px-4 py-3 text-sm text-state-problem">
          {error} Nothing below is a statement that no deadline falls in this month.
        </div>
      )}

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Compliance Calendar</h1>
          <p className="text-sm text-ps-label mt-0.5">
            Each client&apos;s own obligations, on the dates the compliance engine computed for them
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <select
            aria-label="Client"
            value={clientId}
            onChange={(e) => { setClientId(e.target.value); setSelectedDay(null); }}
            className="border border-ps-border rounded-lg px-3 py-1.5 text-sm text-ps-body focus:outline-none focus:ring-2 focus:ring-brand/30"
          >
            <option value="">All my clients</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.client_name}</option>)}
          </select>
          <button onClick={goToday} className="px-3 py-1.5 text-sm border border-ps-border rounded-lg text-ps-label hover:bg-ps-bg">
            Today
          </button>
          <button onClick={prevMonth} className="p-1.5 border border-ps-border rounded-lg text-ps-label hover:bg-ps-bg" aria-label="Previous month">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-semibold text-ps-ink w-36 text-center">
            {MONTH_NAMES[viewMonth]} {viewYear}
          </span>
          <button onClick={nextMonth} className="p-1.5 border border-ps-border rounded-lg text-ps-label hover:bg-ps-bg" aria-label="Next month">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3">
        {(Object.keys(CATEGORY_STYLES) as CalendarCategory[]).map((cat) => (
          <div key={cat} className="flex items-center gap-1.5">
            <span className={`w-2.5 h-2.5 rounded-full ${CATEGORY_STYLES[cat].badge}`} />
            <span className="text-xs text-ps-label">{CATEGORY_LABELS[cat]}</span>
          </div>
        ))}
        {loading && <span className="text-xs text-ps-hint ml-2">Loading…</span>}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_300px] gap-6">
        {/* Calendar grid */}
        <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
          <div className="grid grid-cols-7 border-b border-ps-border">
            {DAY_LABELS.map((d) => (
              <div key={d} className="py-2 text-center text-xs font-medium text-ps-hint">{d}</div>
            ))}
          </div>
          <div className="grid grid-cols-7">
            {cells.map((day, idx) => {
              if (day === null) {
                return <div key={`empty-${idx}`} className="min-h-[90px] border-b border-r border-ps-border bg-ps-bg/30" />;
              }
              const iso = isoOf(viewYear, viewMonth, day);
              const chips = groupsOnDay(monthGroups, iso);
              const isSelected = selectedDay === iso;
              return (
                <div
                  key={iso}
                  onClick={() => setSelectedDay(isSelected ? null : iso)}
                  className={`min-h-[90px] border-b border-r border-ps-border p-1.5 cursor-pointer transition-colors
                    ${isSelected ? "bg-blue-50" : "hover:bg-ps-bg/60"}`}
                >
                  <div className={`w-6 h-6 flex items-center justify-center rounded-full text-xs font-medium mb-1
                    ${iso === todayISO ? "bg-brand text-white" : "text-ps-body"}`}>
                    {day}
                  </div>
                  <div className="space-y-0.5">
                    {chips.slice(0, 3).map((g) => {
                      const allDone = g.open === 0;
                      return (
                        <div
                          key={g.key}
                          title={`${g.label} — ${g.filed} of ${g.total} filed`}
                          className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-3xs font-medium select-none
                            ${CATEGORY_STYLES[g.category].chip} ${allDone ? "opacity-50" : ""}`}
                        >
                          {allDone ? <CheckCircle className="w-3 h-3 shrink-0" /> : <Circle className="w-3 h-3 shrink-0" />}
                          <span className="truncate">{g.label}</span>
                          <span className="opacity-70 shrink-0">· {g.total}</span>
                        </div>
                      );
                    })}
                    {chips.length > 3 && <div className="text-3xs text-ps-hint pl-1">+{chips.length - 3} more</div>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right side */}
        <div className="space-y-4">
          {selectedDay && (
            <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
              <div className="px-4 py-3 border-b border-ps-border flex items-center gap-2">
                <Calendar className="w-4 h-4 text-blue-600" />
                <h2 className="text-sm font-semibold text-ps-ink">{formatDate(selectedDay)}</h2>
              </div>
              {selectedGroups.length === 0 ? (
                <p className="px-4 py-6 text-xs text-ps-hint text-center">
                  {error ? "This day could not be loaded." : "Nothing falls due this day."}
                </p>
              ) : (
                <div className="divide-y divide-ps-border max-h-[32rem] overflow-y-auto">
                  {selectedGroups.map((g) => (
                    <div key={g.key} className="px-4 py-3 space-y-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`text-3xs px-1.5 py-0.5 rounded border font-medium ${CATEGORY_STYLES[g.category].chip}`}>
                          {CATEGORY_LABELS[g.category]}
                        </span>
                        <span className="text-sm font-medium text-ps-ink">{g.label}</span>
                        <span className="text-3xs text-ps-hint">
                          {g.filed} of {g.total} filed{g.not_applicable > 0 ? ` · ${g.not_applicable} not applicable` : ""}
                        </span>
                      </div>
                      <ul className="space-y-1">
                        {g.entries.map((e) => {
                          const done = e.filing_status === "filed";
                          const na = e.filing_status === "na";
                          const late = !done && !na && e.due_date < todayISO;
                          return (
                            <li key={e.id} className="flex items-center gap-2 text-xs">
                              {done ? (
                                <CheckCircle className="w-4 h-4 text-green-500 shrink-0" aria-label="Filed" />
                              ) : na ? (
                                <span className="w-4 h-4 shrink-0 text-center text-ps-hint" aria-label="Not applicable">–</span>
                              ) : (
                                <button
                                  onClick={() => { setFilingError(null); setMarking({ entry: e, label: `${nameOf(e.client_id)} — ${g.label}` }); }}
                                  className="shrink-0 text-ps-disabled hover:text-ps-label"
                                  aria-label={`Record ${nameOf(e.client_id)} as filed`}
                                >
                                  <Circle className="w-4 h-4" />
                                </button>
                              )}
                              <span className="flex-1 min-w-0 truncate text-ps-body">{nameOf(e.client_id)}</span>
                              <span className={`shrink-0 text-3xs ${late ? "text-state-problem font-semibold" : "text-ps-hint"}`}>
                                {done
                                  ? `Filed${e.filed_date ? ` ${formatDate(e.filed_date)}` : ""}${e.arn_number ? ` · ${e.arn_number}` : ""}`
                                  : na ? "Not applicable" : late ? "Overdue" : "Pending"}
                              </span>
                            </li>
                          );
                        })}
                        {g.external.map((x) => (
                          <li key={`${x.client_id}-${x.company_name}`} className="text-xs text-ps-body">
                            <span className="font-medium">{x.company_name}</span>
                            <p className="text-3xs text-ps-hint">
                              {x.description} — counted from the company&apos;s own AGM date; the filing is recorded
                              in its MCA workspace.
                            </p>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Overdue — never windowed, so another month cannot hide it */}
          {lateCount > 0 && (
            <div className="bg-white rounded-xl border border-state-problem-border overflow-hidden">
              <div className="px-4 py-3 border-b border-ps-border flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-state-problem" />
                <h2 className="text-sm font-semibold text-ps-ink">Overdue ({lateCount})</h2>
              </div>
              <div className="divide-y divide-ps-border">
                {late.slice(0, 6).map((g) => (
                  <div key={g.key} className="px-4 py-2.5 flex items-center gap-3">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${CATEGORY_STYLES[g.category].badge}`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-ps-ink truncate">{g.label}</p>
                      <p className="text-3xs text-ps-hint">{formatDate(g.due_date)} · {g.overdue} of {g.total} not filed</p>
                    </div>
                  </div>
                ))}
                <div className="px-4 py-2.5">
                  <Link href="/deadlines" className="text-xs text-brand-dark hover:underline">
                    {late.length > 6 ? `All ${late.length} overdue obligations on Deadlines →` : "Open them on Deadlines →"}
                  </Link>
                </div>
              </div>
            </div>
          )}

          {/* Upcoming */}
          <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
            <div className="px-4 py-3 border-b border-ps-border">
              <h2 className="text-sm font-semibold text-ps-ink">Upcoming</h2>
              <p className="text-xs text-ps-hint mt-0.5">Next {upcoming.length || 10} with something still to do</p>
            </div>
            {ahead === null ? (
              <p className="px-4 py-6 text-xs text-ps-hint text-center">Could not be loaded.</p>
            ) : upcoming.length === 0 ? (
              <p className="px-4 py-6 text-xs text-ps-hint text-center">Nothing is waiting in the next {UPCOMING_WINDOW_DAYS} days.</p>
            ) : (
              <div className="divide-y divide-ps-border">
                {upcoming.map((g) => {
                  const away = daysBetweenLocalISO(todayISO, g.due_date) ?? 0;
                  const urgent = away <= 3 ? "text-red-600 font-semibold" : away <= 7 ? "text-amber-600" : "text-ps-hint";
                  return (
                    <div key={g.key} className="px-4 py-2.5 flex items-center gap-3">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${CATEGORY_STYLES[g.category].badge}`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-ps-ink truncate">{g.label}</p>
                        <p className="text-3xs text-ps-hint">{formatDate(g.due_date)} · {g.open} of {g.total} to do</p>
                      </div>
                      <span className={`text-3xs shrink-0 ${urgent}`}>
                        {away === 0 ? "Today" : away === 1 ? "Tomorrow" : `${away}d`}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {marking && (
        <MarkFiledModal
          intro={marking.label}
          initialArn={marking.entry.arn_number ?? ""}
          busy={filingBusy}
          error={filingError}
          onConfirm={confirmFiled}
          onClose={() => { setMarking(null); setFilingError(null); }}
        />
      )}
    </div>
  );
}
