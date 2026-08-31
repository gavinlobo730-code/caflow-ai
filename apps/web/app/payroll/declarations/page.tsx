"use client";

/**
 * Employee income-tax declarations — the CA's side.
 *
 * IT Act §192, CBDT Circular 04/2023 (the regime intimation), Rule 26C /
 * Form 12BB (the evidence).
 *
 * THIS PAGE COMPUTES NOTHING. Every figure and every notice comes from
 * apps/api — the regime gate on Chapter VI-A, the §10(13A) formula, the
 * §115BAC(2) exclusions and the Rule 26C particulars all live in
 * domain/payroll/declarations.py. A second implementation here would drift, and
 * the drift would be invisible because both numbers look reasonable
 * (CLAUDE.md: zero business logic in the frontend).
 *
 * All monetary values are integer paise on the wire and formatted to ₹ here.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { ArrowLeft, AlertCircle, CheckCircle2, Info, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { api, type DeclarationRow, type DeclarationItemRow } from "@/lib/api";

type Client = { id: string; client_name: string };
type Employee = { id: string; name: string };

// ── Helpers ────────────────────────────────────────────────────────────────

function formatPaise(paise: number | null | undefined): string {
  const v = paise ?? 0;
  const rupees = Math.floor(v / 100);
  const p = v % 100;
  const formatted = new Intl.NumberFormat("en-IN").format(rupees);
  return p > 0 ? `₹${formatted}.${String(p).padStart(2, "0")}` : `₹${formatted}`;
}

/** Rupees typed into a box -> integer paise. Parsed as a whole number of
 *  rupees plus at most two decimals, never via floating-point multiplication
 *  (0.1 * 100 is 10.000000000000002). */
function rupeesToPaise(text: string): number {
  const cleaned = text.replace(/[^\d.]/g, "");
  if (!cleaned) return 0;
  const [whole, frac = ""] = cleaned.split(".");
  const paise = (frac + "00").slice(0, 2);
  return Number(whole || "0") * 100 + Number(paise);
}

/** Indian financial years, current first. April to March. */
function recentFinancialYears(count = 4): string[] {
  const now = new Date();
  const startYear = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return Array.from({ length: count }, (_, i) => {
    const y = startYear - i;
    return `${y}-${String((y + 1) % 100).padStart(2, "0")}`;
  });
}

const SECTION_LABELS: Record<string, string> = {
  "80C": "§80C — PPF, ELSS, LIC, principal, tuition",
  "80CCD(1B)": "§80CCD(1B) — additional NPS",
  "80CCD(2)": "§80CCD(2) — employer's NPS",
  "80D-self": "§80D — self and family",
  "80D-parents": "§80D — parents",
  "80TTA": "§80TTA — savings interest",
};

// ── Page ───────────────────────────────────────────────────────────────────

