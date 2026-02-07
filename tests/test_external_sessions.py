"""Tests for tool_modules/aa_workflow/src/external_sessions.py"""

import json
from unittest.mock import patch

from tool_modules.aa_workflow.src.external_sessions import (
    ClaudeSession,
    GeminiSession,
    analyze_session,
    extract_patterns,
    get_claude_session,
    get_gemini_session,
    import_gemini_session,
    list_claude_sessions,
    list_gemini_sessions,
)

# ---------------------------------------------------------------------------
# ClaudeSession
# ---------------------------------------------------------------------------


class TestClaudeSession:
    def _make(self, messages=None, **kwargs):
        data = {
            "messages": messages or [],
            "created_at": "2025-01-01T10:00:00",
            "updated_at": "2025-01-01T11:00:00",
            "project_path": "/home/user/project",
        }
        data.update(kwargs)
        return ClaudeSession("sess123", data)

    def test_basic_properties(self):
        s = self._make()
        assert s.session_id == "sess123"
        assert s.created_at == "2025-01-01T10:00:00"
        assert s.updated_at == "2025-01-01T11:00:00"
        assert s.project_path == "/home/user/project"

    def test_message_count_empty(self):
        s = self._make()
        assert s.message_count == 0

    def test_message_count(self):
        s = self._make([{"role": "user"}, {"role": "assistant"}])
        assert s.message_count == 2

    def test_name_from_first_user_message_short(self):
        s = self._make([{"role": "user", "content": "Hello"}])
        assert s.name == "Hello"

    def test_name_from_first_user_message_truncated(self):
        long_msg = "x" * 60
        s = self._make([{"role": "user", "content": long_msg}])
        assert s.name.endswith("...")
        assert len(s.name) == 53  # 50 + "..."

    def test_name_fallback_no_user_messages(self):
        s = self._make([{"role": "assistant", "content": "Hi"}])
        assert "sess1234" in s.name or "Session" in s.name

    def test_get_user_messages(self):
        s = self._make(
            [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "q2"},
            ]
        )
        assert s.get_user_messages() == ["q1", "q2"]

    def test_get_assistant_messages(self):
        s = self._make(
            [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a1"},
                {"role": "assistant", "content": "a2"},
            ]
        )
        assert s.get_assistant_messages() == ["a1", "a2"]

    def test_get_tool_calls_with_tool_use(self):
        s = self._make(
            [
                {"role": "assistant", "content": "tool_use invoked"},
                {"role": "assistant", "content": "no tools here"},
            ]
        )
        calls = s.get_tool_calls()
        assert len(calls) == 1

    def test_get_tool_calls_empty(self):
        s = self._make([{"role": "user", "content": "q"}])
        assert s.get_tool_calls() == []

    def test_to_dict(self):
        s = self._make([{"role": "user", "content": "Hello"}])
        d = s.to_dict()
        assert d["id"] == "sess123"
        assert d["source"] == "claude"
        assert d["message_count"] == 1
        assert d["created_at"] == "2025-01-01T10:00:00"
        assert d["project_path"] == "/home/user/project"


# ---------------------------------------------------------------------------
# GeminiSession
# ---------------------------------------------------------------------------


class TestGeminiSession:
    def _make(self, contents=None, **kwargs):
        data = {
            "contents": contents or [],
            "model": "gemini-pro",
            "createTime": "2025-02-01T09:00:00",
        }
        data.update(kwargs)
        return GeminiSession("gem1", data)

    def test_basic_properties(self):
        s = self._make()
        assert s.session_id == "gem1"
        assert s.model == "gemini-pro"
        assert s.created_at == "2025-02-01T09:00:00"

    def test_message_count(self):
        s = self._make([{"role": "user"}, {"role": "model"}])
        assert s.message_count == 2

    def test_name_from_user_message(self):
        s = self._make([{"role": "user", "parts": [{"text": "Short question"}]}])
        assert s.name == "Short question"

    def test_name_truncated(self):
        long_text = "y" * 60
        s = self._make([{"role": "user", "parts": [{"text": long_text}]}])
        assert s.name.endswith("...")
        assert len(s.name) == 53

    def test_name_fallback(self):
        s = self._make([{"role": "model", "parts": [{"text": "hi"}]}])
        assert "Gemini" in s.name

    def test_name_non_dict_parts(self):
        s = self._make([{"role": "user", "parts": ["raw string"]}])
        # Should fall through to fallback
        assert "Gemini" in s.name

    def test_get_user_messages(self):
        s = self._make(
            [
                {"role": "user", "parts": [{"text": "q1"}, {"text": "q2"}]},
                {"role": "model", "parts": [{"text": "a"}]},
                {"role": "user", "parts": [{"image": "binary"}]},  # no text
            ]
        )
        assert s.get_user_messages() == ["q1", "q2"]

    def test_get_model_messages(self):
        s = self._make(
            [
                {"role": "model", "parts": [{"text": "a1"}]},
                {"role": "user", "parts": [{"text": "q"}]},
                {"role": "model", "parts": [{"text": "a2"}]},
            ]
        )
        assert s.get_model_messages() == ["a1", "a2"]

    def test_to_dict(self):
        s = self._make()
        d = s.to_dict()
        assert d["id"] == "gem1"
        assert d["source"] == "gemini"
        assert d["model"] == "gemini-pro"


