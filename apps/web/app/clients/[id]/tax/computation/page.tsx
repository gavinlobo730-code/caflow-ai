"use client";

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useEffect, useState, useCallback } from "react";
import { Plus, Loader2, ChevronDown, ChevronUp, AlertTriangle, CheckCircle, Save } from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { assessmentYearChoicesAround } from "@/lib/dates/periods";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// The years this build can actually compute are the server's to state — see
// GET /api/income-tax/financial-years. Hard-coding them here is what let the
// picker offer FY 2023-24 and FY 2024-25, which the engine has no rates for
// and silently computed at the current year's instead.
interface SupportedFY { fy: string; verified: boolean }

/** What GET /api/form-26as/claimable returns (IT-31).
 *
 *  FOUR figures, because the return has four lines: TDS is Schedule TDS, TCS
 *  is Schedule TCS under §206C(4), tax the client paid itself is Part C and
 *  its own line, and a refund already received is not a credit at all.
 *  Anything not booked FINAL at TRACES is `provisional_paise` and excluded —
 *  claiming an unmatched credit is what produces a §143(1) demand.
 *
 *  `available: false` is a NAMED absence, never a zero: nobody having
 *  uploaded 26AS and the client having no credit are opposite facts. */
interface ClaimableCredit {
  available: boolean;
  reason?: string;
  financial_year?: string;
  uploaded_at?: string | null;
  record_count?: number;
  tds_claimable_paise?: number;
  tcs_claimable_paise?: number;
  provisional_paise?: number;
  tax_paid_by_client_paise?: number;
  refund_already_received_paise?: number;
  by_deductor?: {
    deductor_name: string; deductor_tan: string | null; kind: string;
    claimable_paise: number; provisional_paise: number; entry_count: number;
  }[];
  caveats?: string[];
  basis?: string;
}
// FROM THE CLOCK, NOT A LITERAL — the same rule as the financial-year list,
// derived from it so the two cannot disagree about which year is current
// (IT Act §2(9): the AY is the FY plus one).
const AY_OPTIONS = assessmentYearChoicesAround(null);
const SECTION_OPTIONS = ["40A(3)", "43B_pf", "43B_gst", "43B_bonus", "43B_leave", "other"];

/** What a snapshot's `regime` means, in words.
 *
 *  This screen used to render `regime === "new" ? "New Regime" : "Old Regime"`,
 *  which is s.115BAC's election — an INDIVIDUAL or HUF question. A company's
 *  choice is s.115BAA / s.115BAB and a firm has no election at all, so every
 *  entity snapshot read "Old Regime", a label with no statute behind it. */
function regimeLabel(regime: string | null | undefined): string {
  switch (regime) {
    case "new": return "New Regime";
    case "old": return "Old Regime";
    case "normal": return "Company — normal rates";
    case "115BAA": return "Company — §115BAA";
    case "115BAB": return "Company — §115BAB";
    case "firm": return "Firm — flat 30%";
    case "llp": return "LLP — flat 30%";
    default: return regime ? regime : "—";
  }
}

async function apiFetch(path: string, opts?: RequestInit) {
  const { supabase } = await import("@/lib/supabase/client");
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

function paise(amount: number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })
    .format(amount / 100);
}

interface Snapshot {
  id: string;
  version: number;
  regime: string;
  financial_year: string;
  taxable_income_paise: number;
  tax_liability_paise: number;
  net_payable_paise: number;
  is_refund: boolean;
  status: string;
  created_at: string;
}

interface Disallowance {
  id: string;
  section: string;
  description: string;
  amount_paise: number;
  status: string;
  auto_detected: boolean;
}

interface ComputeResult {
  income: { taxable_income_paise: number };
  tax: { total_tax_paise: number; rebate_87a_paise: number };
  payable: { net_payable_paise: number; is_refund: boolean };
  warnings: string[];
  validation_errors?: string[];
  /** IT-10. What the brought-forward losses actually relieved, and the working
   *  behind it. A total with no breakdown is not checkable, and a loss the
   *  statute would not let through has to be visibly NOT set off rather than
   *  quietly absent — §71(3) and §74 deny a capital loss any relief against
   *  salary, business or other income, and a CA has to be able to see that
   *  the engine agreed. */
  brought_forward?: {
    set_off_paise: number;
    lines: {
      loss_type: string;
      section: string;
      offered_paise: number;
      set_off_paise: number;
      carried_forward_paise: number;
      against: string[];
      reasons: string[];
    }[];
  };
  /** WHO was assessed, and on what basis. A firm, an LLP and a company are
   *  each taxed differently from an individual and from each other; until
   *  IT-01 this screen ran individual slabs for every client, so a Private
   *  Limited company's profit was taxed nil to Rs 4 lakh with a Rs 60,000
   *  s.87A rebate against the 22%/25%/30% it actually owes. */
  assessee?: {
    kind: string;
    rate_percent: number;
    /** The year the 25%/30% turnover test looks at — two back, never the year
     *  being taxed. */
    turnover_reference_fy: string | null;
    workings: string[];
  };
  /** s.115JB (a company) / s.115JC (a firm or LLP). `credit_paise` is the
   *  point: s.115JAA and s.115JD carry the excess forward for fifteen
   *  assessment years, and charging the floor without recording the credit
   *  turns a timing difference into a permanent cost. */
  minimum_tax?: {
    section: string;
    applies: boolean;
    minimum_tax_paise: number;
    applied: boolean;
    credit_paise: number;
    credit_expires_after_ay: number | null;
    reasons: string[];
  };
  /** The capital-gains working, section by section.
   *
   *  The engine has computed `basic_exemption_absorbed_paise` and a per-bucket
   *  explanation since IT-08, documented as existing "so a CA can see WHICH
   *  gain the exemption was set against" — and a grep across the routers and
   *  the whole frontend found no reader. So this screen showed ₹20,800 of tax
   *  on a ₹5,00,000 STCG and nothing about the ₹4,00,000 that vanished.
   *
   *  The allocation is a CHOICE: the provisos to §111A(1), §112(1)(a)(ii) and
   *  §112A(2) fix no order between the three, and the engine takes the highest
   *  rate first because that is most beneficial to the assessee. A reader is
   *  entitled to check that, and cannot from a total. */
  capital_gains?: {
    lines: {
      section: string;
      gross_paise: number;
      exempt_paise: number;
      absorbed_paise: number;
      charged_paise: number;
      rate_percent: number;
      tax_paise: number;
    }[];
    tax_paise: number;
    basic_exemption_absorbed_paise: number;
    basic_exemption_absorption: string[];
  };
  /** §10 income, echoed. The field on this form was live, sent, accepted and
   *  then read by nothing — the tax is right without it (§10 income is not
   *  part of total income) but a CA typed a figure that changed nothing and
   *  nothing said so. */
  exempt_income?: { reported_paise: number; note: string };
  // The year whose rates were ACTUALLY applied, and whether they are
  // confirmed against the Finance Act. The backend has always returned both;
  // this screen used to discard them, which is how a computation at another
  // year's rates could reach a CA looking entirely normal.
  fy: string;
  rates_verified: boolean;
}

/** One §80G donation as the form holds it. Every field is a fact about the
 *  DONEE, not a preference: §80G's four categories are the product of the
 *  percentage and whether the qualifying limit applies, and §80G(5D) bars a
 *  cash donation over ₹2,000 outright. `paidInCash` is tri-state — "" is "the
 *  CA did not say", which the engine allows with a warning, because a zero for
 *  "paid by cheque" and a zero for "nobody stated the mode" are not the same
 *  answer. */
interface DonationRow {
  description: string;
  amount: string;
  pct: number;
  subjectToLimit: boolean;
  paidInCash: "" | "yes" | "no";
}

/** What POST /api/income-tax/presumptive/{scheme} answers. `workings` is the
 *  point: a presumptive figure is a statutory computation on the turnover, not
 *  a number a CA types, and it has to be checkable. */
interface PresumptiveResult {
  section: string;
  eligible: boolean;
  presumptive_income_paise: number;
  /** What will actually be taken as the business income: the deemed figure,
   *  or a higher one the assessee declared, or ZERO where the scheme is
   *  refused — `PresumptiveResult` sets it to 0 when `eligible` is false, so
   *  it must never be read without checking that flag. */
  declared_income_paise: number;
  turnover_limit_paise: number;
  enhanced_limit_applied: boolean;
  reasons: string[];
  workings: string[];
}

interface BFLoss {
  id: string;
  assessment_year: string;
  loss_type: string;
  original_amount_paise: number;
  remaining_amount_paise: number;
  expiry_assessment_year: string;
}