export default function DeclarationsPage() {
  const financialYears = useMemo(() => recentFinancialYears(), []);
  const [clients, setClients] = useState<Client[]>([]);
  const [employees, setEmployees] = useState<Record<string, string>>({});
  const [clientId, setClientId] = useState("");
  const [fy, setFy] = useState(financialYears[0]);
  const [rows, setRows] = useState<DeclarationRow[]>([]);
  const [loading, setLoading] = useState(false);
  // Distinguishes "this client has no declarations" from "the load failed" —
  // rendering a failure as an empty state tells the CA everyone declined to
  // declare, which is a different fact entirely.
  const [loadFailed, setLoadFailed] = useState(false);
  const [verifying, setVerifying] = useState<DeclarationRow | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const sb = getSupabaseClient();
        const fid = await getFirmId();
        if (!fid) return;
        const { data } = await sb.from("clients")
          .select("id, client_name").eq("firm_id", fid).order("client_name");
        setClients(data ?? []);
      } catch (e) {
        console.error("load clients:", e);
      }
    })();
  }, []);

  const load = useCallback(async () => {
    if (!clientId || !fy) { setRows([]); return; }
    setLoading(true);
    setLoadFailed(false);
    try {
      const [decls, emps] = await Promise.all([
        api.payroll.listDeclarations(clientId, fy),
        api.payroll.listEmployees(clientId, true),
      ]);
      setRows(decls?.data?.declarations ?? []);
      const byId: Record<string, string> = {};
      for (const e of ((emps as { data?: Employee[] })?.data ?? [])) byId[e.id] = e.name;
      setEmployees(byId);
    } catch (e) {
      console.error("load declarations:", e);
      setLoadFailed(true);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [clientId, fy]);

  useEffect(() => { void load(); }, [load]);

  const outstanding = rows.filter((r) => !r.proofs_verified).length;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/payroll" className="text-[#64748B] hover:text-[#0F172A]">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Tax declarations</h1>
          <p className="text-sm text-[#64748B]">
            What each employee declared under §192, and what their proofs support.
          </p>
        </div>
      </div>

      <Card>
        <CardContent className="pt-5 flex flex-wrap items-end gap-3">
          <div className="min-w-[260px]">
            <label className="block text-xs text-[#64748B] mb-1">Client</label>
            <ClientLookup clients={clients} value={clientId} onChange={setClientId} />
          </div>
          <div>
            <label className="block text-xs text-[#64748B] mb-1">Financial year</label>
            <select
              value={fy}
              onChange={(e) => setFy(e.target.value)}
              className="border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm"
            >
              {financialYears.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          {rows.length > 0 && (
            <div className="ml-auto text-sm text-[#64748B]">
              {rows.length} declaration{rows.length === 1 ? "" : "s"}
              {outstanding > 0 && (
                <span className="ml-2 text-[#B45309]">
                  · {outstanding} awaiting proof
                </span>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* The rule that makes the fourth quarter matter. Stated once, here,
          rather than repeated on every unverified row. */}
      {outstanding > 0 && (
        <div className="flex gap-2.5 text-sm bg-[#FFFBEB] border border-[#FDE68A] rounded-lg p-3.5">
          <AlertCircle className="w-4 h-4 text-[#B45309] shrink-0 mt-0.5" />
          <p className="text-[#78350F]">
            <strong>{outstanding}</strong> declaration{outstanding === 1 ? " has" : "s have"} no
            verified proofs. Declared figures stop reducing tax from January, because §192(1)
            makes the employer answerable for a correct deduction — an unproved claim left in
            place becomes a Q4 shortfall with no salary left to recover it from.
          </p>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-sm text-[#64748B] py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading declarations…
        </div>
      )}

      {!loading && loadFailed && (
        <Card><CardContent className="py-10 text-center text-sm text-[#B91C1C]">
          Could not load declarations. This is a load failure, not an empty year —
          <button onClick={() => void load()} className="underline ml-1">try again</button>.
        </CardContent></Card>
      )}

      {!loading && !loadFailed && clientId && rows.length === 0 && (
        <Card><CardContent className="py-10 text-center text-sm text-[#64748B]">
          No declarations for {fy}. Every employee is withheld on the new regime with only
          the §16(ia) standard deduction — which is the correct default under §115BAC(1A),
          and the wrong answer for anyone who has deductions to claim.
        </CardContent></Card>
      )}

      {!loading && rows.map((row) => (
        <DeclarationCard
          key={row.id}
          row={row}
          employeeName={employees[row.employee_id] ?? "Unknown employee"}
          onVerify={() => setVerifying(row)}
        />
      ))}

      {verifying && (
        <VerifyModal
          row={verifying}
          clientId={clientId}
          employeeName={employees[verifying.employee_id] ?? "Unknown employee"}
          onClose={() => setVerifying(null)}
          onSaved={() => { setVerifying(null); void load(); }}
        />
      )}
    </div>
  );
}

// ── One declaration ────────────────────────────────────────────────────────

function DeclarationCard({ row, employeeName, onVerify }: {
  row: DeclarationRow; employeeName: string; onVerify: () => void;
}) {
  const chapterViA = row.items.reduce((n, i) => n + i.amount_declared_paise, 0);
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="text-base">{employeeName}</CardTitle>
          <p className="text-xs text-[#64748B] mt-0.5">
            {row.regime === "old" ? "Old regime" : "New regime (§115BAC(1A) default)"}
            {" · "}
            {row.proofs_verified
              ? <span className="text-[#047857]">proofs verified</span>
              : <span className="text-[#B45309]">proofs outstanding</span>}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onVerify}>
          {row.proofs_verified ? "Review" : "Verify proofs"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <Figure label="Rent paid (§10(13A))"
                  declared={row.rent_paid_declared_paise}
                  verified={row.rent_paid_verified_paise}
                  verifiedKnown={row.proofs_verified} />
          <Figure label="Leave travel (§10(5))"
                  declared={row.lta_declared_paise}
                  verified={row.lta_verified_paise}
                  verifiedKnown={row.proofs_verified} />
          <Figure label="Home loan interest (§24(b))"
                  declared={row.home_loan_interest_declared_paise}
                  verified={row.home_loan_interest_verified_paise}
                  verifiedKnown={row.proofs_verified} />
          <Figure label="Chapter VI-A" declared={chapterViA}
                  verified={row.items.reduce((n, i) => n + i.amount_verified_paise, 0)}
                  verifiedKnown={row.proofs_verified} />
        </div>

        {row.items.length > 0 && (
          <div className="border-t border-[#F1F5F9] pt-3 space-y-1">
            {row.items.map((i) => (
              <div key={i.id} className="flex items-center justify-between text-sm">
                <span className="text-[#475569]">
                  {SECTION_LABELS[i.section] ?? i.section}
                  {i.label ? <span className="text-[#94A3B8]"> · {i.label}</span> : null}
                </span>
                <span className="tabular-nums">
                  {i.status === "rejected"
                    ? <span className="text-[#B91C1C]">rejected</span>
                    : formatPaise(i.status === "verified"
                        ? i.amount_verified_paise : i.amount_declared_paise)}
                </span>
              </div>
            ))}
          </div>
        )}

        {row.problems.length > 0 && (
          <div className="border-t border-[#F1F5F9] pt-3 space-y-2">
            {row.problems.map((n, idx) => (
              <div key={idx} className="flex gap-2 text-xs text-[#991B1B]">
                <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <span>{n}</span>
              </div>
            ))}
          </div>
        )}

        {row.notices.length > 0 && (
          <div className="border-t border-[#F1F5F9] pt-3 space-y-2">
            {row.notices.map((n, idx) => (
              <div key={idx} className="flex gap-2 text-xs text-[#475569]">
                <Info className="w-3.5 h-3.5 shrink-0 mt-0.5 text-[#64748B]" />
                <span>{n}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** A declared figure beside what the proofs supported.
 *  Before verification the verified column reads "—", not "₹0": nobody has
 *  looked yet, which is not the same as a proof supporting nothing. */
function Figure({ label, declared, verified, verifiedKnown }: {
  label: string; declared: number; verified: number; verifiedKnown: boolean;
}) {
  const short = verifiedKnown && verified < declared;
  return (
    <div>
      <p className="text-xs text-[#64748B]">{label}</p>
      <p className="tabular-nums text-[#0F172A]">{formatPaise(declared)}</p>
      <p className={`text-xs tabular-nums ${short ? "text-[#B45309]" : "text-[#94A3B8]"}`}>
        {verifiedKnown ? `proved ${formatPaise(verified)}` : "—"}
      </p>
    </div>
  );
}

// ── Verifying ──────────────────────────────────────────────────────────────

function VerifyModal({ row, clientId, employeeName, onClose, onSaved }: {
  row: DeclarationRow; clientId: string; employeeName: string;
  onClose: () => void; onSaved: () => void;
}) {
  const [rent, setRent] = useState(String(row.rent_paid_verified_paise / 100));
  const [lta, setLta] = useState(String(row.lta_verified_paise / 100));
  const [interest, setInterest] = useState(
    String(row.home_loan_interest_verified_paise / 100));
  const [items, setItems] = useState<Record<string, string>>(() => {
    const seed: Record<string, string> = {};
    for (const i of row.items) seed[i.section] = String(i.amount_verified_paise / 100);
    return seed;
  });
  const [markVerified, setMarkVerified] = useState(row.proofs_verified);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.payroll.verifyDeclaration(row.id, {
        client_id: clientId,
        rent_paid_verified_paise: rupeesToPaise(rent),
        lta_verified_paise: rupeesToPaise(lta),
        home_loan_interest_verified_paise: rupeesToPaise(interest),
        items: row.items.map((i) => ({
          section: i.section,
          amount_verified_paise: rupeesToPaise(items[i.section] ?? "0"),
          status: rupeesToPaise(items[i.section] ?? "0") > 0 ? "verified" : "rejected",
        })),
        proofs_verified: markVerified,
      });
      onSaved();
    } catch (e) {
      // The API refuses a verified amount above the declared one — a proof can
      // support less than was claimed, never more. Surface its words, not ours.
      setError(e instanceof Error ? e.message : "Could not save. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`Verify proofs — ${employeeName}`}
      note={`${row.fy} · ${row.regime === "old" ? "old regime" : "new regime"}`}
      onClose={onClose}
      maxWidthClass="max-w-2xl"
    >
      <div className="space-y-4">
        <p className="text-xs text-[#64748B]">
          Enter what the proofs actually support. A proof can support less than was
          claimed and never more.
        </p>

        <ProofRow label="Rent paid (§10(13A))"
                  declared={row.rent_paid_declared_paise} value={rent} onChange={setRent} />
        <ProofRow label="Leave travel (§10(5))"
                  declared={row.lta_declared_paise} value={lta} onChange={setLta} />
        <ProofRow label="Home loan interest (§24(b))"
                  declared={row.home_loan_interest_declared_paise}
                  value={interest} onChange={setInterest} />

        {row.items.map((i: DeclarationItemRow) => (
          <ProofRow
            key={i.id}
            label={SECTION_LABELS[i.section] ?? i.section}
            declared={i.amount_declared_paise}
            value={items[i.section] ?? "0"}
            onChange={(v) => setItems((prev) => ({ ...prev, [i.section]: v }))}
          />
        ))}

        <label className="flex items-start gap-2.5 text-sm border-t border-[#F1F5F9] pt-4">
          <input type="checkbox" checked={markVerified}
                 onChange={(e) => setMarkVerified(e.target.checked)}
                 className="mt-0.5" />
          <span className="text-[#334155]">
            Every proof has been through.
            <span className="block text-xs text-[#64748B] mt-0.5">
              Until this is ticked, the declared figures keep reducing tax for the first
              three quarters and stop from January. Ticking it also locks the declaration
              against further edits by the employee.
            </span>
          </span>
        </label>

        {error && (
          <p className="text-sm text-[#B91C1C] bg-[#FEF2F2] border border-[#FECACA] rounded-lg p-3">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={() => void save()} disabled={saving}>
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4 mr-1.5" />}
            Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function ProofRow({ label, declared, value, onChange }: {
  label: string; declared: number; value: string; onChange: (v: string) => void;
}) {
  const over = rupeesToPaise(value) > declared;
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1">
        <p className="text-sm text-[#334155]">{label}</p>
        <p className="text-xs text-[#94A3B8]">declared {formatPaise(declared)}</p>
      </div>
      <div className="w-40">
        <input
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label={`${label} — amount proved`}
          className={`w-full border rounded-lg px-3 py-2 text-sm text-right tabular-nums ${
            over ? "border-[#DC2626] bg-[#FEF2F2]" : "border-[#E2E8F0]"}`}
        />
        {over && <p className="text-[11px] text-[#B91C1C] mt-1">above what was declared</p>}
      </div>
    </div>
  );
}
