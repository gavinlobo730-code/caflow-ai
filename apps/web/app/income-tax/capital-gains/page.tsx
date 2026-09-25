"use client";

/**
 * Capital Gains Calculator & Register — IT Act 1961
 * Section 2(29B): Short-term capital gains
 * Section 2(29A): Long-term capital gains
 * Section 45: Chargeability of capital gains
 * Section 48: Mode of computation
 * Section 2(42A), proviso: a security LISTED in a recognised stock exchange in
 *   India is long-term after 12 months where everything else needs 24 (IT-28).
 *   The asset type cannot carry it, so it is its own tri-state field; blank is
 *   NOT RECORDED, takes the unlisted period — more tax, never less — and comes
 *   back as a named gap rather than a silent answer.
 * Section 55(2)(ac): the s.112A grandfathered cost (IT-19) — for a holding
 *   acquired before 01-02-2018 the cost is deemed to be the higher of the
 *   actual cost and the lower of the 31-01-2018 fair market value and the sale
 *   value. That fair market value is a fact about one scrip on one day and
 *   nothing here can derive it, so it is an INPUT and blank is refused and
 *   named. This page renders the working and computes none of it.
 * Section 54 / 54B / 54EC / 54F: reinvestment exemption (IT-19) — recorded
 *   per claim against a register entry and computed by
 *   domain/income_tax/reinvestment_exemption.py. This page renders the
 *   working and decides none of it: s.54F apportions on net consideration
 *   where s.54 takes the lower of two amounts, s.54EC's Rs 50 lakh spans two
 *   financial years, and s.54B is the one section a short-term gain reaches.
 * Finance (No. 2) Act 2024, for transfers made ON OR AFTER 23-07-2024: s.111A
 *   15% -> 20%; s.112A 10%/Rs 1,00,000 -> 12.5%/Rs 1,25,000; s.112 20%-with-
 *   indexation -> 12.5%-without. THE HOLDING PERIODS CHANGED TOO — s.2(42A)
 *   went to 12/24 months, and a non-property, non-listed asset needed 36
 *   months before that date. An earlier version of this header said "holding
 *   periods unchanged"; it was wrong, and the engine now forks on the date of
 *   transfer rather than applying one law to every year.
 * Finance Act 2023: Debt MF taxed as per slab (removed indexation benefit)
 *
 * R3.1b: all classification/indexation/tax-rate computation now happens on
 * the backend (domain/income_tax/capital_gains_engine.py) — this page only
 * collects input and displays results. See that module's docstring for the
 * verification status of the CII table and the asset-type tax treatment.
 */

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Calculator, Info, BookOpen, Plus, X, Trash2, ShieldCheck, AlertTriangle } from "lucide-react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import {
  computeCapitalGains, listCapitalGains, createCapitalGain, deleteCapitalGain, getCiiTable,
  type CapitalGainsAssetType, type CapitalGainsRegisterAssetType,
  type CapitalGainsAssesseeType,
  type CapitalGainsComputeResult, type CapitalGainsRecord,
  getCapitalGainExemption, getReinvestmentSections, addReinvestment, deleteReinvestment,
  type CapitalGainExemption, type ReinvestmentSectionInfo,
  type ReinvestmentSection, type AcquisitionKind, type TransferredAssetNature,
} from "@/lib/data/income-tax";
import { listingIsAsked, grandfatheringIsAsked } from "@/lib/income-tax/capitalGainsFacts";
import { Callout, GapList } from "@/components/ui/callout";
import { formatPaise } from "@/lib/money/format";

/** Anything the compute endpoint accepts. The calculator and the register
 *  have different vocabularies and the backend takes the union of both. */
type AnyCapitalGainsAssetType = CapitalGainsAssetType | CapitalGainsRegisterAssetType;

// Asset types with their holding period thresholds and tax treatment.
//
// `bonds` and `other` are the register's values and are offered here too
// (IT-28): a plain bond or debenture had nowhere to go on this form, so a CA
// computing one reached for "Debt MF / Bonds", which routes to s.50AA — the
// wrong section for a bond — and could never say the bond was LISTED, which
// is what decides whether twelve months or twenty-four apply to it.
const ASSET_TYPES_CALC: { value: AnyCapitalGainsAssetType; label: string }[] = [
  { value: "equity",     label: "Listed Equity / Equity MF" },
  { value: "debt_mf",    label: "Debt MF / Bonds (post Apr 2023)" },
  { value: "bonds",      label: "Bonds / Debentures" },
  { value: "property",   label: "Immovable Property" },
  { value: "unlisted",   label: "Unlisted Shares" },
  { value: "vda",        label: "Cryptocurrency / VDA" },
  { value: "gold",       label: "Gold / Jewellery" },
  { value: "other",      label: "Other Asset" },
];

/** A tri-state on the wire: "" is NOT RECORDED and is sent as null, which the
 *  engine reads as unlisted AND reports as a named gap. It is not a "no". */
function listedFromChoice(choice: string): boolean | null {
  if (choice === "listed") return true;
  if (choice === "unlisted") return false;
  return null;
}

// Asset types for register (matches DB constraint)
const ASSET_TYPES_REG: { value: CapitalGainsRegisterAssetType; label: string }[] = [
  { value: "equity_shares", label: "Equity Shares" },
  { value: "mutual_funds",  label: "Mutual Funds" },
  { value: "property",      label: "Immovable Property" },
  { value: "bonds",         label: "Bonds" },
  { value: "other",         label: "Other" },
];

// What was SOLD, in the vocabulary the s.54 family charges on (IT-19). The
// four VALUES come from the server (`getReinvestmentSections`); only the
// labels live here, because a label is prose and a value is a contract.
const NATURE_LABELS: Record<TransferredAssetNature, string> = {
  residential_house: "Residential house",
  agricultural_land: "Agricultural land",
  land_or_building: "Land or building (not a residence)",
  other: "Something else",
};

function getFYFromDate(dateStr: string): string {
  const d = new Date(dateStr);
  const y = d.getFullYear();
  const m = d.getMonth(); // 0=Jan
  if (m >= 3) return `${y}-${String(y + 1).slice(2)}`;
  return `${y - 1}-${String(y).slice(2)}`;
}

interface Client { id: string; client_name: string; }

const BLANK_CLAIM = {
  section: "54" as ReinvestmentSection,
  new_asset_description: "",
  acquisition_kind: "" as "" | AcquisitionKind,
  acquisition_date: "",
  cost_rs: "",
  cgas_rs: "",
  cgas_date: "",
  // "" is a THIRD state, not a zero: s.54F refuses a claim where how many
  // other houses the assessee owned is unrecorded, and a 0 would assert none.
  other_houses: "" as "" | string,
  agri_use: "" as "" | "yes" | "no",
};

