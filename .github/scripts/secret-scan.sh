#!/usr/bin/env bash
# Runs gitleaks over what this event introduced — or over everything, when it cannot tell.
#
# WHY THE RANGE IS CHOSEN HERE AND NOT BY THE WORKFLOW
#   A pull request should be judged on the commits it adds (BASE..HEAD). Judged on the whole
#   history, every PR would be red for a secret somebody committed years ago, and "a check that
#   is always red is a check nobody reads". A push to main is judged on what the push added.
#   A scheduled run, a manual run, and any event whose base cannot be resolved (a first push, a
#   force-push) scan ALL of history: a wasted minute is cheaper than a skipped scan reporting
#   clean — the rule backend-ci.yml's `scope` job applies to its own filter.
#
#   It lives in a script rather than inline in the workflow so it can be run and tested: the
#   range logic is the part that goes wrong quietly.
#
# `--redact` IS NOT OPTIONAL. The log of a run on a public repository is public, and an
#   unredacted finding prints the very secret it found.
#
# Environment: EVENT_NAME (required); BASE_SHA and HEAD_SHA for a pull request; BEFORE_SHA and
#   AFTER_SHA for a push; GITLEAKS to name the binary (default: gitleaks on PATH).
set -euo pipefail

gitleaks="${GITLEAKS:-gitleaks}"
event="${EVENT_NAME:?EVENT_NAME is required}"
zeros="0000000000000000000000000000000000000000"

reachable() { [ -n "${1:-}" ] && [ "$1" != "$zeros" ] && git cat-file -e "${1}^{commit}" 2>/dev/null; }

range=""
case "$event" in
  pull_request)
    if reachable "${BASE_SHA:-}" && reachable "${HEAD_SHA:-}"; then
      range="${BASE_SHA}..${HEAD_SHA}"
    fi
    ;;
  push)
    if reachable "${BEFORE_SHA:-}" && reachable "${AFTER_SHA:-}"; then
      range="${BEFORE_SHA}..${AFTER_SHA}"
    fi
    ;;
esac

# --verbose prints each finding (rule, file, line, commit) — without it gitleaks says only "leaks
# found: 1" and a red run tells nobody what to fix. The VALUE stays redacted.
args=(git . --config .gitleaks.toml --redact --verbose --no-banner)
if [ -n "$range" ]; then
  echo "secret scan: the commits in ${range}"
  args+=("--log-opts=${range}")
else
  echo "secret scan: ALL of history (event '${event}'${BASE_SHA:+, base given but unusable})"
fi

exec "$gitleaks" "${args[@]}"
