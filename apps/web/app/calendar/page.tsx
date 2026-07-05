"use client";

/**
 * Compliance Calendar — monthly view of all Indian tax filing deadlines
 * CGST Act Section 37: GSTR-1 filing obligation
 * CGST Act Section 39: GSTR-3B filing obligation
 * CGST Act Section 44: GSTR-9 annual return
 * IT Act Section 208: Advance Tax obligation
 * IT Act Section 200: TDS return filing
 * Companies Act 2013 Section 137: AOC-4 filing
 * Companies Act 2013 Section 92: MGT-7 filing
 */

import { useState, useEffect, useCallback } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Calendar,
  CheckCircle,
  Circle,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Client } from "@/lib/types";
import { todayLocalISO } from "@/lib/dateMath";

// ─── TYPES ────────────────────────────────────────────────────────────────────

type DeadlineCategory = "GST" | "IncomeTax" | "TDS" | "MCA" | "Other";

interface Deadline {
  id: string;
  date: Date;
  label: string;       // e.g. "GSTR-1", "Advance Tax"
  category: DeadlineCategory;
  description: string;
  clientIds: string[]; // which clients this applies to (empty = firm-wide)
  done: boolean;
}

// ─── COLOUR SCHEME ────────────────────────────────────────────────────────────

const CATEGORY_STYLES: Record<DeadlineCategory, { chip: string; dot: string; badge: string }> = {
  GST:        { chip: "bg-red-100 text-red-700 border-red-200",     dot: "bg-red-500",    badge: "bg-red-500" },
  IncomeTax:  { chip: "bg-blue-100 text-blue-700 border-blue-200",  dot: "bg-blue-500",   badge: "bg-blue-500" },
  TDS:        { chip: "bg-orange-100 text-orange-700 border-orange-200", dot: "bg-orange-500", badge: "bg-orange-500" },
  MCA:        { chip: "bg-purple-100 text-purple-700 border-purple-200", dot: "bg-purple-500", badge: "bg-purple-500" },
  Other:      { chip: "bg-green-100 text-green-700 border-green-200",  dot: "bg-green-500",  badge: "bg-green-500" },
};

const CATEGORY_LABELS: Record<DeadlineCategory, string> = {
  GST: "GST",
  IncomeTax: "Income Tax",
  TDS: "TDS",
  MCA: "MCA",
  Other: "Other",
};

// ─── DEADLINE GENERATION ──────────────────────────────────────────────────────

/**
 * Generate all statutory deadlines for months [baseYear/baseMonth .. baseYear/baseMonth+3].
 * Dates are based on the Indian tax calendar — no client filtering here.
 *
 * CGST Act / IT Act references in each block.
 */
