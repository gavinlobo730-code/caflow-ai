/**
 * Does the signed-in identity have employee-portal access?
 *
 * Asked of the server (`GET /api/portal/employee/access`), which resolves the caller to an employee the same way every other
 * employee route does: the identity's own `payroll_employees` row must be bound (`auth_user_id`) AND `portal_enabled` —
 * exactly the state that accepting an employee invite produces. It used to be asked of the database straight from the
 * browser, under migration 262's `employee_sees_own_record` policy (POST-A-010 moved it).
 *
 * It lives here rather than inside a page because TWO places need it and they need it for opposite reasons:
 *
 *  - /portal/employee/activate asks "have they already done this?", so a spent single-use token sends them on to their
 *    payslips instead of showing "invalid";
 *  - /portal/dashboard asks "is this person in the wrong portal?". It resolves CLIENT memberships only, so before this
 *    existed an activated employee who signed in at /portal/login — which pushes everyone to /portal/dashboard — landed on
 *    the zero-memberships branch and was told "You don't have access to a client portal right now. If you believe you
 *    should have access, ask your accountant to invite you." They did have access, to a different portal, and their only
 *    working route to it was the original invite link.
 *
 * Two copies of this query would drift, and the one that drifted would be whichever is read less.
 *
 * Never throws: every caller is deciding where to send somebody, and a failed probe should mean "not an employee, carry on"
 * rather than an error screen. A false negative puts them back where they already were; a thrown error would strand them.
 */
import { api } from "@/lib/api";

export async function hasEmployeePortalAccess(): Promise<boolean> {
  try {
    const res = await api.portalSelf.employeeAccess();
    return Boolean(res?.success && res.data?.enabled === true);
  } catch {
    return false;
  }
}
