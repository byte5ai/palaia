"""The curator's system prompt, assembled at runtime (SPEC-206 "The prompt").

Three parts, in this order:

(a) :data:`ROLE_BLOCK` — fixed, quoted verbatim from the SPEC. It is not
    edited here, ever: the SPEC calls it a "binding starting point — tune via
    PR", which means a prompt change is a spec change, not a code change.
(b) the vault's own ``meta/curation.md`` note, read live if it exists —
    per-vault rules the owner maintains in the vault itself. Absent is fine;
    the format spec's defaults apply.
(c) the capture being curated: its id, permalink and full text.

The JSON self-report the last line asks for is parsed
(:func:`palaia_hub.curator.models.parse_self_report`) and recorded, but never
believed — classification is the runner's own vault search (SPEC-206 rule 3).
It is asked for anyway because it makes a session's *intent* legible in the
audit trail when verification disagrees with it.
"""

from __future__ import annotations

#: The vault note holding per-vault curation rules (part (b) above).
CURATION_NOTE_PERMALINK = "meta/curation"

#: SPEC-206 "The prompt (binding starting point — tune via PR)", verbatim.
#: ``{vault_name}`` and ``{purpose}`` fill the SPEC's own ``<name>`` /
#: ``<purpose>`` placeholders.
ROLE_BLOCK = """\
You are the palaia curator for the vault "{vault_name}" — {purpose}. Session
agents drop raw captures into inbox/ while working on something else; this
run turns ONE capture into well-formed, findable vault knowledge. You are
unattended: you cannot ask questions — writing a proposal into review/ is
how you raise one, and it is a first-class outcome, not a failure.
INGEST is yours: a new note in the right place, or additive observations on
an existing note. MAINTENANCE is never yours: rewriting, merging, renaming
or retiring what exists — propose it in review/ and stop. The restriction
is enforced, not advisory; a rejected call is information, not an obstacle.
Search the vault at least twice (entity name, then the claim itself) before
writing; the title is the key — extend rather than duplicate. Titles and
link targets stay volatility-free. Every note you write carries
`- [source] inbox capture <capture_id>`. Never invent facts the capture
does not contain. Be conservative: a proposal costs the owner thirty
seconds; a wrong note costs the vault its trustworthiness.
End with one line of JSON: {{"action":"ingested"|"needs_review",
"targets":[…],"summary":"…","reason":"…"}}"""


def build_prompt(
    *,
    vault_name: str,
    purpose: str,
    capture_id: str,
    capture_permalink: str,
    capture_text: str,
    curation_note: str | None = None,
) -> str:
    """Assemble the full prompt for one capture's session."""
    parts = [ROLE_BLOCK.format(vault_name=vault_name, purpose=purpose.rstrip("."))]
    if curation_note and curation_note.strip():
        parts.append(
            "## This vault's own curation rules (meta/curation.md)\n\n"
            f"{curation_note.strip()}"
        )
    parts.append(
        "## The capture to curate\n\n"
        f"capture_id: {capture_id}\n"
        f"permalink: {capture_permalink}\n"
        f"provenance line every note you write must carry: "
        f"- [source] inbox capture {capture_id}\n\n"
        f"{capture_text.strip()}"
    )
    return "\n\n".join(parts) + "\n"


__all__ = ["CURATION_NOTE_PERMALINK", "ROLE_BLOCK", "build_prompt"]
