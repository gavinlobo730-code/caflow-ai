-- Phase 6: Accounts Production Engine — Year-End Close & Financial Statements
-- All monetary values stored as INTEGER/BIGINT (paise). Never float.

-- ─── year_end_engagements ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS year_end_engagements (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id           UUID        NOT NULL,
  client_id         UUID        NOT NULL,
  financial_year    VARCHAR(7)  NOT NULL,  -- e.g. "2024-25"
  fy_start          DATE        NOT NULL,  -- April 1
  fy_end            DATE        NOT NULL,  -- March 31
  status            TEXT        NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','in_review','approved','locked')),
  prepared_by       UUID        REFERENCES users(id),
  reviewed_by       UUID        REFERENCES users(id),
  approved_by       UUID        REFERENCES users(id),
  prepared_at       TIMESTAMPTZ,
  reviewed_at       TIMESTAMPTZ,
  approved_at       TIMESTAMPTZ,
  locked_at         TIMESTAMPTZ,
  created_by        UUID        NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (firm_id, client_id, financial_year)
);

CREATE INDEX IF NOT EXISTS idx_yee_firm_id      ON year_end_engagements (firm_id);
CREATE INDEX IF NOT EXISTS idx_yee_client_id    ON year_end_engagements (client_id);
CREATE INDEX IF NOT EXISTS idx_yee_status       ON year_end_engagements (firm_id, status);
CREATE INDEX IF NOT EXISTS idx_yee_fy           ON year_end_engagements (firm_id, financial_year);

ALTER TABLE year_end_engagements ENABLE ROW LEVEL SECURITY;

CREATE POLICY yee_firm_isolation ON year_end_engagements
  USING (firm_id::text = (auth.jwt() ->> 'firm_id'));


