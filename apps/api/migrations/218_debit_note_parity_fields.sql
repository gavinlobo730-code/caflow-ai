-- Purchase Debit Note feature parity with Purchase Bills (task: full-page editor
-- overhaul for Debit/Credit Notes). Purchase Bills already have document_url
-- (original invoice attachment, CGST Rule 36(1) evidence), notes (internal,
-- never shown to vendor), and a per-line unit-of-measure (UQC) — Debit Notes
-- had none of the three.
ALTER TABLE debit_notes ADD COLUMN IF NOT EXISTS document_url text;
ALTER TABLE debit_notes ADD COLUMN IF NOT EXISTS notes text;
ALTER TABLE debit_note_lines ADD COLUMN IF NOT EXISTS unit text;