# ---------------------------------------------------------------------------
# list_claude_sessions
# ---------------------------------------------------------------------------


def test_list_claude_sessions_no_dirs(tmp_path):
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CODE_DIR",
        tmp_path / "nope1",
    ):
        with patch(
            "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CONFIG_DIR",
            tmp_path / "nope2",
        ):
            result = list_claude_sessions()
    assert result == []


def test_list_claude_sessions_with_sessions(tmp_path):
    projects_dir = tmp_path / "projects" / "myproject"
    projects_dir.mkdir(parents=True)

    # Valid session
    (projects_dir / "s1.jsonl").write_text(
        '{"type": "metadata", "created_at": "2025-01-01", "updated_at": "2025-01-02"}\n'
        '{"type": "message", "role": "user", "content": "hi"}\n'
    )
    # Empty session (no messages)
    (projects_dir / "s2.jsonl").write_text('{"type": "metadata"}\n')
    # Corrupt line
    (projects_dir / "s3.jsonl").write_text(
        "not-json\n" '{"type": "message", "role": "user", "content": "test"}\n'
    )

    with patch(
        "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CODE_DIR", tmp_path
    ):
        with patch(
            "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CONFIG_DIR",
            tmp_path / "nope",
        ):
            result = list_claude_sessions()

    # s1 and s3 should load (s2 has no messages)
    assert len(result) == 2
    ids = {s.session_id for s in result}
    assert "s1" in ids
    assert "s3" in ids


def test_list_claude_sessions_ioerror(tmp_path):
    projects_dir = tmp_path / "projects" / "proj"
    projects_dir.mkdir(parents=True)
    (projects_dir / "bad.jsonl").write_text("")

    with patch(
        "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CODE_DIR", tmp_path
    ):
        with patch(
            "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CONFIG_DIR",
            tmp_path / "no",
        ):
            result = list_claude_sessions()
    assert result == []  # empty file -> no messages -> None


# ---------------------------------------------------------------------------
# list_gemini_sessions
# ---------------------------------------------------------------------------


def test_list_gemini_sessions_no_dir(tmp_path):
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.GEMINI_IMPORT_DIR",
        tmp_path / "nope",
    ):
        result = list_gemini_sessions()
    assert result == []


def test_list_gemini_sessions_with_sessions(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "g1.json").write_text(
        json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
                "model": "gemini-pro",
                "createTime": "2025-03-01",
            }
        )
    )
    (tmp_path / "g2.json").write_text(
        json.dumps(
            {
                "contents": [],
                "createTime": "2025-02-01",
            }
        )
    )
    # Corrupt file
    (tmp_path / "g3.json").write_text("bad json")

    with patch(
        "tool_modules.aa_workflow.src.external_sessions.GEMINI_IMPORT_DIR", tmp_path
    ):
        result = list_gemini_sessions()
    assert len(result) == 2  # g1 and g2 (g3 fails)
    assert result[0].created_at >= result[1].created_at  # sorted desc


# ---------------------------------------------------------------------------
# import_gemini_session
# ---------------------------------------------------------------------------


def test_import_gemini_nonexistent(tmp_path):
    result = import_gemini_session(str(tmp_path / "nope.json"))
    assert result is None


def test_import_gemini_success(tmp_path):
    source = tmp_path / "export.json"
    source.write_text(json.dumps({"contents": [], "model": "gemini"}))

    dest_dir = tmp_path / "imports"
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.GEMINI_IMPORT_DIR", dest_dir
    ):
        result = import_gemini_session(str(source))
    assert result is not None
    assert result.session_id.startswith("gemini_")
    assert result.model == "gemini"
    assert dest_dir.exists()


def test_import_gemini_bad_json(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text("not json")

    dest_dir = tmp_path / "imports"
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.GEMINI_IMPORT_DIR", dest_dir
    ):
        result = import_gemini_session(str(source))
    assert result is None


# ---------------------------------------------------------------------------
# get_claude_session
# ---------------------------------------------------------------------------


