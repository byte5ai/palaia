"""The golden vault's query battery (SPEC-113 deliverable #1).

Two flavors, both against the ``work`` vault unless noted:

- :data:`MUST_INCLUDE` — spot checks: a query paired with permalinks that
  MUST appear among its results. Used where a scenario only needs to prove
  "this is findable", not "these are exactly the results".
- :data:`CANONICAL_QUERIES` — the fixed query list SPEC-113's rebuild
  scenario (S4) runs before and after reindexing and asserts byte-for-byte
  identical permalink sets against (format spec §10: "reindex MUST
  reproduce identical query results from files alone").

Every query here is deliberately chosen to also exercise a specific corpus
feature: a forward reference (``"Q3 Roadmap"``), a personal-vault-only hit,
and a query with no matches at all (the empty case is a result too).
"""

from __future__ import annotations

#: query -> permalinks that MUST be present in that query's results
#: (against the golden ``work`` vault, except where marked "(personal)").
MUST_INCLUDE: dict[str, list[str]] = {
    "API Gateway": ["projects/api-gateway"],
    "Vault Engine": ["projects/vault-engine"],
    "Alice Novak": ["people/alice-novak"],
    "Rate limit decision": ["inbox/rate-limit-decision-from-pr-review"],
    # Forward reference (vault-format.md §5.2): "Q3 Roadmap" names no entity
    # that exists anywhere in the vault; the note that *references* it must
    # still be findable by that text.
    "Q3 Roadmap": ["projects/legacy-migration"],
    "curator": ["projects/curator"],
    # personal vault
    "marathon": ["projects/marathon-training"],  # (personal)
}

#: A query with no matches anywhere in the golden ``work`` vault — the
#: empty-result case is part of the contract too.
NO_MATCH_QUERY = "xyzzy-nonexistent-term-42"

#: Fixed query set for the S4 rebuild-identity check. Deliberately a mix of
#: title hits, body-only hits, and a forward reference.
CANONICAL_QUERIES: list[str] = [
    "API Gateway",
    "Vault Engine",
    "Recall Engine",
    "Dashboard",
    "Alice Novak",
    "curator",
    "rate limit",
    "Q3 Roadmap",
    "commit messages",
    NO_MATCH_QUERY,
]

__all__ = ["CANONICAL_QUERIES", "MUST_INCLUDE", "NO_MATCH_QUERY"]
