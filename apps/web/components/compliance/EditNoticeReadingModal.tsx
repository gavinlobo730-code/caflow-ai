"use client";

/**
 * EditNoticeReadingModal: a CA corrects what the model read from a notice, before approving it.
 *
 * Approving a staged notice creates the response task with the due date on the reading and tells the partners, so a wrong date
 * or the wrong kind of notice used to mean rejecting it and extracting again, or approving it wrong. This opens the reading as
 * form fields beside the note that the model's own reading is kept, sends only what changed, and shows the server's sentence when
 * it refuses (a date no notice could carry, a type it does not know). The rules are the server's
 * (`domain/ai/extraction_schemas.correct_notice`); nothing here decides what is valid.
 */
import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { DateInput } from "@/components/ui/date-input";
import { useDateProblems } from "@/lib/dates/useDateProblems";
import {
  NOTICE_TYPE_OPTIONS,
  buildCorrection,
  readingFormFrom,
  type NoticeReadingForm,
} from "@/lib/compliance/noticeReading";

const FIELD = "w-full px-3 py-1.5 text-sm border border-state-working-border rounded-md focus:outline-none focus:ring-2 focus:ring-brand bg-white";

export function EditNoticeReadingModal({
  notice, busy, error, onSave, onClose,
}: {
  notice: Record<string, unknown>;
  busy: boolean;
  /** The server's sentence when the last attempt was refused. */
  error?: string | null;
  onSave: (patch: Partial<NoticeReadingForm>) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<NoticeReadingForm>(() => readingFormFrom(notice));
  // A date box holding text that is not a date must not read as "no date" and send a clearing value.
  const dates = useDateProblems();
  const patch = buildCorrection(notice, form);
  const unchanged = Object.keys(patch).length === 0;
  const set = (key: keyof NoticeReadingForm) => (value: string) => setForm((f) => ({ ...f, [key]: value }));

  return (
    <Modal title="Correct the reading" onClose={onClose} maxWidthClass="max-w-lg"
      note="The model read these details from the notice. Correct anything it got wrong before you approve it; approving makes the response task from what is here. The model's own reading is kept alongside, and each correction is logged.">
      <div className="space-y-3">
        <div>
          <label htmlFor="notice-authority" className="text-xs font-medium text-ps-body block mb-1">Issuing authority</label>
          <input id="notice-authority" value={form.authority} onChange={(e) => set("authority")(e.target.value)} className={FIELD} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="notice-type" className="text-xs font-medium text-ps-body block mb-1">Kind of notice</label>
            <select id="notice-type" value={form.notice_type} onChange={(e) => set("notice_type")(e.target.value)} className={FIELD}>
              {!NOTICE_TYPE_OPTIONS.some((o) => o.value === form.notice_type) && (
                <option value={form.notice_type}>{form.notice_type || "Choose…"}</option>
              )}
              {NOTICE_TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="notice-ref" className="text-xs font-medium text-ps-body block mb-1">Reference number</label>
            <input id="notice-ref" value={form.reference_no} onChange={(e) => set("reference_no")(e.target.value)}
              placeholder="Leave empty if none is stated" className={FIELD} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="notice-issued" className="text-xs font-medium text-ps-body block mb-1">Issued on</label>
            <DateInput id="notice-issued" value={form.issue_date} onChange={set("issue_date")}
              onStateChange={dates.watch("issue_date", "Issued on")} className={FIELD} />
          </div>
          <div>
            <label htmlFor="notice-due" className="text-xs font-medium text-ps-body block mb-1">Response due on</label>
            <DateInput id="notice-due" value={form.response_due_date} onChange={set("response_due_date")}
              onStateChange={dates.watch("response_due_date", "Response due on")} className={FIELD} />
          </div>
        </div>
        <p className="text-3xs text-ps-hint">Clear a date if the notice states none. The task is made with the response date shown here.</p>
        <div>
          <label htmlFor="notice-desc" className="text-xs font-medium text-ps-body block mb-1">What the notice requires</label>
          <textarea id="notice-desc" rows={3} value={form.description} onChange={(e) => set("description")(e.target.value)} className={FIELD} />
        </div>

        {error && (
          <p role="alert" className="text-xs text-state-problem bg-state-problem-surface rounded px-2 py-1.5">{error}</p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose}
            className="text-xs px-3 py-1.5 border border-ps-border rounded-md hover:bg-ps-muted bg-white">Cancel</button>
          <button type="button" onClick={() => onSave(patch)} disabled={busy || unchanged || !!dates.first}
            className="text-xs px-3 py-1.5 bg-brand text-white rounded-md hover:bg-brand-dark disabled:opacity-50">
            {busy ? "Saving…" : "Save correction"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