const BLANK_REG = {
  asset_description: "",
  asset_type: "equity_shares" as CapitalGainsRegisterAssetType,
  assessee_type: "unspecified" as CapitalGainsAssesseeType,
  transferred_asset_nature: "" as "" | TransferredAssetNature,
  // Both "" are a THIRD state, exactly as `other_houses` above: the engine
  // reads them as NOT RECORDED, takes the answer that cannot under-tax, and
  // names the gap. Neither is a "no".
  listed: "" as "" | "listed" | "unlisted",
  fmv_31_01_2018_rs: "",
  purchase_date: "",
  sale_date: "",
  purchase_cost_rs: "",
  improvement_cost_rs: "",
  sale_value_rs: "",
};

function rsToP(rs: string): number {
  return paiseFromRupeeInput(rs || "0") ?? 0;
}

function fmtRs(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CapitalGainsPage() {
  const [activeTab, setActiveTab] = useState<"calculator" | "register">("calculator");

  // ── CII reference table (fetched once, display + FY dropdown only —
  // never used to compute anything client-side) ──
  const [ciiByFy, setCiiByFy] = useState<Record<string, number>>({});
  useEffect(() => {
    getCiiTable().then(({ ciiByFy }) => setCiiByFy(ciiByFy ?? {})).catch(() => {});
  }, []);
  const ciiYears = Object.keys(ciiByFy).sort();

  // ── Calculator state ──
  const [assetType, setAssetType] = useState<AnyCapitalGainsAssetType>("equity");
  // WHO the assessee is. The fifth proviso to s.112(1) gives a resident
  // individual or HUF the lower of 12.5% without indexation and 20% with it on
  // immovable property acquired before 23-07-2024; a company, an LLP or a
  // non-resident never gets it. Defaults to "unspecified", which charges the
  // flat 12.5% and says in the result why the option was withheld — an
  // unanswered question, not a claim nobody was entitled to make.
  const [assesseeType, setAssesseeType] = useState<CapitalGainsAssesseeType>("unspecified");
  const [purchaseDate, setPurchaseDate] = useState("");
  const [purchaseRupees, setPurchaseRupees] = useState("");
  const [saleDate, setSaleDate] = useState("");
  const [saleRupees, setSaleRupees] = useState("");
  const [improvementRupees, setImprovementRupees] = useState("");
  // IT-28 and IT-19. Two facts nothing in this product can derive. "" is NOT
  // RECORDED in both cases and is sent as null, so the engine answers the way
  // that cannot under-tax and says on the result which fact it was missing.
  const [listedChoice, setListedChoice] = useState<"" | "listed" | "unlisted">("");
  const [fmv2018Rupees, setFmv2018Rupees] = useState("");
  const fmv2018Paise = fmv2018Rupees.trim()
    ? paiseFromRupeeInput(fmv2018Rupees)
    : null;
  const askListing = listingIsAsked(assetType);
  const askGrandfathering = grandfatheringIsAsked(assetType, purchaseDate);

  // A capital gain is sale less cost: read either as ₹1 and the gain is the
  // other one in full, taxed at whatever rate the holding period implies.
  const purchasePaise = paiseFromRupeeInput(purchaseRupees || "0");
  const salePaise = paiseFromRupeeInput(saleRupees || "0");
  const improvementPaise = paiseFromRupeeInput(improvementRupees || "0");
  const amountsUnreadable =
    purchasePaise === null || salePaise === null || improvementPaise === null
    // A fair market value that is not an amount must not read as "not
    // recorded": those are opposite states and only one of them is honest.
    || (fmv2018Rupees.trim() !== "" && fmv2018Paise === null);
  const purchaseFY = purchaseDate ? getFYFromDate(purchaseDate) : "";
  const saleFY = saleDate ? getFYFromDate(saleDate) : "";

  const [result, setResult] = useState<CapitalGainsComputeResult | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [computing, setComputing] = useState(false);

  // Server-side compute, debounced 400ms (matches the deductions page's
  // pattern) so every keystroke doesn't fire a request.
  useEffect(() => {
    if (amountsUnreadable) {
      // Not silently nothing: a field that is not an amount has to say so,
      // or the result panel just stays blank and the CA re-types the dates.
      setResult(null);
      setComputeError("Purchase, sale, improvement and 31-01-2018 fair market "
                      + "value must be amounts in rupees, e.g. 2500000 — "
                      + "without commas.");
      return;
    }
    if (!purchaseDate || !saleDate || purchasePaise <= 0 || salePaise <= 0) {
      setResult(null);
      setComputeError(null);
      return;
    }
    const timer = setTimeout(() => {
      setComputing(true);
      computeCapitalGains({
        asset_type: assetType,
        purchase_date: purchaseDate,
        sale_date: saleDate,
        purchase_cost_paise: purchasePaise as number,
        sale_value_paise: salePaise as number,
        improvement_cost_paise: improvementPaise as number,
        assessee_type: assesseeType,
        // Sent even where this form would not render the control, so the
        // SERVER decides whether either fact reaches the computation. A value
        // it does not use comes back named in `caveats` rather than silently
        // discarded.
        is_listed_security: listedFromChoice(listedChoice),
        fmv_31_01_2018_paise: fmv2018Paise,
      })
        .then(r => { setResult(r); setComputeError(null); })
        .catch(e => { setResult(null); setComputeError(e instanceof Error ? e.message : "Failed to compute"); })
        .finally(() => setComputing(false));
    }, 400);
    return () => clearTimeout(timer);
  }, [assetType, assesseeType, purchaseDate, saleDate, purchasePaise, salePaise,
      improvementPaise, amountsUnreadable, listedChoice, fmv2018Paise]);

  const showIndexation = assetType === "property" && result?.is_long_term && result?.tax_with_indexation_percent != null;
  const showCII = assetType === "property";

  // ── Register state ──
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [records, setRecords] = useState<CapitalGainsRecord[]>([]);
  const [regLoading, setRegLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [regForm, setRegForm] = useState(BLANK_REG);
  const [saving, setSaving] = useState(false);
  const [regError, setRegError] = useState<string | null>(null);
  const [clientsError, setClientsError] = useState<string | null>(null);
  const [regLoadError, setRegLoadError] = useState<string | null>(null);

  const loadClients = useCallback(() => {
    api.clients.list().then(res => {
      const cl = res.data?.clients ?? [];
      setClients(cl);
      if (cl.length > 0) setSelectedClientId(cl[0].id);
      setClientsError(null);
    }).catch((e) => {
      setClientsError(e instanceof Error ? e.message : "Couldn't load clients.");
    });
  }, []);

  useEffect(() => { loadClients(); }, [loadClients]);

  const loadRecords = useCallback(async () => {
    if (!selectedClientId) return;
    setRegLoading(true);
    try {
      const data = await listCapitalGains(selectedClientId);
      setRecords(data);
      setRegLoadError(null);
    } catch (e) {
      setRecords([]);
      setRegLoadError(e instanceof Error ? e.message : "Couldn't load the capital gains register.");
    } finally {
      setRegLoading(false);
    }
  }, [selectedClientId]);

  useEffect(() => {
    if (activeTab === "register" && selectedClientId) loadRecords();
  }, [activeTab, selectedClientId, loadRecords]);

  // Live preview for the "Add Transaction" modal — same debounced
  // server-side compute as the calculator tab, not a client-side re-implementation.
  // ── s.54 family (IT-19). Everything below is READ; nothing is computed
  // here. Which section reaches a transfer, whether a claim is in time, and
  // how much it exempts are all the server's answers.
  const [natures, setNatures] = useState<TransferredAssetNature[]>([]);
  const [sectionInfo, setSectionInfo] = useState<ReinvestmentSectionInfo[]>([]);
  const [exemptFor, setExemptFor] = useState<CapitalGainsRecord | null>(null);
  const [exemption, setExemption] = useState<CapitalGainExemption | null>(null);
  const [exemptBusy, setExemptBusy] = useState(false);
  const [exemptError, setExemptError] = useState("");
  const [claimForm, setClaimForm] = useState({ ...BLANK_CLAIM });

  useEffect(() => {
    getReinvestmentSections()
      .then(d => { setNatures(d.asset_natures); setSectionInfo(d.sections); })
      .catch(() => { /* the labels above stand in until the server answers */ });
  }, []);

  const loadExemption = useCallback(async (recordId: string) => {
    setExemptBusy(true);
    try {
      setExemption(await getCapitalGainExemption(recordId));
      setExemptError("");
    } catch (e) {
      setExemption(null);
      setExemptError(e instanceof Error ? e.message : "Couldn't load the exemption working.");
    } finally {
      setExemptBusy(false);
    }
  }, []);

  async function openExemption(r: CapitalGainsRecord) {
    setExemptFor(r);
    setClaimForm({ ...BLANK_CLAIM });
    setExemptError("");
    await loadExemption(r.id);
  }

  async function saveClaim() {
    if (!exemptFor || !claimForm.new_asset_description.trim()) {
      setExemptError("Describe what was bought.");
      return;
    }
    setExemptBusy(true);
    try {
      await addReinvestment(exemptFor.id, {
        section: claimForm.section,
        new_asset_description: claimForm.new_asset_description.trim(),
        acquisition_kind: claimForm.acquisition_kind || null,
        acquisition_date: claimForm.acquisition_date || null,
        cost_paise: rsToP(claimForm.cost_rs),
        cgas_deposit_paise: rsToP(claimForm.cgas_rs),
        cgas_deposit_date: claimForm.cgas_date || null,
        other_residential_houses_owned:
          claimForm.other_houses === "" ? null : Number(claimForm.other_houses),
        agricultural_use_two_years:
          claimForm.agri_use === "" ? null : claimForm.agri_use === "yes",
      });
      setClaimForm({ ...BLANK_CLAIM });
      await loadExemption(exemptFor.id);
    } catch (e) {
      setExemptError(e instanceof Error ? e.message : "Couldn't record the claim.");
    } finally {
      setExemptBusy(false);
    }
  }

  async function removeClaim(claimId: string) {
    if (!exemptFor) return;
    setExemptBusy(true);
    try {
      await deleteReinvestment(exemptFor.id, claimId);
      await loadExemption(exemptFor.id);
    } catch (e) {
      setExemptError(e instanceof Error ? e.message : "Couldn't delete the claim.");
    } finally {
      setExemptBusy(false);
    }
  }

  const [regPreview, setRegPreview] = useState<CapitalGainsComputeResult | null>(null);
  useEffect(() => {
    if (!showModal || !regForm.purchase_date || !regForm.sale_date || !regForm.purchase_cost_rs || !regForm.sale_value_rs) {
      setRegPreview(null);
      return;
    }
    const timer = setTimeout(() => {
      computeCapitalGains({
        asset_type: regForm.asset_type,
        assessee_type: regForm.assessee_type,
        purchase_date: regForm.purchase_date,
        sale_date: regForm.sale_date,
        purchase_cost_paise: rsToP(regForm.purchase_cost_rs),
        sale_value_paise: rsToP(regForm.sale_value_rs),
        improvement_cost_paise: rsToP(regForm.improvement_cost_rs),
        // The preview must be computed on exactly what will be SAVED, or the
        // classification the CA approves is not the one persisted.
        is_listed_security: listedFromChoice(regForm.listed),
        fmv_31_01_2018_paise: regForm.fmv_31_01_2018_rs.trim()
          ? paiseFromRupeeInput(regForm.fmv_31_01_2018_rs)
          : null,
      }).then(setRegPreview).catch(() => setRegPreview(null));
    }, 400);
    return () => clearTimeout(timer);
  }, [showModal, regForm.asset_type, regForm.purchase_date, regForm.sale_date,
      regForm.assessee_type, regForm.purchase_cost_rs, regForm.sale_value_rs,
      regForm.improvement_cost_rs, regForm.listed, regForm.fmv_31_01_2018_rs]);

  async function handleSaveRecord() {
    if (!selectedClientId) return;
    if (!regForm.asset_description.trim() || !regForm.purchase_date || !regForm.sale_date) {
      setRegError("Asset description, purchase date, and sale date are required");
      return;
    }
    setSaving(true);
    setRegError(null);
    try {
      await createCapitalGain({
        client_id: selectedClientId,
        asset_description: regForm.asset_description.trim(),
        asset_type: regForm.asset_type,
        assessee_type: regForm.assessee_type,
        // Unstated goes as null. Defaulting to any of the four would decide
        // which section reaches this transfer by omission.
        transferred_asset_nature: regForm.transferred_asset_nature || null,
        // Same rule, two more facts (IT-28, IT-19). "" goes as null, which the
        // register stores as NOT RECORDED and the engine reports as a gap —
        // never as a "no".
        is_listed_security: listedFromChoice(regForm.listed),
        fmv_31_01_2018_paise: regForm.fmv_31_01_2018_rs.trim()
          ? paiseFromRupeeInput(regForm.fmv_31_01_2018_rs)
          : null,
        purchase_date: regForm.purchase_date,
        sale_date: regForm.sale_date,
        purchase_cost_paise: rsToP(regForm.purchase_cost_rs),
        improvement_cost_paise: rsToP(regForm.improvement_cost_rs),
        sale_value_paise: rsToP(regForm.sale_value_rs),
      });
      setShowModal(false);
      setRegForm(BLANK_REG);
      await loadRecords();
    } catch (e) {
      setRegError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteRecord(id: string) {
    if (!confirm("Delete this record?")) return;
    try {
      await deleteCapitalGain(id);
      await loadRecords();
    } catch (e) {
      setRegLoadError(e instanceof Error ? e.message : "Failed to delete the record.");
    }
  }

  return (
    <div className="p-6 max-w-ps-data mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/income-tax" className="text-ps-hint hover:text-ps-label">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Capital Gains</h1>
          <p className="text-sm text-ps-label mt-0.5">IT Act Section 45 — Capital Gains Tax (Budget 2024 rates)</p>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="flex border-b border-ps-border">
        <button
          onClick={() => setActiveTab("calculator")}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === "calculator" ? "border-brand text-brand" : "border-transparent text-ps-label hover:text-ps-body"}`}
        >
          <Calculator className="w-4 h-4" /> Calculator
        </button>
        <button
          onClick={() => setActiveTab("register")}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === "register" ? "border-brand text-brand" : "border-transparent text-ps-label hover:text-ps-body"}`}
        >
          <BookOpen className="w-4 h-4" /> Register
        </button>
      </div>

      {/* ── Calculator Tab ── */}
      {activeTab === "calculator" && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Input Form */}
            <div className="bg-white rounded-xl border border-ps-border p-5 space-y-4">
              <div className="flex items-center gap-2 mb-2">
                <Calculator className="w-4 h-4 text-brand" />
                <h2 className="text-sm font-semibold text-ps-ink">Asset Details</h2>
              </div>

              <div>
                <label className="text-xs font-medium text-ps-body block mb-1">Asset Type</label>
                <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={assetType} onChange={e => setAssetType(e.target.value as AnyCapitalGainsAssetType)}>
                  {ASSET_TYPES_CALC.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                </select>
              </div>

              {/* IT-28. The proviso to s.2(42A) gives a LISTED security (other
                  than a unit) twelve months where an unlisted asset needs
                  twenty-four, and the asset type cannot carry it — a debenture
                  is the same kind of asset either way. "Not recorded" is a
                  real third answer: the engine then takes the unlisted period,
                  which over-states the tax rather than under-stating it, and
                  says so on the result. */}
              {askListing && (
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">Listed on a recognised stock exchange in India?</label>
                  <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
                          aria-label="Listed security"
                          value={listedChoice} onChange={e => setListedChoice(e.target.value as "" | "listed" | "unlisted")}>
                    <option value="">Not recorded</option>
                    <option value="listed">Listed</option>
                    <option value="unlisted">Not listed</option>
                  </select>
                  <p className="text-2xs text-ps-label mt-1">
                    Section 2(42A), proviso: a security listed in a recognised stock exchange
                    in India is long-term after 12 months; anything else needs 24.
                  </p>
                </div>
              )}

              {/* IT-19. s.55(2)(ac) — the grandfathered cost. Shown only where
                  the section reaches the transfer at all: a s.112A asset
                  acquired before 01-02-2018. */}
              {askGrandfathering && (
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">Fair market value on 31 Jan 2018 (₹) — the whole holding</label>
                  <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
                         aria-label="Fair market value on 31 January 2018"
                         value={fmv2018Rupees} onChange={e => setFmv2018Rupees(e.target.value)} placeholder="Not recorded" />
                  <p className="text-2xs text-ps-label mt-1">
                    Section 55(2)(ac): acquired before 1 February 2018, so the cost is deemed to
                    be the higher of the actual cost and the lower of this and the sale value.
                    Enter the value of the WHOLE holding sold, not a per-share price. Left
                    blank, the actual cost stands and the gain is over-stated by the whole of
                    the appreciation up to 31 January 2018.
                  </p>
                </div>
              )}

              {/* The fifth proviso to s.112(1) — who the assessee is decides
                  whether the grandfathered 20%-with-indexation option is even
                  available on immovable property acquired before 23-07-2024.
                  Left unspecified, the engine charges the flat 12.5% and says
                  in its note why it withheld the option, rather than claiming
                  a benefit nobody established a right to. */}
              <div>
                <label className="text-xs font-medium text-ps-body block mb-1">Assessee</label>
                <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
                        aria-label="Assessee type"
                        value={assesseeType} onChange={e => setAssesseeType(e.target.value as CapitalGainsAssesseeType)}>
                  <option value="unspecified">Not stated</option>
                  <option value="resident_individual_huf">Resident individual or HUF</option>
                  <option value="other">Company, LLP, firm or non-resident</option>
                </select>
                <p className="text-2xs text-ps-label mt-1">
                  Section 112(1), fifth proviso: only a resident individual or HUF may pay the
                  lower of 12.5% without indexation and 20% with it, and only on immovable
                  property acquired before 23 July 2024.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">Purchase Date</label>
                  <input type="date" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={purchaseDate} onChange={e => setPurchaseDate(e.target.value)} />
                </div>
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">Sale Date</label>
                  <input type="date" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={saleDate} onChange={e => setSaleDate(e.target.value)} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">Purchase Price (₹)</label>
                  <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={purchaseRupees} onChange={e => setPurchaseRupees(e.target.value)} placeholder="0.00" />
                </div>
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">Sale Price (₹)</label>
                  <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={saleRupees} onChange={e => setSaleRupees(e.target.value)} placeholder="0.00" />
                </div>
              </div>

              {(assetType === "property" || assetType === "gold") && (
                <div>
                  <label className="text-xs font-medium text-ps-body block mb-1">Improvement Costs (₹) — optional</label>
                  <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={improvementRupees} onChange={e => setImprovementRupees(e.target.value)} placeholder="0.00" />
                </div>
              )}

              {showCII && purchaseFY && saleFY && (
                <div className="bg-ps-bg rounded-lg px-3 py-2">
                  <p className="text-3xs text-ps-hint">
                    Purchase FY: {purchaseFY} (CII: {ciiByFy[purchaseFY] ?? "—"}) · Sale FY: {saleFY} (CII: {ciiByFy[saleFY] ?? "—"})
                  </p>
                </div>
              )}
            </div>

            {/* Result Panel */}
            <div className="space-y-4">
              {computeError && <Callout tone="problem">{computeError}</Callout>}
              {!result ? (
                <div className="bg-white rounded-xl border border-ps-border p-5 flex items-center justify-center h-full min-h-[200px]">
                  <div className="text-center">
                    <Calculator className="w-8 h-8 text-ps-disabled mx-auto mb-2" />
                    <p className="text-sm text-ps-hint">
                      {computing ? "Computing…" : "Enter asset details to compute capital gains"}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="bg-white rounded-xl border border-ps-border p-4">
                    <h3 className="text-xs font-semibold text-ps-label uppercase tracking-wide mb-3">Classification</h3>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-xs text-ps-hint">Holding Period</p>
                        <p className="text-sm font-semibold text-ps-ink">{result.holding_months} months</p>
                      </div>
                      <div>
                        <p className="text-xs text-ps-hint">Classification</p>
                        <span className={`inline-flex text-xs font-semibold px-2 py-0.5 rounded-full ${result.is_long_term ? "bg-state-ready-surface text-state-ready" : "bg-state-attention-surface text-state-attention"}`}>
                          {result.is_long_term ? "Long Term" : "Short Term"} Capital Gain
                        </span>
                      </div>
                      <div>
                        <p className="text-xs text-ps-hint">Capital Gain</p>
                        <p className={`text-sm font-semibold ${result.gain_paise >= 0 ? "text-state-ready" : "text-state-problem"}`}>
                          {result.gain_paise >= 0 ? "+" : ""}{formatPaise(result.gain_paise)}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-ps-hint">Applicable Rate</p>
                        <p className="text-sm font-semibold text-ps-ink">{result.tax_rate_percent}%</p>
                      </div>
                    </div>
                  </div>

                  <div className="bg-white rounded-xl border border-ps-border p-4">
                    <h3 className="text-xs font-semibold text-ps-label uppercase tracking-wide mb-3">Tax Computation</h3>
                    <div className="space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-ps-label">Sale Price</span>
                        <span className="font-medium">{formatPaise(salePaise ?? 0)}</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-ps-label">Cost of Acquisition</span>
                        <span className="font-medium">{formatPaise(purchasePaise ?? 0)}</span>
                      </div>
                      {/* IT-19. Where s.55(2)(ac) substituted the cost, the gain
                          below is measured against the DEEMED figure, so the
                          working has to show it or the panel does not add up. */}
                      {result.grandfathered_cost_is_applied && (
                        <div className="flex justify-between text-sm">
                          <span className="text-ps-label">Deemed cost — s.55(2)(ac)</span>
                          <span className="font-medium">{formatPaise(result.cost_of_acquisition_paise ?? 0)}</span>
                        </div>
                      )}
                      {(improvementPaise ?? 0) > 0 && (
                        <div className="flex justify-between text-sm">
                          <span className="text-ps-label">Improvement Cost</span>
                          <span className="font-medium">{formatPaise(improvementPaise ?? 0)}</span>
                        </div>
                      )}
                      <div className="border-t border-ps-border pt-2 flex justify-between text-sm font-semibold">
                        <span className="text-ps-ink">Capital Gain</span>
                        <span className={result.gain_paise >= 0 ? "text-state-ready" : "text-state-problem"}>
                          {formatPaise(result.gain_paise)}
                        </span>
                      </div>

                      {showIndexation && (
                        <div className="mt-3 border-t border-dashed border-ps-border pt-3">
                          <p className="text-xs font-medium text-ps-label mb-2">With Indexation ({result.tax_with_indexation_percent}%)</p>
                          <div className="flex justify-between text-sm">
                            <span className="text-ps-label">Indexed Cost (CII {ciiByFy[purchaseFY] ?? "—"} → {ciiByFy[saleFY] ?? "—"})</span>
                            <span>{formatPaise(result.indexed_cost_paise)}</span>
                          </div>
                          <div className="flex justify-between text-sm font-semibold mt-1">
                            <span className="text-ps-ink">Gain (indexed)</span>
                            <span className={result.gain_with_indexation_paise >= 0 ? "text-state-ready" : "text-state-problem"}>
                              {formatPaise(result.gain_with_indexation_paise)}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="bg-brand-surface rounded-xl border border-brand-light p-4">
                    <h3 className="text-xs font-semibold text-brand uppercase tracking-wide mb-3">Estimated Tax Liability</h3>
                    {showIndexation ? (
                      <div className="space-y-2">
                        <div className="flex justify-between text-sm">
                          <span className="text-ps-label">Tax without indexation ({result.tax_rate_percent}%)</span>
                          <span className="font-medium">{fmtRs(result.tax_without_indexation_paise)}</span>
                        </div>
                        <div className="flex justify-between text-sm">
                          <span className="text-ps-label">Tax with indexation ({result.tax_with_indexation_percent}%)</span>
                          <span className="font-medium">{fmtRs(result.tax_with_indexation_paise ?? 0)}</span>
                        </div>
                        <div className="border-t border-brand-light pt-2 flex justify-between">
                          <span className="text-sm font-semibold text-ps-ink">Recommended (lower)</span>
                          <span className="text-lg font-bold text-brand">{fmtRs(result.tax_liability_paise)}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-ps-label">Tax @ {result.tax_rate_percent}%</span>
                        <span className="text-2xl font-bold text-brand">{fmtRs(result.tax_liability_paise)}</span>
                      </div>
                    )}
                  </div>

                  {/* IT-19 / IT-28. `gaps` and `caveats` are NOT the same
                      thing and are rendered differently on purpose: a gap is a
                      fact nobody recorded and the CA has to go and find, a
                      caveat is a settled reason a section does not reach this
                      transfer. Collapsing them would turn "go and get this"
                      into "nothing to do here". */}
                  {(result.gaps?.length ?? 0) > 0 && (
                    <div className="bg-state-attention-surface rounded-lg border border-state-attention-border p-3 flex gap-2">
                      <AlertTriangle className="w-4 h-4 text-state-attention shrink-0 mt-0.5" />
                      <div>
                        <p className="text-xs font-semibold text-state-attention">Not recorded — this changes the figure above</p>
                        <ul className="mt-1 space-y-1">
                          {result.gaps!.map((g, i) => (
                            <li key={i} className="text-xs text-state-attention">{g}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  )}
                  {(result.caveats?.length ?? 0) > 0 && (
                    <div className="bg-ps-bg rounded-lg border border-ps-border p-3">
                      <ul className="space-y-1">
                        {result.caveats!.map((c, i) => (
                          <li key={i} className="text-xs text-ps-label">{c}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {(result.grandfathering_working?.length ?? 0) > 0 && (
                    <div className="bg-ps-bg rounded-lg border border-ps-border p-3">
                      <p className="text-xs font-semibold text-ps-label uppercase tracking-wide mb-1">Section 55(2)(ac) working</p>
                      <ul className="space-y-1">
                        {result.grandfathering_working!.map((w, i) => (
                          <li key={i} className="text-xs text-ps-label">{w}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="bg-state-attention-surface rounded-lg p-3 flex gap-2">
                    <Info className="w-4 h-4 text-state-attention shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs text-state-attention font-medium">{result.section_ref}</p>
                      <p className="text-xs text-state-attention mt-0.5">{result.note}</p>
                      <p className="text-3xs text-state-attention mt-1">
                        {result.is_slab_rate_estimate
                          ? "This rate is an ESTIMATE at the highest slab — your actual liability depends on your own income slab. "
                          : ""}
                        This is an estimate. Add to ITR filing and consult CA for final computation. Surcharge and cess apply.
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* CII Table */}
          <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
            <div className="px-5 py-4 border-b border-ps-border">
              <h2 className="text-sm font-semibold text-ps-ink">Cost Inflation Index (CII) Table</h2>
              <p className="text-xs text-ps-hint mt-0.5">IT Act Section 48 — Base year FY 2001-02 = 100</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <tbody>
                  <tr>
                    {ciiYears.map(y => (
                      <td key={y} className={`px-3 py-2 text-center border-r border-ps-border ${purchaseFY === y || saleFY === y ? "bg-brand-surface" : ""}`}>
                        <p className="text-3xs text-ps-hint">FY {y}</p>
                        <p className="text-xs font-semibold text-ps-ink">{ciiByFy[y]}</p>
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── Register Tab ── */}
      {activeTab === "register" && (
        <div className="space-y-4">
          {/* Client selector + Add button */}
          <div className="flex items-end gap-4 flex-wrap">
            <div>
              <label className="text-xs font-medium text-ps-body block mb-1">Client</label>
              <div className="min-w-[200px]">
                <ClientLookup
                  clients={clients}
                  value={selectedClientId}
                  onChange={setSelectedClientId}
                  ariaLabel="Client"
                  placeholder="Select client…"
                />
              </div>
              {clientsError && (
                <p className="text-2xs text-state-problem mt-1">
                  {clientsError}{" "}
                  <button onClick={loadClients} className="underline hover:no-underline">Retry</button>
                </p>
              )}
            </div>
            <Button size="sm" onClick={() => { setRegForm(BLANK_REG); setRegError(null); setShowModal(true); }} className="flex items-center gap-1">
              <Plus className="w-4 h-4" /> Add Transaction
            </Button>
          </div>

          {/* Records table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-brand" />
                Capital Gains Register ({records.length})
              </CardTitle>
            </CardHeader>
            {regLoadError && (
              <div className="px-4 pb-3">
                <div className="bg-state-problem-surface text-state-problem text-xs px-3 py-2 rounded-lg flex items-center justify-between gap-3">
                  <span>{regLoadError}</span>
                  <button onClick={loadRecords} className="underline hover:no-underline shrink-0">Retry</button>
                </div>
              </div>
            )}
            {regLoading ? (
              <TableSkeleton cols={11} bare />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-ps-bg text-xs text-ps-label uppercase tracking-wide">
                      <th className="px-4 py-3 text-left">Asset</th>
                      <th className="px-4 py-3 text-left">Type</th>
                      <th className="px-4 py-3 text-left">Purchase</th>
                      <th className="px-4 py-3 text-left">Sale</th>
                      <th className="px-4 py-3 text-right">Cost</th>
                      <th className="px-4 py-3 text-right">Sale Value</th>
                      <th className="px-4 py-3 text-right">Indexed Cost</th>
                      <th className="px-4 py-3 text-center">Gain Type</th>
                      <th className="px-4 py-3 text-right">Tax Rate</th>
                      <th className="px-4 py-3 text-center">s.54</th>
                      <th className="px-4 py-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ps-border">
                    {records.map(r => {
                      const gain = r.sale_value_paise - r.purchase_cost_paise - r.improvement_cost_paise;
                      return (
                        <tr key={r.id} className="hover:bg-ps-bg">
                          <td className="px-4 py-3 font-medium text-ps-ink max-w-[160px] truncate">{r.asset_description}</td>
                          <td className="px-4 py-3 text-ps-label text-xs">{ASSET_TYPES_REG.find(a => a.value === r.asset_type)?.label ?? r.asset_type}</td>
                          <td className="px-4 py-3 text-ps-label">{r.purchase_date}</td>
                          <td className="px-4 py-3 text-ps-label">{r.sale_date}</td>
                          <td className="px-4 py-3 text-right text-ps-body">{fmtRs(r.purchase_cost_paise)}</td>
                          <td className="px-4 py-3 text-right text-ps-body">{fmtRs(r.sale_value_paise)}</td>
                          <td className="px-4 py-3 text-right text-ps-label text-xs">{r.indexed_cost_paise != null ? fmtRs(r.indexed_cost_paise) : "—"}</td>
                          <td className="px-4 py-3 text-center">
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${r.gain_type === "LTCG" ? "bg-state-ready-surface text-state-ready" : "bg-state-attention-surface text-state-attention"}`}>
                              {r.gain_type ?? "—"}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-ps-body">{r.tax_rate_percent != null ? `${r.tax_rate_percent}%` : "—"}</td>
                          <td className="px-4 py-3 text-center">
                            <button onClick={() => openExemption(r)}
                                    className="text-xs px-2 py-1 rounded-lg border border-state-ready-border text-state-ready hover:bg-state-ready-surface transition-colors whitespace-nowrap">
                              Exemption
                            </button>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <div className="flex flex-col items-end gap-1">
                              <span className={`text-xs font-semibold ${gain >= 0 ? "text-state-ready" : "text-state-problem"}`}>{gain >= 0 ? "+" : ""}{fmtRs(gain)}</span>
                              <button onClick={() => handleDeleteRecord(r.id)} className="text-ps-disabled hover:text-state-problem transition-colors">
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                    {records.length === 0 && (
                      <tr><td colSpan={11} className="px-4 py-8 text-center text-ps-hint text-sm">No capital gains transactions recorded yet.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* ── s.54 family exemption (IT-19) ──────────────────────────────
              Everything shown is the server's working. This panel formats it
              and decides nothing: which section reaches the transfer, whether
              a claim is in time, s.54F's proportion and s.54EC's cap are all
              domain/income_tax/reinvestment_exemption.py's answers. */}
          {exemptFor && (
            <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
              <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
                <div className="flex items-center justify-between px-5 py-4 border-b sticky top-0 bg-white">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-state-ready" />
                    <h2 className="text-sm font-semibold text-ps-ink">
                      Reinvestment exemption — {exemptFor.asset_description}
                    </h2>
                  </div>
                  <button onClick={() => { setExemptFor(null); setExemption(null); }} aria-label="Close">
                    <X className="w-4 h-4 text-ps-hint" />
                  </button>
                </div>

                <div className="px-5 py-4 space-y-4">
                  {exemptError && <Callout tone="problem">{exemptError}</Callout>}

                  {exemption && (
                    <div className="grid grid-cols-3 gap-3">
                      <div className="bg-ps-bg rounded-lg px-3 py-2">
                        <p className="text-2xs text-ps-label">Gain (s. 48)</p>
                        <p className="text-sm font-semibold text-ps-ink">{fmtRs(exemption.gain_paise)}</p>
                      </div>
                      <div className="bg-state-ready-surface rounded-lg px-3 py-2">
                        <p className="text-2xs text-state-ready">Exempt</p>
                        <p className="text-sm font-semibold text-state-ready">{fmtRs(exemption.total_exemption_paise)}</p>
                      </div>
                      <div className="bg-state-attention-surface rounded-lg px-3 py-2">
                        <p className="text-2xs text-state-attention">Still taxable</p>
                        <p className="text-sm font-semibold text-state-attention">{fmtRs(exemption.taxable_gain_paise)}</p>
                      </div>
                    </div>
                  )}

                  {/* What the register could not answer. A sentence saying what
                      to go and record beats a figure computed from a guess. */}
                  <GapList gaps={exemption?.gaps ?? []} tone="attention" />

                  {exemption?.claims?.map(c => (
                    <div key={c.id ?? c.section}
                         className={`rounded-lg border px-3 py-2.5 space-y-1.5 ${c.allowed ? "border-state-ready-border bg-state-ready-surface/40" : "border-ps-border bg-ps-bg"}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-ps-ink">
                            s. {c.section} — {c.new_asset_description}
                          </p>
                          <p className="text-2xs text-ps-label">{c.heading}</p>
                        </div>
                        <div className="text-right shrink-0">
                          <p className={`text-sm font-semibold ${c.allowed ? "text-state-ready" : "text-ps-hint"}`}>
                            {c.allowed ? fmtRs(c.exemption_paise) : "Not allowed"}
                          </p>
                          {c.deadline && (
                            <p className="text-2xs text-ps-label">
                              by {c.deadline}{c.within_time === false ? " — missed" : ""}
                            </p>
                          )}
                        </div>
                      </div>
                      {c.working.map((w, i) => (
                        <p key={`w${i}`} className="text-2xs text-ps-label">{w}</p>
                      ))}
                      {c.gaps.map((g, i) => (
                        <p key={`g${i}`} className="text-2xs text-state-attention flex gap-1.5">
                          <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />{g}
                        </p>
                      ))}
                      {c.caveats.map((v, i) => (
                        <p key={`c${i}`} className="text-2xs text-ps-label italic">{v}</p>
                      ))}
                      {c.id && (
                        <button onClick={() => removeClaim(c.id as string)} disabled={exemptBusy}
                                className="text-2xs text-ps-hint hover:text-state-problem transition-colors">
                          Delete this claim
                        </button>
                      )}
                    </div>
                  ))}

                  {exemption && exemption.caveats.map((v, i) => (
                    <p key={i} className="text-2xs text-ps-label italic">{v}</p>
                  ))}

                  {/* ── record a claim ─────────────────────────────────── */}
                  <div className="border-t pt-4 space-y-3">
                    <p className="text-xs font-semibold text-ps-body">Record a claim</p>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs font-medium text-ps-body block mb-1">Section</label>
                        <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm"
                                value={claimForm.section}
                                onChange={e => setClaimForm(f => ({ ...f, section: e.target.value as ReinvestmentSection }))}>
                          {(sectionInfo.length
                            ? sectionInfo.map(x => x.section)
                            : (["54", "54B", "54EC", "54F"] as ReinvestmentSection[])).map(sec => (
                            <option key={sec} value={sec}>s. {sec}</option>
                          ))}
                        </select>
                        <p className="text-2xs text-ps-label mt-1">
                          {sectionInfo.find(x => x.section === claimForm.section)?.new_asset ?? ""}
                        </p>
                      </div>
                      <div>
                        <label className="text-xs font-medium text-ps-body block mb-1">Bought by</label>
                        <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm"
                                aria-label="Acquisition kind"
                                value={claimForm.acquisition_kind}
                                onChange={e => setClaimForm(f => ({ ...f, acquisition_kind: e.target.value as "" | AcquisitionKind }))}>
                          <option value="">Not stated</option>
                          <option value="purchase">Purchase</option>
                          <option value="construction">Construction</option>
                          <option value="bonds">Bond subscription</option>
                        </select>
                      </div>
                    </div>

                    <div>
                      <label className="text-xs font-medium text-ps-body block mb-1">What was bought *</label>
                      <input className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm"
                             value={claimForm.new_asset_description}
                             onChange={e => setClaimForm(f => ({ ...f, new_asset_description: e.target.value }))}
                             placeholder="e.g. Flat 402, Prabhat Residency, Pune" />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs font-medium text-ps-body block mb-1">Cost (₹)</label>
                        <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm"
                               value={claimForm.cost_rs}
                               onChange={e => setClaimForm(f => ({ ...f, cost_rs: e.target.value }))} placeholder="0" />
                      </div>
                      <div>
                        <label className="text-xs font-medium text-ps-body block mb-1">Acquired on</label>
                        <input type="date" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm"
                               aria-label="Acquisition date"
                               value={claimForm.acquisition_date}
                               onChange={e => setClaimForm(f => ({ ...f, acquisition_date: e.target.value }))} />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs font-medium text-ps-body block mb-1">
                          Capital Gains Accounts Scheme (₹)
                        </label>
                        <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm"
                               value={claimForm.cgas_rs}
                               onChange={e => setClaimForm(f => ({ ...f, cgas_rs: e.target.value }))} placeholder="0" />
                      </div>
                      <div>
                        <label className="text-xs font-medium text-ps-body block mb-1">Deposited on</label>
                        <input type="date" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm"
                               aria-label="CGAS deposit date"
                               value={claimForm.cgas_date}
                               onChange={e => setClaimForm(f => ({ ...f, cgas_date: e.target.value }))} />
                      </div>
                    </div>

                    {/* The two facts no ledger holds. Blank is a THIRD state
                        and the server refuses on it — a 0 here would assert
                        the assessee owned no other house. */}
                    {claimForm.section === "54F" && (
                      <div>
                        <label className="text-xs font-medium text-ps-body block mb-1">
                          Other residential houses owned on the date of transfer
                        </label>
                        <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm"
                               value={claimForm.other_houses}
                               onChange={e => setClaimForm(f => ({ ...f, other_houses: e.target.value }))}
                               placeholder="Leave blank if not established" />
                        <p className="text-2xs text-ps-label mt-1">
                          s. 54F needs this and no ledger holds it. Blank is not zero —
                          the working says the claim cannot be tested until it is recorded.
                        </p>
                      </div>
                    )}
                    {claimForm.section === "54B" && (
                      <div>
                        <label className="text-xs font-medium text-ps-body block mb-1">
                          Farmed in the two years before the transfer?
                        </label>
                        <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm"
                                aria-label="Agricultural use in the two preceding years"
                                value={claimForm.agri_use}
                                onChange={e => setClaimForm(f => ({ ...f, agri_use: e.target.value as "" | "yes" | "no" }))}>
                          <option value="">Not established</option>
                          <option value="yes">Yes — by the assessee or a parent</option>
                          <option value="no">No</option>
                        </select>
                      </div>
                    )}

                    <div className="flex justify-end gap-2">
                      <Button size="sm" onClick={saveClaim} disabled={exemptBusy}>
                        {exemptBusy ? "Saving…" : "Record claim"}
                      </Button>
                    </div>
                  </div>

                  <p className="text-2xs text-ps-hint border-t pt-3">
                    Every figure and window here is written from knowledge rather than read
                    off the bare Act — this environment cannot reach incometax.gov.in.
                    Check s. 54EC&apos;s ₹50 lakh, the six-month and two- and three-year
                    windows and the Finance Act 2023 ₹10 crore cap against the section
                    before relying on them.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Add Transaction Modal */}
          {showModal && (
            <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
              <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
                <div className="flex items-center justify-between px-5 py-4 border-b">
                  <h2 className="text-sm font-semibold text-ps-ink">Add Capital Gains Transaction</h2>
                  <button onClick={() => setShowModal(false)}><X className="w-4 h-4 text-ps-hint" /></button>
                </div>
                <div className="px-5 py-4 space-y-4">
                  {regError && <Callout tone="problem">{regError}</Callout>}

                  <div>
                    <label className="text-xs font-medium text-ps-body block mb-1">Asset Description *</label>
                    <input className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={regForm.asset_description} onChange={e => setRegForm(f => ({ ...f, asset_description: e.target.value }))} placeholder="e.g. Reliance Industries Ltd — 100 shares" />
                  </div>

                  <div>
                    <label className="text-xs font-medium text-ps-body block mb-1">Asset Type *</label>
                    <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={regForm.asset_type} onChange={e => setRegForm(f => ({ ...f, asset_type: e.target.value as CapitalGainsRegisterAssetType }))}>
                      {ASSET_TYPES_REG.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                    </select>
                  </div>

                  <div>
                    <label className="text-xs font-medium text-ps-body block mb-1">Sold as</label>
                    <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
                            aria-label="What was sold, for the s.54 family"
                            value={regForm.transferred_asset_nature}
                            onChange={e => setRegForm(f => ({ ...f, transferred_asset_nature: e.target.value as "" | TransferredAssetNature }))}>
                      <option value="">Not stated</option>
                      {(natures.length ? natures : (Object.keys(NATURE_LABELS) as TransferredAssetNature[])).map(n => (
                        <option key={n} value={n}>{NATURE_LABELS[n] ?? n}</option>
                      ))}
                    </select>
                    <p className="text-2xs text-ps-label mt-1">
                      Decides which of ss. 54, 54B, 54EC and 54F can reach this transfer.
                      &quot;Immovable property&quot; above cannot say — s. 54 reaches a residential
                      house and s. 54F reaches an asset that is not one.
                    </p>
                  </div>

                  {/* IT-28. Same third state as "Sold as" above: unrecorded is
                      not "no". The engine takes the unlisted period, which
                      over-states the tax, and names the gap on the preview. */}
                  {listingIsAsked(regForm.asset_type) && (
                    <div>
                      <label className="text-xs font-medium text-ps-body block mb-1">Listed on a recognised stock exchange in India?</label>
                      <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
                              aria-label="Register listed security"
                              value={regForm.listed}
                              onChange={e => setRegForm(f => ({ ...f, listed: e.target.value as "" | "listed" | "unlisted" }))}>
                        <option value="">Not recorded</option>
                        <option value="listed">Listed</option>
                        <option value="unlisted">Not listed</option>
                      </select>
                      <p className="text-2xs text-ps-label mt-1">
                        Section 2(42A), proviso — a listed security (other than a unit) is
                        long-term after 12 months, everything else after 24. &quot;Bonds&quot; above
                        cannot say which this is.
                      </p>
                    </div>
                  )}

                  <div>
                    <label className="text-xs font-medium text-ps-body block mb-1">Assessee</label>
                    <select className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
                            aria-label="Register assessee type"
                            value={regForm.assessee_type} onChange={e => setRegForm(f => ({ ...f, assessee_type: e.target.value as CapitalGainsAssesseeType }))}>
                      <option value="unspecified">Not stated</option>
                      <option value="resident_individual_huf">Resident individual or HUF</option>
                      <option value="other">Company, LLP, firm or non-resident</option>
                    </select>
                    <p className="text-2xs text-ps-label mt-1">
                      Section 112(1), fifth proviso — decides whether the 20%-with-indexation
                      option is available on property acquired before 23 July 2024.
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs font-medium text-ps-body block mb-1">Purchase Date *</label>
                      <input type="date" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={regForm.purchase_date} onChange={e => setRegForm(f => ({ ...f, purchase_date: e.target.value }))} />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-ps-body block mb-1">Sale Date *</label>
                      <input type="date" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={regForm.sale_date} onChange={e => setRegForm(f => ({ ...f, sale_date: e.target.value }))} />
                    </div>
                  </div>

                  {/* IT-19. Shown only where s.55(2)(ac) reaches the transfer:
                      a s.112A asset acquired before 01-02-2018. The purchase
                      date is asked above it because it is half the test. */}
                  {grandfatheringIsAsked(regForm.asset_type, regForm.purchase_date) && (
                    <div>
                      <label className="text-xs font-medium text-ps-body block mb-1">Fair market value on 31 Jan 2018 (₹) — the whole holding</label>
                      <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand"
                             aria-label="Register fair market value on 31 January 2018"
                             value={regForm.fmv_31_01_2018_rs}
                             onChange={e => setRegForm(f => ({ ...f, fmv_31_01_2018_rs: e.target.value }))}
                             placeholder="Not recorded" />
                      <p className="text-2xs text-ps-label mt-1">
                        Section 55(2)(ac) — acquired before 1 February 2018, so the cost is
                        deemed to be the higher of the actual cost and the lower of this and
                        the sale value. The WHOLE holding, not a per-share price. Left blank,
                        the actual cost stands and the gain is over-stated by the whole of the
                        appreciation up to 31 January 2018.
                      </p>
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs font-medium text-ps-body block mb-1">Purchase Cost (₹)</label>
                      <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={regForm.purchase_cost_rs} onChange={e => setRegForm(f => ({ ...f, purchase_cost_rs: e.target.value }))} placeholder="0" />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-ps-body block mb-1">Sale Value (₹)</label>
                      <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={regForm.sale_value_rs} onChange={e => setRegForm(f => ({ ...f, sale_value_rs: e.target.value }))} placeholder="0" />
                    </div>
                  </div>

                  <div>
                    <label className="text-xs font-medium text-ps-body block mb-1">Improvement Cost (₹) — optional</label>
                    <input type="number" min="0" className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand" value={regForm.improvement_cost_rs} onChange={e => setRegForm(f => ({ ...f, improvement_cost_rs: e.target.value }))} placeholder="0" />
                  </div>

                  {/* Server-computed preview (STCG/LTCG, rate, indexed cost) */}
                  {regPreview && (
                    <div className="bg-brand-surface rounded-lg px-4 py-3 space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-ps-label">Holding Period</span>
                        <span className="font-medium text-ps-ink">{regPreview.holding_months} months</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-ps-label">Classification</span>
                        <span className={`font-semibold ${regPreview.gain_type === "LTCG" ? "text-state-ready" : "text-state-attention"}`}>{regPreview.gain_type}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-ps-label">Tax Rate</span>
                        <span className="font-medium text-ps-ink">{regPreview.tax_rate_percent}%</span>
                      </div>
                      {regPreview.grandfathered_cost_is_applied && (
                        <div className="flex justify-between text-xs">
                          <span className="text-ps-label">Deemed cost — s.55(2)(ac)</span>
                          <span className="font-medium text-ps-ink">{fmtRs(regPreview.cost_of_acquisition_paise ?? 0)}</span>
                        </div>
                      )}
                      {regForm.asset_type === "property" && (
                        <div className="flex justify-between text-xs">
                          <span className="text-ps-label">Indexed Cost</span>
                          <span className="font-medium text-ps-ink">{fmtRs(regPreview.indexed_cost_paise)}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* The classification and the rate above are what gets
                      PERSISTED, so a fact that would move either has to be
                      said before the CA presses Save — not afterwards on the
                      calculator tab. */}
                  {(regPreview?.gaps?.length ?? 0) > 0 && (
                    <div className="bg-state-attention-surface rounded-lg border border-state-attention-border px-4 py-3">
                      <p className="text-xs font-semibold text-state-attention">Not recorded — this changes what is saved</p>
                      <ul className="mt-1 space-y-1">
                        {regPreview!.gaps!.map((g, i) => (
                          <li key={i} className="text-xs text-state-attention">{g}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {(regPreview?.caveats?.length ?? 0) > 0 && (
                    <ul className="space-y-1">
                      {regPreview!.caveats!.map((c, i) => (
                        <li key={i} className="text-xs text-ps-label">{c}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="flex justify-end gap-3 px-5 py-4 border-t">
                  <Button variant="outline" size="sm" onClick={() => setShowModal(false)}>Cancel</Button>
                  <Button size="sm" onClick={handleSaveRecord} disabled={saving}>{saving ? "Saving…" : "Save Transaction"}</Button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
