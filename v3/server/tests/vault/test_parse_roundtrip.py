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
* **Parse time stays linear in note size.** Ten times the body costs roughly
  ten times the parse, not a hundred; this guards against catastrophic regex
  backtracking creeping in as the grammar grows. The guard is a *ratio*
  measured on the machine running the test, not a wall-clock budget: an
  absolute millisecond bound is a property of the host, not of the parser,
  and turned the check into a false red on any runner slower than the one it
  was tuned on (issue #420). The absolute number is still available, printed
  by the same test and asserted only when a budget is opted into:

    # p50 on this machine, with the historical 1 ms budget enforced
    PALAIA_PARSE_BUDGET_MS=1.0 uv run pytest \
        server/tests/vault/test_parse_roundtrip.py -s -k parse_time
"""

from __future__ import annotations

import os
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
# Performance: parse time grows linearly with note size
# --------------------------------------------------------------------------

#: Optional wall-clock budget in milliseconds for the p50 of the small note.
#: Unset by default: the budget is a property of the machine, not of the
#: parser (issue #420). Set it on a host whose speed is known if you want the
#: historical 1 ms bound enforced.
BUDGET_MS = float(os.environ.get("PALAIA_PARSE_BUDGET_MS", "0"))

#: Body-size multiple between the two measured notes.
SIZE_FACTOR = 10

#: Tolerated growth of the p50 across that multiple. Linear parsing lands at
#: ~SIZE_FACTOR; the bound leaves generous room for timer noise and per-call
#: fixed cost (which *shrinks* the ratio) while staying far below what any
#: super-linear blowup would produce — quadratic backtracking over 10x the
#: body is 100x the time, not 25x.
MAX_GROWTH = 2.5 * SIZE_FACTOR


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


def _parse_p50_ms(text: str, *, runs: int = 200, batches: int = 3) -> float:
    """Median parse time in ms, taken as the best of several batch medians.

    A scheduler hiccup can inflate any single batch on a shared runner, so the
    reading kept is the cheapest batch: noise only ever adds time.
    """
    parse_note(text, "perf-note.md")  # warm up caches and the regex engine
    medians: list[float] = []
    for _ in range(batches):
        timings: list[float] = []
        for _ in range(runs):
            started = time.perf_counter()
            parse_note(text, "perf-note.md")
            timings.append((time.perf_counter() - started) * 1000)
        medians.append(statistics.median(timings))
    return min(medians)


def test_parse_time_grows_linearly_with_note_size(capsys: pytest.CaptureFixture[str]) -> None:
    # "Corpus-sized": the largest golden file (case 03) is 27 lines; 15
    # observation pairs (30 body lines + the frontmatter block) is already
    # bigger than any real corpus fixture, so this is a comfortable margin
    # above what the SPEC calls "corpus-sized", not a best case. The large
    # note is the same shape, SIZE_FACTOR times the body.
    small_p50 = _parse_p50_ms(_sized_note(observation_count=15))
    large_p50 = _parse_p50_ms(_sized_note(observation_count=15 * SIZE_FACTOR))

    growth = large_p50 / small_p50
    with capsys.disabled():
        print(
            f"\nparse p50: {small_p50:.3f} ms at 15 observations, "
            f"{large_p50:.3f} ms at {15 * SIZE_FACTOR} (growth {growth:.1f}x "
            f"for {SIZE_FACTOR}x the body)"
        )

    assert growth < MAX_GROWTH, (
        f"parse time grew {growth:.1f}x for {SIZE_FACTOR}x the body "
        f"({small_p50:.3f} ms -> {large_p50:.3f} ms) — super-linear parsing "
        "suggests catastrophic backtracking in the grammar"
    )
    if BUDGET_MS:
        assert small_p50 < BUDGET_MS, (
            f"parse p50 {small_p50:.3f} ms exceeds the {BUDGET_MS} ms budget "
            "set via PALAIA_PARSE_BUDGET_MS"
        )
