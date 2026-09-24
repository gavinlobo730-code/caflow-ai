/**
 * What this product says about filing — the browser's FALLBACK copy.
 *
 * THE AUTHORITY IS `apps/api/domain/filing_posture.py`, and every filing-demo
 * response carries it as `script.posture`. This file exists only for the
 * window where the frontend has redeployed ahead of the backend, and for the
 * moment before the script has loaded — the wizard's banner renders
 * immediately, deliberately, so that somebody glancing at the screen while it
 * is still fetching cannot mistake it for a real filing.
 *
 * It is a FALLBACK, not a second implementation, and both halves of that are
 * enforced. Every render reaches it through a `??` so a served value always
 * wins; and
 * `apps/api/tests/test_one_filing_posture_and_the_browser_echoes_it.py` pins
 * each field to the Python authority's, FROM THE PYTHON SIDE — a guard
 * written here would assert this file against a copy of itself and pass
 * whenever both drifted together, which is exactly what the Schedule III
 * caption list did for months.
 *
 * So: do not edit these strings. Edit `domain/filing_posture.py` and let the
 * guard tell you to copy them across.
 */
export interface FilingPosture {
  badge: string;
  headline: string;
  body: string;
  roadmap: string;
  disclaimer: string;
}

export const FILING_POSTURE: FilingPosture = {
  badge: "DEMO",
  headline: "Demonstration — no return is being filed",
  body:
    "A step-by-step walk-through of the real submission sequence. No data " +
    "leaves PracticeSync, no government system is contacted, and no filing " +
    "status changes.",
  roadmap:
    "PracticeSync prepares the return and you submit it on the authority's " +
    "own portal. Direct submission from within PracticeSync is planned: it " +
    "requires authorisation from GSTN, the Income Tax Department or NIC, " +
    "which those bodies grant only to registered providers.",
  disclaimer:
    "DEMONSTRATION — nothing was transmitted to any government system and " +
    "nothing has been filed. No stored status has changed. PracticeSync " +
    "prepares this return; submission happens on the authority's own " +
    "portal. Direct submission from within PracticeSync is planned and " +
    "requires a registration with the relevant authority.",
};
