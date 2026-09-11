#!/usr/bin/env bash
# Run an advisory audit and make its outcome visible without gating the job
# (v3-ci.yml `dependency-audit`, issue #401): the full output lands in the
# job summary, and a non-zero exit becomes a workflow warning annotation.
#
# Usage: report-audit.sh "<label>" <command...>
set -uo pipefail
label="$1"
shift
output="$(mktemp)"
"$@" 2>&1 | tee "${output}"
status=${PIPESTATUS[0]}
{
  echo "### ${label}"
  echo
  if [[ ${status} -eq 0 ]]; then
    echo "No advisories."
  else
    echo "**Advisories found (exit ${status}).** Per v3/docs/security/dependencies.md a high/critical"
    echo "advisory in something a user runs blocks the next release; check before cutting one."
  fi
  echo
  echo '```'
  tail -n 200 "${output}"
  echo '```'
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
if [[ ${status} -ne 0 ]]; then
  echo "::warning title=${label}::advisories found — see the job summary"
fi
rm -f "${output}"
exit "${status}"
