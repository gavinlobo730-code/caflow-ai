"use client";

/**
 * Supplier Master — TDS section mapping and credit terms.
 *
 * THIS SCREEN WROTE TO THE WRONG TABLE UNTIL 2026-09-13 (PUR-16).
 * It read and wrote `public.suppliers` (migration 030) straight over
 * PostgREST, while every purchase path in the product reads `public.vendors`:
 * bill creation, TDS withholding, the AP ageing, the Schedule III payables
 * note, GSTR-2B matching and s.43B(h). Two masters and no join between them.
 *
 * The credit limit was the harmless half — nothing anywhere reads one. The TDS
 * SECTION was not. A CA who picked 194J here against a professional firm wrote
 * `suppliers.tds_section`; the bill path read `vendors.tds_section`, found
 * NULL and withheld nothing. IT Act s.40(a)(ia) disallows the WHOLE
 * expenditure for an under-deduction, and s.201(1) makes the deductor liable
 * for the tax with s.201(1A) interest on top.
 *
 * It now goes through GET/POST/PATCH /api/vendors, so `rbac()` runs and what
 * is recorded here is what the bill reads. Migration 378 gave `vendors` the
 * one column it lacked (`credit_limit_paise`) and marked `public.suppliers`
 * retired in the database.
 *
 * TWO FIELDS ARE NAMED DIFFERENTLY on the master this now writes:
 *     supplier_name       -> name
 *     payment_terms_days  -> credit_days
 *
 * THE THIRD, `tds_rate_percent` -> `tds_rate_bps`, IS NOT WRITTEN AT ALL
 * (PUR-06 = TDS-13). Nothing in the withholding engine reads
 * `vendors.tds_rate_bps`: `services/vendor_tds.resolve_resident_tds` takes the
 * rate from the FY-versioned registry for the vendor's section, and a rate
 * BELOW it is a s.197 certificate, which s.197(1) requires the Assessing
 * Officer to issue for a specified amount and a specified period — four facts
 * a bare percentage on the vendor master expresses none of (the reasoning is
 * in `domain/tds/lower_deduction.py`, which names this screen). So the box
 * showed a CA a rate, stored it, and withheld at a different one. The client
 * Vendors form dropped it first; this was the second copy, and
 * `scripts/a-screen-does-not-set-a-vendors-tds-rate.test.ts` is there so there
 * is no third.
 *
 * IT Act sections 194C (Contractor), 194I (Rent), 194J (Professional), 194H
 * (Commission), 194A (Interest), 194B (Lottery) — deduct at source before
 * payment to the supplier. All monetary amounts are integer paise.
 */

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, X, Users, IndianRupee } from "lucide-react";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { Combobox } from "@/components/ui/combobox";
import { getClients } from "@/lib/data/clients";
import { api, type Vendor, type VendorWrite } from "@/lib/api";
import { listTdsSections, computeTdsAmount, type TDSSection, type TDSAmountResult } from "@/lib/data/tds";
import { arrayOrEmpty } from "@/lib/api/shape";
import { PossibleDuplicatesNotice, type PossibleDuplicate } from "@/components/parties/PossibleDuplicatesNotice";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ClientOption {
  id: string;
  client_name: string;
}

