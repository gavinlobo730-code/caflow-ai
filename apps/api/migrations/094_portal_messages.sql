-- Migration 094: Portal Messages
-- Two-way messaging between CA and client via the portal.
-- Idempotent: uses CREATE TABLE IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS portal_messages (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  sender_type    TEXT NOT NULL CHECK (sender_type IN ('ca', 'client')),
  sender_name    TEXT,
  body           TEXT NOT NULL,
  is_read        BOOLEAN NOT NULL DEFAULT FALSE,
  read_at        TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_portal_messages_client
  ON portal_messages (client_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_portal_messages_firm
  ON portal_messages (firm_id, created_at DESC);

ALTER TABLE portal_messages ENABLE ROW LEVEL SECURITY;

-- CA (firm staff) can access all messages in their firm
DROP POLICY IF EXISTS "firm_portal_messages" ON portal_messages;
CREATE POLICY "firm_portal_messages" ON portal_messages
  FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- Portal clients can read/insert for their own client_id
DROP POLICY IF EXISTS "portal_client_messages" ON portal_messages;
CREATE POLICY "portal_client_messages" ON portal_messages
  FOR ALL TO authenticated
  USING (
    client_id IN (
      SELECT id FROM clients WHERE portal_user_id = auth.uid()
    )
  );

GRANT SELECT, INSERT, UPDATE ON portal_messages TO authenticated;
GRANT ALL ON portal_messages TO service_role;
