-- Customer and Vendor master tables for CA client businesses
-- Supports GSTIN-based state derivation and TDS tracking per IT Act Section 194C/194I/194J

CREATE TABLE IF NOT EXISTS customers (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  name                     TEXT NOT NULL,
  -- GSTIN format: 2-digit state code + PAN (10 chars) + entity digit + Z + check digit (CGST Act, Section 25)
  gstin                    TEXT,
  state_code               TEXT(2),  -- derived from gstin[0:2] if present, else manual entry
  pan                      TEXT,
  email                    TEXT,
  phone                    TEXT,
  address                  TEXT,
  city                     TEXT,
  state                    TEXT,
  pincode                  TEXT(6),
  -- All monetary values in integer paise to avoid floating point errors
  -- positive value = receivable from customer
  opening_balance_paise    BIGINT NOT NULL DEFAULT 0,
  opening_balance_date     DATE,
  credit_days              INTEGER NOT NULL DEFAULT 30,
  is_active                BOOLEAN NOT NULL DEFAULT TRUE,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_client_id ON customers(client_id);
CREATE INDEX IF NOT EXISTS idx_customers_firm_id_is_active ON customers(firm_id, is_active);

ALTER TABLE customers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_customers" ON customers
  FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON customers TO authenticated;


CREATE TABLE IF NOT EXISTS vendors (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  name                     TEXT NOT NULL,
  -- GSTIN format: 2-digit state code + PAN (10 chars) + entity digit + Z + check digit (CGST Act, Section 25)
  gstin                    TEXT,
  state_code               TEXT(2),  -- derived from gstin[0:2] if present, else manual entry
  pan                      TEXT,
  email                    TEXT,
  phone                    TEXT,
  address                  TEXT,
  city                     TEXT,
  state                    TEXT,
  pincode                  TEXT(6),
  -- TDS applicability per IT Act Section 194C (contractors), 194I (rent), 194J (professional fees)
  tds_applicable           BOOLEAN NOT NULL DEFAULT FALSE,
  tds_section              TEXT,     -- e.g. '194C', '194I', '194J'
  -- Rate in basis points: 1000 bps = 10.00% — integer arithmetic, never float (IT Act, Section 194C)
  tds_rate_bps             INTEGER DEFAULT 0,
  -- All monetary values in integer paise to avoid floating point errors
  -- positive value = payable to vendor
  opening_balance_paise    BIGINT NOT NULL DEFAULT 0,
  opening_balance_date     DATE,
  is_active                BOOLEAN NOT NULL DEFAULT TRUE,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendors_client_id ON vendors(client_id);
CREATE INDEX IF NOT EXISTS idx_vendors_firm_id_is_active ON vendors(firm_id, is_active);

ALTER TABLE vendors ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_vendors" ON vendors
  FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON vendors TO authenticated;
