"use client";

/**
 * PEOPLE — the roster across every client, and its exception index.
 *
 * WHY IT IS ITS OWN SCREEN (payroll v1 item 10)
 *
 * /payroll had grown into a rival of /clients/[id]/payroll: both could add an
 * employee, compute a run and read payslips, this one behind a client dropdown.
 * Two places to do one job is how the salary register and the ECR each ended up
 * implemented twice, once per surface, with only one of them right.
 *
 * The split is not "firm page loses everything". It is by GRAIN:
 *
 *   a MONTH is completed for one client   → /clients/[id]/payroll
 *   a ROSTER spans every client           → here
 *
 * An employee belongs to a client but is maintained across the firm — one form,
 * one bulk import, one place to see who is missing a UAN. That is what this
 * screen is, and it is why the Employees and Exceptions tabs moved off the rail
 * rather than being deleted with it.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import {
  Users, Plus, X, AlertCircle, Upload, Pencil, Ban, Trash2, RotateCcw,
  ArrowLeft, ShieldAlert, } from "lucide-react";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { DataTable, exportSelectedAction } from "@/components/ui/data-table";
import type { Column, FilterDef, BulkAction } from "@/lib/table/types";
import { formatPaise } from "@/lib/services/formatting";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api, type ApiResp } from "@/lib/api";
import {
  apiErr, employeeGrossPaise,
  type Client, type Employee,
} from "@/components/payroll/shared";
import { EMPLOYEE_IMPORT_COLUMNS as SERVER_COLUMNS } from "@/lib/imports/mappers";
import { AddEmployeeModal } from "@/components/payroll/AddEmployeeModal";
import { PortalAccessModal } from "@/components/payroll/PortalAccessModal";
import { ExceptionIndexTab } from "@/components/payroll/ExceptionIndex";

/** The importable columns: the server-mirrored list, plus the one column only a
 *  FIRM-wide import needs.
 *
 *  lib/imports/mappers.EMPLOYEE_IMPORT_COLUMNS mirrors
 *  domain/payroll/employee_import.COLUMNS and a Python parity test holds the two
 *  identical — a column the browser offers and the server ignores is one a CA
 *  fills in that silently does nothing. `client_name` is added here rather than
 *  there because the per-client import takes a client_id parameter and has
 *  nothing to resolve; only this screen does. */
const PEOPLE_IMPORT_COLUMNS = [
  { key: "client_name", label: "Client Name", required: true,
    hint: "Must match an existing client — the roster spans all of them" },
  ...SERVER_COLUMNS,
];

