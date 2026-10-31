"""Tests for ptools/sync_commands.py."""

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "ptools" / "sync_commands.py"


@pytest.fixture(name="sync")
def fixture_sync(tmp_path, monkeypatch):
    """Load sync_commands with its directories pointed at tmp_path."""
    spec = importlib.util.spec_from_file_location("sync_commands_under_test", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "CURSOR_COMMANDS", tmp_path / ".cursor" / "commands")
    monkeypatch.setattr(module, "CLAUDE_COMMANDS", tmp_path / ".claude" / "commands")
    monkeypatch.setattr(module, "SKILLS_DIR", tmp_path / "skills")
    return module


def _run_main(sync, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["sync_commands.py", *argv])
    return sync.main()


def test_missing_source_dir_exits_non_zero(sync, monkeypatch):
    """A missing source directory is reported as a failure."""
    assert _run_main(sync, monkeypatch, "--quiet") == 1


def test_forward_sync_adds_frontmatter(sync, monkeypatch):
    """Cursor commands are copied to Claude with frontmatter."""
    sync.CURSOR_COMMANDS.mkdir(parents=True)
    (sync.CURSOR_COMMANDS / "do-thing.md").write_text("# Do Thing\n\nDoes the thing.\n")
    assert _run_main(sync, monkeypatch, "--quiet") == 0
    text = (sync.CLAUDE_COMMANDS / "do-thing.md").read_text()
    assert text.startswith('---\nname: do-thing\ndescription: "Does the thing."\n---\n')


def test_reverse_sync_strips_frontmatter(sync, monkeypatch):
    """--reverse runs and removes the Claude frontmatter."""
    sync.CLAUDE_COMMANDS.mkdir(parents=True)
    (sync.CLAUDE_COMMANDS / "x.md").write_text("---\nname: x\n---\n# X\n")
    assert _run_main(sync, monkeypatch, "--reverse", "--quiet") == 0
    assert (sync.CURSOR_COMMANDS / "x.md").read_text() == "# X\n"


def test_generate_missing_without_yaml_exits_non_zero(sync, monkeypatch):
    """--generate-missing fails when PyYAML is unavailable."""
    monkeypatch.setattr(sync, "yaml", None)
    assert _run_main(sync, monkeypatch, "--generate-missing") == 1


def test_generate_missing_renders_dict_inputs(sync, monkeypatch):
    """Dict-format inputs produce a skill_run call and parameter table."""
    pytest.importorskip("yaml")
    sync.SKILLS_DIR.mkdir(parents=True)
    (sync.SKILLS_DIR / "my_skill.yaml").write_text(
        "name: my_skill\ndescription: Does it\ninputs:\n  key: {required: true, description: Key, default: k1}\n"
    )
    assert _run_main(sync, monkeypatch, "--generate-missing", "--quiet") == 0
    text = (sync.CURSOR_COMMANDS / "my-skill.md").read_text()
    assert 'skill_run("my_skill", \'{"key": "$KEY"}\')' in text
    assert "| `key` | Key (default: k1) | Yes |" in text


def test_generate_missing_skips_existing_and_bad_yaml(sync):
    """Existing commands and unreadable skills are not generated."""
    pytest.importorskip("yaml")
    sync.SKILLS_DIR.mkdir(parents=True)
    sync.CURSOR_COMMANDS.mkdir(parents=True)
    (sync.CURSOR_COMMANDS / "have-it.md").write_text("# Have\n")
    (sync.SKILLS_DIR / "have_it.yaml").write_text("name: have_it\n")
    (sync.SKILLS_DIR / "broken.yaml").write_text("a: [\n")
    assert sync.generate_missing_commands(verbose=False) == 0