export default function TaxComputationPage() {
  // Not useParams(): apps/web is a static export and Cloudflare's 200-rewrite
  // serves the pre-rendered "_placeholder" HTML for every real client URL, so
  // useParams().id was the literal string "_placeholder" — the load below bailed
  // on its own guard and the workspace rendered permanently empty, while Compute
  // and Add Disallowance posted "_placeholder" as client_id. useClientNav reads
  // the real UUID out of window.location.
  const { clientId } = useClientNav();

  const [fyOptions, setFyOptions] = useState<SupportedFY[]>([]);
  const [fy, setFy] = useState("");
  const [ay, setAy] = useState(AY_OPTIONS[0]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [disallowances, setDisallowances] = useState<Disallowance[]>([]);
  const [bfLosses, setBfLosses] = useState<BFLoss[]>([]);
  const [activeSection, setActiveSection] = useState<string | null>("overview");

  // The client's own entity type, read from the client record and passed
  // through UNINTERPRETED. Deciding that 'Private Limited' is a company and
  // 'Proprietorship' is an individual is statutory knowledge and lives in
  // apps/api — CLAUDE.md, "zero business logic in the frontend".
  const [entityType, setEntityType] = useState<string | null>(null);
  // WHICH ASSESSEE that entity type makes them, answered by the server. The
  // mapping is statutory — a proprietorship is an individual, a trust is
  // refused — so this screen asks rather than deciding.
  const [assesseeKind, setAssesseeKind] = useState<string | null>(null);
  const [assesseeRefusal, setAssesseeRefusal] = useState<string | null>(null);
  const isEntity = assesseeKind === "firm" || assesseeKind === "llp"
                   || assesseeKind === "domestic_company";
  const isCompany = assesseeKind === "domestic_company";

  // Computation inputs
  const [regime, setRegime] = useState("new");
  // Company only: s.115BAA (22%) and s.115BAB (15%) are elections whose
  // surcharge is a flat 10% whatever the income.
  const [companyRegime, setCompanyRegime] = useState("normal");
  const [turnoverRefYear, setTurnoverRefYear] = useState("");
  const [bookProfit, setBookProfit] = useState("");
  const [claimedSpecifiedDeduction, setClaimedSpecifiedDeduction] = useState(false);
  const [salary, setSalary] = useState("");
  const [businessIncome, setBusinessIncome] = useState("");
  const [otherIncome, setOtherIncome] = useState("");
  const [tds, setTds] = useState("");
  const [advanceTax, setAdvanceTax] = useState("");
  // IT-31 — what Form 26AS actually supports, so the CA stops retyping a
  // figure they have just reconciled. `tdsTouched` is why the prefill is safe:
  // it fills an EMPTY box once and never overwrites a number somebody typed.
  const [claim, setClaim] = useState<ClaimableCredit | null>(null);
  const [tdsTouched, setTdsTouched] = useState(false);

  // IT-05. The endpoint has accepted every one of these since IT-01; this
  // screen sent six figures and nothing else, so an OLD-REGIME individual was
  // computed with zero Chapter VI-A relief — no 80C, no 80D, no house
  // property, no capital gains — and the number looked entirely reasonable.
  //
  // Held as TEXT and parsed with the one money parser at submit, never as
  // numbers: parseFloat("1,25,000") is 1, and this is exactly where an Indian
  // amount is typed with Indian grouping.
  const [housePropertyIncome, setHousePropertyIncome] = useState("");
  const [stcg, setStcg] = useState("");
  const [ltcgEquity, setLtcgEquity] = useState("");
  const [ltcgOther, setLtcgOther] = useState("");
  const [exemptIncome, setExemptIncome] = useState("");
  const [s80cTotal, setS80cTotal] = useState("");
  const [s80dSelf, setS80dSelf] = useState("");
  const [s80dSelfSenior, setS80dSelfSenior] = useState(false);
  const [s80dParents, setS80dParents] = useState("");
  const [s80dParentsSenior, setS80dParentsSenior] = useState(false);
  const [savingsInterest80tta, setSavingsInterest80tta] = useState("");
  const [homeLoanInterest24b, setHomeLoanInterest24b] = useState("");
  const [otherDeductions, setOtherDeductions] = useState("");

  // IT-05, the five the endpoint accepts and this screen still did not send.
  //
  // RESIDENCE IS NOT A DEDUCTION and is not gated on the regime. It decides
  // whether an unused basic exemption may be set against a capital gain —
  // the provisos to §111A(1), §112(1)(a)(ii) and §112A(2) reach a RESIDENT
  // individual only — so `is_resident` defaulting to true with no control
  // silently granted a non-resident an absorption the statute does not.
  const [isResident, setIsResident] = useState(true);
  // §10(13A) with Rule 2A. Old regime only: §115BAC(2)(i) withdraws it.
  const [hraBasic, setHraBasic] = useState("");
  const [hraReceived, setHraReceived] = useState("");
  const [hraRent, setHraRent] = useState("");
  const [hraMetro, setHraMetro] = useState(false);
  // §80CCD(1B) — the assessee's own NPS, ₹50,000 over and above §80C.
  const [nps80ccd1b, setNps80ccd1b] = useState("");
  // §80CCD(2) — the EMPLOYER's contribution, and the one Chapter VI-A head
  // §115BAC(2) leaves standing, so it is offered under both regimes.
  const [employerNps, setEmployerNps] = useState("");
  const [isGovtEmployee, setIsGovtEmployee] = useState(false);
  const [nps80ccd2Salary, setNps80ccd2Salary] = useState("");
  const [donations, setDonations] = useState<DonationRow[]>([]);

  // IT-16. §44AD / §44ADA / §44AE. The figure is COMPUTED by the server from
  // the turnover — 8%, 6% on the banked part, 50%, or the per-tonne rate — and
  // it REPLACES business income and every disallowance in the computation
  // (§44AD(2), §44ADA(3), §44AE(6) each deem the deductions already allowed).
  // So it is not a box a CA types into: they give the turnover, the server
  // says what the section deems, and the working comes back with it.
  const [presumptiveScheme, setPresumptiveScheme] = useState("");
  const [presTurnover, setPresTurnover] = useState("");
  const [presDigital, setPresDigital] = useState("");
  const [presCash, setPresCash] = useState("");
  const [presGross, setPresGross] = useState("");
  const [presDeclared, setPresDeclared] = useState("");
  const [presVehicles, setPresVehicles] = useState<{ weight: string; months: string }[]>([]);
  const [presResult, setPresResult] = useState<PresumptiveResult | null>(null);
  const [presError, setPresError] = useState<string | null>(null);
  const [presComputing, setPresComputing] = useState(false);

  const [isSenior, setIsSenior] = useState(false);
  const [isVerySenior, setIsVerySenior] = useState(false);
  const [computing, setComputing] = useState(false);
  const [computeResult, setComputeResult] = useState<ComputeResult | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);

  // Disallowance form
  const [showDisallForm, setShowDisallForm] = useState(false);
  const [disallSection, setDisallSection] = useState("40A(3)");
  const [disallDesc, setDisallDesc] = useState("");
  const [disallAmount, setDisallAmount] = useState("");
  const [savingDisall, setSavingDisall] = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = computing || savingDisall || presComputing;

  // Distinguishes "fetch failed" from "nothing recorded yet" — a masked
  // failure previously rendered the whole workspace (snapshots,
  // disallowances, brought-forward losses) as fully empty with no
  // indication anything went wrong.
  const [loadError, setLoadError] = useState<string | null>(null);
  /** IT-30. `POST /api/itr/snapshots/{id}/review` has existed since the
   *  workspace was built and NOTHING called it, so every snapshot's status was
   *  permanently "draft" — while this very panel already rendered a green tick
   *  for "reviewed", a state it had no way to reach. A filing pins a snapshot
   *  (`itr_filings.computation_snapshot_id`) and the transition now refuses to
   *  move a filing out of draft while the computation it is built on has not
   *  been checked, so the button below is what unblocks the filing workflow. */
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    // Plain reads — routed directly to Supabase (RLS: firm_isolation) instead
    // of through the FastAPI backend, which cold-starts. Mirrors the exact
    // table/columns/filters/ordering of list_snapshots, list_disallowances,
    // and list_bf_losses in apps/api/domain/income_tax/computation_workspace.py.
    // The actual computation (POST /api/income-tax/compute) stays backend-routed.
    const supabase = getSupabaseClient();
    const [
      { data: snapsData, error: snapsErr },
      { data: disallData, error: disallErr },
      { data: lossData, error: lossErr },
      { data: clientRow },
    ] = await Promise.all([
      supabase
        .from("tax_computation_snapshots")
        .select("id, version, regime, financial_year, taxable_income_paise, tax_liability_paise, net_payable_paise, is_refund, status, created_at")
        .eq("client_id", clientId)
        .eq("financial_year", fy)
        .order("version", { ascending: false }),
      supabase
        .from("tax_disallowances")
        .select("id, section, description, amount_paise, status, auto_detected")
        .eq("client_id", clientId)
        .eq("financial_year", fy)
        .order("created_at", { ascending: false }),
      supabase
        .from("brought_forward_losses")
        .select("id, assessment_year, loss_type, original_amount_paise, remaining_amount_paise, expiry_assessment_year")
        .eq("client_id", clientId)
        .order("assessment_year"),
      // Which assessee this client IS. Not interpreted here — the raw value
      // goes to the endpoint, which maps it.
      supabase.from("clients").select("entity_type").eq("id", clientId).maybeSingle(),
    ]);
    const firstError = snapsErr ?? disallErr ?? lossErr;
    if (firstError) {
      setSnapshots([]);
      setDisallowances([]);
      setBfLosses([]);
      setLoadError(firstError.message || "Couldn't load the tax computation workspace.");
      return;
    }
    setSnapshots((snapsData as Snapshot[]) ?? []);
    setDisallowances((disallData as Disallowance[]) ?? []);
    setBfLosses((lossData as BFLoss[]) ?? []);
    setEntityType(((clientRow as { entity_type?: string } | null)?.entity_type) ?? null);
    setLoadError(null);
  }, [clientId, fy]);

  async function markSnapshotReviewed(snapshotId: string) {
    setReviewing(snapshotId);
    setReviewError(null);
    try {
      // Through the API, not PostgREST: the endpoint is rbac("income_tax",
      // "approve") — a review is an approval and not every role may make one —
      // and it writes the client timeline entry. A browser write would do
      // neither.
      const res = await apiFetch(`/api/itr/snapshots/${snapshotId}/review`, {
        method: "POST",
      });
      if (!res.success) throw new Error(res.error ?? "Could not mark the computation reviewed.");
      await load();
    } catch (e) {
      setReviewError(e instanceof Error ? e.message : "Could not mark the computation reviewed.");
    } finally {
      setReviewing(null);
    }
  }

  useEffect(() => { load(); }, [load]);

  // The entity type -> assessee mapping, from the server. A refusal (a trust, a
  // co-operative society, a blank entity type) is shown BEFORE the CA types a
  // figure, rather than as a 422 after they have.
  useEffect(() => {
    let cancelled = false;
    if (!entityType) { setAssesseeKind(null); setAssesseeRefusal(null); return; }
    (async () => {
      try {
        const r = await apiFetch(
          `/api/income-tax/assessee-kind?entity_type=${encodeURIComponent(entityType)}`);
        if (cancelled || !r.success) return;
        setAssesseeKind(r.data?.kind ?? null);
        setAssesseeRefusal(r.data?.refusal ?? null);
      } catch {
        /* leave it unresolved; the compute call answers definitively anyway */
      }
    })();
    return () => { cancelled = true; };
  }, [entityType]);

  // WHAT 26AS SUPPORTS (IT-31). Rule 37BA(1) gives credit on the basis of the
  // deductor's own statement to the department, which is what 26AS reproduces
  // — so this is the claim and the books are the check on it. Until now the CA
  // ran the reconciliation on one tab, learned exactly which credits were
  // supported, and then retyped the total into this box by hand.
  //
  // The prefill fills an EMPTY field once. It never overwrites a typed figure:
  // the CA may know something 26AS does not yet show, and silently replacing
  // their number would be worse than not helping at all. Where the two differ,
  // the panel says so rather than resolving it.
  useEffect(() => {
    let cancelled = false;
    if (!clientId || !fy) { setClaim(null); return; }
    (async () => {
      try {
        const r = await apiFetch(
          `/api/form-26as/claimable?client_id=${encodeURIComponent(clientId)}`
          + `&financial_year=${encodeURIComponent(fy)}`);
        if (cancelled || !r.success) return;
        const c = r.data as ClaimableCredit;
        setClaim(c);
        if (c?.available) {
          setTds((prev) => (prev.trim() === "" && (c.tds_claimable_paise ?? 0) > 0
            ? String((c.tds_claimable_paise ?? 0) / 100) : prev));
          setAdvanceTax((prev) => (prev.trim() === "" && (c.tax_paid_by_client_paise ?? 0) > 0
            ? String((c.tax_paid_by_client_paise ?? 0) / 100) : prev));
        }
      } catch {
        /* no claim panel; the CA types the figure as before */
      }
    })();
    return () => { cancelled = true; };
  }, [clientId, fy]);

  // Which years this build can compute is the server's answer, not a constant
  // in this file. A failed probe leaves the picker empty rather than guessing:
  // an empty picker is visibly broken, whereas a wrong year computes silently.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch("/api/income-tax/financial-years");
        if (cancelled || !r.success) return;
        const years = (r.data?.financial_years ?? []) as SupportedFY[];
        setFyOptions(years);
        setFy((prev) => prev || r.data?.current_fy || years[0]?.fy || "");
      } catch {
        /* picker stays empty; Compute is gated on fy below */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  /** IT-16. Ask the server what the section deems, and keep its working.
   *
   *  Nothing here decides eligibility or a rate: §44AD's ceiling depends on
   *  how much of the turnover came through a bank, §44ADA's on the cash
   *  receipts, and §44AE's on each vehicle's gross weight and the months it
   *  was owned. Those are the endpoint's rules — this collects the facts. */
  async function handlePresumptive() {
    const amounts: [string, string][] =
      presumptiveScheme === "44ad"
        ? [["Turnover", presTurnover], ["Digital turnover", presDigital],
           ["Cash receipts", presCash], ["Declared income", presDeclared]]
        : presumptiveScheme === "44ada"
        ? [["Gross receipts", presGross], ["Cash receipts", presCash],
           ["Declared income", presDeclared]]
        : [["Declared income", presDeclared]];
    const bad = amounts.find(([, v]) => paiseFromRupeeInput(v || "0") === null);
    if (bad) {
      setPresError(`${bad[0]} must be an amount in rupees, without commas.`);
      return;
    }
    if (presumptiveScheme === "44ae" && !presVehicles.length) {
      setPresError("Add at least one goods carriage — §44AE charges per vehicle "
                   + "per month, so there is nothing to compute without one.");
      return;
    }
    const badVehicle = presVehicles.find(
      v => !(Number(v.weight) > 0) || !(Number(v.months) >= 0 && Number(v.months) <= 12));
    if (badVehicle) {
      setPresError("Every carriage needs a gross weight in kilograms and the "
                   + "months owned, 0 to 12 — a part month counts as a whole one.");
      return;
    }
    setPresComputing(true);
    setPresError(null);
    const toP = (v: string) => paiseFromRupeeInput(v || "0") as number;
    const declared = presDeclared.trim() === "" ? null : toP(presDeclared);
    // §44AD and §44ADA each name the assessee they reach and each require a
    // resident; §44AE names no kind at all, so its request carries neither.
    const who = { assessee_kind: assesseeKind, is_resident: isResident };
    const body =
      presumptiveScheme === "44ad"
        ? { fy, ...who, turnover_paise: toP(presTurnover),
            digital_turnover_paise: toP(presDigital),
            cash_receipts_paise: toP(presCash), declared_income_paise: declared }
        : presumptiveScheme === "44ada"
        ? { fy, ...who, gross_receipts_paise: toP(presGross),
            cash_receipts_paise: toP(presCash), declared_income_paise: declared }
        : { fy,
            vehicles: presVehicles.map(v => ({
              gross_vehicle_weight_kg: Number(v.weight),
              months_owned: Number(v.months),
            })),
            declared_income_paise: declared };
    try {
      const r = await apiFetch(`/api/income-tax/presumptive/${presumptiveScheme}`, {
        method: "POST", body: JSON.stringify(body),
      });
      if (!r.success) throw new Error(r.error ?? "Could not compute the presumptive income.");
      setPresResult(r.data as PresumptiveResult);
    } catch (err) {
      setPresResult(null);
      setPresError(err instanceof Error ? err.message : "Could not compute the presumptive income.");
    } finally {
      setPresComputing(false);
    }
  }

  async function handleCompute() {
    // Every figure read exactly BEFORE anything is computed. These five are the
    // inputs to a tax computation: a gross salary read as ₹1 because it was
    // typed "12,00,000" would produce a return that is internally consistent
    // and completely wrong.
    // EVERY amount field, not the original five. toP() below casts the parser's
    // result `as number`, so an unvalidated field that the parser refuses
    // becomes NaN and reaches the server as null — the money-parser failure
    // this codebase has already fixed twice. House property is in the list
    // like the rest: the parser accepts a leading minus, which is what a loss
    // under that head is.
    const fields: [string, string][] = [
      ["Gross salary", salary], ["Business income", businessIncome],
      ["Other income", otherIncome], ["TDS deducted", tds],
      ["Advance tax paid", advanceTax],
      ["House property income", housePropertyIncome],
      ["Short-term capital gains", stcg],
      ["Long-term capital gains (equity)", ltcgEquity],
      ["Long-term capital gains (other)", ltcgOther],
      ["Exempt income", exemptIncome],
      ["Section 80C", s80cTotal],
      ["Section 80D — self and family", s80dSelf],
      ["Section 80D — parents", s80dParents],
      ["Savings interest (80TTA)", savingsInterest80tta],
      ["Home loan interest (24b)", homeLoanInterest24b],
      ["Other deductions", otherDeductions],
      // IT-05. In the list like the rest: toP() casts the parser's answer
      // `as number`, so a field left out of this check reaches the server as
      // null the moment somebody types an amount the way Indians write one.
      ["HRA — basic salary", hraBasic],
      ["HRA received", hraReceived],
      ["Rent paid", hraRent],
      ["Section 80CCD(1B) — NPS", nps80ccd1b],
      ["Section 80CCD(2) — employer NPS", employerNps],
      ["Salary for the 80CCD(2) ceiling", nps80ccd2Salary],
      ...donations.map((d, i): [string, string] =>
        [`Donation ${i + 1}${d.description ? ` (${d.description})` : ""}`, d.amount]),
    ];
    const bad = fields.find(([, v]) => paiseFromRupeeInput(v || "0") === null);
    if (bad) {
      setComputeError(`${bad[0]} must be an amount in rupees, e.g. 1200000 or `
                      + "1200000.50 — without commas.");
      return;
    }
    setComputing(true);
    setComputeError(null);
    const toP = (v: string) => paiseFromRupeeInput(v || "0") as number;
    // Accepted disallowances are an ADD-BACK to business income, so they have
    // to reach the computation — not merely the snapshot. This total used to be
    // computed after the compute call and saved alongside a figure it had not
    // influenced, so accepting a disallowance changed the tax by exactly ₹0.
    const totalDisall = disallowances
      .filter(d => d.status === "accepted")
      .reduce((s, d) => s + d.amount_paise, 0);
    try {
      // 1. Compute tax
      const computeRes = await apiFetch("/api/income-tax/compute", {
        method: "POST",
        body: JSON.stringify({
          fy,
          gross_salary_paise: toP(salary),
          business_income_paise: toP(businessIncome),
          disallowances_paise: totalDisall,
          other_income_paise: toP(otherIncome),
          tds_deducted_paise: toP(tds),
          advance_tax_paid_paise: toP(advanceTax),
          use_new_regime: regime === "new",

          // IT-05 — the heads and deductions the endpoint has always accepted.
          house_property_income_paise: toP(housePropertyIncome),
          capital_gains_stcg_paise: toP(stcg),
          capital_gains_ltcg_paise: toP(ltcgEquity),
          capital_gains_ltcg_other_paise: toP(ltcgOther),
          exempt_income_paise: toP(exemptIncome),
          is_senior_citizen: isSenior,
          is_very_senior_citizen: isVerySenior,
          // 80C is collected as one figure rather than nine: the sub-limits
          // are all inside the same ₹1,50,000 ceiling, and asking a CA to
          // split a total they already know adds keystrokes without changing
          // the answer. The engine's per-instrument fields stay available to
          // any caller that has the split.
          s80c: { ppf_paise: toP(s80cTotal) },
          s80d: {
            self_family_premium_paise: toP(s80dSelf),
            self_family_is_senior: s80dSelfSenior,
            parents_premium_paise: toP(s80dParents),
            parents_is_senior: s80dParentsSenior,
          },
          savings_interest_80tta_paise: toP(savingsInterest80tta),
          home_loan_interest_24b_paise: toP(homeLoanInterest24b),
          other_deductions_paise: toP(otherDeductions),

          // IT-05. Sent under BOTH regimes and left to the server to allow or
          // withdraw: §115BAC(2) is a statutory list, and a screen that
          // decided which of these survives would be a second copy of it.
          is_resident: isResident,
          hra: {
            basic_salary_paise: toP(hraBasic),
            hra_received_paise: toP(hraReceived),
            rent_paid_paise: toP(hraRent),
            is_metro: hraMetro,
          },
          nps_80ccd1b_paise: toP(nps80ccd1b),
          employer_nps_80ccd2_paise: toP(employerNps),
          is_government_employee: isGovtEmployee,
          // Blank means "use the salary already given". §80CCD(2)'s ceiling is
          // a percentage of BASIC + DA, which is not the gross, so a client
          // whose gross carries allowances needs the base stated separately.
          salary_for_80ccd2_paise:
            nps80ccd2Salary.trim() === "" ? null : toP(nps80ccd2Salary),
          donations_80g: donations
            .filter(d => (paiseFromRupeeInput(d.amount || "0") ?? 0) > 0)
            .map(d => ({
              description: d.description,
              amount_paise: toP(d.amount),
              deduction_pct: d.pct,
              subject_to_qualifying_limit: d.subjectToLimit,
              // "" is not false. The engine treats null as "unstated" and warns,
              // which is the honest answer where nobody recorded the mode.
              paid_in_cash: d.paidInCash === "" ? null : d.paidInCash === "yes",
            })),

          // IT-16. Only what the server computed, never a typed figure — and
          // only while the scheme is still selected, so clearing the picker
          // clears the deeming with it.
          presumptive_income_paise:
            presumptiveScheme && presResult?.eligible
              ? presResult.presumptive_income_paise
              : null,

          // IT-10 — the losses this screen has always LOADED and never sent.
          // remaining_amount_paise, not the original: a loss already partly
          // utilised can only relieve what is left of it. Which head each one
          // may reach is the server's decision (§72/§73/§71B/§74), and its
          // working comes back in `brought_forward`.
          brought_forward_losses: bfLosses
            .filter(l => (l.remaining_amount_paise ?? 0) > 0)
            .map(l => ({
              loss_type: l.loss_type,
              amount_paise: l.remaining_amount_paise,
              assessment_year: l.assessment_year,
              expiry_assessment_year: l.expiry_assessment_year,
            })),
          // The raw client entity type. The endpoint maps it, refuses a trust
          // or a co-operative society by name, and computes the flat entity
          // rate where one applies.
          entity_type: entityType,
          company_regime: companyRegime,
          turnover_in_reference_year_paise:
            turnoverRefYear.trim() === "" ? null : toP(turnoverRefYear),
          book_profit_paise: bookProfit.trim() === "" ? null : toP(bookProfit),
          claimed_specified_deduction: claimedSpecifiedDeduction,
          assessment_year_end: Number(ay.slice(0, 4)) + 1,
        }),
      });
      if (!computeRes.success) throw new Error(computeRes.error ?? "Computation failed");
      // A refused input is not a computation. The engine returns the reasons
      // with every figure at zero, and showing a zero tax beside them would be
      // worse than showing nothing.
      const refusals = (computeRes.data?.validation_errors ?? []) as string[];
      if (refusals.length) {
        setComputeResult(null);
        setComputeError(refusals.join(" "));
        return;
      }
      setComputeResult(computeRes.data);

      // 2. Save snapshot

      await apiFetch("/api/itr/snapshots", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId,
          financial_year: fy,
          assessment_year: ay,
          // The regime the SERVER applied, not the local dropdown. A company
          // is on s.115BAA/s.115BAB/normal and a firm has none, so sending the
          // s.115BAC value stamped an election on a snapshot that could not
          // have made it. Falls back to the assessee kind where there is no
          // regime, so the label is at least true.
          regime: (computeRes.data?.regime as string) || (isEntity ? assesseeKind : regime),
          income: {
            gross_salary_paise: toP(salary),
            business_income_paise: toP(businessIncome),
            other_income_paise: toP(otherIncome),
            total_disallowances_paise: totalDisall,
            advance_tax_paid_paise: toP(advanceTax),
            tds_deducted_paise: toP(tds),
            taxable_income_paise: computeRes.data?.income?.taxable_income_paise ?? 0,
            tax_liability_paise: computeRes.data?.tax?.total_tax_paise ?? 0,
            net_payable_paise: computeRes.data?.payable?.net_payable_paise ?? 0,
            is_refund: (computeRes.data?.payable?.net_payable_paise ?? 0) < 0,
          },
          computation_result: computeRes.data,
        }),
      });
      await load();
    } catch (err) {
      setComputeError(err instanceof Error ? err.message : "Failed");
    } finally {
      setComputing(false);
    }
  }

  async function handleSaveDisallowance() {
    // A disallowance is an ADD-BACK to business income, so a mis-read amount
    // moves the tax directly.
    const disallPaise = paiseFromRupeeInput(disallAmount);
    if (disallPaise === null) {
      setComputeError("The disallowance amount must be in rupees, e.g. 50000 or "
                      + "50000.50 — without commas.");
      return;
    }
    setSavingDisall(true);
    try {
      const res = await apiFetch("/api/itr/disallowances", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId,
          financial_year: fy,
          section: disallSection,
          description: disallDesc,
          amount_paise: disallPaise,
        }),
      });
      if (!res.success) throw new Error(res.error);
      setShowDisallForm(false);
      setDisallDesc("");
      setDisallAmount("");
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    } finally {
      setSavingDisall(false);
    }
  }

  const toggle = (s: string) => setActiveSection(prev => prev === s ? null : s);
  const latestSnap = snapshots[0];

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[#1E293B]">Tax Computation Workspace</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">IT Act 1961 — Sections 40A, 43B, 80C–80JJAA</p>
        </div>
        <select
          value={fy}
          onChange={e => setFy(e.target.value)}
          className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {fyOptions.map(o => (
            <option key={o.fy} value={o.fy}>
              {o.fy}{o.verified ? "" : " (provisional rates)"}
            </option>
          ))}
        </select>
      </div>

      {/* CA Review Banner */}
      <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5">
        <AlertTriangle size={13} className="text-amber-600 flex-shrink-0" />
        <p className="text-xs text-amber-800 font-medium">CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT</p>
      </div>

      {loadError && (
        <div className="flex items-center justify-between gap-2 bg-red-50 border border-red-200 rounded-xl px-4 py-2.5">
          <p className="text-xs text-red-700 font-medium">{loadError}</p>
          <button onClick={() => load()} className="text-xs px-3 py-1 border border-red-200 rounded hover:bg-red-100 text-red-700 shrink-0">Retry</button>
        </div>
      )}

      {/* Overview Card */}
      {latestSnap && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5">
          <p className="text-xs font-semibold text-[#334155] mb-3">Latest Computation (v{latestSnap.version})</p>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-[10px] text-[#94A3B8]">Taxable Income</p>
              <p className="text-sm font-semibold text-[#1E293B]">{paise(latestSnap.taxable_income_paise)}</p>
            </div>
            <div>
              <p className="text-[10px] text-[#94A3B8]">Tax Liability</p>
              <p className="text-sm font-semibold text-[#1E293B]">{paise(latestSnap.tax_liability_paise)}</p>
            </div>
            <div>
              <p className="text-[10px] text-[#94A3B8]">
                {latestSnap.is_refund ? "Refund" : "Payable"}
              </p>
              <p className={`text-sm font-semibold ${latestSnap.is_refund ? "text-green-600" : "text-red-600"}`}>
                {paise(Math.abs(latestSnap.net_payable_paise))}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 mt-3">
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
              latestSnap.status === "reviewed" ? "bg-green-100 text-green-700" :
              latestSnap.status === "finalized" ? "bg-blue-100 text-blue-700" :
              "bg-[#F1F5F9] text-[#64748B]"
            }`}>{latestSnap.status}</span>
            <span className="text-[10px] text-[#94A3B8]">
              {regimeLabel(latestSnap.regime)} · FY {latestSnap.financial_year}
            </span>
          </div>
        </div>
      )}

      {/* Computation Input Section */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
        <button
          onClick={() => toggle("compute")}
          className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-[#F8FAFC] text-left"
        >
          <p className="text-xs font-semibold text-[#334155]">Run Computation</p>
          {activeSection === "compute" ? <ChevronUp size={14} className="text-[#94A3B8]" /> : <ChevronDown size={14} className="text-[#94A3B8]" />}
        </button>

        {activeSection === "compute" && (
          <div className="px-5 pb-5 border-t border-[#F1F5F9] space-y-4 pt-4">
            <div className="flex gap-3">
              <div className="flex-1">
                <label className="text-[10px] text-[#64748B] mb-1 block">Assessment Year</label>
                <select value={ay} onChange={e => setAy(e.target.value)}
                  className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                  {AY_OPTIONS.map(a => <option key={a}>{a}</option>)}
                </select>
              </div>
              <div className="flex-1">
                {/* s.115BAC's new/old election reaches an individual or HUF.
                    A company's choice is s.115BAA / s.115BAB, which is a
                    different question with different rates and a flat 10%
                    surcharge — offering "New Regime" to a Private Limited
                    company is offering an election it cannot make. */}
                {isCompany ? (
                  <>
                    <label className="text-[10px] text-[#64748B] mb-1 block">Company Regime</label>
                    <select value={companyRegime} onChange={e => setCompanyRegime(e.target.value)}
                      className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                      <option value="normal">Normal rates — 25% or 30%</option>
                      <option value="115BAA">§115BAA — 22%</option>
                      <option value="115BAB">§115BAB — 15%, new manufacturing</option>
                    </select>
                  </>
                ) : isEntity ? (
                  <>
                    <label className="text-[10px] text-[#64748B] mb-1 block">Tax Regime</label>
                    <p className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg bg-[#F8FAFC] text-[#64748B]">
                      Flat 30% — a firm has no regime election
                    </p>
                  </>
                ) : (
                  <>
                    <label className="text-[10px] text-[#64748B] mb-1 block">Tax Regime</label>
                    <select value={regime} onChange={e => setRegime(e.target.value)}
                      className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                      <option value="new">New Regime (Default)</option>
                      <option value="old">Old Regime</option>
                    </select>
                  </>
                )}
              </div>
            </div>

            {assesseeRefusal ? (
              <p className="text-[11px] text-red-700 bg-red-50 border border-red-200 rounded-lg p-2.5">
                {assesseeRefusal}
              </p>
            ) : entityType ? (
              <p className="text-[11px] text-[#64748B]">
                Assessed as recorded on the client: <strong>{entityType}</strong>.
                {isEntity && " Taxed at a flat rate from the first rupee — no slabs, no exemption limit and no §87A rebate."}
              </p>
            ) : null}

            {/* IT-31 — the credit Form 26AS supports, beside the box the CA
                used to retype it into. Rule 37BA(1) gives credit on the basis
                of the deductor's own statement to the department, so this is
                the claim and the books are the check on it. */}
            {claim && (
              <div className={`rounded-lg border px-4 py-3 ${
                claim.available ? "border-blue-100 bg-blue-50/50" : "border-amber-200 bg-amber-50"}`}>
                {!claim.available ? (
                  <p className="text-[11px] text-amber-900">{claim.reason}</p>
                ) : (
                  <>
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="text-[11px] font-medium text-[#334155]">
                        Form 26AS supports {paise(claim.tds_claimable_paise ?? 0)} of TDS
                        {(claim.tcs_claimable_paise ?? 0) > 0 &&
                          <> and {paise(claim.tcs_claimable_paise ?? 0)} of TCS</>}
                        {(claim.tax_paid_by_client_paise ?? 0) > 0 &&
                          <>, with {paise(claim.tax_paid_by_client_paise ?? 0)} paid by the client itself</>}
                        .
                      </p>
                      {tdsTouched && (
                        <button
                          onClick={() => { setTds(String((claim.tds_claimable_paise ?? 0) / 100)); }}
                          className="text-[10px] text-blue-700 border border-blue-200 rounded-md px-2 py-0.5 hover:bg-blue-100 flex-shrink-0"
                        >
                          Use the 26AS figure
                        </button>
                      )}
                    </div>
                    {/* THE VARIANCE, STATED AND NOT RESOLVED. The CA may know
                        something 26AS does not yet show; what they must not do
                        is claim a different number without noticing. */}
                    {/* ONE money parser, and only one (CLAUDE.md).
                        `Math.round(parseFloat(tds) * 100)` reads as harmless
                        and turns a CA's "1,25,000" into ₹1 — the guard in
                        scripts/every-amount-field-uses-the-one-parser.test.ts
                        caught exactly that here. */}
                    {tdsTouched
                      && (paiseFromRupeeInput(tds || "0") ?? 0) !== (claim.tds_claimable_paise ?? 0) && (
                      <p className="text-[11px] text-amber-800 mt-1">
                        You have entered {paise(paiseFromRupeeInput(tds || "0") ?? 0)}, which is
                        not the 26AS figure. Under Rule 37BA(1) the department gives credit on the
                        deductor&apos;s statement — a claim above it is the one that comes back as a
                        §143(1) adjustment.
                      </p>
                    )}
                    {(claim.caveats ?? []).map((c, i) => (
                      <p key={i} className="text-[10px] text-[#64748B] mt-1">{c}</p>
                    ))}
                    {(claim.by_deductor ?? []).length > 0 && (
                      <details className="mt-1.5">
                        <summary className="text-[10px] text-blue-700 cursor-pointer">
                          Per deductor ({(claim.by_deductor ?? []).length})
                        </summary>
                        <table className="w-full text-[10px] mt-1">
                          <tbody>
                            {(claim.by_deductor ?? []).map((d, i) => (
                              <tr key={i} className="border-t border-blue-100">
                                <td className="py-0.5 pr-2 text-[#334155]">{d.deductor_name}</td>
                                <td className="py-0.5 pr-2 text-[#94A3B8]">{d.deductor_tan ?? "—"}</td>
                                <td className="py-0.5 pr-2 uppercase text-[#94A3B8]">{d.kind}</td>
                                <td className="py-0.5 text-right tabular-nums text-[#334155]">
                                  {paise(d.claimable_paise)}
                                </td>
                                <td className="py-0.5 pl-2 text-right tabular-nums text-amber-700">
                                  {d.provisional_paise > 0 ? `+${paise(d.provisional_paise)} not final` : ""}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </details>
                    )}
                  </>
                )}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "Gross Salary (₹)", value: salary, set: setSalary },
                { label: "Business Income (₹)", value: businessIncome, set: setBusinessIncome },
                { label: "Other Income (₹)", value: otherIncome, set: setOtherIncome },
                { label: "TDS Deducted (₹)", value: tds,
                  set: (v: string) => { setTdsTouched(true); setTds(v); } },
                { label: "Advance Tax Paid (₹)", value: advanceTax, set: setAdvanceTax },
                // IT-05 — the heads the endpoint has always accepted and this
                // screen never sent. A house-property LOSS is entered with a
                // leading minus; §71(3A) caps the set-off at ₹2,00,000 under
                // the old regime and §115BAC(2) allows none at all under the
                // new one, and the server decides which.
                { label: "House Property Income (₹)", value: housePropertyIncome,
                  set: setHousePropertyIncome, hint: "Negative for a loss" },
                { label: "Short-Term Capital Gains (₹)", value: stcg, set: setStcg },
                { label: "LTCG — listed equity, §112A (₹)", value: ltcgEquity, set: setLtcgEquity },
                { label: "LTCG — property, debt etc (₹)", value: ltcgOther, set: setLtcgOther },
                { label: "Exempt Income (₹)", value: exemptIncome, set: setExemptIncome },
              ].map(({ label, value, set, hint }) => (
                <div key={label}>
                  <label className="text-[10px] text-[#64748B] mb-1 block">{label}</label>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={value}
                    onChange={e => set(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="0"
                  />
                  {hint && <p className="text-[10px] text-[#94A3B8] mt-0.5">{hint}</p>}
                </div>
              ))}
            </div>

            {/* IT-16 — the presumptive schemes. The engine has honoured
                `presumptive_income_paise` since IT-01 and the three endpoints
                have existed since; no screen sent any of it, so a §44AD client
                — the commonest small-business return in an Indian practice —
                had to have its deemed income worked out somewhere else and
                typed in as business income.

                The picker is offered to every assessee on purpose. §44AD and
                §44ADA name who they reach and the SERVER answers on the
                client's recorded entity type; a list of eligible kinds in this
                file would be a second copy of the section. */}
            <div className="space-y-3 border-t border-[#F1F5F9] pt-3">
              <div className="flex items-center gap-3">
                <label className="text-[11px] font-semibold text-[#334155] whitespace-nowrap">
                  Presumptive scheme
                </label>
                <select value={presumptiveScheme}
                  onChange={e => { setPresumptiveScheme(e.target.value);
                                   setPresResult(null); setPresError(null); }}
                  className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                  <option value="">None — books of account</option>
                  <option value="44ad">§44AD — eligible business</option>
                  <option value="44ada">§44ADA — specified profession</option>
                  <option value="44ae">§44AE — goods carriages</option>
                </select>
              </div>

              {presumptiveScheme && (
                <>
                  <p className="text-[10px] text-[#94A3B8]">
                    A presumptive figure REPLACES the business income above and
                    every accepted disallowance — §44AD(2), §44ADA(3) and
                    §44AE(6) each deem the deductions already allowed.
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    {(presumptiveScheme === "44ad"
                      ? [
                          { label: "Turnover (₹)", value: presTurnover, set: setPresTurnover },
                          { label: "Of which received through a bank (₹)", value: presDigital,
                            set: setPresDigital,
                            hint: "6% on this part, 8% on the rest — §44AD(1) proviso" },
                          { label: "Cash receipts (₹)", value: presCash, set: setPresCash,
                            hint: "Within 5% of turnover raises the ceiling to ₹3 crore" },
                        ]
                      : presumptiveScheme === "44ada"
                      ? [
                          { label: "Gross receipts (₹)", value: presGross, set: setPresGross },
                          { label: "Cash receipts (₹)", value: presCash, set: setPresCash,
                            hint: "Within 5% raises the ceiling to ₹75 lakh" },
                        ]
                      : []
                    ).map(({ label, value, set, hint }) => (
                      <div key={label}>
                        <label className="text-[10px] text-[#64748B] mb-1 block">{label}</label>
                        <input type="text" inputMode="decimal" value={value}
                          onChange={e => set(e.target.value)}
                          className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                          placeholder="0" />
                        {hint && <p className="text-[10px] text-[#94A3B8] mt-0.5">{hint}</p>}
                      </div>
                    ))}
                    <div>
                      <label className="text-[10px] text-[#64748B] mb-1 block">
                        Income declared, if higher (₹)
                      </label>
                      <input type="text" inputMode="decimal" value={presDeclared}
                        onChange={e => setPresDeclared(e.target.value)}
                        className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        placeholder="Blank uses the deemed figure" />
                      <p className="text-[10px] text-[#94A3B8] mt-0.5">
                        Declaring LESS is refused — §44AD(5) then requires books
                        under §44AA and an audit under §44AB.
                      </p>
                    </div>
                  </div>

                  {presumptiveScheme === "44ae" && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <p className="text-[11px] font-semibold text-[#334155]">
                          Goods carriages
                          <span className="font-normal text-[#94A3B8]">
                            {" "}— §44AE charges per vehicle per month
                          </span>
                        </p>
                        <button type="button"
                          onClick={() => setPresVehicles(v => [...v, { weight: "", months: "12" }])}
                          className="text-[11px] text-blue-600 hover:text-blue-700 flex items-center gap-1">
                          <Plus className="w-3 h-3" /> Add carriage
                        </button>
                      </div>
                      {presVehicles.map((v, i) => (
                        <div key={i} className="grid grid-cols-12 gap-2">
                          <input type="text" inputMode="numeric" value={v.weight}
                            placeholder="Gross vehicle weight (kg)"
                            onChange={e => setPresVehicles(rows => rows.map((r, j) =>
                              j === i ? { ...r, weight: e.target.value } : r))}
                            className="col-span-6 text-xs px-2 py-1.5 border border-[#E2E8F0] rounded-lg" />
                          <input type="text" inputMode="numeric" value={v.months}
                            placeholder="Months owned"
                            onChange={e => setPresVehicles(rows => rows.map((r, j) =>
                              j === i ? { ...r, months: e.target.value } : r))}
                            className="col-span-5 text-xs px-2 py-1.5 border border-[#E2E8F0] rounded-lg" />
                          <button type="button" aria-label="Remove carriage"
                            onClick={() => setPresVehicles(rows => rows.filter((_, j) => j !== i))}
                            className="col-span-1 text-[11px] text-[#94A3B8] hover:text-red-600">
                            ×
                          </button>
                        </div>
                      ))}
                      <p className="text-[10px] text-[#94A3B8]">
                        A part of a month counts as a whole one. Over 12,000 kg is
                        charged per tonne of gross weight; at or under, a flat rate.
                      </p>
                    </div>
                  )}

                  <button type="button" onClick={handlePresumptive}
                    disabled={actionInFlight}
                    className="text-xs px-3 py-1.5 bg-[#0F172A] text-white rounded-lg disabled:opacity-50">
                    {presComputing ? "Computing…" : "Compute presumptive income"}
                  </button>

                  {presError && (
                    <p className="text-[11px] text-red-700 bg-red-50 border border-red-200 rounded-lg p-2.5">
                      {presError}
                    </p>
                  )}

                  {presResult && (
                    <div className={`rounded-lg border p-3 space-y-1.5 ${
                      presResult.eligible
                        ? "border-[#E2E8F0] bg-[#F8FAFC]"
                        : "border-amber-200 bg-amber-50"}`}>
                      <p className="text-xs font-semibold text-[#0F172A]">
                        {presResult.eligible
                          ? `${presResult.section} — ${paise(presResult.declared_income_paise)} will be taken as the business income`
                          : `${presResult.section} is not available`}
                      </p>
                      {presResult.workings.map((w, i) => (
                        <p key={i} className="text-[10px] text-[#64748B]">{w}</p>
                      ))}
                      {presResult.reasons.map((r, i) => (
                        <p key={i} className="text-[10px] text-[#92400E]">{r}</p>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* WHO THE ASSESSEE IS, under BOTH regimes.
                Residence is not a deduction and §80CCD(2) is the one Chapter
                VI-A head §115BAC(2) leaves standing, so neither belongs behind
                the old-regime gate below. */}
            {!isEntity && (
              <div className="space-y-3 border-t border-[#F1F5F9] pt-3">
                <p className="text-[11px] font-semibold text-[#334155]">
                  Residence and employer NPS
                  <span className="font-normal text-[#94A3B8]"> — both regimes</span>
                </p>
                <label className="flex items-start gap-1.5 text-[11px] text-[#334155]">
                  <input type="checkbox" checked={isResident} className="mt-0.5"
                    onChange={e => setIsResident(e.target.checked)} />
                  <span>
                    Resident in India
                    <span className="block text-[10px] text-[#94A3B8]">
                      Unused basic exemption may be set against a capital gain only
                      for a RESIDENT individual — the provisos to §111A(1),
                      §112(1)(a)(ii) and §112A(2). Clearing this withdraws it.
                    </span>
                  </span>
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-[#64748B] mb-1 block">
                      §80CCD(2) — employer NPS contribution (₹)
                    </label>
                    <input type="text" inputMode="decimal" value={employerNps}
                      onChange={e => setEmployerNps(e.target.value)}
                      className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="0" />
                    <p className="text-[10px] text-[#94A3B8] mt-0.5">
                      Allowed under the new regime too — §115BAC(2) withdraws the
                      rest of Chapter VI-A and leaves this.
                    </p>
                  </div>
                  <div>
                    <label className="text-[10px] text-[#64748B] mb-1 block">
                      Salary for the §80CCD(2) ceiling (₹)
                    </label>
                    <input type="text" inputMode="decimal" value={nps80ccd2Salary}
                      onChange={e => setNps80ccd2Salary(e.target.value)}
                      className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="Blank uses the gross salary above" />
                    <p className="text-[10px] text-[#94A3B8] mt-0.5">
                      Basic + dearness allowance, not the gross.
                    </p>
                  </div>
                </div>
                <label className="flex items-center gap-1.5 text-[11px] text-[#334155]">
                  <input type="checkbox" checked={isGovtEmployee}
                    onChange={e => setIsGovtEmployee(e.target.checked)} />
                  Employed by the Central or a State Government
                  <span className="text-[10px] text-[#94A3B8]">(a higher §80CCD(2) ceiling)</span>
                </label>
              </div>
            )}

            {/* Chapter VI-A and §24(b). Shown only for an individual on the
                OLD regime, because that is the only assessee they reach:
                §115BAC(2) allows §80CCD(2) and §80JJAA and nothing else, and
                a firm or company is on the flat entity rate. Offering boxes
                that cannot change the answer is worse than not offering
                them — it reads as relief that was claimed and refused. */}
            {!isEntity && regime === "old" && (
              <div className="space-y-3 border-t border-[#F1F5F9] pt-3">
                <p className="text-[11px] font-semibold text-[#334155]">
                  Chapter VI-A deductions
                  <span className="font-normal text-[#94A3B8]"> — old regime only</span>
                </p>
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: "Section 80C (₹)", value: s80cTotal, set: setS80cTotal,
                      hint: "PPF, ELSS, LIC, principal, tuition — ceiling ₹1,50,000" },
                    { label: "80D — self and family (₹)", value: s80dSelf, set: setS80dSelf },
                    { label: "80D — parents (₹)", value: s80dParents, set: setS80dParents },
                    { label: "80TTA — savings interest (₹)", value: savingsInterest80tta,
                      set: setSavingsInterest80tta },
                    { label: "§24(b) — home loan interest (₹)", value: homeLoanInterest24b,
                      set: setHomeLoanInterest24b },
                    { label: "Other deductions (₹)", value: otherDeductions, set: setOtherDeductions },
                  ].map(({ label, value, set, hint }) => (
                    <div key={label}>
                      <label className="text-[10px] text-[#64748B] mb-1 block">{label}</label>
                      <input type="text" inputMode="decimal" value={value}
                        onChange={e => set(e.target.value)}
                        className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        placeholder="0" />
                      {hint && <p className="text-[10px] text-[#94A3B8] mt-0.5">{hint}</p>}
                    </div>
                  ))}
                </div>
                <div className="flex flex-wrap gap-4">
                  {[
                    { label: "80D: self/family is a senior citizen", v: s80dSelfSenior, set: setS80dSelfSenior },
                    { label: "80D: parents are senior citizens", v: s80dParentsSenior, set: setS80dParentsSenior },
                    { label: "Assessee is a senior citizen (60+)", v: isSenior, set: setIsSenior },
                    { label: "Assessee is very senior (80+)", v: isVerySenior, set: setIsVerySenior },
                  ].map(({ label, v, set }) => (
                    <label key={label} className="flex items-center gap-1.5 text-[11px] text-[#334155]">
                      <input type="checkbox" checked={v} onChange={e => set(e.target.checked)} />
                      {label}
                    </label>
                  ))}
                </div>

                {/* §80CCD(1B) — the assessee's OWN NPS, ₹50,000 over and above
                    the §80C ceiling. Separate from the employer's contribution
                    above: different sub-section, different limit, and only
                    this one is withdrawn by §115BAC(2). */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-[#64748B] mb-1 block">
                      §80CCD(1B) — own NPS (₹)
                    </label>
                    <input type="text" inputMode="decimal" value={nps80ccd1b}
                      onChange={e => setNps80ccd1b(e.target.value)}
                      className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="0" />
                    <p className="text-[10px] text-[#94A3B8] mt-0.5">
                      Ceiling ₹50,000, in addition to §80C.
                    </p>
                  </div>
                </div>

                {/* §10(13A) with Rule 2A. The exemption is the LEAST of three
                    figures — the HRA received, rent less 10% of salary, and
                    50% or 40% of salary — so all four facts are needed and the
                    server computes it. This is the largest relief the screen
                    was not collecting: an old-regime salaried client paying
                    rent had it omitted entirely. */}
                <div className="space-y-2">
                  <p className="text-[11px] font-semibold text-[#334155]">
                    House rent allowance — §10(13A)
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    {[
                      { label: "Basic salary + DA (₹)", value: hraBasic, set: setHraBasic,
                        hint: "Rule 2A reads 'salary' as basic plus dearness allowance" },
                      { label: "HRA received (₹)", value: hraReceived, set: setHraReceived },
                      { label: "Rent actually paid (₹)", value: hraRent, set: setHraRent },
                    ].map(({ label, value, set, hint }) => (
                      <div key={label}>
                        <label className="text-[10px] text-[#64748B] mb-1 block">{label}</label>
                        <input type="text" inputMode="decimal" value={value}
                          onChange={e => set(e.target.value)}
                          className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                          placeholder="0" />
                        {hint && <p className="text-[10px] text-[#94A3B8] mt-0.5">{hint}</p>}
                      </div>
                    ))}
                  </div>
                  <label className="flex items-center gap-1.5 text-[11px] text-[#334155]">
                    <input type="checkbox" checked={hraMetro}
                      onChange={e => setHraMetro(e.target.checked)} />
                    Accommodation is in Delhi, Mumbai, Kolkata or Chennai
                    <span className="text-[10px] text-[#94A3B8]">(50% of salary, else 40%)</span>
                  </label>
                </div>

                {/* §80G. Two facts about the DONEE, not one: the percentage and
                    whether the qualifying limit applies are independent, and
                    §80G(5D) bars a cash donation over ₹2,000 outright. */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-semibold text-[#334155]">
                      Donations — §80G
                    </p>
                    <button type="button"
                      onClick={() => setDonations(d => [...d, {
                        description: "", amount: "", pct: 50,
                        subjectToLimit: true, paidInCash: "",
                      }])}
                      className="text-[11px] text-blue-600 hover:text-blue-700 flex items-center gap-1">
                      <Plus className="w-3 h-3" /> Add donation
                    </button>
                  </div>
                  {donations.length === 0 && (
                    <p className="text-[10px] text-[#94A3B8]">
                      None recorded. §80G(4) caps the residual category at 10% of
                      adjusted gross total income, so the ceiling depends on the
                      rest of the computation and is applied last.
                    </p>
                  )}
                  {donations.map((d, i) => (
                    <div key={i} className="grid grid-cols-12 gap-2 items-start">
                      <input type="text" value={d.description} placeholder="Donee"
                        onChange={e => setDonations(rows => rows.map((r, j) =>
                          j === i ? { ...r, description: e.target.value } : r))}
                        className="col-span-4 text-xs px-2 py-1.5 border border-[#E2E8F0] rounded-lg" />
                      <input type="text" inputMode="decimal" value={d.amount} placeholder="Amount (₹)"
                        onChange={e => setDonations(rows => rows.map((r, j) =>
                          j === i ? { ...r, amount: e.target.value } : r))}
                        className="col-span-2 text-xs px-2 py-1.5 border border-[#E2E8F0] rounded-lg" />
                      <select value={d.pct}
                        onChange={e => setDonations(rows => rows.map((r, j) =>
                          j === i ? { ...r, pct: Number(e.target.value) } : r))}
                        className="col-span-2 text-xs px-2 py-1.5 border border-[#E2E8F0] rounded-lg">
                        <option value={50}>50%</option>
                        <option value={100}>100%</option>
                      </select>
                      <select value={d.paidInCash}
                        onChange={e => setDonations(rows => rows.map((r, j) =>
                          j === i ? { ...r, paidInCash: e.target.value as DonationRow["paidInCash"] } : r))}
                        className="col-span-3 text-xs px-2 py-1.5 border border-[#E2E8F0] rounded-lg">
                        <option value="">Mode not stated</option>
                        <option value="no">Cheque, draft or bank</option>
                        <option value="yes">Cash</option>
                      </select>
                      <button type="button" aria-label="Remove donation"
                        onClick={() => setDonations(rows => rows.filter((_, j) => j !== i))}
                        className="col-span-1 text-[11px] text-[#94A3B8] hover:text-red-600 py-1.5">
                        ×
                      </button>
                      <label className="col-span-12 flex items-center gap-1.5 text-[10px] text-[#64748B] -mt-1">
                        <input type="checkbox" checked={d.subjectToLimit}
                          onChange={e => setDonations(rows => rows.map((r, j) =>
                            j === i ? { ...r, subjectToLimit: e.target.checked } : r))} />
                        Subject to the §80G(4) qualifying limit
                        <span className="text-[#94A3B8]">
                          — clear it only for a fund listed in §80G(1)(i), such as the
                          PM National Relief Fund
                        </span>
                      </label>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {isEntity && (
              <div className="grid grid-cols-2 gap-3">
                {isCompany && (
                  <div>
                    <label className="text-[10px] text-[#64748B] mb-1 block">
                      Turnover in {computeResult?.assessee?.turnover_reference_fy ?? "the reference year"} (₹)
                    </label>
                    <input type="text" inputMode="decimal" value={turnoverRefYear}
                      onChange={e => setTurnoverRefYear(e.target.value)}
                      className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="Leave blank for 30%" />
                    {/* The 25% concession looks at the turnover of a year TWO
                        BACK, not the year being taxed. Left blank, the higher
                        rate is used: a concession has to be established. */}
                    <p className="text-[10px] text-[#94A3B8] mt-0.5">
                      Two years back — not this year. Under ₹400 crore gives 25%.
                    </p>
                  </div>
                )}
                <div>
                  <label className="text-[10px] text-[#64748B] mb-1 block">
                    {isCompany ? "Book profit — §115JB (₹)" : "Adjusted total income — §115JC (₹)"}
                  </label>
                  <input type="text" inputMode="decimal" value={bookProfit}
                    onChange={e => setBookProfit(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder={isCompany ? "Companies Act profit as adjusted" : "Total income with §10AA/§35AD/VI-A Part C added back"} />
                  <p className="text-[10px] text-[#94A3B8] mt-0.5">
                    {isCompany
                      ? "Not taxable income — the gap between them is why §115JB exists."
                      : "Total income with the §10AA, §35AD and Chapter VI-A Part C deductions added back."}
                  </p>
                </div>
                {!isCompany && (
                  <label className="flex items-start gap-2 text-[11px] text-[#475569] col-span-2">
                    <input type="checkbox" checked={claimedSpecifiedDeduction}
                      onChange={e => setClaimedSpecifiedDeduction(e.target.checked)}
                      className="mt-0.5" />
                    <span>
                      A §10AA, §35AD or Chapter VI-A Part C deduction was claimed.
                      §115JC applies only where one was — an assessee who claimed
                      none is outside Chapter XII-BA entirely, not below a threshold.
                    </span>
                  </label>
                )}
              </div>
            )}

            {computeError && <p className="text-xs text-red-600">{computeError}</p>}

            <button
              onClick={handleCompute}
              // No year resolved means the server never told us which years it
              // can compute. Posting fy:"" would take the engine's own default
              // and put a figure on screen for a year nobody chose.
              disabled={actionInFlight || !fy || assesseeRefusal !== null}
              className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {computing && <Loader2 size={12} className="animate-spin" />}
              <Save size={12} />
              Compute &amp; Save Snapshot
            </button>

            {computeResult && computeResult.fy && computeResult.fy !== fy && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
                <p className="text-[11px] text-amber-800">
                  Computed at <strong>FY {computeResult.fy}</strong> rates, not
                  FY {fy} — this build has no rate table for the year you
                  selected. Treat the figures as indicative only.
                </p>
              </div>
            )}
            {computeResult && computeResult.rates_verified === false && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
                <p className="text-[11px] text-amber-800">
                  FY {computeResult.fy} rates are <strong>provisional</strong> —
                  carried forward pending the Finance Act.
                </p>
              </div>
            )}
            {computeResult && (
              <div className="bg-[#F8FAFC] rounded-xl p-4 space-y-2">
                <p className="text-xs font-semibold text-[#334155]">Result</p>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <p className="text-[#94A3B8]">Taxable Income</p>
                    <p className="font-medium">{paise(computeResult.income?.taxable_income_paise ?? 0)}</p>
                  </div>
                  <div>
                    <p className="text-[#94A3B8]">Tax Liability</p>
                    <p className="font-medium">{paise(computeResult.tax?.total_tax_paise ?? 0)}</p>
                  </div>
                  {/* §87A reaches "an individual, being a resident". Showing a
                      "Rebate 87A" line reading ₹0 to a company implies a relief
                      it was never eligible for; the rate it WAS charged at is
                      the useful figure in its place. */}
                  {computeResult.assessee && computeResult.assessee.kind !== "individual" ? (
                    <div>
                      <p className="text-[#94A3B8]">Rate charged</p>
                      <p className="font-medium">
                        {computeResult.assessee.rate_percent}%
                        {computeResult.assessee.turnover_reference_fy
                          ? ` · turnover test on FY ${computeResult.assessee.turnover_reference_fy}`
                          : ""}
                      </p>
                    </div>
                  ) : (
                    <div>
                      <p className="text-[#94A3B8]">Rebate 87A</p>
                      <p className="font-medium">{paise(computeResult.tax?.rebate_87a_paise ?? 0)}</p>
                    </div>
                  )}
                  <div>
                    <p className="text-[#94A3B8]">{computeResult.payable?.is_refund ? "Refund" : "Net Payable"}</p>
                    <p className={`font-medium ${computeResult.payable?.is_refund ? "text-green-600" : "text-red-600"}`}>
                      {paise(Math.abs(computeResult.payable?.net_payable_paise ?? 0))}
                    </p>
                  </div>
                </div>
                {/* §115JB / §115JC. The CREDIT is the reason this is on the
                    screen at all: §115JAA and §115JD carry the excess forward
                    for fifteen assessment years, and a floor charged without
                    the credit recorded turns a timing difference into a
                    permanent cost that is invisible in the year it arises. */}
                {computeResult.minimum_tax?.applied && (
                  <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 space-y-1">
                    <p className="text-[11px] font-medium text-amber-900">
                      §{computeResult.minimum_tax.section} minimum tax applies —{" "}
                      {paise(computeResult.minimum_tax.minimum_tax_paise)} is payable
                      instead of the ordinary computation.
                    </p>
                    <p className="text-[11px] text-amber-900">
                      Credit carried forward:{" "}
                      <strong>{paise(computeResult.minimum_tax.credit_paise)}</strong>
                      {computeResult.minimum_tax.credit_expires_after_ay
                        ? ` — available until AY ${computeResult.minimum_tax.credit_expires_after_ay}`
                        : ""}
                      .
                    </p>
                    {computeResult.minimum_tax.reasons?.map((r: string, i: number) => (
                      <p key={i} className="text-[10px] text-amber-800">{r}</p>
                    ))}
                  </div>
                )}
                {computeResult.assessee?.workings?.length ? (
                  <div className="mt-2 space-y-0.5">
                    {computeResult.assessee.workings.map((w: string, i: number) => (
                      <p key={i} className="text-[10px] text-[#64748B]">{w}</p>
                    ))}
                  </div>
                ) : null}
                {/* IT-08's own working, which used to stop inside the engine.
                    Only the rows that carry a figure are listed: three zero
                    rows on a return with no capital gains is noise, and the
                    absorption line below states the total whether or not a
                    row shows it. */}
                {computeResult.capital_gains?.lines?.some(
                  l => l.gross_paise > 0) ? (
                  <div className="mt-3 border-t border-[#F1F5F9] pt-2 space-y-1.5">
                    <p className="text-[10px] font-semibold text-[#334155]">
                      Capital gains — {paise(computeResult.capital_gains.tax_paise)} tax
                    </p>
                    {computeResult.capital_gains.lines
                      .filter(l => l.gross_paise > 0)
                      .map((l, i) => (
                        <p key={i} className="text-[10px] text-[#1E293B]">
                          <span className="font-mono">{l.section}</span> —{" "}
                          {paise(l.gross_paise)} gain
                          {l.exempt_paise > 0 ? `, less ${paise(l.exempt_paise)} exempt` : ""}
                          {l.absorbed_paise > 0
                            ? `, less ${paise(l.absorbed_paise)} basic exemption`
                            : ""}
                          , {paise(l.charged_paise)} charged at {l.rate_percent}% ={" "}
                          {paise(l.tax_paise)}
                        </p>
                      ))}
                    {computeResult.capital_gains.basic_exemption_absorption.map((w, i) => (
                      <p key={i} className="text-[10px] text-[#64748B] pl-3">{w}</p>
                    ))}
                    {computeResult.capital_gains.basic_exemption_absorbed_paise > 0 && (
                      <p className="text-[10px] text-[#94A3B8] pl-3">
                        The order is the engine&apos;s choice — the provisos to §111A(1),
                        §112(1)(a)(ii) and §112A(2) fix none, so the exemption is set
                        against the highest-rate gain first.
                      </p>
                    )}
                  </div>
                ) : null}
                {/* Received, not taxable — said rather than left to be inferred
                    from a figure that does not appear anywhere in the result. */}
                {(computeResult.exempt_income?.reported_paise ?? 0) > 0 && (
                  <p className="mt-2 text-[10px] text-[#64748B]">
                    Exempt income {paise(computeResult.exempt_income!.reported_paise)} —{" "}
                    {computeResult.exempt_income!.note}
                  </p>
                )}
                {/* IT-10. Which section reached which head, per loss — and a
                    loss that found no home shown as such, with the reason. A
                    zero beside "set off" and a loss simply missing from the
                    list are opposite statements, and the CA needs the first. */}
                {computeResult.brought_forward?.lines?.length ? (
                  <div className="mt-3 border-t border-[#F1F5F9] pt-2 space-y-1.5">
                    <p className="text-[10px] font-semibold text-[#334155]">
                      Brought-forward losses — {paise(computeResult.brought_forward.set_off_paise)} set off
                    </p>
                    {computeResult.brought_forward.lines.map((ln, i) => (
                      <div key={i} className="text-[10px]">
                        <p className={ln.set_off_paise > 0 ? "text-[#1E293B]" : "text-[#94A3B8]"}>
                          <span className="font-mono">{ln.section}</span>{" "}
                          {ln.loss_type.replace(/_/g, " ")} — {paise(ln.set_off_paise)} set off
                          {ln.against.length ? ` against ${ln.against.join(", ").replace(/_/g, " ")}` : ""}
                          {ln.carried_forward_paise > 0
                            ? `, ${paise(ln.carried_forward_paise)} carried forward`
                            : ""}
                        </p>
                        {ln.reasons.map((r, j) => (
                          <p key={j} className="text-[10px] text-[#94A3B8] pl-3">{r}</p>
                        ))}
                      </div>
                    ))}
                  </div>
                ) : null}
                {(computeResult.warnings?.length > 0) && (
                  <div className="mt-2 space-y-1">
                    {computeResult.warnings.map((w: string, i: number) => (
                      <p key={i} className="text-[10px] text-amber-600">⚠ {w}</p>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Disallowances Section */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
        <button
          onClick={() => toggle("disallowances")}
          className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-[#F8FAFC]"
        >
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold text-[#334155]">Disallowances</p>
            <span className="text-[10px] px-1.5 py-0.5 bg-red-50 text-red-600 rounded-full">
              {disallowances.length}
            </span>
          </div>
          {activeSection === "disallowances" ? <ChevronUp size={14} className="text-[#94A3B8]" /> : <ChevronDown size={14} className="text-[#94A3B8]" />}
        </button>

        {activeSection === "disallowances" && (
          <div className="px-5 pb-5 border-t border-[#F1F5F9] pt-4 space-y-3">
            <p className="text-[11px] text-[#64748B]">
              IT Act §40A(3): Cash payments &gt;₹10,000 | §43B: Unpaid statutory liabilities
            </p>

            {disallowances.length === 0 ? (
              <p className="text-xs text-[#94A3B8] py-4 text-center">No disallowances recorded</p>
            ) : (
              <div className="space-y-2">
                {disallowances.map(d => (
                  <div key={d.id} className="flex items-center justify-between p-3 bg-[#F8FAFC] rounded-lg">
                    <div>
                      <p className="text-xs font-medium text-[#1E293B]">{d.description}</p>
                      <p className="text-[10px] text-[#94A3B8]">
                        §{d.section} · {d.auto_detected ? "Auto-detected" : "Manual"}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs font-semibold text-red-600">{paise(d.amount_paise)}</p>
                      <span className={`text-[10px] ${d.status === "accepted" ? "text-green-600" : d.status === "rejected" ? "text-red-500" : "text-amber-600"}`}>
                        {d.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {!showDisallForm ? (
              <button
                onClick={() => setShowDisallForm(true)}
                className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
              >
                <Plus size={12} /> Add Disallowance
              </button>
            ) : (
              <div className="border border-[#E2E8F0] rounded-xl p-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-[#64748B] mb-1 block">Section</label>
                    <select value={disallSection} onChange={e => setDisallSection(e.target.value)}
                      className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                      {SECTION_OPTIONS.map(s => <option key={s}>{s}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-[#64748B] mb-1 block">Amount (₹)</label>
                    <input type="number" value={disallAmount} onChange={e => setDisallAmount(e.target.value)}
                      className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" placeholder="0" />
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-[#64748B] mb-1 block">Description</label>
                  <input value={disallDesc} onChange={e => setDisallDesc(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" placeholder="Payment description" />
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setShowDisallForm(false)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded">Cancel</button>
                  <button
                    onClick={handleSaveDisallowance}
                    disabled={actionInFlight || !disallDesc || !disallAmount}
                    className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50 flex items-center gap-1"
                  >
                    {savingDisall && <Loader2 size={10} className="animate-spin" />}
                    Save
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Brought Forward Losses */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
        <button
          onClick={() => toggle("losses")}
          className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-[#F8FAFC]"
        >
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold text-[#334155]">Brought Forward Losses</p>
            <span className="text-[10px] px-1.5 py-0.5 bg-amber-50 text-amber-600 rounded-full">
              {bfLosses.length}
            </span>
          </div>
          {activeSection === "losses" ? <ChevronUp size={14} className="text-[#94A3B8]" /> : <ChevronDown size={14} className="text-[#94A3B8]" />}
        </button>

        {activeSection === "losses" && (
          <div className="px-5 pb-5 border-t border-[#F1F5F9] pt-4 space-y-3">
            <p className="text-[11px] text-[#64748B]">IT Act §72 (Business, 8 yrs) · §74 (Capital, 8 yrs)</p>
            {bfLosses.length === 0 ? (
              <p className="text-xs text-[#94A3B8] py-4 text-center">No carried-forward losses recorded</p>
            ) : (
              <div className="space-y-2">
                {bfLosses.map(l => (
                  <div key={l.id} className="flex items-center justify-between p-3 bg-[#F8FAFC] rounded-lg">
                    <div>
                      <p className="text-xs font-medium text-[#1E293B] capitalize">
                        {l.loss_type.replace(/_/g, " ")} Loss — AY {l.assessment_year}
                      </p>
                      <p className="text-[10px] text-[#94A3B8]">Expires AY {l.expiry_assessment_year}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs font-semibold text-[#1E293B]">{paise(l.remaining_amount_paise)}</p>
                      <p className="text-[10px] text-[#94A3B8]">remaining of {paise(l.original_amount_paise)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Snapshot History */}
      {snapshots.length > 0 && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
          <button
            onClick={() => toggle("history")}
            className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-[#F8FAFC]"
          >
            <p className="text-xs font-semibold text-[#334155]">Computation History ({snapshots.length} versions)</p>
            {activeSection === "history" ? <ChevronUp size={14} className="text-[#94A3B8]" /> : <ChevronDown size={14} className="text-[#94A3B8]" />}
          </button>
          {activeSection === "history" && (
            <div className="px-5 pb-5 border-t border-[#F1F5F9] pt-4 space-y-2">
              {snapshots.map(s => (
                <div key={s.id} className="flex items-center justify-between p-3 bg-[#F8FAFC] rounded-lg">
                  <div>
                    <p className="text-xs font-medium text-[#1E293B]">Version {s.version} — {regimeLabel(s.regime)}</p>
                    <p className="text-[10px] text-[#94A3B8]">{new Date(s.created_at).toLocaleDateString("en-IN")}</p>
                  </div>
                  <div className="text-right flex items-center gap-2">
                    {s.status !== "reviewed" && (
                      <button
                        onClick={() => markSnapshotReviewed(s.id)}
                        disabled={reviewing !== null}
                        className="text-[10px] px-2 py-1 border border-[#E2E8F0] rounded-md text-[#475569] hover:bg-white disabled:opacity-50"
                        title="A filing cannot leave draft while the computation it pins is unreviewed"
                      >
                        {reviewing === s.id ? "Marking…" : "Mark reviewed"}
                      </button>
                    )}
                    {s.status === "reviewed" && <CheckCircle size={12} className="text-green-500" />}
                    <div>
                      <p className="text-xs font-semibold text-[#1E293B]">
                        {s.is_refund ? "+" : ""}{paise(Math.abs(s.net_payable_paise))}
                      </p>
                      <p className={`text-[10px] ${s.is_refund ? "text-green-600" : "text-red-500"}`}>
                        {s.is_refund ? "Refund" : "Payable"}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
              {reviewError && (
                <p className="text-[11px] text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {reviewError}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
