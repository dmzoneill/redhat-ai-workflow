"""Tests for the slop fixer MCP tools."""

import asyncio
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from tool_modules.aa_slop_fixer.src import tools_basic


def _private(name):
    return vars(tools_basic)[name]


FINDINGS = [
    {"id": "a", "file": "x.py", "line": 1, "category": "unused_imports", "description": "d" * 90, "confidence": 0.95},
    {"id": "b", "file": "y.py", "line": 2, "category": "bare_except", "description": "short", "tool": "ruff"},
    {"id": "c", "file": "y.py", "line": 3, "category": "bare_except", "description": "other"},
]


def test_format_fixable_groups_by_category():
    """Findings are grouped by category with confidence and tool."""
    text = _private("_format_fixable")(FINDINGS, 0.9)
    assert text.startswith("## Auto-Fixable Findings (3 total)\n")
    assert "### bare_except (2)" in text
    assert "- `x.py:1` (95%, LLM)" in text
    assert "- `y.py:2` (0%, ruff)" in text


def test_commit_message_counts_fixed_categories():
    """Only fixed findings are counted in the commit message."""
    message = _private("_commit_message")(FINDINGS, ["b", "c"])
    assert message == "fix(slop): auto-fix 2 high-confidence issues\n\nCategories fixed:\n- bare_except: 2\n"


def test_format_stats():
    """Stats show totals, fixable markers and recent fixes."""
    text = _private("_format_stats")(
        {"open": 2, "fixed": 1},
        [{"category": "unused_imports", "count": 2}, {"category": "security", "count": 1}],
        [{"category": "bare_except", "count": 1, "last_fixed": "2026-10-31"}],
    )
    assert "- **Total**: 3" in text
    assert "- unused_imports: 2 ✅" in text
    assert "- security: 1 ❌" in text
    assert "- bare_except: 1 (last: 2026-10-31)" in text


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_commit_fixes_commits_and_returns_hash(tmp_path, monkeypatch):
    """Files are committed and the new HEAD hash is returned."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "f.py").write_text("x = 1\n")
    monkeypatch.chdir(tmp_path)
    commit_hash = asyncio.run(_private("_commit_fixes")(["f.py"], "msg"))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert commit_hash == head.stdout.strip()


def test_commit_fixes_reports_failure(tmp_path, monkeypatch):
    """Outside a git repo the commit fails and an empty hash is returned."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert asyncio.run(_private("_commit_fixes")(["missing.py"], "msg")) == ""
    assert asyncio.run(_private("_commit_fixes")([], "msg")) == ""


@pytest.fixture(name="tools")
def fixture_tools(tmp_path, monkeypatch):
    """Registered tools backed by a temporary findings database."""
    pytest.importorskip("aiosqlite")
    db_path = tmp_path / "slop.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE findings (id TEXT, loop TEXT, file TEXT, line INTEGER, category TEXT, severity TEXT,"
            " description TEXT, suggestion TEXT DEFAULT '', tool TEXT DEFAULT '', status TEXT DEFAULT 'open',"
            " detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, fixed_at TIMESTAMP, git_commit TEXT)"
        )
        conn.execute(
            "INSERT INTO findings (id, loop, file, line, category, severity, description, tool)"
            " VALUES ('f1', 'l', 'a.py', 1, 'unused_imports', 'low', 'unused os', 'ruff')"
        )
        conn.execute(
            "INSERT INTO findings (id, loop, file, line, category, severity, description, status)"
            " VALUES ('f2', 'l', 'b.py', 2, 'security', 'high', 'sec', 'fixed')"
        )
    monkeypatch.setattr(tools_basic, "DEFAULT_DB_PATH", db_path)
    tools = {}
    server = SimpleNamespace(tool=lambda: lambda func: tools.setdefault(func.__name__, func))
    assert tools_basic.register_tools(server) == 3
    return tools


def test_stats_tool_reads_database(tools):
    """slop_fix_stats summarises the findings table."""
    text = asyncio.run(tools["slop_fix_stats"]())[0].text
    assert "- **open**: 1" in text
    assert "- **Total**: 2" in text


def test_fix_tool_dry_run(tools, monkeypatch):
    """A dry run applies nothing and reports the per-finding results."""

    async def fake_apply(finding, dry_run):
        assert dry_run
        return {"success": False, "finding_id": finding["id"], "error": "nope"}

    monkeypatch.setattr(tools_basic, "_apply_fix", fake_apply)
    findings = asyncio.run(_private("_get_fixable_findings")(0.0))
    assert [f["id"] for f in findings] == ["f1"]
    text = asyncio.run(tools["slop_fix"](dry_run=True, min_confidence=0.0))[0].text
    assert "❌ `a.py:1` - nope" in text
    assert "**Errors:** 1" in text