// Cosmetic section names only — no rates/thresholds here. Those are always
// resolved from GET /api/tds/sections (the authoritative TDSComputer table),
// never hardcoded, so a Finance Act rate/threshold change never has to be
// re-applied in two places.
const SECTION_LABELS: Record<string, string> = {
  "193": "Interest on Securities", "194": "Dividends", "194A": "Interest (other than securities)",
  "194B": "Lottery/Game Winnings", "194C": "Contractor", "194D": "Insurance Commission",
  "194G": "Lottery Commission", "194H": "Commission/Brokerage", "194I": "Rent",
  "194J": "Professional/Technical Fees", "194K": "Mutual Fund Income",
  "194LA": "Compensation on Land Acquisition", "194Q": "Purchase of Goods",
  // The clauses of s.194I and s.194J (TDS-22). Wording from the Income Tax
  // Department's own ITR-6 AY 2026-27 schema, which is what the backend
  // registry's clause keys are sourced from —
  // apps/api/domain/income_tax/schemas/ITR6_2026_Main_V1.0.json.
  //
  // The (a) limbs are charged at a LOWER rate the software does not hold, so
  // choosing one records the clause correctly on the 26Q row and still
  // withholds at the section's higher rate. The engine says so on the bill:
  // GET /api/tds/sections carries `rate_gap`, and the computed bill's `why`
  // relays the same sentence. Nothing here states a percentage.
  "194I(A)": "Rent — plant, machinery or equipment",
  "194I(B)": "Rent — land, building, furniture or fittings",
  "194J(A)": "Fees for technical services",
  "194J(B)": "Professional fees or royalty",
};
const NONE_OPTION = { value: "", label: "None (No TDS)" };
// NO "Other (manual rate)" OPTION, and removing the rate box is what made that
// visible rather than what caused it. Picking it sent `tds_applicable: true`
// with `tds_section: null`, and `resolve_resident_tds` opens with
//
//     if not tds_section: raise HTTPException(422, "Vendor is marked
//         TDS-applicable but has no TDS section set.")
//
// so EVERY bill from that vendor was refused — while the calculator beside the
// picker cheerfully showed the manual rate's arithmetic, which is what taught
// the CA the option worked. Every deduction is under a section; a rate that is
// not one is a s.197 certificate, recorded on the TDS compliance screen.

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtRs(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

/** Rupees as typed → integer paise, or null if the text is not an amount. */
function rsToP(rs: string): number | null {
  return paiseFromRupeeInput(rs || "0");
}

const BLANK_FORM = {
  name: "",
  gstin: "",
  pan: "",
  tds_section: "",
  credit_limit_rs: "",
  credit_days: "30",
  // "" is UNRECORDED, which is a real third state rather than a missing
  // answer — CGST Act s.31(3)(f) turns on it and the self-invoice path names
  // an unrecorded vendor as a gap rather than assuming either way.
  gst_registration_status: "",
  is_active: true,
};

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function SuppliersPage() {
  const [clients, setClients] = useState<ClientOption[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resemblances, setResemblances] = useState<PossibleDuplicate[]>([]);

  // TDS section list — thresholds/rates always come from the authoritative
  // TDSComputer via GET /api/tds/sections, never hardcoded here.
  const [tdsSections, setTdsSections] = useState<TDSSection[]>([]);

  // The three answers to "is this supplier registered" (PUR-19), served by
  // GET /api/rcm-documents/registration-states rather than spelled here.
  // `domain/gst/rcm_documents.py` owns the vocabulary because s.31(3)(f) turns
  // on it; there is deliberately no hardcoded fallback, since an unreachable
  // server leaving the box on "Not recorded" is the truth, where a guessed
  // pair could offer a value the server refuses.
  const [registrationStates, setRegistrationStates] = useState<string[]>([]);

  // TDS calculator
  const [billRs, setBillRs] = useState("");
  // null means "not an amount" — the TDS preview below simply shows nothing for
  // it rather than computing on a coerced zero, which would tell the CA no TDS
  // is deductible on a bill it could not read.
  const billPaise = rsToP(billRs) ?? 0;
  const [tdsCalc, setTdsCalc] = useState<TDSAmountResult | null>(null);
  const [tdsCalcError, setTdsCalcError] = useState<string | null>(null);

  useEffect(() => {
    getClients()
      .then((cs) => {
        const opts = cs.map((c) => ({ id: c.id, client_name: c.client_name }));
        setClients(opts);
        if (opts.length > 0) setSelectedClientId(opts[0].id);
      })
      .catch(() => setError("Failed to load clients"))
      .finally(() => setLoading(false));
  }, []);

  const loadVendors = useCallback(async () => {
    if (!selectedClientId) return;
    try {
      // include_inactive: a deactivated supplier has to stay visible, or the
      // Activate button below has nothing to act on.
      const res = await api.vendors.list(selectedClientId, true);
      if (!res.success) throw new Error(res.error ?? "Couldn't load suppliers.");
      setVendors(res.data ?? []);
      setError(null);
    } catch (e) {
      setVendors([]);
      setError(e instanceof Error ? e.message : "Couldn't load suppliers.");
    }
  }, [selectedClientId]);

  useEffect(() => { loadVendors(); }, [loadVendors]);

  useEffect(() => {
    listTdsSections().then(r => setTdsSections(arrayOrEmpty(r?.sections))).catch(() => setTdsSections([]));
  }, []);

  useEffect(() => {
    let alive = true;
    api.rcmDocuments.registrationStates()
      .then((res) => {
        if (alive && res.success && Array.isArray(res.data)) setRegistrationStates(res.data);
      })
      .catch(() => { /* leaves the field unset, which is the third state */ });
    return () => { alive = false; };
  }, []);

  // Recompute the calculator via the authoritative TDSComputer whenever the
  // bill amount, section, or supplier PAN changes — never re-derive rates
  // or the individual/company/§206AA rules locally.
  useEffect(() => {
    if (!(billPaise > 0) || !form.tds_section) {
      setTdsCalc(null);
      setTdsCalcError(null);
      return;
    }
    let cancelled = false;
    computeTdsAmount({ section: form.tds_section, payment_amount_paise: billPaise, pan: form.pan || null })
      .then(result => { if (!cancelled) { setTdsCalc(result); setTdsCalcError(null); } })
      .catch(err => { if (!cancelled) { setTdsCalc(null); setTdsCalcError(err instanceof Error ? err.message : "TDS calculation failed"); } });
    return () => { cancelled = true; };
  }, [billPaise, form.tds_section, form.pan]);

  function openAdd() {
    setEditingId(null);
    setForm(BLANK_FORM);
    setBillRs("");
    setError(null);
    setShowModal(true);
  }

  function openEdit(v: Vendor) {
    setEditingId(v.id);
    setForm({
      name: v.name,
      gstin: v.gstin ?? "",
      pan: v.pan ?? "",
      tds_section: v.tds_section ?? "",
      credit_limit_rs: v.credit_limit_paise ? String(v.credit_limit_paise / 100) : "",
      credit_days: v.credit_days !== null && v.credit_days !== undefined ? String(v.credit_days) : "",
      gst_registration_status: v.gst_registration_status ?? "",
      is_active: v.is_active,
    });
    setBillRs("");
    setError(null);
    setShowModal(true);
  }

  function onSectionChange(val: string) {
    setForm(f => ({ ...f, tds_section: val }));
  }

  // ONLY THE SECTIONS A VENDOR MAY ACTUALLY CARRY.
  //
  // This list came straight from the registry, so it offered §192 and §206C —
  // both of which `domain/tds/residency.deduction_section_refusal` rejects at
  // the save. §192's refusal at least existed; §206C's did not, so picking it
  // withheld 0.1% of every rupee of every bill from that vendor (the section
  // carries no threshold) and stamped the row 26Q, which is not where TCS is
  // reported. TCS is collected by a SELLER from a BUYER: on a bill you are
  // paying there is nothing to collect at all.
  //
  // The server decides it (`vendor_eligible`), not this file. `?? true` is the
  // fallback for the window where the frontend has redeployed ahead of the
  // backend — the same `??` rule the Schedule III captions follow.
  const sectionOptions = [
    NONE_OPTION,
    ...tdsSections
      .filter(s => s.vendor_eligible ?? true)
      .map(s => ({
        value: s.section,
        label: SECTION_LABELS[s.section] ? `${s.section} — ${SECTION_LABELS[s.section]}` : s.section,
      })),
  ];

  async function handleSave() {
    if (!selectedClientId) return;
    if (!form.name.trim()) { setError("Supplier name is required"); return; }

    const creditLimit = form.credit_limit_rs.trim() ? rsToP(form.credit_limit_rs) : null;
    if (form.credit_limit_rs.trim() && creditLimit === null) {
      setError("Credit limit must be an amount in rupees, e.g. 500000 or 500000.50 "
               + "— without commas.");
      return;
    }

    // Blank is a real answer — "no payment terms confirmed" is a different fact
    // from 0 ("Due on Receipt"), which is why migration 202 took the NOT NULL
    // DEFAULT 30 off the column.
    const creditDaysText = form.credit_days.trim();
    let creditDays: number | null = null;
    if (creditDaysText) {
      const n = Number(creditDaysText);
      if (!Number.isInteger(n) || n < 0) { setError("Payment terms must be a whole number of days."); return; }
      creditDays = n;
    }

    setSaving(true);
    setError(null);
    const body: VendorWrite = {
      name: form.name.trim(),
      gstin: form.gstin.trim() || null,
      pan: form.pan.trim() || null,
      // Section and applicability only. THE RATE IS THE ENGINE'S: it comes
      // from the FY-versioned registry for this section, so the two move
      // together when a Finance Act moves one — see this file's header.
      tds_applicable: !!form.tds_section,
      tds_section: form.tds_section || null,
      credit_limit_paise: creditLimit,
      credit_days: creditDays,
      // Omitted rather than sent as null when unrecorded: the server drops
      // nulls on a PATCH, so sending one would be inert and sending "" would
      // fail the CHECK. Leaving it out leaves the column as it is.
      gst_registration_status: form.gst_registration_status || undefined,
      is_active: form.is_active,
    };
    try {
      const res = editingId
        ? await api.vendors.update(editingId, body)
        : await api.vendors.create({ ...body, client_id: selectedClientId });
      if (!res.success) throw new Error(res.error ?? "Couldn't save the supplier.");
      if (!editingId && (res.data as { duplicate?: boolean })?.duplicate) {
        setError("A supplier with that GSTIN or PAN already exists for this client — "
                 + "the existing record was kept.");
      }
      // PUR-32. The supplier WAS created; this names what it resembles. Kept
      // out of setError deliberately — an error reads as "this did not save".
      setResemblances(
        (res.data as { possible_duplicates?: PossibleDuplicate[] })?.possible_duplicates ?? []);
      setShowModal(false);
      await loadVendors();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the supplier.");
    } finally {
      // In a finally: a rejected write used to leave Save disabled with no
      // message, so the CA could neither tell it had failed nor try again.
      setSaving(false);
    }
  }

  async function toggleActive(v: Vendor) {
    setBusyId(v.id);
    setError(null);
    try {
      const res = await api.vendors.update(v.id, { is_active: !v.is_active });
      if (!res.success) throw new Error(res.error ?? "Couldn't change the supplier's status.");
      await loadVendors();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't change the supplier's status.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-ps-hint hover:text-ps-label">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-ps-ink">Supplier Master</h1>
          <p className="text-sm text-ps-label mt-0.5">TDS section mapping &amp; credit terms</p>
        </div>
        <Button onClick={openAdd} size="sm" className="flex items-center gap-1" disabled={!selectedClientId}>
          <Plus className="w-4 h-4" /> Add Supplier
        </Button>
      </div>

      {error && <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>}
      {/* PUR-32 — outside the modal, because the modal has closed and the
          supplier is saved. Dismissed by the CA, never on a timer. */}
      <PossibleDuplicatesNotice duplicates={resemblances} noun="supplier"
        onDismiss={() => setResemblances([])} />

      {/* Client selector */}
      <Card>
        <CardContent className="pt-4 pb-4">
          <label className="text-xs font-medium text-ps-body block mb-1">Select Client</label>
          <div className="w-full max-w-xs">
            <ClientLookup
              clients={clients}
              value={selectedClientId}
              onChange={setSelectedClientId}
              ariaLabel="Client"
              placeholder="Select client…"
            />
          </div>
          <p className="text-xs text-ps-label mt-2">
            These are the same suppliers the client&apos;s Purchases → Vendors tab shows.
            A TDS section set here is the one every bill for this client withholds on.
          </p>
        </CardContent>
      </Card>

      {/* Suppliers table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Users className="w-4 h-4 text-blue-600" />
            Suppliers ({vendors.length})
          </CardTitle>
        </CardHeader>
        {loading ? (
          <TableSkeleton bare rows={5} cols={5} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-ps-bg text-xs text-ps-label uppercase tracking-wide">
                  <th className="px-4 py-3 text-left">Supplier Name</th>
                  <th className="px-4 py-3 text-left">GSTIN</th>
                  <th className="px-4 py-3 text-left">PAN</th>
                  <th className="px-4 py-3 text-left">TDS Section</th>
                  <th className="px-4 py-3 text-right">Credit Limit</th>
                  <th className="px-4 py-3 text-right">Payment Terms</th>
                  <th className="px-4 py-3 text-center">Status</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-bg">
                {vendors.map(v => (
                  <tr key={v.id} className="hover:bg-ps-bg">
                    <td className="px-4 py-3 font-medium text-ps-ink">{v.name}</td>
                    <td className="px-4 py-3 text-ps-label font-mono text-xs">{v.gstin ?? "—"}</td>
                    <td className="px-4 py-3 text-ps-label font-mono text-xs">{v.pan ?? "—"}</td>
                    <td className="px-4 py-3">
                      {v.tds_section ? (
                        <span className="bg-amber-100 text-amber-700 text-xs px-2 py-0.5 rounded-full font-medium">{v.tds_section}</span>
                      ) : (
                        <span className="text-ps-hint text-xs">No TDS</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-ps-body">{v.credit_limit_paise ? fmtRs(v.credit_limit_paise) : "—"}</td>
                    <td className="px-4 py-3 text-right text-ps-body">
                      {v.credit_days !== null && v.credit_days !== undefined ? `${v.credit_days} days` : "—"}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${v.is_active ? "bg-green-100 text-green-700" : "bg-ps-muted text-ps-label"}`}>
                        {v.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-4 py-3 flex gap-2 justify-end">
                      <button onClick={() => openEdit(v)} className="text-xs text-blue-600 hover:underline">Edit</button>
                      <button
                        onClick={() => toggleActive(v)}
                        disabled={busyId === v.id}
                        className="text-xs text-ps-hint hover:underline disabled:opacity-50"
                      >
                        {busyId === v.id ? "Saving…" : v.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
                {vendors.length === 0 && (
                  <tr><td colSpan={8} className="px-4 py-8 text-center text-ps-hint text-sm">No suppliers yet. Add your first supplier.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Add/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h2 className="text-sm font-semibold text-ps-ink">{editingId ? "Edit Supplier" : "Add Supplier"}</h2>
              <button onClick={() => setShowModal(false)}><X className="w-4 h-4 text-ps-hint" /></button>
            </div>
            <div className="px-5 py-4 space-y-4">
              {error && <div className="bg-red-50 text-red-700 text-xs px-3 py-2 rounded-lg">{error}</div>}

              <div>
                <label className="text-xs font-medium text-ps-body block mb-1">Supplier Name *</label>
                <input className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. ABC Contractors Pvt Ltd" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">GSTIN</label>
                  <input className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono" value={form.gstin} onChange={e => setForm(f => ({ ...f, gstin: e.target.value.toUpperCase() }))} placeholder="27AABCU9603R1ZM" maxLength={15} />
                </div>
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">PAN</label>
                  <input className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono" value={form.pan} onChange={e => setForm(f => ({ ...f, pan: e.target.value.toUpperCase() }))} placeholder="AAAAA0000A" maxLength={10} />
                </div>
              </div>

              {/* PUR-19. Not derived from whether a GSTIN is on file: a blank
                  GSTIN box means nobody typed one, which is not the same fact
                  as the supplier being unregistered — and CGST Act s.31(3)(f)
                  makes the RECIPIENT issue a self-invoice on exactly that
                  fact. Leaving it unrecorded is a real answer. */}
              <div>
                <label htmlFor="supplier-gst-registration" className="text-xs font-medium text-ps-body block mb-1">
                  GST registration
                </label>
                <select
                  id="supplier-gst-registration"
                  value={form.gst_registration_status}
                  onChange={e => setForm(f => ({ ...f, gst_registration_status: e.target.value }))}
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Not recorded</option>
                  {registrationStates.filter(o => o !== "unrecorded").map(o => (
                    <option key={o} value={o}>
                      {o === "registered" ? "Registered" : "Unregistered"}
                    </option>
                  ))}
                </select>
                <p className="text-2xs text-ps-hint mt-1 leading-tight">
                  A reverse-charge bill from an unregistered supplier needs a self-invoice
                  (CGST Act s.31(3)(f)). Left unrecorded, the self-invoice says so rather
                  than guessing.
                </p>
              </div>

              <div>
                <label className="text-xs font-medium text-ps-body block mb-1">TDS Section</label>
                <Combobox
                  options={sectionOptions}
                  value={sectionOptions.find(s => s.value === form.tds_section) ?? null}
                  onChange={(v) => { const s = v && !Array.isArray(v) ? v : null; onSectionChange(s ? s.value : ""); }}
                  getOptionId={(s) => s.value || "__none__"}
                  getLabel={(s) => s.label}
                  getSearchFields={(s) => [s.value, s.label]}
                  placeholder="Select section…"
                  searchPlaceholder="Search TDS section…"
                  ariaLabel="TDS section"
                />
              </div>

              {form.tds_section && (
                <p className="text-2xs text-ps-hint leading-tight">
                  The rate is the section&rsquo;s own, for the bill&rsquo;s financial year — it is not
                  recorded here. A lower rate under an Assessing Officer&rsquo;s s.197 certificate is
                  recorded against the certificate, on the client&rsquo;s TDS compliance screen.
                </p>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">Credit Limit (₹)</label>
                  <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={form.credit_limit_rs} onChange={e => setForm(f => ({ ...f, credit_limit_rs: e.target.value }))} placeholder="Leave blank for none" />
                  <p className="text-2xs text-ps-hint mt-1 leading-tight">Recorded only — no bill is blocked or flagged by it.</p>
                </div>
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">Payment Terms (days)</label>
                  <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={form.credit_days} onChange={e => setForm(f => ({ ...f, credit_days: e.target.value }))} placeholder="Leave blank if unconfirmed" />
                  <p className="text-2xs text-ps-hint mt-1 leading-tight">Blank and 0 differ: 0 is Due on Receipt.</p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <input type="checkbox" id="is_active" checked={form.is_active} onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))} className="rounded" />
                <label htmlFor="is_active" className="text-xs text-ps-body">Active supplier</label>
              </div>

              {/* TDS Calculator */}
              {form.tds_section && (
                <div className="bg-amber-50 rounded-lg p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <IndianRupee className="w-4 h-4 text-amber-600" />
                    <p className="text-xs font-semibold text-amber-800">Calculate TDS on Bill</p>
                  </div>
                  <p className="text-xs text-amber-700">IT Act Section {form.tds_section} — deduct at source before payment to supplier</p>
                  <div>
                    <label className="text-xs font-medium text-ps-body block mb-1">Bill Amount (₹)</label>
                    <input type="number" min="0" className="w-full border border-amber-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-white" value={billRs} onChange={e => setBillRs(e.target.value)} placeholder="0" />
                  </div>
                  {billPaise > 0 && tdsCalcError && (
                    <p className="text-xs text-red-600">{tdsCalcError}</p>
                  )}
                  {billPaise > 0 && tdsCalc && !tdsCalc.tds_applicable && (
                    <p className="text-xs text-ps-label">
                      Below the ₹{(tdsCalc.threshold_paise / 100).toLocaleString("en-IN")} threshold for Section {tdsCalc.section} — no TDS applicable.
                    </p>
                  )}
                  {billPaise > 0 && tdsCalc && tdsCalc.tds_applicable && (
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs text-ps-label">
                        <span>Bill Amount</span>
                        <span className="font-medium">{fmtRs(billPaise)}</span>
                      </div>
                      <div className="flex justify-between text-xs text-ps-label">
                        <span>TDS @ {tdsCalc.applicable_rate_pct}% (Section {tdsCalc.section}, FY {tdsCalc.fy})</span>
                        <span className="font-medium text-red-600">- {fmtRs(tdsCalc.tds_paise)}</span>
                      </div>
                      <div className="flex justify-between text-xs font-semibold text-ps-ink border-t border-amber-200 pt-1">
                        <span>Net Payment to Supplier</span>
                        <span className="text-green-700">{fmtRs(billPaise - tdsCalc.tds_paise)}</span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3 px-5 py-4 border-t">
              <Button variant="outline" size="sm" onClick={() => setShowModal(false)}>Cancel</Button>
              <Button size="sm" onClick={handleSave} disabled={saving}>{saving ? "Saving…" : "Save Supplier"}</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
