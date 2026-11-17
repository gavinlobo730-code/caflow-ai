-- 670 — a compliance obligation can be recorded as NOT REQUIRED of the client (POST-A-267, item 4).
--
-- THE GAP
--
-- The compliance calendar generates the four advance-tax instalments (obligation type ADVANCE_TAX: 15 June, 15 September,
-- 15 December, 15 March) for every client with an Advance Tax engagement. A §44AD or §44ADA assessee pays the whole amount by
-- 15 March under the proviso to §211(1), so for that client three of the four are not owed, and there was no state to put them in:
-- `compliance_records_status_check` (migration 108) allows the workflow steps, Filed, Completed and Overdue. "Filed" would state a
-- payment that was never made, a deleted row is put back by the generator, and an open row turns overdue on every screen that
-- counts what is late (Deadlines, the client's Compliance tab, the health score, the dashboard).
--
-- WHAT THIS ADDS
--
-- One more value in the CHECK, 'Not Required'. Nothing else: the reason a CA gives is appended to the row's existing `notes` and
-- written to the audit log by `compliance_record_service.mark_not_required`, which is the only writer of the value and accepts it on
-- ADVANCE_TAX obligations only, with a written reason, for a person holding compliance.approve. No row is changed here and no
-- figure is held: whether a client owes an instalment is the CA's statement, not the database's.
--
-- WHY A CHECK WIDENING IS SAFE ON ITS OWN, AND IN EITHER ORDER WITH THE API
--
-- Every existing row satisfies the wider check, so the ADD validates without a rewrite. The API may deploy before this runs: until
-- then the new door is refused by the old check (a 23514 the door reports as a failure, and the obligation stays as it was); every
-- reader already treats the new word as settled, so nothing reads it wrongly in either order.
--
-- Nothing here transmits anything to a portal.

BEGIN;

ALTER TABLE public.compliance_records DROP CONSTRAINT IF EXISTS compliance_records_status_check;
ALTER TABLE public.compliance_records ADD CONSTRAINT compliance_records_status_check
    CHECK (status IN ('Not Started','Awaiting Documents','In Progress','Ready For Review',
                      'Ready To File','Filed','Completed','Overdue','Not Required'));

COMMIT;
