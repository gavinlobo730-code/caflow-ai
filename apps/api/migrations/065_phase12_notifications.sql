-- Phase 1.2: Notification Centre
-- Idempotent migration — safe to run multiple times

-- Add is_archived column if it doesn't exist yet
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'notifications' AND column_name = 'is_archived'
  ) THEN
    ALTER TABLE notifications ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'notifications' AND column_name = 'metadata'
  ) THEN
    ALTER TABLE notifications ADD COLUMN IF NOT EXISTS metadata JSONB;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_notifications_firm_id ON notifications(firm_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(is_read, firm_id) WHERE is_read = false;