-- ─── year_end_checklists ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS year_end_checklists (
  id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  engagement_id   UUID    NOT NULL REFERENCES year_end_engagements(id) ON DELETE CASCADE,
  firm_id         UUID    NOT NULL,
  category        TEXT    NOT NULL,
  item_code       TEXT    NOT NULL,
  item_label      TEXT    NOT NULL,
  status          TEXT    NOT NULL DEFAULT 'not_started'
                  CHECK (status IN ('not_started','in_progress','complete','not_applicable')),
  notes           TEXT,
  completed_by    UUID,
  completed_at    TIMESTAMPTZ,
  sequence_no     INTEGER NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_yec_engagement_id ON year_end_checklists (engagement_id);
CREATE INDEX IF NOT EXISTS idx_yec_firm_id       ON year_end_checklists (firm_id);

ALTER TABLE year_end_checklists ENABLE ROW LEVEL SECURITY;

CREATE POLICY yec_firm_isolation ON year_end_checklists
  USING (firm_id::text = (auth.jwt() ->> 'firm_id'));


-- ─── year_end_adjustments ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS year_end_adjustments (
  id                UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  engagement_id     UUID    NOT NULL REFERENCES year_end_engagements(id) ON DELETE CASCADE,
  firm_id           UUID    NOT NULL,
  client_id         UUID    NOT NULL,
  adjustment_type   TEXT    NOT NULL
                    CHECK (adjustment_type IN ('accrual','prepayment','provision','reclassification','depreciation_adj','manual')),
  description       TEXT    NOT NULL,
  journal_entry_id  UUID,   -- populated after posting via journal engine
  amount_paise      BIGINT  NOT NULL,  -- always integer paise, never float
  status            TEXT    NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','pending_review','approved','posted','rejected')),
  reviewed_by       UUID,
  reviewed_at       TIMESTAMPTZ,
  approved_by       UUID,
  approved_at       TIMESTAMPTZ,
  rejection_reason  TEXT,
  created_by        UUID    NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_yea_engagement_id ON year_end_adjustments (engagement_id);
CREATE INDEX IF NOT EXISTS idx_yea_firm_id        ON year_end_adjustments (firm_id);
CREATE INDEX IF NOT EXISTS idx_yea_client_id      ON year_end_adjustments (client_id);
CREATE INDEX IF NOT EXISTS idx_yea_status         ON year_end_adjustments (firm_id, status);

ALTER TABLE year_end_adjustments ENABLE ROW LEVEL SECURITY;

CREATE POLICY yea_firm_isolation ON year_end_adjustments
  USING (firm_id::text = (auth.jwt() ->> 'firm_id'));


-- ─── account_group_mappings ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS account_group_mappings (
  id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID    NOT NULL,
  account_id      TEXT    NOT NULL,  -- maps to chart_of_accounts account code
  account_name    TEXT    NOT NULL,
  statement_type  TEXT    NOT NULL
                  CHECK (statement_type IN ('balance_sheet','profit_loss')),
  schedule_line   TEXT    NOT NULL,  -- Schedule III line e.g. 'cash_and_bank'
  sub_line        TEXT,
  sequence_no     INTEGER NOT NULL DEFAULT 0,
  is_active       BOOLEAN NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (firm_id, account_id)
);

CREATE INDEX IF NOT EXISTS idx_agm_firm_id        ON account_group_mappings (firm_id);
CREATE INDEX IF NOT EXISTS idx_agm_statement_type ON account_group_mappings (firm_id, statement_type);
CREATE INDEX IF NOT EXISTS idx_agm_schedule_line  ON account_group_mappings (firm_id, schedule_line);

ALTER TABLE account_group_mappings ENABLE ROW LEVEL SECURITY;

CREATE POLICY agm_firm_isolation ON account_group_mappings
  USING (firm_id::text = (auth.jwt() ->> 'firm_id'));


-- ─── financial_statement_versions ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS financial_statement_versions (
  id                    UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  engagement_id         UUID    NOT NULL REFERENCES year_end_engagements(id) ON DELETE CASCADE,
  firm_id               UUID    NOT NULL,
  version_number        INTEGER NOT NULL DEFAULT 1,
  statement_data        JSONB   NOT NULL,  -- full BS + P&L snapshot, all values in paise
  trial_balance_hash    TEXT    NOT NULL,  -- SHA-256 of trial balance
  change_reason         TEXT,
  created_by            UUID    NOT NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (engagement_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_fsv_engagement_id ON financial_statement_versions (engagement_id);
CREATE INDEX IF NOT EXISTS idx_fsv_firm_id       ON financial_statement_versions (firm_id);

ALTER TABLE financial_statement_versions ENABLE ROW LEVEL SECURITY;

CREATE POLICY fsv_firm_isolation ON financial_statement_versions
  USING (firm_id::text = (auth.jwt() ->> 'firm_id'));


-- ─── notes_to_accounts ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notes_to_accounts (
  id                  UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  engagement_id       UUID    NOT NULL REFERENCES year_end_engagements(id) ON DELETE CASCADE,
  version_id          UUID    REFERENCES financial_statement_versions(id),
  firm_id             UUID    NOT NULL,
  note_type           TEXT    NOT NULL
                      CHECK (note_type IN ('fixed_assets','share_capital','loans','gst_tds','related_party','contingent_liabilities','custom')),
  note_number         INTEGER NOT NULL,
  title               TEXT    NOT NULL,
  content_data        JSONB   NOT NULL,
  is_auto_generated   BOOLEAN NOT NULL DEFAULT false,
  is_locked           BOOLEAN NOT NULL DEFAULT false,
  created_by          UUID    NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nta_engagement_id ON notes_to_accounts (engagement_id);
CREATE INDEX IF NOT EXISTS idx_nta_firm_id       ON notes_to_accounts (firm_id);
CREATE INDEX IF NOT EXISTS idx_nta_version_id    ON notes_to_accounts (version_id);

ALTER TABLE notes_to_accounts ENABLE ROW LEVEL SECURITY;

CREATE POLICY nta_firm_isolation ON notes_to_accounts
  USING (firm_id::text = (auth.jwt() ->> 'firm_id'));


-- ─── year_end_reviews ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS year_end_reviews (
  id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  engagement_id   UUID    NOT NULL REFERENCES year_end_engagements(id) ON DELETE CASCADE,
  firm_id         UUID    NOT NULL,
  review_type     TEXT    NOT NULL
                  CHECK (review_type IN ('prepared','reviewed','approved')),
  action          TEXT    NOT NULL
                  CHECK (action IN ('submitted','approved','rejected','revision_requested')),
  comment         TEXT,
  reviewed_by     UUID    NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_yer_engagement_id ON year_end_reviews (engagement_id);
CREATE INDEX IF NOT EXISTS idx_yer_firm_id       ON year_end_reviews (firm_id);

ALTER TABLE year_end_reviews ENABLE ROW LEVEL SECURITY;

CREATE POLICY yer_firm_isolation ON year_end_reviews
  USING (firm_id::text = (auth.jwt() ->> 'firm_id'));


-- ─── year_end_exports ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS year_end_exports (
  id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  engagement_id   UUID    NOT NULL REFERENCES year_end_engagements(id) ON DELETE CASCADE,
  version_id      UUID    REFERENCES financial_statement_versions(id),
  firm_id         UUID    NOT NULL,
  export_type     TEXT    NOT NULL
                  CHECK (export_type IN ('financial_statements','notes','complete_pack')),
  file_path       TEXT    NOT NULL,
  file_size_bytes INTEGER,
  created_by      UUID    NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_yex_engagement_id ON year_end_exports (engagement_id);
CREATE INDEX IF NOT EXISTS idx_yex_firm_id       ON year_end_exports (firm_id);

ALTER TABLE year_end_exports ENABLE ROW LEVEL SECURITY;

CREATE POLICY yex_firm_isolation ON year_end_exports
  USING (firm_id::text = (auth.jwt() ->> 'firm_id'));


-- ─── Grants ──────────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON year_end_engagements         TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON year_end_checklists          TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON year_end_adjustments         TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON account_group_mappings       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON financial_statement_versions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON notes_to_accounts            TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON year_end_reviews             TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON year_end_exports             TO authenticated;

GRANT ALL ON year_end_engagements         TO service_role;
GRANT ALL ON year_end_checklists          TO service_role;
GRANT ALL ON year_end_adjustments         TO service_role;
GRANT ALL ON account_group_mappings       TO service_role;
GRANT ALL ON financial_statement_versions TO service_role;
GRANT ALL ON notes_to_accounts            TO service_role;
GRANT ALL ON year_end_reviews             TO service_role;
GRANT ALL ON year_end_exports             TO service_role;
