#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Generator for a toy vault of N notes (frontmatter + observations +
wikilinks), per SPEC-003 deliverable #1.

Usable as a library (import gen_vault; gen_vault.write_vault(...)) by the
other spike scripts, or standalone:

    uv run gen_vault.py --n 1000 --out /tmp/toy-vault --seed 42
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import random
from pathlib import Path

CATEGORIES = ["fact", "decision", "preference", "technique", "issue", "idea"]
REL_TYPES = ["relates_to", "depends_on", "part_of", "contradicts", "follows"]
TOPICS = [
    "authentication", "vault-format", "recall-scoring", "git-layer",
    "dashboard-ux", "mcp-gateway", "curator-policy", "inbox-contract",
    "embedding-model", "search-ranking", "schema-inference", "event-bus",
    "oauth-flow", "session-scoping", "importer-basic-memory", "hub-config",
    "watcher-debounce", "sqlite-index", "graph-traversal", "token-budget",
]
WORDS = (
    "the system should always prefer synchronous writes over eventual "
    "consistency because agents need to see their own writes immediately "
    "and the vault is the source of truth for every derived index we build "
    "on top of it later during recall and search"
).split()


def _permalink(n: int) -> str:
    return f"note-{n:06d}"


def _title(n: int, rng: random.Random) -> str:
    topic = rng.choice(TOPICS)
    return f"{topic.replace('-', ' ').title()} — note {n}"


def _prose(rng: random.Random, forward_ref: str | None) -> str:
    sentence = " ".join(rng.choices(WORDS, k=rng.randint(8, 16)))
    if forward_ref:
        sentence += f" See also [[{forward_ref}]] for more context."
    return sentence.capitalize() + "."


def make_note_text(n: int, total: int, rng: random.Random) -> tuple[str, str]:
    """Return (permalink, markdown_text) for note n of `total`."""
    permalink = _permalink(n)
    title = _title(n, rng)
    tags = rng.sample(TOPICS, k=rng.randint(1, 3))
    created = (
        dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        + dt.timedelta(minutes=n)
    ).isoformat()

    # ~15% of notes carry a forward reference to a note that does not exist
    # yet (higher permalink number), per research/basic-memory.md §1.
    forward_target = None
    if total > 1 and rng.random() < 0.15:
        forward_target = _permalink(rng.randint(n + 1, total - 1) if n < total - 1 else n)

    prose = _prose(rng, forward_target)

    n_obs = rng.randint(1, 4)
    obs_lines = []
    for _ in range(n_obs):
        cat = rng.choice(CATEGORIES)
        text = " ".join(rng.choices(WORDS, k=rng.randint(4, 10)))
        obs_tags = " ".join(f"#{t}" for t in rng.sample(TOPICS, k=rng.randint(0, 2)))
        has_ctx = rng.random() < 0.4
        ctx = f" ({rng.choice(['from review', 'user reported', 'design call'])})" if has_ctx else ""
        obs_lines.append(f"- [{cat}] {text} {obs_tags}{ctx}".rstrip())

    n_rel = rng.randint(0, 2)
    rel_lines = []
    for _ in range(n_rel):
        target_n = rng.randint(0, total - 1)
        if target_n == n:
            continue
        rel_type = rng.choice(REL_TYPES)
        ctx = f" ({rng.choice(['supersedes v2', 'discussed in standup', ''])})".rstrip()
        ctx = ctx if ctx.strip() != "()" else ""
        rel_lines.append(f"- {rel_type} [[{_permalink(target_n)}]]{ctx}")

    text = (
        "---\n"
        f"title: {title}\n"
        "type: note\n"
        f"permalink: {permalink}\n"
        f"tags: [{', '.join(tags)}]\n"
        f"created: {created}\n"
        f"modified: {created}\n"
        "---\n\n"
        f"# {title}\n\n"
        f"{prose}\n\n"
        "## Observations\n"
        + "\n".join(obs_lines)
        + "\n\n## Relations\n"
        + ("\n".join(rel_lines) if rel_lines else "(none)")
        + "\n"
    )
    return permalink, text


def write_vault(out_dir: str | os.PathLike, n: int, seed: int = 42) -> list[str]:
    """Write n toy notes into out_dir (flat, one file per note). Returns
    the list of file paths written, in generation order."""
    rng = random.Random(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        permalink, text = make_note_text(i, n, rng)
        p = out / f"{permalink}.md"
        p.write_text(text, encoding="utf-8")
        paths.append(str(p))
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    paths = write_vault(args.out, args.n, args.seed)
    print(f"wrote {len(paths)} notes to {args.out}")


if __name__ == "__main__":
    main()
