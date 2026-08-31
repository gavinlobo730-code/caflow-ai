"use client";

/**
 * Employee Self-Service Portal — PracticeSync AI
 * Allows employees of CA firm clients to view their own payroll info.
 * Detects employee record by matching auth_user_id on payroll_employees.
 */

import { useState, useEffect, useCallback } from "react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
import { User, FileText, Calendar, Download, Loader2, Receipt } from "lucide-react";
import { TaxDeclarationTab } from "@/components/portal/TaxDeclarationTab";

// ─── Types ────────────────────────────────────────────────────────────────────

interface EmployeeRecord {
  id: string;
  name: string;
  designation: string | null;
  department: string | null;
  pan: string | null;
  bank_account_no: string | null;
  bank_name: string | null;
  bank_ifsc: string | null;
}

interface SalarySlip {
  id: string;
  month: number;
  year: number;
  // All monetary values in integer paise — CGST Act / Income Tax Act
  gross_salary_paise: number | null;
  net_salary_paise: number | null;
  created_at: string;
}

// Mirrors leave_balances as it actually is (migration 027): ONE row per
// employee per year, holding the days REMAINING for each of three fixed leave
// types. There is no leave_type/total_days/used_days shape — this page used to
// ask for those three columns and PostgREST rejected the whole select, so the
// leave tab could never load even for firm staff.
//
// Nothing records days taken, so "Total" and "Used" cannot be shown without
// inventing them. The table below shows the balance, which is the number the
// employee is actually asking for.
interface LeaveBalance {
  id: string;
  year: number;
  casual_leave_balance: number;
  sick_leave_balance: number;
  earned_leave_balance: number;
}

const LEAVE_TYPES: ReadonlyArray<{ label: string; key: keyof LeaveBalance }> = [
  { label: "Casual", key: "casual_leave_balance" },
  { label: "Sick", key: "sick_leave_balance" },
  { label: "Earned", key: "earned_leave_balance" },
];

