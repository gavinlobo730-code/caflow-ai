"use client";

/**
 * Employee Self-Service Portal — PracticeSync AI
 * Allows employees of CA firm clients to view their own payroll info.
 * Detects employee record by matching auth_user_id on payroll_employees.
 */

import { useState, useEffect, useCallback } from "react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { User, FileText, Calendar, Download, Loader2 } from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface EmployeeRecord {
  id: string;
  name: string;
  designation: string | null;
  department: string | null;
  pan: string | null;
  bank_account_number: string | null;
  bank_name: string | null;
  ifsc_code: string | null;
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

interface LeaveBalance {
  id: string;
  leave_type: string;
  total_days: number;
  used_days: number;
  year: number;
}

type TabId = "payslips" | "leave" | "profile";

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
      <button onClick={onClose} className="text-gray-400 hover:text-white">×</button>
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
  const [leaveBalances, setLeaveBalances] = useState<LeaveBalance[]>([]);
  const [leaveLoading, setLeaveLoading] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

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
          .select("id, name, designation, department, pan, bank_account_number, bank_name, ifsc_code")
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
    try {
      const supabase = getSupabaseClient();
      const { data, error: err } = await supabase
        .from("salary_slips")
        .select("id, month, year, gross_salary_paise, net_salary_paise, created_at")
        .eq("employee_id", employee.id)
        .order("year", { ascending: false })
        .order("month", { ascending: false });
      if (err) throw new Error(err.message);
      setPayslips(data ?? []);
    } catch (e) {
      console.error("loadPayslips:", e);
    } finally {
      setPayslipsLoading(false);
    }
  }, [employee]);

  const loadLeaveBalances = useCallback(async () => {
    if (!employee) return;
    setLeaveLoading(true);
    try {
      const supabase = getSupabaseClient();
      // Indian FY: April 1 to March 31
      const now = new Date();
      const currentYear = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
      const { data, error: err } = await supabase
        .from("leave_balances")
        .select("id, leave_type, total_days, used_days, year")
        .eq("employee_id", employee.id)
        .eq("year", currentYear);
      if (err) throw new Error(err.message);
      setLeaveBalances(data ?? []);
    } catch (e) {
      console.error("loadLeaveBalances:", e);
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
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex items-center gap-3 text-gray-500">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Loading your portal…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl border border-gray-200 p-8 max-w-md text-center space-y-3">
          <div className="w-12 h-12 rounded-full bg-red-50 flex items-center justify-center mx-auto">
            <User className="w-6 h-6 text-red-400" />
          </div>
          <p className="text-sm font-semibold text-gray-900">Access Unavailable</p>
          <p className="text-xs text-gray-500">{error}</p>
        </div>
      </div>
    );
  }

  if (!employee) return null;

  const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
    { id: "payslips", label: "Payslips", icon: <FileText size={15} /> },
    { id: "leave", label: "Leave Balance", icon: <Calendar size={15} /> },
    { id: "profile", label: "Profile", icon: <User size={15} /> },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}

      {/* Header */}
      <header className="bg-white border-b border-gray-100 px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-xs font-bold text-indigo-600 tracking-wide uppercase">PracticeSync</span>
              <span className="text-xs text-gray-300">|</span>
              <span className="text-xs text-gray-400">Employee Portal</span>
            </div>
            <h1 className="text-base font-semibold text-gray-900">Hello, {employee.name}</h1>
            {employee.designation && (
              <p className="text-xs text-gray-400 mt-0.5">{employee.designation}{employee.department ? ` · ${employee.department}` : ""}</p>
            )}
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="max-w-3xl mx-auto px-4 pt-6">
        <div className="flex gap-1 bg-white rounded-xl border border-gray-100 p-1 mb-6">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-medium transition-all ${
                activeTab === tab.id
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
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
              <div className="text-center py-10 text-sm text-gray-400 flex items-center justify-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading payslips…
              </div>
            ) : payslips.length === 0 ? (
              <div className="bg-white rounded-xl border border-gray-100 px-5 py-12 text-center">
                <FileText className="w-8 h-8 text-gray-200 mx-auto mb-2" />
                <p className="text-sm text-gray-400">No payslips found</p>
              </div>
            ) : (
              <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-xs text-gray-400">
                      <th className="px-5 py-3 text-left font-semibold">Period</th>
                      <th className="px-4 py-3 text-right font-semibold">Gross</th>
                      <th className="px-4 py-3 text-right font-semibold">Net Pay</th>
                      <th className="px-5 py-3 text-left font-semibold">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {payslips.map(slip => (
                      <tr key={slip.id} className="hover:bg-gray-50">
                        <td className="px-5 py-3 font-medium text-gray-900">
                          {MONTH_NAMES[(slip.month ?? 1) - 1]} {slip.year}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-600 font-mono text-xs">
                          {formatPaise(slip.gross_salary_paise)}
                        </td>
                        <td className="px-4 py-3 text-right text-green-700 font-semibold font-mono text-xs">
                          {formatPaise(slip.net_salary_paise)}
                        </td>
                        <td className="px-5 py-3">
                          <button
                            onClick={() => setToast("Payslip PDF generation coming soon")}
                            className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
                          >
                            <Download size={12} /> Download
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
              <div className="text-center py-10 text-sm text-gray-400 flex items-center justify-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> Loading leave balances…
              </div>
            ) : leaveBalances.length === 0 ? (
              <div className="bg-white rounded-xl border border-gray-100 px-5 py-12 text-center">
                <Calendar className="w-8 h-8 text-gray-200 mx-auto mb-2" />
                <p className="text-sm text-gray-400">No leave records found for current year</p>
              </div>
            ) : (
              <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-xs text-gray-400">
                      <th className="px-5 py-3 text-left font-semibold">Leave Type</th>
                      <th className="px-4 py-3 text-right font-semibold">Total Days</th>
                      <th className="px-4 py-3 text-right font-semibold">Used</th>
                      <th className="px-4 py-3 text-right font-semibold">Balance</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {leaveBalances.map(lb => {
                      const balance = lb.total_days - lb.used_days;
                      return (
                        <tr key={lb.id} className="hover:bg-gray-50">
                          <td className="px-5 py-3 font-medium text-gray-900 capitalize">{lb.leave_type}</td>
                          <td className="px-4 py-3 text-right text-gray-600">{lb.total_days}</td>
                          <td className="px-4 py-3 text-right text-amber-600">{lb.used_days}</td>
                          <td className={`px-4 py-3 text-right font-semibold ${balance > 0 ? "text-green-700" : "text-red-600"}`}>
                            {balance}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Profile Tab */}
        {activeTab === "profile" && (
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-gray-900">Employee Profile</h2>
              <p className="text-xs text-gray-400 mt-0.5">Read-only — contact HR to update your details</p>
            </div>
            <div className="px-5 py-4 space-y-4">
              {[
                { label: "Full Name", value: employee.name },
                { label: "Designation", value: employee.designation ?? "—" },
                { label: "Department", value: employee.department ?? "—" },
                { label: "PAN", value: employee.pan ?? "—" },
                { label: "Bank Name", value: employee.bank_name ?? "—" },
                { label: "Account Number", value: employee.bank_account_number
                  ? `****${employee.bank_account_number.slice(-4)}`
                  : "—"
                },
                { label: "IFSC Code", value: employee.ifsc_code ?? "—" },
              ].map(field => (
                <div key={field.label} className="flex items-center justify-between py-1 border-b border-gray-50 last:border-0">
                  <span className="text-xs text-gray-500">{field.label}</span>
                  <span className="text-sm font-medium text-gray-900">{field.value}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
