"""THE MARKETING SITE'S PALETTE IS THE PRODUCT'S, AND NOW SOMETHING SAYS SO.

`apps/marketing/tailwind.config.ts` opened with

    // Brand tokens mirror apps/web/tailwind.config.ts so the marketing site and
    // the application read as one product.

and nothing checked it. A comment asserting a mirror that nothing enforces is
the drift shape CLAUDE.md records three times — the Schedule III caption list,
the Team screen's `ROLE_DEFAULTS`, the browser's Schedule III fallback — and in
each of those the copy had drifted in BOTH directions before anybody looked.

It had drifted here too, in the quieter direction: nine of the ten colours
agreed to the character, and the tenth — `brand.hover: #0F1A3D` — existed in
this file and **nowhere in the product**. `apps/web` expresses a brand-primary
hover as `hover:bg-brand-dark` at fifteen sites, so the marketing site's
primary CTA was hovering to a navy the application never uses. It is gone and
both call sites take `brand-dark`.

Three `boxShadow` tokens went with it — `card`, `card-hover`, `modal` — the
same three T3-a deleted from `apps/web/tailwind.config.ts`. `grep -r
"shadow-card"` over `apps/marketing` was empty: a palette the site declared and
never wore.

**THIS GUARD IS ON THE PYTHON SIDE** and that is not the Schedule III reflex
applied blindly — the two files here are in DIFFERENT apps, so a check in
`apps/web` would not be asserting a copy against itself. It is Python because
the required `pytest — mock mode` check runs on every push, where the Node job
is behind a `scope` filter that a marketing-only change can miss. CLAUDE.md's
warning about path-filtered workflows is the reason.

**IT IS ONE-DIRECTIONAL, deliberately.** Every colour the marketing site
declares must equal the product's at the same path; the product may hold
tokens the marketing site does not, because `apps/web` has thirty-four and a
landing page needs ten. The claim being enforced is the one the comment makes.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
WEB_CONFIG = REPO / "apps" / "web" / "tailwind.config.ts"
MKT_CONFIG = REPO / "apps" / "marketing" / "tailwind.config.ts"

#: A token the marketing site may declare that the product does not, with the
#: reason. EMPTY, and that is the point: the one entry that would have gone
#: here (`brand.hover`) was a colour nobody chose for the product, so it was
#: removed rather than exempted. An entry here is a claim that the two sites
#: deliberately differ, which is a design decision and belongs in a review.
MARKETING_ONLY: dict[str, str] = {}

#: Read the real TS object rather than regexing hexes out of it: a regex would
#: match a colour inside a comment, and both files explain their choices in
#: prose. Node is present in CI for the frontend job and locally; where it is
#: not, the test SKIPS rather than passing silently.
_EXTRACT = r"""
const src = require("fs").readFileSync(process.argv[1], "utf8");
const i = src.indexOf("colors: {");
if (i < 0) { process.stdout.write("{}"); } else {
  let depth = 0, j = i + "colors: ".length, out = "";
  for (; j < src.length; j++) {
    const ch = src[j];
    if (ch === "{") depth++;
    if (ch === "}") { depth--; if (!depth) { out += ch; break; } }
    out += ch;
  }
  const clean = out.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const obj = eval("(" + clean + ")");
  const flat = {};
  const walk = (o, p) => {
    for (const [k, v] of Object.entries(o)) {
      const key = p ? `${p}.${k}` : k;
      if (v && typeof v === "object") walk(v, key);
      else if (typeof v === "string" && v.startsWith("#")) flat[key] = v.toUpperCase();
    }
  };
  walk(obj, "");
  process.stdout.write(JSON.stringify(flat));
}
"""


def _colours(path: pathlib.Path) -> dict[str, str]:
    proc = subprocess.run(
        ["node", "-e", _EXTRACT, str(path)], capture_output=True, text=True
    )
    if proc.returncode != 0:
        pytest.skip(f"node cannot read {path.name} here: {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout or "{}")


def test_both_configs_are_readable():
    """Vacuity floor. Two of the assertions below are 'nothing differs', which
    is also what an empty read reports."""
    web, mkt = _colours(WEB_CONFIG), _colours(MKT_CONFIG)
    assert len(web) >= 25, f"only {len(web)} product colours — the extractor is broken"
    assert len(mkt) >= 8, f"only {len(mkt)} marketing colours — the extractor is broken"


def test_every_marketing_colour_equals_the_products():
    web, mkt = _colours(WEB_CONFIG), _colours(MKT_CONFIG)
    differing = {
        k: (mkt[k], web[k]) for k in sorted(set(mkt) & set(web)) if mkt[k] != web[k]
    }
    assert not differing, (
        "apps/marketing declares a colour under the same name as the product and "
        "gives it a different value, so the two sites no longer read as one:\n  "
        + "\n  ".join(f"{k}: marketing {m}, product {w}" for k, (m, w) in differing.items())
    )


def test_the_marketing_site_invents_no_colour_of_its_own():
    web, mkt = _colours(WEB_CONFIG), _colours(MKT_CONFIG)
    invented = sorted(set(mkt) - set(web) - set(MARKETING_ONLY))
    assert not invented, (
        "apps/marketing declares a colour the product does not have. Use the "
        "product's token for that role — a brand-primary hover is `brand-dark`, "
        "which apps/web uses at fifteen sites — or add it to MARKETING_ONLY with "
        "the reason the two deliberately differ:\n  "
        + "\n  ".join(f"{k} = {mkt[k]}" for k in invented)
    )


def test_the_product_may_hold_tokens_the_marketing_site_does_not():
    """The check is one-directional and this states it, so nobody `fixes` the
    asymmetry by copying thirty-four tokens into a landing page."""
    web, mkt = _colours(WEB_CONFIG), _colours(MKT_CONFIG)
    assert set(web) - set(mkt), (
        "the product now declares no colour the marketing site lacks, which "
        "means either the palettes converged or somebody copied the whole "
        "product config across. Read the docstring before relaxing this."
    )


def test_the_dead_shadow_tokens_did_not_come_back():
    """`card`, `card-hover` and `modal` were declared and never used. T3-a
    deleted the same three from apps/web; they are not re-declared here without
    a call site."""
    src = MKT_CONFIG.read_text(encoding="utf-8")
    code = "\n".join(line.split("//", 1)[0] for line in src.splitlines())
    assert "boxShadow: {" not in code, (
        "apps/marketing declares boxShadow tokens again. If they are used, say "
        "where; if they are not, they are the palette T3-a deleted."
    )


@pytest.mark.parametrize("token", ["brand-hover", "brand\\.hover"])
def test_no_call_site_still_reaches_for_the_removed_token(token: str):
    """A Tailwind class naming a token the config does not declare is simply
    absent from the emitted CSS, and the element renders unstyled — so a
    leftover `hover:bg-brand-hover` fails silently in the browser rather than
    at build time. That is why this is asserted rather than left to the build."""
    import re

    pattern = re.compile(token)
    offenders = []
    for p in (REPO / "apps" / "marketing").rglob("*.ts*"):
        if "node_modules" in p.parts:
            continue
        src = p.read_text(encoding="utf-8")
        code = "\n".join(line.split("//", 1)[0] for line in src.splitlines())
        if pattern.search(code):
            offenders.append(str(p.relative_to(REPO)))
    assert not offenders, (
        f"these still reference the removed `{token}` token: " + ", ".join(offenders)
    )


def test_the_header_comment_names_this_guard():
    """The comment claiming the mirror must say where the mirror is enforced,
    or the next reader has the same unchecked claim this test was written for."""
    src = MKT_CONFIG.read_text(encoding="utf-8")
    assert "test_the_marketing_site_reads_as_one_product" in src
