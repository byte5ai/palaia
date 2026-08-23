"""Round-trip stability, fuzz safety and parse-time budget (SPEC-103).

Three acceptance criteria live here:

* **Round-trip is a fixed point.** ``render_note`` canonicalizes frontmatter
  (key order, quoting) but leaves the body untouched, so re-parsing what it
  produces should be *stable*: a second render/parse cycle changes nothing
  further. We check the fixed point one render past the first, not against
  the very first parse, because the first parse of a non-canonical or
  degraded file (a defaulted title, a reordered frontmatter block) can
  legitimately shift line numbers and warnings once — that's the
  canonicalization the render is for, not an instability bug. Requiring
  ``parse(x) == parse(x)``'s own second application is the corpus-independent
  form of that guarantee.
* **Garbage never raises.** Across a spread of adversarial and random inputs,
  ``parse_note`` always returns a ``ParsedNote`` — never an exception.
* **Parse time stays flat.** A corpus-sized note parses in well under a
  millisecond at the median; this guards against catastrophic regex
  backtracking creeping in as the grammar grows.
"""

from __future__ import annotations

import random
import statistics
import time
from pathlib import Path

import pytest

from palaia_hub.vault.parse import parse_note, render_note, to_json

CORPUS_DIR = Path(__file__).resolve().parents[3] / "docs" / "vault-format-conformance"


def _corpus_texts() -> list[tuple[str, str]]:
    return [
        (path.name, path.read_bytes().decode("utf-8"))
        for path in sorted(CORPUS_DIR.glob("*.md"))
        if path.with_suffix("").with_suffix(".expected.json").exists()
    ]


@pytest.mark.parametrize(
    "name,text", _corpus_texts(), ids=[name for name, _ in _corpus_texts()]
)
def test_render_parse_reaches_a_fixed_point(name: str, text: str) -> None:
    first = parse_note(text, name)
    rendered_once = render_note(first)
    second = parse_note(rendered_once, name)
    rendered_twice = render_note(second)
    third = parse_note(rendered_twice, name)

    assert to_json(second) == to_json(third), (
        f"{name}: render/parse did not stabilize after one canonicalization pass"
    )
    assert rendered_once == rendered_twice, (
        f"{name}: render_note is not idempotent on its own output"
    )


# --------------------------------------------------------------------------
# Fuzz: random garbage never raises
# --------------------------------------------------------------------------

_ADVERSARIAL_INPUTS = [
    "",
    "\x00\x01\x02",
    "---",
    "---\n",
    "---\n---",
    "---\ntitle: [\n---\n",
    "- [" * 200,
    "[[" * 500,
    "]]" * 500,
    "#" * 10_000,
    "- [cat] " + ("x" * 100_000),
    "```\n" * 1000,
    "> " * 5000 + "- [cat] deeply quoted",
    "﻿---\ntitle: \ud83d\n---\nbody",
    "---\n" + "a: b\n" * 5000 + "---\nbody",
    "- relates_to [[" + ("a" * 50_000) + "]]",
    "\r\n\r\n\r\n",
    "title: no fence at all\npermalink: nope\n",
]


@pytest.mark.parametrize("text", _ADVERSARIAL_INPUTS)
def test_adversarial_input_never_raises(text: str) -> None:
    note = parse_note(text, "fuzz.md")
    assert note.title  # always non-empty (defaults to the filename stem)
    to_json(note)  # serialization must not raise either


def test_random_bytes_never_raise() -> None:
    rng = random.Random(103)
    for _ in range(200):
        length = rng.randint(0, 2000)
        raw = bytes(rng.randrange(256) for _ in range(length))
        text = raw.decode("utf-8", errors="replace")
        note = parse_note(text, "random.md")
        to_json(note)


def test_random_markdown_shaped_garbage_never_raises() -> None:
    rng = random.Random(104)
    tokens = [
        "- [",
        "]",
        "|",
        "[[",
        "]]",
        "#",
        "^",
        "\n",
        "> ",
        "```",
        "~~~",
        "relates_to",
        '"quoted type"',
        "---",
        ":",
        "  ",
        "\t",
        "title",
        "2026-08-22",
    ]
    for _ in range(200):
        length = rng.randint(0, 80)
        text = "".join(rng.choice(tokens) for _ in range(length))
        note = parse_note(text, "garbage.md")
        to_json(note)


# --------------------------------------------------------------------------
# Performance: p50 parse time on a corpus-sized note
# --------------------------------------------------------------------------


def _sized_note(observation_count: int) -> str:
    lines = [
        "---",
        "title: Perf Note",
        "permalink: notes/perf-note",
        "type: note",
        "tags: [perf, bench]",
        "---",
        "",
        "Some intro prose with a [[Related Entity]] mention.",
        "",
    ]
    for i in range(observation_count):
        lines.append(f"- [fact-{i % 7}] Observation number {i} #bench (context {i}) ^anchor-{i}")
        lines.append(f"- relates_to [[Target {i}]]")
    return "\n".join(lines) + "\n"


def test_parse_time_p50_under_one_millisecond() -> None:
    # "Corpus-sized": the largest golden file (case 03) is 27 lines; 15
    # observation pairs (30 body lines + the frontmatter block) is already
    # bigger than any real corpus fixture, so this is a comfortable margin
    # above what the SPEC calls "corpus-sized", not a best case.
    text = _sized_note(observation_count=15)
    timings: list[float] = []
    for _ in range(200):
        started = time.perf_counter()
        parse_note(text, "perf-note.md")
        timings.append((time.perf_counter() - started) * 1000)
    p50 = statistics.median(timings)
    assert p50 < 1.0, f"parse p50 {p50:.3f} ms exceeds the 1 ms budget"
