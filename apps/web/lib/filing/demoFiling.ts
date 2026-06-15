/**
 * DEMO MODE filing simulation — pure helpers (PR-3).
 *
 * This powers a WORKFLOW SIMULATION ONLY. Nothing here submits anything to any
 * government portal, and the references it generates are deliberately, visibly
 * fake (DEMO-/SIM- prefixed) so a simulated filing can never be mistaken for a
 * real one. Kept pure so it is unit-tested.
 */

/** Required banner copy — shown on every screen of the simulation. */
export const DEMO_BANNER_TITLE = "DEMO MODE";
export const DEMO_BANNER_BODY =
  "No data is being submitted to any government portal. This is a workflow simulation only.";

/** Status label for a simulated filing — NEVER the bare word "Filed". */
export const DEMO_STATUS_LABEL = "Demo Filed";
export const DEMO_STATUS_LONG = "Simulated Filing Complete";

/**
 * Which compliance types can be simulated, and which demo reference scheme each
 * uses. Period-return filings only:
 *   - GST returns      → SIM-GST-…  (GST portal)
 *   - ITR / TDS / TCS  → DEMO-ARN-… (Acknowledgement Reference Number)
 *   - MCA forms        → DEMO-SRN-… (Service Request Number)
 * Advance tax is a payment, not a return, so it is intentionally NOT simulatable.
 */
export type DemoScheme = "gst" | "arn" | "srn";

const SCHEME_BY_TYPE: Record<string, DemoScheme> = {
  GSTR1: "gst",
  GSTR3B: "gst",
  GSTR9: "gst",
  ITR: "arn",
  TDS24Q: "arn",
  TDS26Q: "arn",
  TCS_RETURN: "arn",
  MCA_AOC4: "srn",
  MCA_MGT7: "srn",
};

const SCHEME_PREFIX: Record<DemoScheme, string> = {
  gst: "SIM-GST-",
  arn: "DEMO-ARN-",
  srn: "DEMO-SRN-",
};

export function isSimulatable(complianceType: string): boolean {
  return complianceType in SCHEME_BY_TYPE;
}

export function demoScheme(complianceType: string): DemoScheme | null {
  return SCHEME_BY_TYPE[complianceType] ?? null;
}

/**
 * Generate a clearly-fake demo reference for a compliance type.
 * Always `<PREFIX><8 uppercase base36 chars>`, e.g. "SIM-GST-3F7K9Q0A".
 * The DEMO-/SIM- prefix and embedded letters mean it can never collide with a
 * real government reference (which are fixed-format all-digit/MCA codes).
 *
 * `rand` is injectable for deterministic tests.
 */
export function generateDemoReference(
  complianceType: string,
  rand: () => number = Math.random,
): string {
  const scheme = SCHEME_BY_TYPE[complianceType] ?? "arn";
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  let suffix = "";
  for (let i = 0; i < 8; i++) {
    suffix += alphabet[Math.floor(rand() * alphabet.length)];
  }
  return SCHEME_PREFIX[scheme] + suffix;
}

/**
 * Guard: is this string one of our demo references (and therefore safe to show)?
 * Used to assert we never persist/display a non-demo reference from this flow.
 */
export function isDemoReference(ref: string): boolean {
  return /^(SIM-GST-|DEMO-ARN-|DEMO-SRN-)[A-Z0-9]{4,}$/.test(ref);
}

export interface SimulatableEntry {
  compliance_type: string;
  period_start?: string;
  period_end?: string;
  due_date?: string;
  filing_status?: string;
}

export interface DemoValidation {
  errors: string[];
  warnings: string[];
}

/**
 * Lightweight pre-simulation validation. Errors block the simulation; warnings
 * are informational (the demo can still proceed).
 */
export function validateForDemo(entry: SimulatableEntry): DemoValidation {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!isSimulatable(entry.compliance_type)) {
    errors.push(`${entry.compliance_type} cannot be simulated (no return/filing for this type).`);
  }
  if (!entry.due_date) errors.push("Missing due date.");
  if (!entry.period_start || !entry.period_end) {
    warnings.push("Filing period is incomplete.");
  }
  if (entry.filing_status === "filed") {
    warnings.push("This return is already marked filed for real — the simulation does not change that.");
  }
  if (entry.due_date && entry.due_date < new Date().toISOString().split("T")[0]) {
    warnings.push("The real due date has passed — simulating does not file the actual return.");
  }

  return { errors, warnings };
}
