"""Errors raised while validating or applying a mode/exposure change (SPEC-205)."""

from __future__ import annotations


class ModeChangeError(RuntimeError):
    """A requested mode/exposure change fails precondition validation.

    Always carries an actionable message — same convention as
    :class:`palaia_hub.config.ConfigError` and
    :class:`palaia_hub.auth.policy.AuthPolicyError`: name what is wrong and
    what to do about it, never just "invalid".
    """


__all__ = ["ModeChangeError"]
