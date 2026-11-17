"use client";

/**
 * Payroll opening positions (POST-A-082): what an employee had been paid and had deducted this financial year BEFORE the client's
 * payroll ran on this product, for a client that comes over part-way through a year.
 *
 * DECIDES NOTHING. The checks (the months against the joining date, tax against gross) and every sentence are the server's. A box
 * is never pre-filled: a figure here is a fact read off the old system, and a blank box is "not entered", which the form refuses
 * rather than reading as nil. Saving posts nothing, makes no payslip and remits nothing, and the page says so beside the form.
 */
import { useCallback, useEffect, useState } from "react";
import { Loader2, History } from "lucide-react";
import { Field, Input, Select } from "@/components/ui/field";
import { api } from "@/lib/api";
import type { OpeningPositions } from "@/lib/api";
import { usePermissions } from "@/lib/auth/AuthContext";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { formatPaise as rupees } from "@/lib/money/format";
import { objectWithLists } from "@/lib/api/shape";
import { EmptyState } from "@/components/ui/states";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { Callout } from "@/components/ui/callout";
import { Button } from "@/components/ui/button";
import { LoadingRegion } from "@/components/ui/skeleton";

const AMOUNTS = [
  ["gross", "Gross paid so far"], ["tds", "Tax withheld (s.192)"],
  ["pfEe", "PF — employee"], ["pfEr", "PF — employer"],
  ["esiEe", "ESI — employee"], ["esiEr", "ESI — employer"], ["pt", "Professional tax"],
] as const;
type AmountKey = (typeof AMOUNTS)[number][0];

