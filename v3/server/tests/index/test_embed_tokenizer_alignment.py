"""A tokenizer that pads to a fixed length but truncates later must not
break embedding.

The 2026-09-27 revision of ``qdrant/all-MiniLM-L6-v2-onnx`` (palaia's
default model) left padding fixed at 128 tokens while fastembed's
truncation moved to 256. Any batch mixing a short and a long text then
produced sequences of different lengths, and every embedding batch failed.
"""

from __future__ import annotations

import pytest

tokenizers = pytest.importorskip("tokenizers", reason="the embeddings extra is not installed")

from palaia_hub.index.embeddings import align_truncation_with_fixed_padding  # noqa: E402

FIXED = 8


def _tokenizer(*, truncate_at: int | None) -> tokenizers.Tokenizer:
    vocab = {"[UNK]": 0, "[PAD]": 1, **{f"w{i}": i + 2 for i in range(40)}}
    tok = tokenizers.Tokenizer(tokenizers.models.WordLevel(vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    tok.enable_padding(length=FIXED, pad_id=1, pad_token="[PAD]")
    if truncate_at is not None:
        tok.enable_truncation(max_length=truncate_at)
    return tok


def _lengths(tok: tokenizers.Tokenizer) -> set[int]:
    short = "w1 w2"
    long = " ".join(f"w{i}" for i in range(12))
    return {len(encoding.ids) for encoding in tok.encode_batch([short, long])}


def test_the_broken_configuration_really_yields_mixed_lengths() -> None:
    assert _lengths(_tokenizer(truncate_at=FIXED * 2)) == {FIXED, 12}


def test_truncation_is_pulled_down_to_the_fixed_padding_length() -> None:
    tok = _tokenizer(truncate_at=FIXED * 2)
    assert align_truncation_with_fixed_padding(tok) == FIXED
    assert _lengths(tok) == {FIXED}


def test_a_tokenizer_with_no_truncation_is_aligned_too() -> None:
    tok = _tokenizer(truncate_at=None)
    assert align_truncation_with_fixed_padding(tok) == FIXED
    assert _lengths(tok) == {FIXED}


def test_a_consistent_tokenizer_is_left_alone() -> None:
    tok = _tokenizer(truncate_at=FIXED)
    assert align_truncation_with_fixed_padding(tok) is None
    assert tok.truncation["max_length"] == FIXED


def test_dynamic_padding_is_left_alone() -> None:
    vocab = {"[UNK]": 0, "[PAD]": 1}
    tok = tokenizers.Tokenizer(tokenizers.models.WordLevel(vocab, unk_token="[UNK]"))
    tok.enable_padding(pad_id=1, pad_token="[PAD]")
    tok.enable_truncation(max_length=256)
    assert align_truncation_with_fixed_padding(tok) is None
    assert tok.truncation["max_length"] == 256