export default function PayrollPeoplePage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  // A failed read must not render as an empty roster — that is indistinguishable
  // from a firm with no employees, and it is the mistake M17 fixed across this
  // module.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [showImportEmp, setShowImportEmp] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [cRes, eRes] = await Promise.all([
        api.clients.list() as Promise<ApiResp<Client[]>>,
        api.payroll.listEmployees() as Promise<ApiResp<Employee[]>>,
      ]);
      if (!cRes.success || !eRes.success) {
        setLoadError(cRes.error ?? eRes.error ?? "Could not load the roster.");
        return;
      }
      setClients(cRes.data ?? []);
      setEmployees(eRes.data ?? []);
    } catch (e) {
      setLoadError(apiErr(e, "Could not load the roster."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Employee roster CRUD (edit / deactivate / delete + bulk) ────────────────
  const [editEmployee, setEditEmployee] = useState<Employee | null>(null);
  // Which employee's portal access is being managed, if any.
  const [portalEmployee, setPortalEmployee] = useState<Employee | null>(null);
  const [empActionMsg, setEmpActionMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const setEmployeeStatus = useCallback(async (emp: Employee, status: "active" | "resigned") => {
    const deactivating = status !== "active";
    if (!confirm(`${deactivating ? "Deactivate" : "Reactivate"} ${emp.name}? ${deactivating ? "They will be excluded from new payroll runs; existing payslips are unaffected." : "They will be eligible for payroll runs again."}`)) return;
    try {
      const res = await api.payroll.updateEmployee(emp.id, { status }) as ApiResp<unknown>;
      if (!res.success) { setEmpActionMsg({ type: "err", text: res.error ?? "Could not update the employee." }); return; }
      setEmpActionMsg({ type: "ok", text: `${emp.name} ${deactivating ? "deactivated" : "reactivated"}.` });
      load();
    } catch (e) { setEmpActionMsg({ type: "err", text: apiErr(e, "Could not update the employee.") }); }
  }, [load]);

  const deleteEmployeeAction = useCallback(async (emp: Employee) => {
    if (!confirm(`Permanently delete ${emp.name}? Only an employee with no payroll history can be deleted — otherwise deactivate them instead.`)) return;
    try {
      const res = await api.payroll.deleteEmployee(emp.id) as ApiResp<unknown>;
      if (!res.success) { setEmpActionMsg({ type: "err", text: res.error ?? "Could not delete the employee." }); return; }
      setEmpActionMsg({ type: "ok", text: `${emp.name} deleted.` });
      load();
    } catch (e) { setEmpActionMsg({ type: "err", text: apiErr(e, "Could not delete the employee.") }); }
  }, [load]);

  // Bulk: set status for the selected rows (deactivate → resigned, reactivate → active).
  const bulkSetEmployeeStatus = useCallback(async (rows: Employee[], status: "active" | "resigned"): Promise<void> => {
    const targets = rows.filter(e => (e.status ?? "active") !== status);
    if (targets.length === 0) { setEmpActionMsg({ type: "ok", text: "Nothing to change — the selected employees are already in that state." }); return; }
    let ok = 0; const failures: string[] = [];
    await Promise.all(targets.map(async (e) => {
      try {
        const res = await api.payroll.updateEmployee(e.id, { status }) as ApiResp<unknown>;
        if (!res.success) throw new Error(res.error ?? "failed");
        ok++;
      } catch (err) { failures.push(`${e.name}: ${apiErr(err, "failed")}`); }
    }));
    const verb = status === "active" ? "reactivated" : "deactivated";
    setEmpActionMsg(failures.length
      ? { type: "err", text: `${ok} ${verb}, ${failures.length} failed. ${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""}` }
      : { type: "ok", text: `${ok} employee${ok === 1 ? "" : "s"} ${verb}.` });
    if (ok) load();
  }, [load]);

  // Bulk delete: employees with payroll history are skipped (backend 409s); report both.
  const bulkDeleteEmployees = useCallback(async (rows: Employee[]): Promise<void> => {
    let deleted = 0, skipped = 0; const failures: string[] = [];
    await Promise.all(rows.map(async (e) => {
      try {
        const res = await api.payroll.deleteEmployee(e.id) as ApiResp<unknown>;
        if (!res.success) throw new Error(res.error ?? "failed");
        deleted++;
      } catch (err) {
        const msg = apiErr(err, "failed");
        if (/payroll history/i.test(msg)) skipped++;
        else failures.push(`${e.name}: ${msg}`);
      }
    }));
    const parts = [`${deleted} deleted`];
    if (skipped) parts.push(`${skipped} skipped (has payroll history — deactivate instead)`);
    if (failures.length) parts.push(`${failures.length} failed`);
    setEmpActionMsg({ type: failures.length ? "err" : "ok", text: parts.join(", ") + "." });
    if (deleted) load();
  }, [load]);

  /** The whole file, in ONE request, decided by the server.
   *
   *  Whole-file validation, whole-file refusal, and idempotent on
   *  `employee_code` (migration 333) — so "fix the spreadsheet and upload it
   *  again" is actually the answer to a refusal, rather than a second copy of
   *  everyone who imported cleanly the first time.
   */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[]; skipped?: number; skippedDetail?: string[] }> {
    // The roster spans clients, so the file names its client per row and the
    // import is grouped by it — a single client_id here would be a guess.
    const byClient = new Map<string, ImportRow[]>();
    for (const r of rows) {
      const name = String(r.client_name ?? "").trim().toLowerCase();
      const c = clients.find((x) => x.client_name.trim().toLowerCase() === name);
      if (!c) continue;
      const list = byClient.get(c.id) ?? [];
      list.push(r);
      byClient.set(c.id, list);
    }
    let matched = 0;
    byClient.forEach((l) => { matched += l.length; });
    const unmatched = rows.length - matched;
    if (unmatched > 0) {
      // Named rather than silently dropped: a row whose client this firm does
      // not have is a typo in the file, and importing the rest without saying
      // so leaves a roster short by exactly the rows nobody looked at.
      return { imported: 0, errors: [`${unmatched} row(s) name a client this firm does not have. Fix the Client Name column and re-upload; nothing was imported.`] };
    }

    let created = 0, updated = 0;
    const errors: string[] = [];
    for (const [clientId, clientRows] of Array.from(byClient.entries())) {
      try {
        const res = await api.payroll.importEmployees(clientId, clientRows as Record<string, string>[]);
        created += res?.data?.created ?? 0;
        updated += res?.data?.updated ?? 0;
      } catch (e) {
        const cname = clients.find((c) => c.id === clientId)?.client_name ?? clientId;
        errors.push(`${cname}: ${apiErr(e, "import failed")}`);
      }
    }
    if (created || updated) await load();
    return {
      imported: created,
      errors,
      skipped: updated,
      skippedDetail: updated > 0 ? [`${updated} existing employee(s) updated from their employee code`] : undefined,
    };
  }

  // ── Employees table (shared DataTable) ─────────────────────────────────────

  const employeeColumns: Column<Employee>[] = useMemo(() => [
    { key: "name", header: "Name", accessor: (e) => e.name, searchable: true, sortable: true, sticky: true, hideable: false,
      render: (e) => <span className="font-medium text-[#0F172A]">{e.name}</span> },
    { key: "pan", header: "PAN", accessor: (e) => e.pan ?? "", searchable: true,
      render: (e) => <span className="font-mono text-xs">{e.pan || "—"}</span> },
    { key: "designation", header: "Designation", accessor: (e) => e.designation ?? "", searchable: true, sortable: true,
      render: (e) => <span className="text-[#475569]">{e.designation || "—"}</span> },
    // Money column — accessor returns integer paise, right-aligned, rendered via formatPaise.
    { key: "gross", header: "Monthly CTC", accessor: (e) => employeeGrossPaise(e), sortable: true, align: "right",
      render: (e) => <span className="font-mono">{formatPaise(employeeGrossPaise(e))}</span> },
    { key: "pf_applicable", header: "PF", accessor: (e) => e.pf_applicable, sortable: true, align: "center",
      render: (e) => (
        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${e.pf_applicable ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
          {e.pf_applicable ? "Yes" : "No"}
        </span>
      ) },
    { key: "esi_applicable", header: "ESI", accessor: (e) => e.esi_applicable, sortable: true, align: "center",
      render: (e) => (
        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${e.esi_applicable ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
          {e.esi_applicable ? "Yes" : "No"}
        </span>
      ) },
    // Reads portal_enabled straight off the employee row rather than calling
    // portal-status per row — one request per employee would be N requests for
    // a column most firms will not use. The modal fetches the detail on open.
    { key: "portal", header: "Payslip portal", accessor: (e) => (e.portal_enabled ? "on" : "off"),
      sortable: true, align: "center",
      render: (e) => (
        <button
          onClick={() => setPortalEmployee(e)}
          className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium hover:ring-1 hover:ring-blue-300 ${
            e.portal_enabled ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}
          title={e.portal_enabled ? "Portal access is on — click to manage" : "Give this employee portal access"}
        >
          {e.portal_enabled ? "Active" : "Give access"}
        </button>
      ) },
    { key: "status", header: "Status", accessor: (e) => e.status ?? "active", sortable: true, align: "center",
      render: (e) => {
        const s = e.status ?? "active";
        const cls = s === "active" ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]";
        return <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize ${cls}`}>{s}</span>;
      } },
  ], []);

  const employeeFilters: FilterDef<Employee>[] = useMemo(() => [
    { key: "status", label: "Status", type: "select", accessor: (e) => e.status ?? "active",
      options: [{ value: "active", label: "Active" }, { value: "resigned", label: "Resigned" }, { value: "terminated", label: "Terminated" }] },
    { key: "pf_applicable", label: "PF", type: "boolean", accessor: (e) => e.pf_applicable, trueLabel: "Applicable", falseLabel: "Not applicable" },
    { key: "esi_applicable", label: "ESI", type: "boolean", accessor: (e) => e.esi_applicable, trueLabel: "Applicable", falseLabel: "Not applicable" },
  ], []);

  const employeeBulkActions: BulkAction<Employee>[] = useMemo(() => [
    { id: "deactivate", label: "Deactivate", icon: <Ban size={13} />,
      confirm: "Deactivate the selected employees? They will be excluded from new payroll runs. Existing payslips are unaffected and this can be undone.",
      run: (rows) => bulkSetEmployeeStatus(rows, "resigned") },
    { id: "reactivate", label: "Reactivate", icon: <RotateCcw size={13} />,
      confirm: "Reactivate the selected employees so they are eligible for payroll runs again?",
      run: (rows) => bulkSetEmployeeStatus(rows, "active") },
    { id: "delete", label: "Delete", icon: <Trash2 size={13} />, variant: "danger",
      confirm: "Permanently delete the selected employees? Anyone with payroll history is skipped (deactivate them instead). This cannot be undone.",
      run: bulkDeleteEmployees },
    exportSelectedAction<Employee>("employees-selected.csv", employeeColumns),
  ], [bulkSetEmployeeStatus, bulkDeleteEmployees, employeeColumns]);

  // ── Payslips table (shared DataTable) ──────────────────────────────────────

  if (loading) {
    return <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center"><p className="text-[#64748B]">Loading the roster…</p></div>;
  }

  if (loadError) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] p-8">
        <Card className="max-w-2xl mx-auto">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle size={18} className="text-red-500" />Couldn&apos;t load the roster
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-[#475569]">{loadError}</p>
            <Button size="sm" variant="outline" onClick={load}>Retry</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-6">
          <Link href="/payroll">
            <Button variant="ghost" size="sm" className="flex items-center gap-1.5 text-[#64748B] hover:text-[#0F172A] -ml-2">
              <ArrowLeft size={14} />Payroll
            </Button>
          </Link>
          <h1 className="text-2xl font-bold text-[#0F172A] flex items-center gap-2 mt-1">
            <Users size={22} className="text-blue-600" />People
          </h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Every employee across every client, and what the statutory outputs
            still need from them.
          </p>
        </div>

        <Tabs defaultValue="roster">
          <TabsList className="mb-6">
            <TabsTrigger value="roster" className="flex items-center gap-1.5"><Users size={14} />Roster</TabsTrigger>
            <TabsTrigger value="exceptions" className="flex items-center gap-1.5"><ShieldAlert size={14} />Exceptions</TabsTrigger>
          </TabsList>

          <TabsContent value="roster">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle>Employees</CardTitle>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="outline" onClick={() => setShowImportEmp(true)} className="flex items-center gap-1.5">
                    <Upload size={14} />Import CSV
                  </Button>
                  <Button size="sm" onClick={() => { setEditEmployee(null); setShowAdd(true); }} className="flex items-center gap-1.5">
                    <Plus size={14} />Add Employee
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {empActionMsg && (
                  <div className={`mb-3 flex items-center gap-2 px-3 py-2 rounded-lg text-xs ${empActionMsg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
                    {empActionMsg.text}
                    <button onClick={() => setEmpActionMsg(null)} className="ml-auto"><X size={12} /></button>
                  </div>
                )}
                <DataTable
                  data={employees}
                  columns={employeeColumns}
                  filters={employeeFilters}
                  getRowId={(e) => e.id}
                  loading={loading}
                  onRefresh={load}
                  searchPlaceholder="Search by name, PAN, or designation…"
                  initialSort={{ key: "name", dir: "asc" }}
                  initialFilters={{ status: "active" }}
                  exportFilename="employees"
                  persistKey="payroll.employees"
                  bulkActions={employeeBulkActions}
                  rowActions={(e) => {
                    const active = (e.status ?? "active") === "active";
                    return (
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => { setEditEmployee(e); setShowAdd(true); }} title="Edit"
                          className="p-1.5 rounded-lg text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#334155]"><Pencil size={14} /></button>
                        {active ? (
                          <button onClick={() => setEmployeeStatus(e, "resigned")} title="Deactivate"
                            className="p-1.5 rounded-lg text-[#64748B] hover:bg-amber-50 hover:text-amber-700"><Ban size={14} /></button>
                        ) : (
                          <button onClick={() => setEmployeeStatus(e, "active")} title="Reactivate"
                            className="p-1.5 rounded-lg text-[#64748B] hover:bg-green-50 hover:text-green-700"><RotateCcw size={14} /></button>
                        )}
                        <button onClick={() => deleteEmployeeAction(e)} title="Delete (only if no payroll history)"
                          className="p-1.5 rounded-lg text-[#64748B] hover:bg-red-50 hover:text-red-600"><Trash2 size={14} /></button>
                      </div>
                    );
                  }}
                  emptyTitle="No employees yet"
                  emptyDescription={'Click "Add Employee" or import a CSV to get started.'}
                />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="exceptions">
            <ExceptionIndexTab />
          </TabsContent>
        </Tabs>
      </div>

      {showAdd && (
        <AddEmployeeModal
          clients={clients}
          employee={editEmployee}
          onClose={() => { setShowAdd(false); setEditEmployee(null); }}
          onSaved={() => { setShowAdd(false); setEditEmployee(null); load(); }}
        />
      )}
      {portalEmployee && (
        <PortalAccessModal
          employee={portalEmployee}
          onClose={() => setPortalEmployee(null)}
          onChanged={load}
        />
      )}
      {showImportEmp && (
        <CsvImportModal
          title="Import Employees"
          columns={PEOPLE_IMPORT_COLUMNS}
          templateFilename="employees-template.csv"
          onImport={handleImport}
          onClose={() => setShowImportEmp(false)}
        />
      )}
    </div>
  );
}
