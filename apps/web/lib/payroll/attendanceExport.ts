/**
 * What the attendance sheet's Export writes for each employee on the roster (POST-A-468).
 *
 * The editor seeds 26 working days and 26 present for every employee who has no attendance row for the month, so its boxes have something to
 * show, and the screen says "Not entered — the run will assume a full month" on that row. The Export used to write the seed as figures, so a
 * file read later said 26 of 26 days present for somebody whose month nobody recorded. A row now says which of three things it is, and a
 * row nobody entered carries no days at all:
 *
 *   - "Entered": the month's saved row, as read;
 *   - "Edited, not saved": what was typed or imported on this screen and not yet saved (the screen's own "Edited — will be saved");
 *   - "Not entered": no row for the month, the day cells blank; the run assumes a full month for it, which the status says.
 */

export type AttendanceDays = {
  working_days: number;
  days_present: number;
  casual_leaves: number;
  sick_leaves: number;
  earned_leaves: number;
};

export type AttendanceExportRow = {
  name: string;
  designation: string;
  status: string;
  working_days: number | null;
  days_present: number | null;
  casual_leaves: number | null;
  sick_leaves: number | null;
  earned_leaves: number | null;
  lop: number | null;
  net_pay_days: number | null;
};

export const ATTENDANCE_STATUS = {
  entered: "Entered",
  edited: "Edited, not saved",
  notEntered: "Not entered (the run assumes a full month)",
} as const;

/** The sentence beside the Export button, so the person knows before downloading what a blank row in the file means. */
export const ATTENDANCE_EXPORT_NOTE =
  "The export marks each employee Entered, Edited (not saved) or Not entered; a not-entered employee's days are left blank, not shown as a full month.";

export function attendanceExportRows<R extends AttendanceDays>(
  roster: { id: string; name: string; designation?: string | null }[],
  attendance: Record<string, R | undefined>,
  entered: ReadonlySet<string>,
  touched: ReadonlySet<string>,
  figures: (row: R) => { lop: number; net_pay_days: number },
): AttendanceExportRow[] {
  return roster.map((emp) => {
    const row = attendance[emp.id];
    const base = { name: emp.name, designation: emp.designation ?? "" };
    if (!row || (!entered.has(emp.id) && !touched.has(emp.id))) {
      return {
        ...base, status: ATTENDANCE_STATUS.notEntered,
        working_days: null, days_present: null, casual_leaves: null, sick_leaves: null, earned_leaves: null,
        lop: null, net_pay_days: null,
      };
    }
    return {
      ...base,
      status: touched.has(emp.id) ? ATTENDANCE_STATUS.edited : ATTENDANCE_STATUS.entered,
      working_days: row.working_days,
      days_present: row.days_present,
      casual_leaves: row.casual_leaves,
      sick_leaves: row.sick_leaves,
      earned_leaves: row.earned_leaves,
      ...figures(row),
    };
  });
}
