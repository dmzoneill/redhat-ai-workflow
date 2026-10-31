"""Tests for the linear-time skill detection patterns in aa_ollama skill discovery."""

import re

import pytest

from tool_modules.aa_ollama.src.skill_discovery import OrderedSubstrings, detect_skill

# The original backtracking regexes, used as the reference behaviour.
REFERENCE = [
    (OrderedSubstrings("spin", "up", "mr"), r"spin.*up.*mr"),
    (OrderedSubstrings("test", "in", "ephemeral"), r"test.*in.*ephemeral"),
    (OrderedSubstrings("check", "mr", "review"), r"check.*mr.*review"),
    (OrderedSubstrings("look", "at", "mr"), r"look.*at.*mr"),
    (OrderedSubstrings("start", "work", "aap-", digit_after_last=True), r"start.*work.*aap-\d+"),
    (OrderedSubstrings("pick", "up", "aap-", digit_after_last=True), r"pick.*up.*aap-\d+"),
    (OrderedSubstrings("look", "into", "alert"), r"look.*into.*alert"),
    (OrderedSubstrings("push", "and", "mr"), r"push.*and.*mr"),
]

SAMPLES = [
    "Spin up MR 123",
    "please spin it up for mr",
    "mr spin up",
    "spin\nup mr",
    "Test this in ephemeral",
    "ephemeral test in",
    "check the MR for review",
    "review the mr check",
    "look at MR !42",
    "LOOK AT\nMR",
    "start work on AAP-1234",
    "start work on aap-x",
    "start work on aap-x then aap-9",
    "aap-12 start work",
    "pick up aap-77",
    "pick it up aap-",
    "look into the alert",
    "alert look into",
    "push and open mr",
    "push the branch\nand mr",
    "",
    "nothing relevant",
    "spinupmr",
]


@pytest.mark.parametrize(("matcher", "regex"), REFERENCE)
@pytest.mark.parametrize("text", SAMPLES)
def test_matches_original_regex(matcher, regex, text):
    """OrderedSubstrings agrees with the regex it replaced."""
    assert matcher.search(text) == bool(re.search(regex, text, re.IGNORECASE))


def test_long_input_is_fast():
    """Adversarial input without a match completes (no catastrophic backtracking)."""
    text = "spin " * 50_000
    assert not OrderedSubstrings("spin", "up", "mr").search(text)


@pytest.mark.parametrize(
    ("message", "skill"),
    [
        ("can you spin up mr 5", "test_mr_ephemeral"),
        ("check the mr and review it", "review_pr"),
        ("pick up AAP-555", "start_work"),
        ("look into this alert", "investigate_slack_alert"),
        ("push and mr please", "create_mr"),
        ("hello there", None),
    ],
)
def test_detect_skill(message, skill):
    """detect_skill still routes messages that use the converted patterns."""
    assert detect_skill(message) == skill
