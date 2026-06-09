-- Portal Messages — secure two-way messaging between CA and client
-- CA posts messages; client reads and replies via portal

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

-- Indexes
CREATE INDEX IF NOT EXISTS idx_portal_messages_client ON portal_messages(client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_portal_messages_firm   ON portal_messages(firm_id, created_at DESC);

-- RLS
ALTER TABLE portal_messages ENABLE ROW LEVEL SECURITY;

-- CA (authenticated firm users) can do everything on their own firm's messages
CREATE POLICY "firm_portal_messages" ON portal_messages
  FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id());

-- Portal clients can read and insert messages for their own client_id
-- They identify themselves via portal_user_id on clients table
CREATE POLICY "portal_client_messages" ON portal_messages
  FOR ALL TO authenticated
  USING (
    client_id IN (
      SELECT id FROM clients WHERE portal_user_id = auth.uid()
    )
  );

-- Grant table access
GRANT SELECT, INSERT, UPDATE ON portal_messages TO authenticated;