export function OpeningPositionsTab({ clientId }: { clientId: string }) {
  const { can } = usePermissions();
  const mayWrite = can("payroll", "write");
  const years = financialYearChoicesAround();
  const [year, setYear] = useState(years[0] ?? "");
  const [data, setData] = useState<OpeningPositions | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [first, setFirst] = useState("");
  const [months, setMonths] = useState("");
  const [amounts, setAmounts] = useState<Record<AmountKey, string>>({ gross: "", tds: "", pfEe: "", pfEr: "", esiEe: "", esiEr: "", pt: "" });
  const [esi, setEsi] = useState("unknown");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || !year) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.payroll.openingPositions(clientId, year);
      if (!res.success || !res.data) { setError(res.error || "Couldn't read the opening positions."); setData(null); return; }
      setData(objectWithLists<OpeningPositions>(res.data, "rows", "without"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't read the opening positions.");
    } finally {
      setLoading(false);
    }
  }, [clientId, year]);
  useEffect(() => { void load(); }, [load]);

  function open(employeeId: string) {
    const row = (data?.rows ?? []).find((r) => r.employee_id === employeeId);
    setEditing(employeeId);
    setError(null);
    setFirst(row ? (row.first_month_here ?? "").slice(0, 7) : "");
    setMonths(row ? String(row.months_paid) : "");
    const rs = (p: number | undefined) => (p === undefined ? "" : (p / 100).toFixed(2));
    setAmounts({ gross: rs(row?.gross_paise), tds: rs(row?.tds_paise), pfEe: rs(row?.pf_employee_paise), pfEr: rs(row?.pf_employer_paise),
      esiEe: rs(row?.esi_employee_paise), esiEr: rs(row?.esi_employer_paise), pt: rs(row?.pt_paise) });
    setEsi(row ? (row.esi_contributed_earlier_in_period === null ? "unknown" : row.esi_contributed_earlier_in_period ? "yes" : "no") : "unknown");
    setNote(row?.source_note ?? "");
  }

  async function save() {
    if (!editing || saving) return;
    const paise: Partial<Record<AmountKey, number>> = {};
    for (const [k, label] of AMOUNTS) {
      // A blank box is not entered, and is refused: the shared parser reads blank as 0, which here would be a claim.
      if (amounts[k].trim() === "") { setError(`Not saved: ${label} is blank. Enter 0 if it was nil.`); return; }
      const v = paiseFromRupeeInput(amounts[k]);
      if (v === null) { setError(`Not saved: ${label} "${amounts[k]}" is not a plain amount (digits and up to two decimals).`); return; }
      paise[k] = v;
    }
    if (!/^\d{1,2}$/.test(months.trim())) { setError("Not saved: months already paid must be a whole number."); return; }
    setSaving(true);
    setError(null);
    try {
      const res = await api.payroll.saveOpeningPositions({
        client_id: clientId,
        rows: [{
          employee_id: editing, first_month_here: first, months_paid: Number(months),
          gross_paise: paise.gross!, tds_paise: paise.tds!, pf_employee_paise: paise.pfEe!, pf_employer_paise: paise.pfEr!,
          esi_employee_paise: paise.esiEe!, esi_employer_paise: paise.esiEr!, pt_paise: paise.pt!,
          esi_contributed_earlier_in_period: esi === "unknown" ? null : esi === "yes",
          source_note: note.trim() || null,
        }],
      });
      if (!res.success) { setError(res.error || "Couldn't record the opening position."); return; }
      setEditing(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record the opening position.");
    } finally {
      setSaving(false);
    }
  }

  async function remove(employeeId: string) {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const res = await api.payroll.deleteOpeningPosition(clientId, employeeId, year);
      if (!res.success) { setError(res.error || "Couldn't take the opening position back."); return; }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't take the opening position back.");
    } finally {
      setSaving(false);
    }
  }

  const names = new Map<string, string>();
  (data?.rows ?? []).forEach((r) => names.set(r.employee_id, r.employee_name ?? r.employee_id));
  (data?.without ?? []).forEach((w) => names.set(w.employee_id, w.employee_name ?? w.employee_id));

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <History size={14} className="text-blue-600" />
            <h2 className="text-sm font-semibold text-ps-ink">Opening positions</h2>
          </div>
          <p className="text-2xs text-ps-label mt-0.5">For a client that came over part-way through the year</p>
        </div>
        <Field label="Financial year" htmlFor="opening-year" size="sm">
          <Select value={year} onChange={(e) => setYear(e.target.value)} size="sm" className="w-auto">
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </Select>
        </Field>
      </div>

      {data && (
        <Callout tone="note" title="What this is, and is not">
          <p>{data.carries}</p>
          <p className="mt-1">{data.does_not_carry}</p>
        </Callout>
      )}
      {error && <Callout tone="problem">{error}</Callout>}

      {loading && !data && <LoadingRegion label="Reading the opening positions"><span /></LoadingRegion>}
      {data && (
          (data.rows ?? []).length === 0 && (data.without ?? []).length === 0 ? (
            <EmptyState icon={<History size={28} />} className="py-10" title="No employees on this client's payroll yet"
              description="Add the employees on the People tab, then record what each had been paid before this product ran the payroll." />
          ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-ps-label">
                <th className="py-1.5">Employee</th><th>First month here</th><th>Months paid</th>
                <th className="text-right">Gross</th><th className="text-right">Tax withheld</th><th />
              </tr>
            </thead>
            <tbody>
              {(data.rows ?? []).map((r) => (
                <tr key={r.id} className="border-t">
                  <td className="py-1.5">{r.employee_name ?? r.employee_id}</td>
                  <td>{r.first_month_here.slice(0, 7)}</td><td>{r.months_paid}</td>
                  <td className="text-right">{rupees(r.gross_paise)}</td><td className="text-right">{rupees(r.tds_paise)}</td>
                  <td className="text-right whitespace-nowrap">
                    {mayWrite && (<>
                      <Button size="sm" variant="ghost" onClick={() => open(r.employee_id)}>Edit</Button>
                      <Button size="sm" variant="ghost" disabled={saving} onClick={() => remove(r.employee_id)}>Take back</Button>
                    </>)}
                  </td>
                </tr>
              ))}
              {(data.without ?? []).map((w) => (
                <tr key={w.employee_id} className="border-t text-ps-label">
                  <td className="py-1.5">{w.employee_name ?? w.employee_id}</td>
                  <td colSpan={4}>Nothing entered yet; that is not the same as nothing paid earlier</td>
                  <td className="text-right">{mayWrite && <Button size="sm" variant="ghost" onClick={() => open(w.employee_id)}>Record</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          )
      )}

      {editing && mayWrite && (
        <div className="rounded-lg border p-4 space-y-3">
          <h3 className="text-xs font-semibold">{names.get(editing)} · {year}</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Field label="First month run here (YYYY-MM)" htmlFor="op-first" size="sm">
              <Input value={first} onChange={(e) => setFirst(e.target.value)} placeholder="2026-10" size="sm" />
            </Field>
            <Field label="Months already paid" htmlFor="op-months" size="sm">
              <Input value={months} onChange={(e) => setMonths(e.target.value)} inputMode="numeric" size="sm" />
            </Field>
            {AMOUNTS.map(([k, label]) => (
              <Field key={k} label={`${label} (₹)`} htmlFor={`op-${k}`} size="sm">
                <Input value={amounts[k]} onChange={(e) => setAmounts({ ...amounts, [k]: e.target.value })} inputMode="decimal" size="sm" />
              </Field>
            ))}
            <Field label="Contributed to ESI earlier in this period?" htmlFor="op-esi" size="sm">
              <Select value={esi} onChange={(e) => setEsi(e.target.value)} size="sm">
                <option value="unknown">Not known</option><option value="yes">Yes</option><option value="no">No</option>
              </Select>
            </Field>
            <Field label="Where the figures came from" htmlFor="op-note" size="sm" className="md:col-span-2">
              <Input value={note} onChange={(e) => setNote(e.target.value)} size="sm" />
            </Field>
          </div>
          <div className="flex gap-2">
            <Button size="sm" disabled={saving} onClick={() => save()}>
              {saving ? <Loader2 size={12} className="animate-spin" /> : null} Save position
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
          </div>
        </div>
      )}
    </div>
  );
}
