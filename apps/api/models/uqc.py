"""
Official CBIC Unit Quantity Code (UQC) list — the fixed set of unit codes
GSTR-1's HSN summary and e-invoicing validate against. Used wherever this app
lets a user pick a "unit" for a goods line: Product/Service catalogue,
firm_hsn_library, and (for goods lines only) sales invoice / purchase bill
line items. Deliberately NOT free text and NOT firm-configurable — an
invalid UQC here would silently produce an invalid GST filing.
"""

UQC_CODES = [
    ("BAG", "BAGS"),
    ("BAL", "BALE"),
    ("BDL", "BUNDLES"),
    ("BKL", "BUCKLES"),
    ("BOU", "BILLION OF UNITS"),
    ("BOX", "BOX"),
    ("BTL", "BOTTLES"),
    ("BUN", "BUNCHES"),
    ("CAN", "CANS"),
    ("CBM", "CUBIC METERS"),
    ("CCM", "CUBIC CENTIMETERS"),
    ("CMS", "CENTIMETERS"),
    ("CTN", "CARTONS"),
    ("DOZ", "DOZENS"),
    ("DRM", "DRUMS"),
    ("GGK", "GREAT GROSS"),
    ("GMS", "GRAMMES"),
    ("GRS", "GROSS"),
    ("GYD", "GROSS YARDS"),
    ("KGS", "KILOGRAMS"),
    ("KLR", "KILOLITRE"),
    ("KME", "KILOMETRE"),
    ("MLT", "MILILITRE"),
    ("MTR", "METERS"),
    ("MTS", "METRIC TON"),
    ("NOS", "NUMBERS"),
    ("PAC", "PACKS"),
    ("PCS", "PIECES"),
    ("PRS", "PAIRS"),
    ("QTL", "QUINTAL"),
    ("ROL", "ROLLS"),
    ("SET", "SETS"),
    ("SQF", "SQUARE FEET"),
    ("SQM", "SQUARE METERS"),
    ("SQY", "SQUARE YARDS"),
    ("TBS", "TABLETS"),
    ("TGM", "TEN GROSS"),
    ("THD", "THOUSANDS"),
    ("TON", "TONNES"),
    ("TUB", "TUBES"),
    ("UGS", "US GALLONS"),
    ("UNT", "UNITS"),
    ("YDS", "YARDS"),
    ("OTH", "OTHERS"),
]

VALID_UQC_CODES = frozenset(code for code, _ in UQC_CODES)
