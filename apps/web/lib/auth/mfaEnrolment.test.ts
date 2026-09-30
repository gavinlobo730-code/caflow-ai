// node --experimental-strip-types --test lib/auth/mfaEnrolment.test.ts
//
// The nudge a new Partner or Manager needs before mfa_guard will answer them.
// Who is covered is the SERVER's answer (`applies_to_caller`, mfa_guard's own
// comparison); these tests cover what the browser does with it.
import test from "node:test";
import assert from "node:assert/strict";
import {
  enrolmentRequired,
  onboardingCompletionTarget,
  parseMfaPolicy,
  showsSecureAccountBanner,
  setupPageLead,
  SETUP_CONTINUE_HREF,
  type EnrolmentState,
  type MfaPolicy,
} from "./mfaEnrolment.ts";

// What the server serves with REQUIRE_MFA on and the default Partner,Manager.
const served = (role: string) => ({
  required: true,
  roles: ["Manager", "Partner"],
  applies_to_caller: role === "Partner" || role === "Manager",
});
const policyFor = (role: string): MfaPolicy => parseMfaPolicy(served(role))!;

const base: EnrolmentState = { policy: policyFor("Partner"), hasVerifiedFactor: false, isPortalPrincipal: false };
const at = (over: Partial<EnrolmentState>) => enrolmentRequired({ ...base, ...over });

test("a Partner with no authenticator must enrol", () => {
  assert.equal(at({}), true);
});

test("a Manager with no authenticator must enrol", () => {
  assert.equal(at({ policy: policyFor("Manager") }), true);
});

test("an Executive or Reviewer is not asked", () => {
  for (const role of ["Executive", "Reviewer"]) {
    assert.equal(at({ policy: policyFor(role) }), false, role);
  }
});

test("somebody with a verified factor is not asked", () => {
  assert.equal(at({ hasVerifiedFactor: true }), false);
});

test("a portal principal is never asked", () => {
  assert.equal(at({ isPortalPrincipal: true }), false);
});

test("with REQUIRE_MFA off nobody is asked", () => {
  const off = parseMfaPolicy({ required: false, roles: ["Manager", "Partner"], applies_to_caller: false });
  assert.equal(at({ policy: off }), false);
});

test("an unknown policy or factor list does not nudge", () => {
  assert.equal(at({ policy: null }), false);
  assert.equal(at({ hasVerifiedFactor: null }), false);
});

test("a malformed payload is not a policy", () => {
  assert.equal(parseMfaPolicy(null), null);
  assert.equal(parseMfaPolicy([]), null);
  assert.equal(parseMfaPolicy({}), null);
  assert.equal(parseMfaPolicy({ required: "true", applies_to_caller: true }), null);
  assert.equal(parseMfaPolicy({ required: true }), null);
});

test("roles arrive as served and junk entries are dropped", () => {
  const p = parseMfaPolicy({ required: true, roles: ["Partner", 3, null], applies_to_caller: true });
  assert.deepEqual(p?.roles, ["Partner"]);
  assert.deepEqual(parseMfaPolicy({ required: true, applies_to_caller: true })?.roles, []);
});

test("onboarding finishes on the enrol screen when enrolment is owed", () => {
  assert.equal(onboardingCompletionTarget(true), "/settings/security?setup=1");
  assert.equal(onboardingCompletionTarget(false), "/?welcome=1");
});

test("the banner shows everywhere except on the enrol screen itself", () => {
  assert.equal(showsSecureAccountBanner(true, "/"), true);
  assert.equal(showsSecureAccountBanner(true, "/team"), true);
  assert.equal(showsSecureAccountBanner(true, "/settings/security"), false);
  assert.equal(showsSecureAccountBanner(true, "/settings/security/"), false);
  assert.equal(showsSecureAccountBanner(false, "/team"), false);
});

test("the setup page welcomes while enrolment is owed and offers a way on once it is not", () => {
  assert.equal(setupPageLead(true, true), "welcome");
  assert.equal(setupPageLead(true, false), "continue");
  assert.equal(setupPageLead(false, true), null);
  assert.equal(setupPageLead(false, false), null);
  assert.equal(SETUP_CONTINUE_HREF, onboardingCompletionTarget(false));
});
