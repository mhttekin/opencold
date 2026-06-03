"""Tests for draft quality checks."""

from opencold import quality


def test_warns_when_grounded_fact_not_used():
    warnings = quality.evaluate_draft(
        "Quick question",
        "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.",
        "Acme provides invoice automation for finance teams.",
    )
    assert "no_grounded_fact_used" in warnings


def test_accepts_fact_token_usage():
    warnings = quality.evaluate_draft(
        "Invoice workflow",
        "Your invoice workflow looks relevant.\n\nI build small finance tools.\n\nWorth a quick look?",
        "Acme provides invoice automation for finance teams.",
    )
    assert "no_grounded_fact_used" not in warnings


def test_flags_missing_subject_and_length():
    body = " ".join(["word"] * 91)
    warnings = quality.evaluate_draft("", body, "")
    assert "missing_subject" in warnings
    assert "too_long" in warnings


def test_merge_warnings_deduplicates():
    merged = quality.merge_warnings("a | b", ["b", "c"])
    assert merged == "a | b | c"
