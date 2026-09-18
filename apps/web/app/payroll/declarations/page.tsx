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

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
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

/** Rupees typed into a box -> integer paise, or null if it is not an amount.
 *
 *  This was a local reimplementation that had the right IDEA — concatenate the
 *  digits rather than multiply by 100 — and then stripped every non-digit
 *  first, so "12abc" became 12 and "1.2.3" became ₹1.20. lib/money/rupeeInput
 *  is the one implementation of this now, and it refuses instead of cleaning. */
function rupeesToPaise(text: string): number | null {
  return paiseFromRupeeInput(text);
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
        <Link href="/payroll" className="text-ps-label hover:text-ps-ink">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Tax declarations</h1>
          <p className="text-sm text-ps-label">
            What each employee declared under §192, and what their proofs support.
          </p>
        </div>
      </div>

      <Card>
        <CardContent className="pt-5 flex flex-wrap items-end gap-3">
          <div className="min-w-[260px]">
            <label className="block text-xs text-ps-label mb-1">Client</label>
            <ClientLookup clients={clients} value={clientId} onChange={setClientId} />
          </div>
          <div>
            <label className="block text-xs text-ps-label mb-1">Financial year</label>
            <select
              value={fy}
              onChange={(e) => setFy(e.target.value)}
              className="border border-ps-border rounded-lg px-3 py-2 text-sm"
            >
              {financialYears.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          {rows.length > 0 && (
            <div className="ml-auto text-sm text-ps-label">
              {rows.length} declaration{rows.length === 1 ? "" : "s"}
              {outstanding > 0 && (
                <span className="ml-2 text-state-attention">
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
        <div className="flex gap-2.5 text-sm bg-state-attention-surface border border-state-attention-border rounded-lg p-3.5">
          <AlertCircle className="w-4 h-4 text-state-attention shrink-0 mt-0.5" />
          <p className="text-[#78350F]">
            <strong>{outstanding}</strong> declaration{outstanding === 1 ? " has" : "s have"} no
            verified proofs. Declared figures stop reducing tax from January, because §192(1)
            makes the employer answerable for a correct deduction — an unproved claim left in
            place becomes a Q4 shortfall with no salary left to recover it from.
          </p>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-sm text-ps-label py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading declarations…
        </div>
      )}

      {!loading && loadFailed && (
        <Card><CardContent className="py-10 text-center text-sm text-state-problem">
          Could not load declarations. This is a load failure, not an empty year —
          <button onClick={() => void load()} className="underline ml-1">try again</button>.
        </CardContent></Card>
      )}

      {!loading && !loadFailed && clientId && rows.length === 0 && (
        <Card><CardContent className="py-10 text-center text-sm text-ps-label">
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
          <p className="text-xs text-ps-label mt-0.5">
            {row.regime === "old" ? "Old regime" : "New regime (§115BAC(1A) default)"}
            {" · "}
            {row.proofs_verified
              ? <span className="text-state-ready">proofs verified</span>
              : <span className="text-state-attention">proofs outstanding</span>}
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
          <div className="border-t border-ps-muted pt-3 space-y-1">
            {row.items.map((i) => (
              <div key={i.id} className="flex items-center justify-between text-sm">
                <span className="text-ps-label">
                  {SECTION_LABELS[i.section] ?? i.section}
                  {i.label ? <span className="text-ps-hint"> · {i.label}</span> : null}
                </span>
                <span className="tabular-nums">
                  {i.status === "rejected"
                    ? <span className="text-state-problem">rejected</span>
                    : formatPaise(i.status === "verified"
                        ? i.amount_verified_paise : i.amount_declared_paise)}
                </span>
              </div>
            ))}
          </div>
        )}

        {row.problems.length > 0 && (
          <div className="border-t border-ps-muted pt-3 space-y-2">
            {row.problems.map((n, idx) => (
              <div key={idx} className="flex gap-2 text-xs text-[#991B1B]">
                <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <span>{n}</span>
              </div>
            ))}
          </div>
        )}

        {row.notices.length > 0 && (
          <div className="border-t border-ps-muted pt-3 space-y-2">
            {row.notices.map((n, idx) => (
              <div key={idx} className="flex gap-2 text-xs text-ps-label">
                <Info className="w-3.5 h-3.5 shrink-0 mt-0.5 text-ps-label" />
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
      <p className="text-xs text-ps-label">{label}</p>
      <p className="tabular-nums text-ps-ink">{formatPaise(declared)}</p>
      <p className={`text-xs tabular-nums ${short ? "text-state-attention" : "text-ps-hint"}`}>
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
  // `undefined` for a section means the CA has not touched its documents, which
  // is a DIFFERENT thing from having cleared them — see the save() comment.
  const [docs, setDocs] = useState<Record<string, { name: string; url?: string; document_id?: string }[]>>({});
  const [markVerified, setMarkVerified] = useState(row.proofs_verified);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    // A VERIFIED figure is the amount the employer will actually withhold
    // against — the whole point of this screen is that it replaces what the
    // employee declared. Read exactly, and refuse rather than coerce.
    const verified = {
      rent: rupeesToPaise(rent), lta: rupeesToPaise(lta),
      interest: rupeesToPaise(interest),
    };
    const itemPaise = Object.fromEntries(
      row.items.map((i) => [i.section, rupeesToPaise(items[i.section] ?? "0")]),
    ) as Record<string, number | null>;
    if (Object.values(verified).some((v) => v === null)
        || Object.values(itemPaise).some((v) => v === null)) {
      setError("Every verified amount must be in rupees, e.g. 150000 or 150000.50 "
               + "— without commas.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.payroll.verifyDeclaration(row.id, {
        client_id: clientId,
        rent_paid_verified_paise: verified.rent as number,
        lta_verified_paise: verified.lta as number,
        home_loan_interest_verified_paise: verified.interest as number,
        items: row.items.map((i) => ({
          section: i.section,
          amount_verified_paise: itemPaise[i.section] as number,
          status: (itemPaise[i.section] as number) > 0 ? "verified" : "rejected",
          // OMITTED where the CA did not touch the documents. The server reads
          // absent as UNCHANGED and an empty array as REMOVE, so sending `[]`
          // here would wipe an employee's uploads every time a verified amount
          // was saved without re-attaching them.
          ...(docs[i.section] === undefined
            ? {} : { proof_attachments: docs[i.section] }),
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
        <p className="text-xs text-ps-label">
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

        {/* CHAPTER VI-A ONLY. The four Rule 26C header claims above — rent,
            leave travel, home loan interest — live on the DECLARATION row and
            have no attachment column, so offering a document box there would
            invite a CA to type into something that goes nowhere. */}
        {row.items.map((i: DeclarationItemRow) => (
          <div key={i.id} className="space-y-1.5">
            <ProofRow
              label={SECTION_LABELS[i.section] ?? i.section}
              declared={i.amount_declared_paise}
              value={items[i.section] ?? "0"}
              onChange={(v) => setItems((prev) => ({ ...prev, [i.section]: v }))}
            />
            <ProofDocuments
              existing={i.proof_attachments ?? []}
              reference={i.proof_reference}
              pending={docs[i.section]}
              onChange={(next) => setDocs((prev) => ({ ...prev, [i.section]: next }))}
            />
          </div>
        ))}

        <label className="flex items-start gap-2.5 text-sm border-t border-ps-muted pt-4">
          <input type="checkbox" checked={markVerified}
                 onChange={(e) => setMarkVerified(e.target.checked)}
                 className="mt-0.5" />
          <span className="text-ps-body">
            Every proof has been through.
            <span className="block text-xs text-ps-label mt-0.5">
              Until this is ticked, the declared figures keep reducing tax for the first
              three quarters and stop from January. Ticking it also locks the declaration
              against further edits by the employee.
            </span>
          </span>
        </label>

        {error && (
          <p className="text-sm text-state-problem bg-state-problem-surface border border-state-problem-border rounded-lg p-3">
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

/** The DOCUMENTS behind one Chapter VI-A claim (PAY-26, migration 410).
 *
 *  `proof_reference` was the employee's own words about a proof — a policy
 *  number, a receipt number — and nothing held the receipt, so the verifier
 *  set an amount against a memory of a document. Both are kept: a claim
 *  evidenced on paper has a reference and no link, and showing an empty
 *  document list for it must not read as "nothing was produced".
 *
 *  THE URL IS NOT VALIDATED HERE AND MUST NOT BE. `domain/attachments` is the
 *  authority and refuses at the API door — the scheme vocabulary is closed to
 *  http/https because a stored `javascript:` or `data:` link is script
 *  execution in this app's own origin the moment somebody clicks the
 *  "receipt". A second, laxer rule in the browser is how that hole reopens.
 *
 *  `pending === undefined` means the CA has not touched this section's
 *  documents at all, which the save path sends as ABSENT — the server reads
 *  absent as unchanged and `[]` as remove. */
function ProofDocuments({ existing, reference, pending, onChange }: {
  existing: { name: string; url?: string; document_id?: string }[];
  reference: string;
  pending?: { name: string; url?: string; document_id?: string }[];
  onChange: (next: { name: string; url?: string; document_id?: string }[]) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const current = pending ?? existing;

  const add = () => {
    if (!name.trim() || !url.trim()) return;
    onChange([...current, { name: name.trim(), url: url.trim() }]);
    setName("");
    setUrl("");
  };

  return (
    <div className="pl-1 border-l-2 border-ps-muted ml-1 space-y-1">
      {reference && (
        <p className="text-[11px] text-ps-hint">
          Employee&apos;s reference: {reference}
        </p>
      )}
      {current.map((a, idx) => (
        <div key={`${a.name}-${idx}`} className="flex items-center gap-2 text-xs">
          {a.url
            ? <a href={a.url} target="_blank" rel="noopener noreferrer"
                 className="text-brand hover:underline">{a.name}</a>
            /* An uploaded document carries an id and NO url — the signed link
               is minted late, so there is nothing to render as a link here. */
            : <span className="text-ps-body">{a.name}</span>}
          <button type="button"
                  onClick={() => onChange(current.filter((_, i) => i !== idx))}
                  className="text-[11px] text-ps-hint hover:text-state-problem">remove</button>
        </div>
      ))}
      <div className="flex gap-2">
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder="Document name"
               aria-label="Proof document name"
               className="flex-1 border border-ps-border rounded-md px-2 py-1 text-xs" />
        <input value={url} onChange={(e) => setUrl(e.target.value)}
               placeholder="https://…"
               aria-label="Proof document link"
               className="flex-[2] border border-ps-border rounded-md px-2 py-1 text-xs" />
        <button type="button" onClick={add} disabled={!name.trim() || !url.trim()}
                className="text-xs px-2 py-1 border border-ps-border rounded-md disabled:opacity-40">
          Add
        </button>
      </div>
    </div>
  );
}

function ProofRow({ label, declared, value, onChange }: {
  label: string; declared: number; value: string; onChange: (v: string) => void;
}) {
  // An unreadable amount is not "over" — it is unreadable, and save() says so.
  const over = (rupeesToPaise(value) ?? 0) > declared;
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1">
        <p className="text-sm text-ps-body">{label}</p>
        <p className="text-xs text-ps-hint">declared {formatPaise(declared)}</p>
      </div>
      <div className="w-40">
        <input
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label={`${label} — amount proved`}
          className={`w-full border rounded-lg px-3 py-2 text-sm text-right tabular-nums ${
            over ? "border-[#DC2626] bg-state-problem-surface" : "border-ps-border"}`}
        />
        {over && <p className="text-[11px] text-state-problem mt-1">above what was declared</p>}
      </div>
    </div>
  );
}
