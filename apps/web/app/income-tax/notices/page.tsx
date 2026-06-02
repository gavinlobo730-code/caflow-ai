"use client";

/**
 * IT Notice / Faceless Assessment Tracker
 * Covers: IT Act Section 143(1), 143(2), 144B, 148, 156, 245, 271
 * Faceless Assessment Scheme — IT Act Section 144B (w.e.f. 13 Aug 2020)
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 * This tracker is for internal CA use only. Never transmit any notice response
 * to the Income Tax portal without explicit CA confirmation.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Plus,
  X,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Bell,
  FileText,
  ChevronDown,
} from "lucide-react";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

type NoticeType =
  | "143(1)"
  | "143(2)"
  | "144B"
  | "148"
  | "156"
  | "245"
  | "271";

interface NoticeTypeInfo {
  label: string;
  description: string;
  defaultDeadlineDays: number;
}

const NOTICE_TYPES: Record<NoticeType, NoticeTypeInfo> = {
  "143(1)": {
    label: "Intimation u/s 143(1)",
    description: "Intimation after processing of return — IT Act Section 143(1)",
    defaultDeadlineDays: 30,
  },
  "143(2)": {
    label: "Scrutiny Notice u/s 143(2)",
    description: "Notice for scrutiny assessment — IT Act Section 143(2)",
    defaultDeadlineDays: 30,
  },
  "144B": {
    label: "Faceless Assessment u/s 144B",
    description: "Faceless Assessment Scheme — IT Act Section 144B",
    defaultDeadlineDays: 15,
  },
  "148": {
    label: "Income Escapement u/s 148",
    description: "Notice for income escaping assessment — IT Act Section 148",
    defaultDeadlineDays: 30,
  },
  "156": {
    label: "Demand Notice u/s 156",
    description: "Demand notice for tax payable — IT Act Section 156",
    defaultDeadlineDays: 30,
  },
  "245": {
    label: "Refund Adjustment u/s 245",
    description: "Notice before adjusting refund against demand — IT Act Section 245",
    defaultDeadlineDays: 30,
  },
  "271": {
    label: "Penalty Notice u/s 271",
    description: "Penalty proceedings — IT Act Section 271",
    defaultDeadlineDays: 30,
  },
};

type NoticeStatus =
  | "pending_response"
  | "response_submitted"
  | "resolved"
  | "closed";

const ASSESSMENT_YEARS = [
  "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "2026-27",
] as const;

interface Notice {
  id: string;
  clientId: string;
  clientName: string;
  noticeType: NoticeType;
  section: string;
  assessmentYear: string;
  dateReceived: string;
  responseDeadline: string;
  documentRef: string;
  notes: string;
  status: NoticeStatus;
  createdAt: string;
}

const STORAGE_KEY = "caflow_it_notices";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function addDays(date: string, days: number): string {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d.toISOString().split("T")[0];
}

function daysRemaining(deadline: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(deadline);
  return Math.ceil((d.getTime() - today.getTime()) / 86400000);
}

function formatDate(d: string): string {
  if (!d) return "—";
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function calcDeadline(noticeType: NoticeType, dateReceived: string): string {
  return addDays(dateReceived, NOTICE_TYPES[noticeType].defaultDeadlineDays);
}

function statusLabel(status: NoticeStatus): string {
  const map: Record<NoticeStatus, string> = {
    pending_response: "Pending Response",
    response_submitted: "Response Submitted",
    resolved: "Resolved",
    closed: "Closed",
  };
  return map[status];
}

function statusStyle(status: NoticeStatus, days: number): string {
  if (status === "resolved") return "bg-green-100 text-green-700";
  if (status === "closed") return "bg-gray-100 text-gray-500";
  if (status === "response_submitted") return "bg-amber-100 text-amber-700";
  // pending_response
  if (days < 0) return "bg-red-100 text-red-700";
  if (days < 7) return "bg-red-100 text-red-700";
  return "bg-amber-100 text-amber-700";
}

function loadNotices(): Notice[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Notice[]) : [];
  } catch {
    return [];
  }
}

function saveNotices(notices: Notice[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(notices));
}

// ---------------------------------------------------------------------------
// Blank form
// ---------------------------------------------------------------------------

const today = new Date().toISOString().split("T")[0];

const BLANK_FORM = {
  clientId: "",
  noticeType: "143(2)" as NoticeType,
  section: "",
  assessmentYear: "2024-25",
  dateReceived: today,
  documentRef: "",
  notes: "",
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function NoticesPage() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loadingClients, setLoadingClients] = useState(true);

  const [showAddModal, setShowAddModal] = useState(false);
  const [form, setForm] = useState(BLANK_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const [filterStatus, setFilterStatus] = useState<NoticeStatus | "all">("all");
  const [filterClient, setFilterClient] = useState("");

  // ---------------------------------------------------------------------------
  // Load
  // ---------------------------------------------------------------------------

  const loadData = useCallback(async () => {
    setNotices(loadNotices());
    try {
      const cl = await getClients();
      setClients(cl);
    } catch {
      // clients unavailable — allow manual client name entry
    } finally {
      setLoadingClients(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const urgentNotices = notices.filter(
    (n) =>
      (n.status === "pending_response" || n.status === "response_submitted") &&
      daysRemaining(n.responseDeadline) < 7
  );

  const filteredNotices = notices.filter((n) => {
    if (filterStatus !== "all" && n.status !== filterStatus) return false;
    if (filterClient && !n.clientName.toLowerCase().includes(filterClient.toLowerCase())) return false;
    return true;
  });

  // ---------------------------------------------------------------------------
  // Add notice
  // ---------------------------------------------------------------------------

  function handleFormChange(field: keyof typeof form, value: string) {
    setForm((prev) => {
      const updated = { ...prev, [field]: value };
      // Auto-calc deadline when noticeType or dateReceived changes
      if (field === "noticeType" || field === "dateReceived") {
        // no side effect needed — computed in submit
      }
      return updated;
    });
  }

  function handleAddNotice() {
    if (!form.clientId && clients.length > 0) {
      setFormError("Please select a client");
      return;
    }
    if (!form.dateReceived) {
      setFormError("Date received is required");
      return;
    }
    setFormError(null);

    const clientObj = clients.find((c) => c.id === form.clientId);
    const clientName = clientObj?.client_name ?? form.clientId;
    const responseDeadline = calcDeadline(form.noticeType, form.dateReceived);

    const notice: Notice = {
      id: `notice-${Date.now()}`,
      clientId: form.clientId,
      clientName,
      noticeType: form.noticeType,
      section: form.section || form.noticeType,
      assessmentYear: form.assessmentYear,
      dateReceived: form.dateReceived,
      responseDeadline,
      documentRef: form.documentRef,
      notes: form.notes,
      status: "pending_response",
      createdAt: new Date().toISOString(),
    };

    const updated = [notice, ...notices];
    setNotices(updated);
    saveNotices(updated);
    setShowAddModal(false);
    setForm(BLANK_FORM);
  }

  function updateStatus(id: string, status: NoticeStatus) {
    const updated = notices.map((n) => (n.id === id ? { ...n, status } : n));
    setNotices(updated);
    saveNotices(updated);
  }

  function deleteNotice(id: string) {
    const updated = notices.filter((n) => n.id !== id);
    setNotices(updated);
    saveNotices(updated);
  }

  // ---------------------------------------------------------------------------
  // Computed deadline for form preview
  // ---------------------------------------------------------------------------

  const previewDeadline =
    form.dateReceived ? calcDeadline(form.noticeType, form.dateReceived) : "";

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link
            href="/income-tax"
            className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 mb-2 transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Income Tax
          </Link>
          <h1 className="text-xl font-semibold text-gray-900">
            IT Notice / Faceless Assessment Tracker
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            IT Act Sections 143, 144B, 148, 156, 245, 271
          </p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Add Notice
        </button>
      </div>

      {/* Urgency alert banner */}
      {urgentNotices.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-5 py-3 flex items-start gap-3">
          <Bell className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-semibold text-red-800 uppercase tracking-wide">
              Urgent — Response Due Within 7 Days
            </p>
            <ul className="mt-1 space-y-0.5">
              {urgentNotices.map((n) => {
                const days = daysRemaining(n.responseDeadline);
                return (
                  <li key={n.id} className="text-xs text-red-700">
                    <span className="font-medium">{n.clientName}</span> — {NOTICE_TYPES[n.noticeType].label}{" "}
                    (AY {n.assessmentYear}) — {days < 0 ? `${Math.abs(days)} days overdue` : days === 0 ? "Due today" : `${days} day${days !== 1 ? "s" : ""} remaining`}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {(
          [
            { label: "Total Notices", value: notices.length, color: "text-blue-600", bg: "bg-blue-50", icon: FileText },
            { label: "Pending Response", value: notices.filter((n) => n.status === "pending_response").length, color: "text-red-600", bg: "bg-red-50", icon: AlertTriangle },
            { label: "Response Submitted", value: notices.filter((n) => n.status === "response_submitted").length, color: "text-amber-600", bg: "bg-amber-50", icon: Clock },
            { label: "Resolved / Closed", value: notices.filter((n) => n.status === "resolved" || n.status === "closed").length, color: "text-green-600", bg: "bg-green-50", icon: CheckCircle2 },
          ] as const
        ).map(({ label, value, color, bg, icon: Icon }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 px-4 py-4 flex items-center gap-3">
            <div className={`flex items-center justify-center w-9 h-9 ${bg} rounded-lg shrink-0`}>
              <Icon className={`w-4.5 h-4.5 ${color}`} />
            </div>
            <div>
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-lg font-semibold text-gray-900">{value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Search by client…"
          value={filterClient}
          onChange={(e) => setFilterClient(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 w-52"
        />
        <div className="relative">
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as NoticeStatus | "all")}
            className="appearance-none border border-gray-200 rounded-lg pl-3 pr-8 py-1.5 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">All Statuses</option>
            <option value="pending_response">Pending Response</option>
            <option value="response_submitted">Response Submitted</option>
            <option value="resolved">Resolved</option>
            <option value="closed">Closed</option>
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
        </div>
      </div>

      {/* Notices table */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        {filteredNotices.length === 0 ? (
          <div className="px-5 py-14 text-center space-y-3">
            <FileText className="w-10 h-10 text-gray-200 mx-auto" />
            <p className="text-sm font-medium text-gray-600">
              {notices.length === 0 ? "No notices tracked yet" : "No notices match the filters"}
            </p>
            {notices.length === 0 && (
              <p className="text-xs text-gray-400 max-w-sm mx-auto">
                Click &ldquo;Add Notice&rdquo; to start tracking IT notices and faceless assessments for your clients.
              </p>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-xs text-gray-500 font-medium uppercase tracking-wider">
                  <th className="px-5 py-2.5 text-left">Client</th>
                  <th className="px-4 py-2.5 text-left">Notice Type</th>
                  <th className="px-4 py-2.5 text-left">Section</th>
                  <th className="px-4 py-2.5 text-left">AY</th>
                  <th className="px-4 py-2.5 text-left">Date Received</th>
                  <th className="px-4 py-2.5 text-left">Response Deadline</th>
                  <th className="px-4 py-2.5 text-left">Days Remaining</th>
                  <th className="px-4 py-2.5 text-left">Status</th>
                  <th className="px-4 py-2.5 text-left">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filteredNotices.map((notice) => {
                  const days = daysRemaining(notice.responseDeadline);
                  const isActive =
                    notice.status === "pending_response" ||
                    notice.status === "response_submitted";
                  return (
                    <tr key={notice.id} className="hover:bg-gray-50/50 transition-colors">
                      <td className="px-5 py-3 font-medium text-gray-900">
                        {notice.clientName}
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                          {notice.noticeType}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {notice.section}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {notice.assessmentYear}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {formatDate(notice.dateReceived)}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {formatDate(notice.responseDeadline)}
                      </td>
                      <td className="px-4 py-3">
                        {isActive ? (
                          <span
                            className={`text-xs font-semibold ${
                              days < 0
                                ? "text-red-700"
                                : days < 7
                                ? "text-red-600"
                                : days < 30
                                ? "text-amber-600"
                                : "text-gray-600"
                            }`}
                          >
                            {days < 0
                              ? `${Math.abs(days)}d overdue`
                              : days === 0
                              ? "Today"
                              : `${days}d`}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusStyle(notice.status, days)}`}
                        >
                          {statusLabel(notice.status)}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          {notice.status === "pending_response" && (
                            <button
                              onClick={() => updateStatus(notice.id, "response_submitted")}
                              className="text-xs px-2 py-1 bg-amber-50 text-amber-700 font-medium rounded hover:bg-amber-100 transition-colors whitespace-nowrap"
                            >
                              Mark Responded
                            </button>
                          )}
                          {(notice.status === "pending_response" ||
                            notice.status === "response_submitted") && (
                            <button
                              onClick={() => updateStatus(notice.id, "resolved")}
                              className="text-xs px-2 py-1 bg-green-50 text-green-700 font-medium rounded hover:bg-green-100 transition-colors"
                            >
                              Resolve
                            </button>
                          )}
                          {notice.status === "resolved" && (
                            <button
                              onClick={() => updateStatus(notice.id, "closed")}
                              className="text-xs px-2 py-1 bg-gray-100 text-gray-600 font-medium rounded hover:bg-gray-200 transition-colors"
                            >
                              Close
                            </button>
                          )}
                          <button
                            onClick={() => deleteNotice(notice.id)}
                            className="text-xs p-1 text-gray-300 hover:text-red-500 transition-colors"
                            title="Delete notice"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Notice type reference */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-gray-900">
            Notice Type Reference
          </h2>
        </div>
        <div className="px-5 py-4 grid sm:grid-cols-2 gap-3">
          {(Object.entries(NOTICE_TYPES) as [NoticeType, NoticeTypeInfo][]).map(
            ([type, info]) => (
              <div key={type} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                <span className="text-xs font-bold text-blue-700 bg-blue-100 px-2 py-0.5 rounded shrink-0">
                  {type}
                </span>
                <div>
                  <p className="text-xs font-medium text-gray-700">{info.description}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Default response window: {info.defaultDeadlineDays} days
                  </p>
                </div>
              </div>
            )
          )}
        </div>
      </div>

      {/* ================================================================== */}
      {/* MODAL: Add Notice                                                   */}
      {/* ================================================================== */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100 sticky top-0 bg-white">
              <h3 className="text-base font-semibold text-gray-900">
                Add IT Notice
              </h3>
              <button
                onClick={() => {
                  setShowAddModal(false);
                  setFormError(null);
                  setForm(BLANK_FORM);
                }}
                className="text-gray-400 hover:text-gray-600 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              {/* Client */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Client <span className="text-red-500">*</span>
                </label>
                {loadingClients ? (
                  <div className="text-xs text-gray-400">Loading clients…</div>
                ) : clients.length > 0 ? (
                  <select
                    value={form.clientId}
                    onChange={(e) => handleFormChange("clientId", e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">Select client…</option>
                    {clients.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.client_name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    placeholder="Enter client name"
                    value={form.clientId}
                    onChange={(e) => handleFormChange("clientId", e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                )}
              </div>

              {/* Notice Type */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Notice Type <span className="text-red-500">*</span>
                </label>
                <select
                  value={form.noticeType}
                  onChange={(e) =>
                    handleFormChange("noticeType", e.target.value)
                  }
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {(Object.keys(NOTICE_TYPES) as NoticeType[]).map((t) => (
                    <option key={t} value={t}>
                      {t} — {NOTICE_TYPES[t].label}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-400 mt-1">
                  {NOTICE_TYPES[form.noticeType].description}
                </p>
              </div>

              {/* Section */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Section / Sub-section
                </label>
                <input
                  type="text"
                  placeholder={`e.g. ${form.noticeType}`}
                  value={form.section}
                  onChange={(e) => handleFormChange("section", e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {/* Assessment Year */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Assessment Year <span className="text-red-500">*</span>
                </label>
                <select
                  value={form.assessmentYear}
                  onChange={(e) => handleFormChange("assessmentYear", e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {ASSESSMENT_YEARS.map((ay) => (
                    <option key={ay} value={ay}>
                      {ay}
                    </option>
                  ))}
                </select>
              </div>

              {/* Date Received */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Date Received <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  value={form.dateReceived}
                  onChange={(e) => handleFormChange("dateReceived", e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                {previewDeadline && (
                  <p className="text-xs text-gray-400 mt-1">
                    Auto-calculated response deadline:{" "}
                    <span className="font-medium text-gray-700">
                      {formatDate(previewDeadline)}
                    </span>{" "}
                    ({NOTICE_TYPES[form.noticeType].defaultDeadlineDays} days)
                  </p>
                )}
              </div>

              {/* Document upload field name */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Document Reference / File Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. Notice_143(2)_AY2024-25.pdf"
                  value={form.documentRef}
                  onChange={(e) => handleFormChange("documentRef", e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-400 mt-1">
                  Record the filename or reference of the physical/digital notice document
                </p>
              </div>

              {/* Notes */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Notes
                </label>
                <textarea
                  rows={3}
                  placeholder="Add any relevant notes about this notice…"
                  value={form.notes}
                  onChange={(e) => handleFormChange("notes", e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                />
              </div>

              {formError && (
                <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                  {formError}
                </p>
              )}
            </div>

            <div className="px-6 py-4 border-t border-gray-100 flex gap-3 justify-end sticky bottom-0 bg-white">
              <button
                onClick={() => {
                  setShowAddModal(false);
                  setFormError(null);
                  setForm(BLANK_FORM);
                }}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleAddNotice}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
              >
                Add Notice
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