function generateDeadlines(clientIds: string[]): Deadline[] {
  const today = new Date();
  const deadlines: Deadline[] = [];

  // We generate for current month + next 3 months (4 months total)
  for (let offset = 0; offset < 4; offset++) {
    const refDate = new Date(today.getFullYear(), today.getMonth() + offset, 1);
    const y = refDate.getFullYear();
    const m = refDate.getMonth(); // 0-based

    // ── GSTR-1: 11th of every month — CGST Act Section 37
    deadlines.push({
      id: `gstr1-${y}-${m}`,
      date: new Date(y, m, 11),
      label: "GSTR-1",
      category: "GST",
      description: "CGST Act Section 37 — outward supplies return due 11th of following month",
      clientIds,
      done: false,
    });

    // ── GSTR-3B: 20th of every month — CGST Act Section 39
    deadlines.push({
      id: `gstr3b-${y}-${m}`,
      date: new Date(y, m, 20),
      label: "GSTR-3B",
      category: "GST",
      description: "CGST Act Section 39 — monthly summary return due 20th of following month",
      clientIds,
      done: false,
    });

    // ── GSTR-9: 31 Dec — CGST Act Section 44
    if (m === 11) { // December
      deadlines.push({
        id: `gstr9-${y}`,
        date: new Date(y, 11, 31),
        label: "GSTR-9",
        category: "GST",
        description: "CGST Act Section 44 — annual return for FY ending March",
        clientIds,
        done: false,
      });
    }

    // ── Advance Tax — IT Act Section 208 / 211
    // 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
    if (m === 5) { // June
      deadlines.push({
        id: `adv-tax-jun-${y}`,
        date: new Date(y, 5, 15),
        label: "Advance Tax (15%)",
        category: "IncomeTax",
        description: "IT Act Section 211 — 1st instalment: 15% of advance tax by 15 Jun",
        clientIds,
        done: false,
      });
    }
    if (m === 8) { // September
      deadlines.push({
        id: `adv-tax-sep-${y}`,
        date: new Date(y, 8, 15),
        label: "Advance Tax (45%)",
        category: "IncomeTax",
        description: "IT Act Section 211 — 2nd instalment: cumulative 45% by 15 Sep",
        clientIds,
        done: false,
      });
    }
    if (m === 11) { // December
      deadlines.push({
        id: `adv-tax-dec-${y}`,
        date: new Date(y, 11, 15),
        label: "Advance Tax (75%)",
        category: "IncomeTax",
        description: "IT Act Section 211 — 3rd instalment: cumulative 75% by 15 Dec",
        clientIds,
        done: false,
      });
    }
    if (m === 2) { // March
      deadlines.push({
        id: `adv-tax-mar-${y}`,
        date: new Date(y, 2, 15),
        label: "Advance Tax (100%)",
        category: "IncomeTax",
        description: "IT Act Section 211 — 4th instalment: 100% by 15 Mar",
        clientIds,
        done: false,
      });
    }

    // ── TDS Returns (24Q/26Q) — IT Act Section 200(3)
    // Q1 (Apr–Jun) → due 31 Jul
    if (m === 6) { // July
      deadlines.push({
        id: `tds-q1-${y}`,
        date: new Date(y, 6, 31),
        label: "TDS Return Q1 (26Q)",
        category: "TDS",
        description: "IT Act Section 200(3) — Q1 (Apr–Jun) TDS return due 31 Jul",
        clientIds,
        done: false,
      });
    }
    // Q2 (Jul–Sep) → due 31 Oct
    if (m === 9) { // October
      deadlines.push({
        id: `tds-q2-${y}`,
        date: new Date(y, 9, 31),
        label: "TDS Return Q2 (26Q)",
        category: "TDS",
        description: "IT Act Section 200(3) — Q2 (Jul–Sep) TDS return due 31 Oct",
        clientIds,
        done: false,
      });
    }
    // Q3 (Oct–Dec) → due 31 Jan
    if (m === 0) { // January
      deadlines.push({
        id: `tds-q3-${y}`,
        date: new Date(y, 0, 31),
        label: "TDS Return Q3 (26Q)",
        category: "TDS",
        description: "IT Act Section 200(3) — Q3 (Oct–Dec) TDS return due 31 Jan",
        clientIds,
        done: false,
      });
    }
    // Q4 (Jan–Mar) → due 31 May
    if (m === 4) { // May
      deadlines.push({
        id: `tds-q4-${y}`,
        date: new Date(y, 4, 31),
        label: "TDS Return Q4 (26Q)",
        category: "TDS",
        description: "IT Act Section 200(3) — Q4 (Jan–Mar) TDS return due 31 May",
        clientIds,
        done: false,
      });
    }

    // ── MCA Deadlines (Companies Act 2013)
    // DIR-3 KYC: 30 Sep every year
    if (m === 8) { // September
      deadlines.push({
        id: `dir3kyc-${y}`,
        date: new Date(y, 8, 30),
        label: "DIR-3 KYC",
        category: "MCA",
        description: "Companies Act 2013 Rule 12A — Director KYC due 30 Sep",
        clientIds,
        done: false,
      });
    }
    // AOC-4: 29 Oct (within 30 days of AGM on 30 Sep)
    if (m === 9) { // October
      deadlines.push({
        id: `aoc4-${y}`,
        date: new Date(y, 9, 29),
        label: "AOC-4",
        category: "MCA",
        description: "Companies Act 2013 Section 137 — financial statements filing due 29 Oct",
        clientIds,
        done: false,
      });
    }
    // MGT-7: 28 Nov (within 60 days of AGM on 30 Sep)
    if (m === 10) { // November
      deadlines.push({
        id: `mgt7-${y}`,
        date: new Date(y, 10, 28),
        label: "MGT-7",
        category: "MCA",
        description: "Companies Act 2013 Section 92 — annual return due 28 Nov",
        clientIds,
        done: false,
      });
    }
  }

  return deadlines;
}

