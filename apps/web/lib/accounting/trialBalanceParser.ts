/**
 * Trial Balance CSV parsing — extracted from the importer page so the
 * parse/type-detection/amount logic is testable independent of Supabase
 * availability (C4). Behavior is unchanged from the original inline code.
 */

export function parseCSV(text: string): string[][] {
  const rows: string[][] = [];
  let i = 0;
  while (i < text.length) {
    const row: string[] = [];
    while (i < text.length && text[i] !== "\n" && text[i] !== "\r") {
      let field = "";
      if (text[i] === '"') {
        i++; // skip opening quote
        while (i < text.length) {
          if (text[i] === '"' && text[i + 1] === '"') { field += '"'; i += 2; }
          else if (text[i] === '"') { i++; break; }
          else { field += text[i++]; }
        }
      } else {
        while (i < text.length && text[i] !== "," && text[i] !== "\n" && text[i] !== "\r") {
          field += text[i++];
        }
      }
      row.push(field.trim());
      if (i < text.length && text[i] === ",") i++;
    }
    if (text[i] === "\r") i++;
    if (text[i] === "\n") i++;
    if (row.length > 0 && !(row.length === 1 && row[0] === "")) rows.push(row);
  }
  return rows;
}

export function detectType(name: string): string {
  const n = name.toLowerCase();
  if (/sales|revenue|income|turnover/.test(n)) return "revenue";
  if (/purchase|cogs|cost of/.test(n)) return "expense";
  if (/expense|depreciation|salary|rent|utilities/.test(n)) return "expense";
  if (/cash|bank|receivable|debtor|advances paid/.test(n)) return "asset";
  if (/fixed asset|plant|machinery|building|vehicle|furniture/.test(n)) return "asset";
  if (/payable|creditor|loan payable|advances received/.test(n)) return "liability";
  if (/capital|reserve|retained earnings|equity/.test(n)) return "equity";
  return "asset";
}

export function parseAmount(s: string): number {
  // Remove commas, Rs, spaces, handle negative in parens
  const clean = s.replace(/[,\s₹Rs]/g, "").replace(/\((.+)\)/, "-$1");
  const n = parseFloat(clean) || 0;
  return Math.round(Math.abs(n) * 100); // paise, always positive
}

export type ParsedAccount = {
  account_name: string;
  account_code: string;
  account_type: string;
  dr_balance: string;
  cr_balance: string;
  dr_paise: number;
  cr_paise: number;
  typeOverride?: string;
};

export type ColumnMap = {
  nameCol: number;
  codeCol: number;
  drCol: number;
  crCol: number;
  typeCol: number;
};

export function buildParsedAccounts(rawRows: string[][], colMap: ColumnMap): ParsedAccount[] {
  return rawRows
    .map((row) => {
      const name = row[colMap.nameCol] ?? "";
      const code = colMap.codeCol >= 0 ? (row[colMap.codeCol] ?? "") : "";
      const drRaw = colMap.drCol >= 0 ? (row[colMap.drCol] ?? "0") : "0";
      const crRaw = colMap.crCol >= 0 ? (row[colMap.crCol] ?? "0") : "0";
      const typeRaw = colMap.typeCol >= 0 ? (row[colMap.typeCol] ?? "") : "";
      return {
        account_name: name,
        account_code: code,
        account_type: typeRaw ? typeRaw.toLowerCase() : detectType(name),
        dr_balance: drRaw,
        cr_balance: crRaw,
        dr_paise: parseAmount(drRaw),
        cr_paise: parseAmount(crRaw),
      };
    })
    .filter((a) => a.account_name.trim() !== "");
}
