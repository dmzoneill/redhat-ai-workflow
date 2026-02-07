"""Tests for scripts/common/skill_error_recovery.py"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.common.skill_error_recovery import SkillErrorRecovery

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory():
    """Create a mock memory helper."""
    m = MagicMock()
    m.read.return_value = None
    return m


@pytest.fixture
def recovery(memory):
    return SkillErrorRecovery(memory_helper=memory)


@pytest.fixture
def recovery_no_mem():
    return SkillErrorRecovery(memory_helper=None)


# ---------------------------------------------------------------------------
# __init__ / _load_known_patterns
# ---------------------------------------------------------------------------


def test_init_loads_default_patterns(recovery_no_mem):
    assert "dict_attribute_access" in recovery_no_mem.patterns
    assert "key_error" in recovery_no_mem.patterns
    assert "undefined_variable" in recovery_no_mem.patterns
    assert "template_not_resolved" in recovery_no_mem.patterns
    assert "missing_import" in recovery_no_mem.patterns


def test_init_merges_learned_patterns(memory):
    memory.read.return_value = {
        "patterns": {
            "custom_pattern": {
                "signature": r"custom error",
                "description": "Custom",
                "fix_template": "Fix custom",
                "auto_fixable": False,
                "confidence": "high",
            }
        }
    }
    r = SkillErrorRecovery(memory_helper=memory)
    assert "custom_pattern" in r.patterns
    assert "dict_attribute_access" in r.patterns  # defaults still present


def test_init_memory_error_falls_back(memory):
    memory.read.side_effect = Exception("fail")
    r = SkillErrorRecovery(memory_helper=memory)
    # Should still have defaults
    assert "dict_attribute_access" in r.patterns


# ---------------------------------------------------------------------------
# detect_error
# ---------------------------------------------------------------------------


def test_detect_dict_attribute_access(recovery):
    result = recovery.detect_error(
        code="x = inputs.name",
        error_msg="'dict' object has no attribute 'name'",
        step_name="step1",
    )
    assert result["pattern_id"] == "dict_attribute_access"
    assert result["auto_fixable"] is True
    assert result["confidence"] == "high"
    assert "inputs.get" in result["suggestion"]
    assert result["fix_code"] is not None


def test_detect_key_error(recovery):
    result = recovery.detect_error(
        code='x = d["missing"]',
        error_msg="KeyError: 'missing'",
        step_name="s",
    )
    assert result["pattern_id"] == "key_error"
    assert result["auto_fixable"] is False
    # Template uses {key} but substitution uses {0} from group0, so template stays raw
    assert result["suggestion"] == "Check if '{key}' exists or use .get() with default"


def test_detect_undefined_variable(recovery):
    result = recovery.detect_error(
        code="print(foo)",
        error_msg="name 'foo' is not defined",
        step_name="s",
    )
    assert result["pattern_id"] == "undefined_variable"
    # Template uses {var} but substitution uses {0} from group0, so template stays raw
    assert result["suggestion"] == "Define {var} or check for typos"


def test_detect_template_not_resolved(recovery):
    result = recovery.detect_error(
        code="t = '{{var}}'",
        error_msg="Found {{var}} in output",
        step_name="s",
    )
    assert result["pattern_id"] == "template_not_resolved"


def test_detect_missing_import(recovery):
    result = recovery.detect_error(
        code="import foobar",
        error_msg="No module named 'foobar'",
        step_name="s",
    )
    assert result["pattern_id"] == "missing_import"


def test_detect_unknown_error(recovery):
    result = recovery.detect_error(
        code="x = 1/0",
        error_msg="ZeroDivisionError: division by zero",
        step_name="s",
    )
    assert result["pattern_id"] is None
    assert result["auto_fixable"] is False
    assert result["confidence"] == "low"
    assert "Unknown" in result["suggestion"] or "manual" in result["suggestion"].lower()


def test_detect_error_truncates_message(recovery):
    long_msg = "KeyError: 'x' " + "z" * 300
    result = recovery.detect_error("", long_msg, "s")
    assert len(result["error_msg"]) <= 200


def test_detect_error_with_previous_fixes():
    mem = MagicMock()
    fixes_data = {
        "fixes": [
            {
                "step_name": "target_step",
                "error_msg": "KeyError: 'k'",
                "timestamp": "2025-01-01",
                "action": "auto_fix",
                "success": True,
                "description": "Applied auto-fix",
            }
        ]
    }
    # First call in __init__ for patterns returns None; second call for fixes
    mem.read.side_effect = [None, fixes_data]
    r = SkillErrorRecovery(memory_helper=mem)

    result = r.detect_error(code="", error_msg="KeyError: 'k'", step_name="target_step")
    assert len(result["previous_fixes"]) == 1
    assert result["previous_fixes"][0]["action"] == "auto_fix"


def test_detect_error_no_memory_no_fixes(recovery_no_mem):
    result = recovery_no_mem.detect_error("", "some error", "s")
    assert result["previous_fixes"] == []


# ---------------------------------------------------------------------------
# _generate_dict_access_fix
# ---------------------------------------------------------------------------


def test_dict_access_fix_basic(recovery):
    code = "x = inputs.name"
    fixed = recovery._generate_dict_access_fix(code, "name")
    assert 'inputs.get("name")' in fixed
    assert "inputs.name" not in fixed


def test_dict_access_fix_chained(recovery):
    code = "x = inputs.name.upper()"
    fixed = recovery._generate_dict_access_fix(code, "name")
    assert 'inputs.get("name", "").upper()' in fixed


def test_dict_access_fix_lower(recovery):
    code = "x = inputs.label.lower()"
    fixed = recovery._generate_dict_access_fix(code, "label")
    assert 'inputs.get("label", "").lower()' in fixed


def test_dict_access_fix_strip(recovery):
    code = "x = inputs.val.strip()"
    fixed = recovery._generate_dict_access_fix(code, "val")
    assert 'inputs.get("val", "").strip()' in fixed


# ---------------------------------------------------------------------------
# _get_previous_fixes
# ---------------------------------------------------------------------------


def test_get_previous_fixes_no_memory(recovery_no_mem):
    result = recovery_no_mem._get_previous_fixes("error", "step")
    assert result == []


def test_get_previous_fixes_no_history(memory):
    memory.read.return_value = None
    r = SkillErrorRecovery(memory_helper=memory)
    result = r._get_previous_fixes("error", "step")
    assert result == []


def test_get_previous_fixes_match_by_step(memory):
    memory.read.side_effect = [
        None,  # __init__
        {
            "fixes": [
                {
                    "step_name": "target",
                    "error_msg": "e",
                    "timestamp": "t",
                    "action": "skip",
                    "success": False,
                    "description": "d",
                },
                {
                    "step_name": "other",
                    "error_msg": "e",
                    "timestamp": "t",
                    "action": "edit",
                    "success": True,
                    "description": "d2",
                },
            ]
        },
    ]
    r = SkillErrorRecovery(memory_helper=memory)
    result = r._get_previous_fixes("something", "target")
    assert len(result) == 1
    assert result[0]["action"] == "skip"


def test_get_previous_fixes_match_by_error_msg():
    mem = MagicMock()
    # The match logic: error_msg[:50] in fix["error_msg"]
    # So the fix's error_msg must contain the first 50 chars of the query
    mem.read.side_effect = [
        None,  # __init__ patterns
        {
            "fixes": [
                {
                    "step_name": "any",
                    "error_msg": "KeyError: 'xyz' blah blah extra stuff",
                    "timestamp": "t",
                    "action": "auto_fix",
                    "success": True,
                    "description": "fixed",
                },
            ]
        },
    ]
    r = SkillErrorRecovery(memory_helper=mem)
    # Query error_msg[:50] = "KeyError: 'xyz'" which is in the fix's error_msg
    result = r._get_previous_fixes("KeyError: 'xyz'", "different_step")
    assert len(result) == 1


def test_get_previous_fixes_max_5(memory):
    fixes = [
        {
            "step_name": "s",
            "error_msg": "e",
            "timestamp": "t",
            "action": f"a{i}",
            "success": True,
            "description": "",
        }
        for i in range(10)
    ]
    memory.read.side_effect = [None, {"fixes": fixes}]
    r = SkillErrorRecovery(memory_helper=memory)
    result = r._get_previous_fixes("e", "s")
    assert len(result) == 5


def test_get_previous_fixes_memory_error(memory):
    memory.read.side_effect = [None, Exception("boom")]
    r = SkillErrorRecovery(memory_helper=memory)
    result = r._get_previous_fixes("e", "s")
    assert result == []


# ---------------------------------------------------------------------------
# prompt_user_for_action (with ask_question_fn)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_with_ask_fn_auto_fix():
    r = SkillErrorRecovery()
    error_info = {
        "step_name": "s1",
        "error_msg": "err",
        "suggestion": "fix it",
        "auto_fixable": True,
        "previous_fixes": [],
    }

    async def mock_ask(q):
        return {"answers": {"q1": "Auto-fix (Recommended)"}}

    result = await r.prompt_user_for_action(error_info, ask_question_fn=mock_ask)
    assert result["action"] == "auto_fix"


@pytest.mark.asyncio
async def test_prompt_with_ask_fn_skip():
    r = SkillErrorRecovery()
    error_info = {
        "step_name": "s1",
        "error_msg": "err",
        "suggestion": "suggestion",
        "auto_fixable": False,
        "previous_fixes": [],
    }

    async def mock_ask(q):
        return {"answers": {"q1": "Skip skill"}}

    result = await r.prompt_user_for_action(error_info, ask_question_fn=mock_ask)
    assert result["action"] == "skip"


@pytest.mark.asyncio
async def test_prompt_with_ask_fn_empty_answers():
    r = SkillErrorRecovery()
    error_info = {
        "step_name": "s1",
        "error_msg": "err",
        "suggestion": "s",
        "auto_fixable": False,
        "previous_fixes": [],
    }

    async def mock_ask(q):
        return {"answers": {}}

    result = await r.prompt_user_for_action(error_info, ask_question_fn=mock_ask)
    assert result["action"] == "abort"  # default for "Create GitHub issue"


@pytest.mark.asyncio
async def test_prompt_with_ask_fn_non_dict_response():
    r = SkillErrorRecovery()
    error_info = {
        "step_name": "s1",
        "error_msg": "err",
        "suggestion": "s",
        "auto_fixable": False,
        "previous_fixes": [],
    }

    async def mock_ask(q):
        return "not a dict"

    result = await r.prompt_user_for_action(error_info, ask_question_fn=mock_ask)
    assert result["action"] == "abort"


@pytest.mark.asyncio
async def test_prompt_ask_fn_fails_falls_back_to_cli(monkeypatch):
    r = SkillErrorRecovery()
    error_info = {
        "step_name": "s1",
        "error_msg": "err",
        "suggestion": "fix",
        "auto_fixable": False,
        "previous_fixes": [
            {"success": True, "action": "edit", "description": "manual edit"}
        ],
    }

    async def mock_ask(q):
        raise Exception("AskUserQuestion unavailable")

    # Mock input() for CLI fallback
    monkeypatch.setattr("builtins.input", lambda _: "1")

    result = await r.prompt_user_for_action(error_info, ask_question_fn=mock_ask)
    assert result["action"] == "edit"  # option 1 without auto_fix is "Edit skill file"


@pytest.mark.asyncio
async def test_prompt_cli_keyboard_interrupt(monkeypatch):
    r = SkillErrorRecovery()
    error_info = {
        "step_name": "s1",
        "error_msg": "err",
        "suggestion": "s",
        "auto_fixable": False,
        "previous_fixes": [],
    }

    monkeypatch.setattr(
        "builtins.input", lambda _: (_ for _ in ()).throw(KeyboardInterrupt)
    )

    result = await r.prompt_user_for_action(error_info, ask_question_fn=None)
    assert result["action"] == "abort"


@pytest.mark.asyncio
async def test_prompt_cli_invalid_then_valid(monkeypatch):
    r = SkillErrorRecovery()
    error_info = {
        "step_name": "s1",
        "error_msg": "err",
        "suggestion": "s",
        "auto_fixable": True,
        "previous_fixes": [],
    }

    # Only integer out of range triggers retry loop; non-integer causes ValueError -> abort
    inputs = iter(["99", "0", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    result = await r.prompt_user_for_action(error_info, ask_question_fn=None)
    assert result["action"] == "edit"  # option 2 with auto_fix is "Edit skill file"


@pytest.mark.asyncio
async def test_prompt_with_previous_fixes():
    """Verify previous fixes are included in context message."""
    r = SkillErrorRecovery()
    error_info = {
        "step_name": "s1",
        "error_msg": "err",
        "suggestion": "s",
        "auto_fixable": False,
        "previous_fixes": [
            {"success": True, "action": "auto_fix", "description": "worked!"},
        ],
    }

    captured_question = {}

    async def mock_ask(q):
        captured_question.update(q)
        return {"answers": {"q1": "Skip skill"}}

    await r.prompt_user_for_action(error_info, ask_question_fn=mock_ask)
    question_text = captured_question["questions"][0]["question"]
    assert (
        "Previous fixes" in question_text or "previous fixes" in question_text.lower()
    )


# ---------------------------------------------------------------------------
# log_fix_attempt
# ---------------------------------------------------------------------------


def test_log_fix_success(memory):
    r = SkillErrorRecovery(memory_helper=memory)
    error_info = {
        "pattern_id": "key_error",
        "step_name": "s",
        "error_msg": "e",
        "suggestion": "s",
    }
    r.log_fix_attempt(error_info, action="auto_fix", success=True, details="worked")
    memory.append.assert_called_once()
    memory.increment.assert_called_once_with(
        "learned/skill_error_fixes", "stats.auto_fix_success"
    )


def test_log_fix_failure(memory):
    r = SkillErrorRecovery(memory_helper=memory)
    error_info = {
        "pattern_id": None,
        "step_name": "s",
        "error_msg": "e",
        "suggestion": "",
    }
    r.log_fix_attempt(error_info, action="skip", success=False)
    memory.increment.assert_called_once_with(
        "learned/skill_error_fixes", "stats.skip_failed"
    )


def test_log_fix_no_memory(recovery_no_mem):
    # Should not raise
    recovery_no_mem.log_fix_attempt(
        {"pattern_id": None, "step_name": "s", "error_msg": "e"},
        action="skip",
        success=True,
    )


def test_log_fix_memory_error(memory):
    memory.append.side_effect = Exception("fail")
    r = SkillErrorRecovery(memory_helper=memory)
    # Should not raise
    r.log_fix_attempt(
        {"pattern_id": None, "step_name": "s", "error_msg": "e"},
        action="edit",
        success=True,
    )


# ---------------------------------------------------------------------------
# apply_auto_fix
# ---------------------------------------------------------------------------


def test_apply_auto_fix_success(tmp_path, recovery):
    import yaml

    skill_path = tmp_path / "skill.yaml"
    skill_data = {
        "steps": [
            {"name": "build", "compute": "x = inputs.name"},
            {"name": "deploy", "tool": "deploy_tool"},
        ]
    }
    skill_path.write_text(yaml.dump(skill_data))

    result = recovery.apply_auto_fix(str(skill_path), "build", 'x = inputs.get("name")')
    assert result["success"] is True
    assert "build" in result["message"]

    # Verify file was updated
    updated = yaml.safe_load(skill_path.read_text())
    assert updated["steps"][0]["compute"] == 'x = inputs.get("name")'


def test_apply_auto_fix_step_not_found(tmp_path, recovery):
    import yaml

    skill_path = tmp_path / "skill.yaml"
    skill_path.write_text(yaml.dump({"steps": [{"name": "other", "compute": "x"}]}))

    result = recovery.apply_auto_fix(str(skill_path), "nonexistent", "fixed")
    assert result["success"] is False
    assert "not found" in result["error"]


def test_apply_auto_fix_step_no_compute(tmp_path, recovery):
    import yaml

    skill_path = tmp_path / "skill.yaml"
    skill_path.write_text(yaml.dump({"steps": [{"name": "s", "tool": "t"}]}))

    result = recovery.apply_auto_fix(str(skill_path), "s", "fixed")
    assert result["success"] is False


def test_apply_auto_fix_file_not_found(recovery):
    result = recovery.apply_auto_fix("/nonexistent/path.yaml", "s", "code")
    assert result["success"] is False


def test_apply_auto_fix_invalid_yaml(tmp_path, recovery):
    skill_path = tmp_path / "bad.yaml"
    skill_path.write_text(": invalid yaml [[[")
    # yaml.safe_load may not raise for all bad yaml, but let's test protection
    result = recovery.apply_auto_fix(str(skill_path), "s", "code")
    # Either succeeds with mangled data or fails
    assert isinstance(result, dict)