// ─── CALENDAR HELPERS ─────────────────────────────────────────────────────────

function daysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function firstDayOfMonth(year: number, month: number): number {
  return new Date(year, month, 1).getDay(); // 0=Sun
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
}

// ─── COMPONENTS ───────────────────────────────────────────────────────────────

interface DeadlineChipProps {
  deadline: Deadline;
  clientMap: Map<string, Client>;
  compact?: boolean;
  onToggle: (id: string) => void;
}

function DeadlineChip({ deadline, clientMap, compact = false, onToggle }: DeadlineChipProps) {
  const style = CATEGORY_STYLES[deadline.category];
  const clientCount = deadline.clientIds.length;

  let clientLabel = "";
  if (clientCount === 1) {
    clientLabel = clientMap.get(deadline.clientIds[0])?.client_name ?? "";
  } else if (clientCount > 1) {
    clientLabel = `${clientCount} clients`;
  }

  return (
    <div
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-medium cursor-pointer select-none transition-opacity
        ${style.chip} ${deadline.done ? "opacity-50 line-through" : ""}`}
      onClick={() => onToggle(deadline.id)}
      title={deadline.description}
    >
      {deadline.done
        ? <CheckCircle className="w-3 h-3 shrink-0" />
        : <Circle className="w-3 h-3 shrink-0" />
      }
      <span className="truncate">{deadline.label}</span>
      {!compact && clientLabel && (
        <span className="opacity-70 truncate">· {clientLabel}</span>
      )}
    </div>
  );
}

// ─── MAIN PAGE ────────────────────────────────────────────────────────────────

export default function CalendarPage() {
  // Anchored at local midnight (not a live instant) so a same-day deadline
  // isn't excluded the moment any time has passed since midnight — see
  // upcomingDeadlines below.
  const today = new Date(todayLocalISO() + "T00:00:00");

  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth());
  const [clients, setClients] = useState<Client[]>([]);
  const [deadlines, setDeadlines] = useState<Deadline[]>([]);
  const [selectedDay, setSelectedDay] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);

  // Load clients from Supabase
  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const sb = getSupabaseClient();
        const { data, error } = await sb
          .from("clients")
          .select("*")
          .is("deleted_at", null)
          .order("client_name");
        if (error) throw new Error(error.message);
        setClients((data ?? []) as Client[]);
      } catch {
        // Silently degrade — deadlines still show without client names
        setClients([]);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Regenerate deadlines when clients load
  useEffect(() => {
    const clientIds = clients.map(c => c.id);
    setDeadlines(generateDeadlines(clientIds));
  }, [clients]);

  const clientMap = new Map(clients.map(c => [c.id, c]));

  const toggleDone = useCallback((id: string) => {
    setDeadlines(prev => prev.map(d => d.id === id ? { ...d, done: !d.done } : d));
  }, []);

  // Navigation
  function prevMonth() {
    if (viewMonth === 0) { setViewYear(y => y - 1); setViewMonth(11); }
    else setViewMonth(m => m - 1);
  }
  function nextMonth() {
    if (viewMonth === 11) { setViewYear(y => y + 1); setViewMonth(0); }
    else setViewMonth(m => m + 1);
  }
  function goToday() {
    setViewYear(today.getFullYear());
    setViewMonth(today.getMonth());
    setSelectedDay(today);
  }

  // Build calendar grid
  const totalDays = daysInMonth(viewYear, viewMonth);
  const startDow = firstDayOfMonth(viewYear, viewMonth); // 0=Sun

  // Deadlines indexed by day-of-month for current view
  function deadlinesForDay(day: number): Deadline[] {
    return deadlines.filter(d =>
      d.date.getFullYear() === viewYear &&
      d.date.getMonth() === viewMonth &&
      d.date.getDate() === day
    );
  }

  // Deadlines for selected day panel
  const selectedDayDeadlines = selectedDay
    ? deadlines.filter(d => isSameDay(d.date, selectedDay))
    : [];

  // Upcoming 10 deadlines from today
  const upcomingDeadlines = deadlines
    .filter(d => d.date >= today && !d.done)
    .sort((a, b) => a.date.getTime() - b.date.getTime())
    .slice(0, 10);

  // Build grid cells: leading empty + day cells
  const gridCells: Array<{ day: number | null }> = [];
  for (let i = 0; i < startDow; i++) gridCells.push({ day: null });
  for (let d = 1; d <= totalDays; d++) gridCells.push({ day: d });
  // Pad to complete last row
  while (gridCells.length % 7 !== 0) gridCells.push({ day: null });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Compliance Calendar</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Indian tax & regulatory deadlines across all clients
          </p>
        </div>

        {/* Month navigation */}
        <div className="flex items-center gap-2">
          <button
            onClick={goToday}
            className="px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg text-[#475569] hover:bg-[#F8FAFC]"
          >
            Today
          </button>
          <button
            onClick={prevMonth}
            className="p-1.5 border border-[#E2E8F0] rounded-lg text-[#64748B] hover:bg-[#F8FAFC]"
            aria-label="Previous month"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-semibold text-[#0F172A] w-36 text-center">
            {MONTH_NAMES[viewMonth]} {viewYear}
          </span>
          <button
            onClick={nextMonth}
            className="p-1.5 border border-[#E2E8F0] rounded-lg text-[#64748B] hover:bg-[#F8FAFC]"
            aria-label="Next month"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3">
        {(Object.keys(CATEGORY_STYLES) as DeadlineCategory[]).map(cat => (
          <div key={cat} className="flex items-center gap-1.5">
            <span className={`w-2.5 h-2.5 rounded-full ${CATEGORY_STYLES[cat].badge}`} />
            <span className="text-xs text-[#64748B]">{CATEGORY_LABELS[cat]}</span>
          </div>
        ))}
        {loading && <span className="text-xs text-[#94A3B8] ml-2">Loading clients…</span>}
      </div>

      {/* Main layout: Calendar + Side panel */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_280px] gap-6">

        {/* Calendar grid */}
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          {/* Day headers */}
          <div className="grid grid-cols-7 border-b border-[#F1F5F9]">
            {DAY_LABELS.map(d => (
              <div key={d} className="py-2 text-center text-xs font-medium text-[#94A3B8]">
                {d}
              </div>
            ))}
          </div>

          {/* Day cells */}
          <div className="grid grid-cols-7">
            {gridCells.map((cell, idx) => {
              if (cell.day === null) {
                return <div key={`empty-${idx}`} className="min-h-[90px] border-b border-r border-gray-50 bg-[#F8FAFC]/30" />;
              }

              const cellDate = new Date(viewYear, viewMonth, cell.day);
              const isToday = isSameDay(cellDate, today);
              const isSelected = selectedDay ? isSameDay(cellDate, selectedDay) : false;
              const chips = deadlinesForDay(cell.day);

              return (
                <div
                  key={cell.day}
                  onClick={() => setSelectedDay(isSelected ? null : cellDate)}
                  className={`min-h-[90px] border-b border-r border-[#F1F5F9] p-1.5 cursor-pointer transition-colors
                    ${isSelected ? "bg-blue-50" : "hover:bg-[#F8FAFC]/60"}`}
                >
                  {/* Day number */}
                  <div className={`w-6 h-6 flex items-center justify-center rounded-full text-xs font-medium mb-1
                    ${isToday ? "bg-blue-600 text-white" : "text-[#334155]"}`}>
                    {cell.day}
                  </div>

                  {/* Deadline chips — show max 3, then "+N more" */}
                  <div className="space-y-0.5">
                    {chips.slice(0, 3).map(dl => (
                      <DeadlineChip
                        key={dl.id}
                        deadline={dl}
                        clientMap={clientMap}
                        compact
                        onToggle={toggleDone}
                      />
                    ))}
                    {chips.length > 3 && (
                      <div className="text-[10px] text-[#94A3B8] pl-1">+{chips.length - 3} more</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right side panel */}
        <div className="space-y-4">

          {/* Selected day panel */}
          {selectedDay && (
            <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-50 flex items-center gap-2">
                <Calendar className="w-4 h-4 text-blue-600" />
                <h2 className="text-sm font-semibold text-[#0F172A]">
                  {selectedDay.getDate()} {MONTH_NAMES[selectedDay.getMonth()]} {selectedDay.getFullYear()}
                </h2>
              </div>
              {selectedDayDeadlines.length === 0 ? (
                <p className="px-4 py-6 text-xs text-[#94A3B8] text-center">No deadlines this day</p>
              ) : (
                <div className="divide-y divide-[#F8FAFC]">
                  {selectedDayDeadlines.map(dl => {
                    const style = CATEGORY_STYLES[dl.category];
                    const clientCount = dl.clientIds.length;
                    const clientLabel = clientCount === 1
                      ? clientMap.get(dl.clientIds[0])?.client_name ?? ""
                      : clientCount > 1 ? `${clientCount} clients` : "Firm-wide";

                    return (
                      <div key={dl.id} className="px-4 py-3 flex items-start gap-3">
                        <button
                          onClick={() => toggleDone(dl.id)}
                          className={`mt-0.5 shrink-0 ${dl.done ? "text-green-500" : "text-[#CBD5E1] hover:text-[#64748B]"}`}
                          aria-label={dl.done ? "Mark pending" : "Mark done"}
                        >
                          {dl.done
                            ? <CheckCircle className="w-4 h-4" />
                            : <Circle className="w-4 h-4" />
                          }
                        </button>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${style.chip}`}>
                              {CATEGORY_LABELS[dl.category]}
                            </span>
                            <span className={`text-sm font-medium ${dl.done ? "line-through text-[#94A3B8]" : "text-[#0F172A]"}`}>
                              {dl.label}
                            </span>
                          </div>
                          <p className="text-xs text-[#64748B] mt-0.5">{dl.description}</p>
                          {clientLabel && (
                            <p className="text-[10px] text-[#94A3B8] mt-0.5">{clientLabel}</p>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Upcoming deadlines */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-[#0F172A]">Upcoming Deadlines</h2>
              <p className="text-xs text-[#94A3B8] mt-0.5">Next 10 pending</p>
            </div>
            {upcomingDeadlines.length === 0 ? (
              <p className="px-4 py-6 text-xs text-[#94A3B8] text-center">All caught up!</p>
            ) : (
              <div className="divide-y divide-[#F8FAFC]">
                {upcomingDeadlines.map(dl => {
                  const style = CATEGORY_STYLES[dl.category];
                  const daysAway = Math.ceil((dl.date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
                  const urgentClass = daysAway <= 3 ? "text-red-600 font-semibold" : daysAway <= 7 ? "text-amber-600" : "text-[#94A3B8]";

                  return (
                    <div key={dl.id} className="px-4 py-3 flex items-center gap-3">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${style.badge}`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-[#0F172A] truncate">{dl.label}</p>
                        <p className="text-[10px] text-[#94A3B8]">
                          {dl.date.getDate()} {MONTH_NAMES[dl.date.getMonth()]}
                        </p>
                      </div>
                      <span className={`text-[10px] shrink-0 ${urgentClass}`}>
                        {daysAway === 0 ? "Today" : daysAway === 1 ? "Tomorrow" : `${daysAway}d`}
                      </span>
                      <button
                        onClick={() => toggleDone(dl.id)}
                        className="text-[#CBD5E1] hover:text-[#64748B] shrink-0"
                        aria-label="Mark done"
                      >
                        <Circle className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
