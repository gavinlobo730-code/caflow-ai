/**
 * Official CBIC Unit Quantity Code (UQC) list — the fixed set of unit codes
 * GSTR-1's HSN summary and e-invoicing validate against. Used wherever this
 * app lets a user pick a "unit" for a goods line: Product/Service catalogue,
 * Firm HSN/SAC Library, and (for goods lines only) sales invoice line items.
 * Deliberately NOT free text and NOT firm-configurable — an invalid UQC here
 * would silently produce an invalid GST filing. Mirrors apps/api/models/uqc.py.
 */
export interface UqcCode {
  code: string;
  label: string;
}

export const UQC_CODES: UqcCode[] = [
  { code: "BAG", label: "BAGS" },
  { code: "BAL", label: "BALE" },
  { code: "BDL", label: "BUNDLES" },
  { code: "BKL", label: "BUCKLES" },
  { code: "BOU", label: "BILLION OF UNITS" },
  { code: "BOX", label: "BOX" },
  { code: "BTL", label: "BOTTLES" },
  { code: "BUN", label: "BUNCHES" },
  { code: "CAN", label: "CANS" },
  { code: "CBM", label: "CUBIC METERS" },
  { code: "CCM", label: "CUBIC CENTIMETERS" },
  { code: "CMS", label: "CENTIMETERS" },
  { code: "CTN", label: "CARTONS" },
  { code: "DOZ", label: "DOZENS" },
  { code: "DRM", label: "DRUMS" },
  { code: "GGK", label: "GREAT GROSS" },
  { code: "GMS", label: "GRAMMES" },
  { code: "GRS", label: "GROSS" },
  { code: "GYD", label: "GROSS YARDS" },
  { code: "KGS", label: "KILOGRAMS" },
  { code: "KLR", label: "KILOLITRE" },
  { code: "KME", label: "KILOMETRE" },
  { code: "MLT", label: "MILILITRE" },
  { code: "MTR", label: "METERS" },
  { code: "MTS", label: "METRIC TON" },
  { code: "NOS", label: "NUMBERS" },
  { code: "PAC", label: "PACKS" },
  { code: "PCS", label: "PIECES" },
  { code: "PRS", label: "PAIRS" },
  { code: "QTL", label: "QUINTAL" },
  { code: "ROL", label: "ROLLS" },
  { code: "SET", label: "SETS" },
  { code: "SQF", label: "SQUARE FEET" },
  { code: "SQM", label: "SQUARE METERS" },
  { code: "SQY", label: "SQUARE YARDS" },
  { code: "TBS", label: "TABLETS" },
  { code: "TGM", label: "TEN GROSS" },
  { code: "THD", label: "THOUSANDS" },
  { code: "TON", label: "TONNES" },
  { code: "TUB", label: "TUBES" },
  { code: "UGS", label: "US GALLONS" },
  { code: "UNT", label: "UNITS" },
  { code: "YDS", label: "YARDS" },
  { code: "OTH", label: "OTHERS" },
];

export const VALID_UQC_CODES = new Set(UQC_CODES.map((u) => u.code));