type TabId = "payslips" | "leave" | "declaration" | "profile";

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Format integer paise to ₹ en-IN display */
function formatPaise(paise: number | null): string {
  if (paise === null || paise === undefined) return "₹0";
  // Integer paise arithmetic — never use floating point for rupee calcs
  const rupees = Math.floor(paise / 100);
  const p = paise % 100;
  const formatted = new Intl.NumberFormat("en-IN").format(rupees);
  return p > 0 ? `₹${formatted}.${String(p).padStart(2, "0")}` : `₹${formatted}`;
}

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 3500);
    return () => clearTimeout(t);
  }, [onClose]);
  return (
    <div className="fixed bottom-4 right-4 z-50 bg-gray-900 text-white text-sm px-4 py-2.5 rounded-lg shadow-lg flex items-center gap-3">
      <span>{message}</span>
      <button onClick={onClose} className="text-[#94A3B8] hover:text-white">×</button>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function EmployeePortalPage() {
  const [employee, setEmployee] = useState<EmployeeRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("payslips");
  const [payslips, setPayslips] = useState<SalarySlip[]>([]);
  const [payslipsLoading, setPayslipsLoading] = useState(false);
  // True when the LAST payslip fetch failed (error/timeout) rather than the
  // employee genuinely having no payslips. Without this, a failed salary-record
  // load renders as "No payslips found" — indistinguishable, to the employee,
  // from having none issued (audit M17). Mirrors TrialBalance.loadFailed in
  // clients/[id]/accounting/page.tsx.
  const [payslipsError, setPayslipsError] = useState(false);
  const [leaveBalances, setLeaveBalances] = useState<LeaveBalance[]>([]);
  const [leaveLoading, setLeaveLoading] = useState(false);
  const [leaveError, setLeaveError] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [downloadingSlipId, setDownloadingSlipId] = useState<string | null>(null);

  const downloadPayslip = useCallback(async (slip: SalarySlip) => {
    setDownloadingSlipId(slip.id);
    try {
      const period = `${slip.year}-${String(slip.month).padStart(2, "0")}`;
      await api.payroll.downloadPayslip(slip.id, `payslip-${period}.pdf`);
    } catch (e) {
      console.error("downloadPayslip:", e);
      setToast("Failed to download payslip. Please try again.");
    } finally {
      setDownloadingSlipId(null);
    }
  }, []);

  // Detect employee by auth_user_id
  useEffect(() => {
    async function loadEmployee() {
      setLoading(true);
      setError(null);
      try {
        const supabase = getSupabaseClient();
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) {
          setError("Not logged in. Please sign in to access your portal.");
          return;
        }
        const { data, error: err } = await supabase
          .from("payroll_employees")
          .select("id, name, designation, department, pan, bank_account_no, bank_name, bank_ifsc")
          .eq("auth_user_id", session.user.id)
          .eq("portal_enabled", true)
          .maybeSingle();
        if (err) throw new Error(err.message);
        if (!data) {
          setError("No employee record found for your account. Please contact your employer.");
          return;
        }
        setEmployee(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load employee record");
      } finally {
        setLoading(false);
      }
    }
    loadEmployee();
  }, []);

  const loadPayslips = useCallback(async () => {
    if (!employee) return;
    setPayslipsLoading(true);
    setPayslipsError(false);
    try {
      const supabase = getSupabaseClient();
      // Reads payroll_slips directly rather than the salary_slips view
      // (migration 072), which also exists and exposes the same rows. Either
      // works; this one names the base table the amounts actually live on.
      //
      // The period lives on the parent run (payroll_runs.month), not on the
      // slip, and the amounts are gross_paise / net_paise. Ordered by
      // created_at because PostgREST cannot sort parent rows by an embedded
      // column, and slips are created per run in period order anyway.
      //
      // The payroll_runs!inner(month) embed needs the RUN to be visible under
      // RLS, not just the slip — an inner join drops the row otherwise.
      // Migration 262 grants both, scoped to the employee's own records.
      const { data, error: err } = await supabase
        .from("payroll_slips")
        .select("id, gross_paise, net_paise, created_at, payroll_runs!inner(month)")
        .eq("employee_id", employee.id)
        .order("created_at", { ascending: false });
      if (err) throw new Error(err.message);

      type SlipRow = {
        id: string; gross_paise: number | null; net_paise: number | null;
        created_at: string; payroll_runs: { month: string } | null;
      };
      setPayslips(((data ?? []) as unknown as SlipRow[]).map((r) => {
        // payroll_runs.month is text. It is empty in this database, so both the
        // "YYYY-MM" and bare-month encodings are handled rather than guessed at.
        const raw = r.payroll_runs?.month ?? "";
        const [ys, ms] = raw.includes("-") ? raw.split("-") : ["", raw];
        return {
          id: r.id,
          month: Number(ms) || 1,
          year: Number(ys) || 0,
          gross_salary_paise: r.gross_paise,
          net_salary_paise: r.net_paise,
          created_at: r.created_at,
        };
      }));
    } catch (e) {
      // A failed fetch must NOT fall through to the empty "No payslips found"
      // state — flag it so the UI shows a retryable error instead (audit M17).
      console.error("loadPayslips:", e);
      setPayslips([]);
      setPayslipsError(true);
    } finally {
      setPayslipsLoading(false);
    }
  }, [employee]);

  const loadLeaveBalances = useCallback(async () => {
    if (!employee) return;
    setLeaveLoading(true);
    setLeaveError(false);
    try {
      const supabase = getSupabaseClient();
      // Indian FY: April 1 to March 31
      const now = new Date();
      const currentYear = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
      const { data, error: err } = await supabase
        .from("leave_balances")
        .select("id, year, casual_leave_balance, sick_leave_balance, earned_leave_balance")
        .eq("employee_id", employee.id)
        .eq("year", currentYear);
      if (err) throw new Error(err.message);
      setLeaveBalances(data ?? []);
    } catch (e) {
      // A failed fetch must NOT fall through to the empty "No leave records"
      // state — flag it so the UI shows a retryable error instead, mirroring
      // loadPayslips' fix above.
      console.error("loadLeaveBalances:", e);
      setLeaveBalances([]);
      setLeaveError(true);
    } finally {
      setLeaveLoading(false);
    }
  }, [employee]);

  useEffect(() => {
    if (!employee) return;
    if (activeTab === "payslips") loadPayslips();
    if (activeTab === "leave") loadLeaveBalances();
  }, [activeTab, employee, loadPayslips, loadLeaveBalances]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center">
        <div className="flex items-center gap-3 text-[#64748B]">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Loading your portal…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center p-4">
        <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 max-w-md text-center space-y-3">
          <div className="w-12 h-12 rounded-full bg-red-50 flex items-center justify-center mx-auto">
            <User className="w-6 h-6 text-red-600" />
          </div>
          <p className="text-sm font-semibold text-[#0F172A]">Access Unavailable</p>
          <p className="text-xs text-[#64748B]">{error}</p>
        </div>
      </div>
    );
  }

  if (!employee) return null;

  const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
    { id: "payslips", label: "Payslips", icon: <FileText size={15} /> },
    { id: "leave", label: "Leave Balance", icon: <Calendar size={15} /> },
    { id: "declaration", label: "Tax Declaration", icon: <Receipt size={15} /> },
    { id: "profile", label: "Profile", icon: <User size={15} /> },
  ];

  return (
    <div className="min-h-screen bg-[#F8FAFC]">
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}

      {/* Header */}
      <header className="bg-white border-b border-[#F1F5F9] px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-xs font-bold text-blue-600 tracking-wide uppercase">PracticeSync</span>
              <span className="text-xs text-[#CBD5E1]">|</span>
              <span className="text-xs text-[#94A3B8]">Employee Portal</span>
            </div>
            <h1 className="text-base font-semibold text-[#0F172A]">Hello, {employee.name}</h1>
            {employee.designation && (
              <p className="text-xs text-[#94A3B8] mt-0.5">{employee.designation}{employee.department ? ` · ${employee.department}` : ""}</p>
            )}
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="max-w-3xl mx-auto px-4 pt-6">
        <div className="flex gap-1 bg-white rounded-xl border border-[#F1F5F9] p-1 mb-6">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-medium transition-all ${
                activeTab === tab.id
                  ? "bg-blue-500 text-white shadow-sm"
                  : "text-[#64748B] hover:text-[#334155] hover:bg-[#F8FAFC]"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* Payslips Tab */}
        {activeTab === "payslips" && (
          <div className="space-y-3">
            {payslipsLoading ? (
              <div className="text-center py-10 text-sm text-[#94A3B8] flex items-center justify-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading payslips…
              </div>
            ) : payslipsError ? (
              <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-12 text-center space-y-3">
                <p className="text-sm text-red-600 font-medium">Couldn&apos;t load your payslips — the request failed or timed out.</p>
                <button
                  onClick={() => loadPayslips()}
                  className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]"
                >
                  Retry
                </button>
              </div>
            ) : payslips.length === 0 ? (
              <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-12 text-center">
                <FileText className="w-8 h-8 text-gray-200 mx-auto mb-2" />
                <p className="text-sm text-[#94A3B8]">No payslips found</p>
              </div>
            ) : (
              <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                      <th className="px-5 py-3 text-left font-semibold">Period</th>
                      <th className="px-4 py-3 text-right font-semibold">Gross</th>
                      <th className="px-4 py-3 text-right font-semibold">Net Pay</th>
                      <th className="px-5 py-3 text-left font-semibold">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {payslips.map(slip => (
                      <tr key={slip.id} className="hover:bg-[#F8FAFC]">
                        <td className="px-5 py-3 font-medium text-[#0F172A]">
                          {MONTH_NAMES[(slip.month ?? 1) - 1]} {slip.year}
                        </td>
                        <td className="px-4 py-3 text-right text-[#475569] font-mono text-xs">
                          {formatPaise(slip.gross_salary_paise)}
                        </td>
                        <td className="px-4 py-3 text-right text-green-700 font-semibold font-mono text-xs">
                          {formatPaise(slip.net_salary_paise)}
                        </td>
                        <td className="px-5 py-3">
                          <button
                            onClick={() => downloadPayslip(slip)}
                            disabled={downloadingSlipId === slip.id}
                            className="flex items-center gap-1 text-xs text-blue-600 hover:underline disabled:opacity-50 disabled:cursor-not-allowed disabled:no-underline"
                          >
                            {downloadingSlipId === slip.id ? (
                              <><Loader2 size={12} className="animate-spin" /> Downloading…</>
                            ) : (
                              <><Download size={12} /> Download</>
                            )}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Leave Balance Tab */}
        {activeTab === "leave" && (
          <div className="space-y-3">
            {leaveLoading ? (
              <div className="text-center py-10 text-sm text-[#94A3B8] flex items-center justify-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading leave balances…
              </div>
            ) : leaveError ? (
              <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-12 text-center space-y-3">
                <p className="text-sm text-red-600 font-medium">Couldn&apos;t load your leave balances — the request failed or timed out.</p>
                <button
                  onClick={() => loadLeaveBalances()}
                  className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]"
                >
                  Retry
                </button>
              </div>
            ) : leaveBalances.length === 0 ? (
              <div className="bg-white rounded-xl border border-[#F1F5F9] px-5 py-12 text-center">
                <Calendar className="w-8 h-8 text-gray-200 mx-auto mb-2" />
                <p className="text-sm text-[#94A3B8]">No leave records found for current year</p>
              </div>
            ) : (
              <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                      <th className="px-5 py-3 text-left font-semibold">Leave Type</th>
                      <th className="px-4 py-3 text-right font-semibold">Days Remaining</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {/* One row per leave type, unpacked from the single
                        leave_balances row for the year. Days taken are not
                        recorded anywhere, so there is no Used column to fill. */}
                    {leaveBalances.flatMap(lb =>
                      LEAVE_TYPES.map(({ label, key }) => {
                        const days = Number(lb[key] ?? 0);
                        return (
                          <tr key={`${lb.id}-${key}`} className="hover:bg-[#F8FAFC]">
                            <td className="px-5 py-3 font-medium text-[#0F172A]">{label}</td>
                            <td className={`px-4 py-3 text-right font-semibold ${days > 0 ? "text-green-700" : "text-red-600"}`}>
                              {days}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Tax declaration — the employee's own Form 12BB (Rule 26C). */}
        {activeTab === "declaration" && (
          <TaxDeclarationTab employeeId={employee.id} onToast={setToast} />
        )}

        {/* Profile Tab */}
        {activeTab === "profile" && (
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-[#0F172A]">Employee Profile</h2>
              <p className="text-xs text-[#94A3B8] mt-0.5">Read-only — contact HR to update your details</p>
            </div>
            <div className="px-5 py-4 space-y-4">
              {[
                { label: "Full Name", value: employee.name },
                { label: "Designation", value: employee.designation ?? "—" },
                { label: "Department", value: employee.department ?? "—" },
                { label: "PAN", value: employee.pan ?? "—" },
                { label: "Bank Name", value: employee.bank_name ?? "—" },
                { label: "Account Number", value: employee.bank_account_no
                  ? `****${employee.bank_account_no.slice(-4)}`
                  : "—"
                },
                { label: "IFSC Code", value: employee.bank_ifsc ?? "—" },
              ].map(field => (
                <div key={field.label} className="flex items-center justify-between py-1 border-b border-gray-50 last:border-0">
                  <span className="text-xs text-[#64748B]">{field.label}</span>
                  <span className="text-sm font-medium text-[#0F172A]">{field.value}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