def test_get_claude_session_found(tmp_path):
    projects_dir = tmp_path / "projects" / "proj"
    projects_dir.mkdir(parents=True)
    (projects_dir / "target.jsonl").write_text(
        '{"type": "message", "role": "user", "content": "hi"}\n'
    )

    with patch(
        "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CODE_DIR", tmp_path
    ):
        with patch(
            "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CONFIG_DIR",
            tmp_path / "no",
        ):
            result = get_claude_session("target")
    assert result is not None
    assert result.session_id == "target"


def test_get_claude_session_not_found(tmp_path):
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CODE_DIR",
        tmp_path / "no1",
    ):
        with patch(
            "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CONFIG_DIR",
            tmp_path / "no2",
        ):
            result = get_claude_session("nope")
    assert result is None


# ---------------------------------------------------------------------------
# get_gemini_session
# ---------------------------------------------------------------------------


def test_get_gemini_session_found(tmp_path):
    (tmp_path / "gs1.json").write_text(json.dumps({"contents": [], "model": "m"}))
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.GEMINI_IMPORT_DIR", tmp_path
    ):
        result = get_gemini_session("gs1")
    assert result is not None
    assert result.session_id == "gs1"


def test_get_gemini_session_not_found(tmp_path):
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.GEMINI_IMPORT_DIR", tmp_path
    ):
        result = get_gemini_session("nope")
    assert result is None


def test_get_gemini_session_bad_json(tmp_path):
    (tmp_path / "bad.json").write_text("nope")
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.GEMINI_IMPORT_DIR", tmp_path
    ):
        result = get_gemini_session("bad")
    assert result is None


# ---------------------------------------------------------------------------
# extract_patterns
# ---------------------------------------------------------------------------


def test_extract_patterns_claude():
    s = ClaudeSession(
        "s1",
        {
            "messages": [
                {"role": "user", "content": "How do I deploy?"},
                {"role": "assistant", "content": "a" * 600},  # long = "good" response
                {"role": "user", "content": "Thanks"},
                {"role": "assistant", "content": "short"},
                {"role": "assistant", "content": "tool_use here"},
            ],
        },
    )
    p = extract_patterns(s)
    assert len(p["successful_prompts"]) == 1
    assert "deploy" in p["successful_prompts"][0]
    assert len(p["tool_usage"]) == 1


def test_extract_patterns_gemini():
    s = GeminiSession(
        "g1",
        {
            "contents": [
                {"role": "user", "parts": [{"text": "What is X?"}]},
                {"role": "model", "parts": [{"text": "b" * 600}]},
                {"role": "user", "parts": [{"text": "ok"}]},
                {"role": "model", "parts": [{"text": "short"}]},
            ],
        },
    )
    p = extract_patterns(s)
    assert len(p["successful_prompts"]) == 1
    assert p["tool_usage"] == []  # Gemini has no tool_use extraction


def test_extract_patterns_empty():
    s = ClaudeSession("s1", {"messages": []})
    p = extract_patterns(s)
    assert p["successful_prompts"] == []
    assert p["tool_usage"] == []


# ---------------------------------------------------------------------------
# analyze_session
# ---------------------------------------------------------------------------


def test_analyze_claude_found(tmp_path):
    projects_dir = tmp_path / "projects" / "proj"
    projects_dir.mkdir(parents=True)
    (projects_dir / "asess.jsonl").write_text(
        '{"type": "message", "role": "user", "content": "hi"}\n'
    )

    with patch(
        "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CODE_DIR", tmp_path
    ):
        with patch(
            "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CONFIG_DIR",
            tmp_path / "no",
        ):
            result = analyze_session("asess", source="claude")

    assert "session" in result
    assert "patterns" in result
    assert "summary" in result
    assert result["session"]["id"] == "asess"


def test_analyze_gemini_found(tmp_path):
    (tmp_path / "gsess.json").write_text(json.dumps({"contents": [], "model": "m"}))
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.GEMINI_IMPORT_DIR", tmp_path
    ):
        result = analyze_session("gsess", source="gemini")
    assert result["session"]["id"] == "gsess"


def test_analyze_not_found(tmp_path):
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CODE_DIR",
        tmp_path / "no1",
    ):
        with patch(
            "tool_modules.aa_workflow.src.external_sessions.CLAUDE_CONFIG_DIR",
            tmp_path / "no2",
        ):
            result = analyze_session("nope", source="claude")
    assert result == {"error": "Session not found"}


def test_analyze_gemini_not_found(tmp_path):
    with patch(
        "tool_modules.aa_workflow.src.external_sessions.GEMINI_IMPORT_DIR",
        tmp_path / "no",
    ):
        result = analyze_session("nope", source="gemini")
    assert result == {"error": "Session not found"}
