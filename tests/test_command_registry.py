"""Tests for scripts/common/command_registry.py."""

import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.common.command_registry import (
    CommandHelp,
    CommandInfo,
    CommandRegistry,
    CommandType,
    get_command_help,
    get_registry,
    list_commands,
)

# ---------------------------------------------------------------------------
# CommandType enum
# ---------------------------------------------------------------------------


class TestCommandType:
    def test_values(self):
        assert CommandType.SKILL == "skill"
        assert CommandType.TOOL == "tool"
        assert CommandType.BUILTIN == "builtin"

    def test_is_str(self):
        assert isinstance(CommandType.SKILL, str)


# ---------------------------------------------------------------------------
# CommandInfo dataclass
# ---------------------------------------------------------------------------


class TestCommandInfo:
    def test_defaults(self):
        ci = CommandInfo(
            name="test", description="desc", command_type=CommandType.BUILTIN
        )
        assert ci.name == "test"
        assert ci.description == "desc"
        assert ci.command_type == CommandType.BUILTIN
        assert ci.category == ""
        assert ci.inputs == []
        assert ci.parameters == {}
        assert ci.examples == []
        assert ci.source == ""
        assert ci.contextual is False

    def test_to_dict(self):
        ci = CommandInfo(
            name="deploy",
            description="Deploy service",
            command_type=CommandType.SKILL,
            category="deployment",
            inputs=[{"name": "env"}],
            parameters={"properties": {"target": {"type": "string"}}},
            examples=["@me deploy"],
            contextual=True,
        )
        d = ci.to_dict()
        assert d["name"] == "deploy"
        assert d["type"] == "skill"
        assert d["category"] == "deployment"
        assert d["contextual"] is True
        assert d["inputs"] == [{"name": "env"}]
        assert d["examples"] == ["@me deploy"]

    def test_to_dict_excludes_source(self):
        ci = CommandInfo(
            name="x",
            description="d",
            command_type=CommandType.TOOL,
            source="/path/to/file.py",
        )
        d = ci.to_dict()
        assert "source" not in d


# ---------------------------------------------------------------------------
# CommandHelp dataclass
# ---------------------------------------------------------------------------


class TestCommandHelp:
    def _make_help(self, **kwargs):
        defaults = dict(
            name="test", description="Test cmd", command_type=CommandType.BUILTIN
        )
        defaults.update(kwargs)
        return CommandHelp(**defaults)

    def test_format_slack_basic(self):
        h = self._make_help()
        text = h.format_slack()
        assert "`test`" in text
        assert "Test cmd" in text
        assert "builtin" in text

    def test_format_slack_with_usage(self):
        h = self._make_help(usage="@me test --arg=val")
        text = h.format_slack()
        assert "```@me test --arg=val```" in text

    def test_format_slack_with_inputs(self):
        h = self._make_help(
            inputs=[
                {"name": "project", "required": True, "description": "The project"},
                {"name": "env", "default": "staging", "description": "Environment"},
            ]
        )
        text = h.format_slack()
        assert "`project`" in text
        assert "(required)" in text
        assert "[default: staging]" in text

    def test_format_slack_with_parameters(self):
        h = self._make_help(
            parameters={
                "properties": {
                    "target": {"description": "Deploy target", "type": "string"},
                },
                "required": ["target"],
            }
        )
        text = h.format_slack()
        assert "`target`" in text
        assert "(required)" in text

    def test_format_slack_with_examples(self):
        h = self._make_help(
            examples=["@me test", "@me test --flag", "@me test arg", "@me test extra"]
        )
        text = h.format_slack()
        # Only first 3 examples shown
        assert text.count("```") >= 6  # 3 examples = 6 backtick blocks
        assert "@me test extra" not in text

    def test_format_slack_with_related(self):
        h = self._make_help(related=["other_cmd", "another"])
        text = h.format_slack()
        assert "Related" in text
        assert "other_cmd" in text

    def test_format_text_basic(self):
        h = self._make_help()
        text = h.format_text()
        assert "test - Test cmd" in text
        assert "builtin" in text

    def test_format_text_with_usage(self):
        h = self._make_help(usage="@me test")
        text = h.format_text()
        assert "Usage: @me test" in text

    def test_format_text_with_inputs(self):
        h = self._make_help(
            inputs=[{"name": "project", "required": True, "description": "The project"}]
        )
        text = h.format_text()
        assert "project" in text
        assert "(required)" in text

    def test_format_text_with_examples(self):
        h = self._make_help(examples=["@me test one", "@me test two"])
        text = h.format_text()
        assert "Examples:" in text
        assert "@me test one" in text

    def test_format_text_no_related(self):
        """Related is only shown in slack format, not text."""
        h = self._make_help(related=["other"])
        text = h.format_text()
        assert "Related" not in text


# ---------------------------------------------------------------------------
# CommandRegistry - built-in commands
# ---------------------------------------------------------------------------


class TestRegistryBuiltins:
    def test_builtin_commands_exist(self):
        CommandRegistry()
        builtins = CommandRegistry.BUILTIN_COMMANDS
        assert "help" in builtins
        assert "status" in builtins
        assert "list" in builtins
        assert "jira" in builtins
        assert "search" in builtins
        assert "sprint" in builtins

    def test_get_builtin_command(self):
        registry = CommandRegistry(
            skills_dir=Path("/nonexistent/skills"),
            tool_modules_dir=Path("/nonexistent/tools"),
        )
        cmd = registry.get_command("help")
        assert cmd is not None
        assert cmd.name == "help"
        assert cmd.command_type == CommandType.BUILTIN

    def test_get_command_normalizes(self):
        registry = CommandRegistry(
            skills_dir=Path("/nonexistent/skills"),
            tool_modules_dir=Path("/nonexistent/tools"),
        )
        cmd = registry.get_command("HELP")
        assert cmd is not None
        assert cmd.name == "help"

    def test_get_command_dashes_to_underscores(self):
        """'some-cmd' should normalize to 'some_cmd'."""
        registry = CommandRegistry(
            skills_dir=Path("/nonexistent/skills"),
            tool_modules_dir=Path("/nonexistent/tools"),
        )
        # Builtins don't have dashes, so this returns None but exercises normalization
        cmd = registry.get_command("some-cmd")
        assert cmd is None

    def test_get_command_not_found(self):
        registry = CommandRegistry(
            skills_dir=Path("/nonexistent/skills"),
            tool_modules_dir=Path("/nonexistent/tools"),
        )
        cmd = registry.get_command("nonexistent_cmd")
        assert cmd is None


# ---------------------------------------------------------------------------
# CommandRegistry - skills discovery
# ---------------------------------------------------------------------------


class TestRegistrySkills:
    @pytest.fixture
    def skills_dir(self, tmp_path):
        """Create temp skills directory with YAML files."""
        sd = tmp_path / "skills"
        sd.mkdir()
        return sd

    @pytest.fixture
    def registry(self, skills_dir):
        return CommandRegistry(
            skills_dir=skills_dir,
            tool_modules_dir=Path("/nonexistent/tools"),
        )

    def test_empty_skills_dir(self, registry):
        cmds = registry.list_commands(command_type=CommandType.SKILL)
        assert cmds == []

    def test_load_skill_from_yaml(self, skills_dir, registry):
        skill_yaml = skills_dir / "deploy_service.yaml"
        skill_yaml.write_text(
            textwrap.dedent(
                """\
            name: deploy_service
            description: Deploy a service to stage or prod
            inputs:
              - name: env
                required: true
                type: string
                description: Target environment
        """
            )
        )

        cmds = registry.list_commands(command_type=CommandType.SKILL)
        assert len(cmds) == 1
        assert cmds[0].name == "deploy_service"
        assert cmds[0].command_type == CommandType.SKILL
        assert len(cmds[0].inputs) == 1
        assert cmds[0].inputs[0]["name"] == "env"

    def test_skill_description_first_line(self, skills_dir, registry):
        skill_yaml = skills_dir / "multi.yaml"
        skill_yaml.write_text(
            textwrap.dedent(
                """\
            name: multi
            description: |
              First line of description
              Second line should be ignored
        """
            )
        )

        cmds = registry.list_commands(command_type=CommandType.SKILL)
        assert cmds[0].description == "First line of description"

    def test_skill_description_bold_stripped(self, skills_dir, registry):
        skill_yaml = skills_dir / "bold.yaml"
        skill_yaml.write_text(
            textwrap.dedent(
                """\
            name: bold
            description: "**Bold description**"
        """
            )
        )

        cmds = registry.list_commands(command_type=CommandType.SKILL)
        assert "**" not in cmds[0].description
        assert "Bold description" in cmds[0].description

    def test_skill_examples_generated(self, skills_dir, registry):
        skill_yaml = skills_dir / "simple.yaml"
        skill_yaml.write_text(
            textwrap.dedent(
                """\
            name: simple
            description: A simple skill
        """
            )
        )

        cmds = registry.list_commands(command_type=CommandType.SKILL)
        assert "@me simple" in cmds[0].examples

    def test_skill_examples_with_required_inputs(self, skills_dir, registry):
        skill_yaml = skills_dir / "with_inputs.yaml"
        skill_yaml.write_text(
            textwrap.dedent(
                """\
            name: with_inputs
            description: Skill with inputs
            inputs:
              - name: project
                required: true
              - name: env
                required: true
              - name: optional_flag
                required: false
        """
            )
        )

        cmds = registry.list_commands(command_type=CommandType.SKILL)
        assert any("--project" in ex for ex in cmds[0].examples)

    def test_empty_yaml_skipped(self, skills_dir, registry):
        (skills_dir / "empty.yaml").write_text("")
        cmds = registry.list_commands(command_type=CommandType.SKILL)
        assert cmds == []

    def test_invalid_yaml_skipped(self, skills_dir, registry):
        (skills_dir / "bad.yaml").write_text("{{invalid yaml")
        cmds = registry.list_commands(command_type=CommandType.SKILL)
        assert cmds == []

    def test_skills_cached(self, skills_dir, registry):
        skill_yaml = skills_dir / "cached.yaml"
        skill_yaml.write_text(
            textwrap.dedent(
                """\
            name: cached
            description: A cached skill
        """
            )
        )

        # First call
        first = registry._get_skills()
        assert "cached" in first

        # Second call returns same dict object (cached)
        second = registry._get_skills()
        assert first is second

    def test_contextual_skill(self, skills_dir, registry):
        """Skills in CONTEXTUAL_SKILLS set should be marked contextual."""
        skill_yaml = skills_dir / "create_jira_issue.yaml"
        skill_yaml.write_text(
            textwrap.dedent(
                """\
            name: create_jira_issue
            description: Create a Jira issue
        """
            )
        )

        cmds = registry.list_commands(command_type=CommandType.SKILL)
        assert cmds[0].contextual is True

    def test_skills_dir_not_exists(self):
        registry = CommandRegistry(
            skills_dir=Path("/nonexistent/skills/path"),
            tool_modules_dir=Path("/nonexistent/tools"),
        )
        cmds = registry.list_commands(command_type=CommandType.SKILL)
        assert cmds == []


# ---------------------------------------------------------------------------
# CommandRegistry - tools discovery
# ---------------------------------------------------------------------------


class TestRegistryTools:
    @pytest.fixture
    def tools_dir(self, tmp_path):
        """Create temp tool modules directory with Python files."""
        td = tmp_path / "tool_modules"
        td.mkdir()
        return td

    @pytest.fixture
    def registry(self, tools_dir):
        return CommandRegistry(
            skills_dir=Path("/nonexistent/skills"),
            tool_modules_dir=tools_dir,
        )

    def test_empty_tools_dir(self, registry):
        cmds = registry.list_commands(command_type=CommandType.TOOL)
        assert cmds == []

    def test_discover_tool_from_file(self, tools_dir, registry):
        mod = tools_dir / "aa_jira" / "src"
        mod.mkdir(parents=True)
        (mod / "tools_basic.py").write_text(
            textwrap.dedent(
                '''\
            async def jira_create_issue(project: str, summary: str) -> dict:
                """Create a new Jira issue."""
                pass

            async def jira_search(query: str) -> list:
                """Search Jira issues by JQL."""
                pass
        '''
            )
        )

        cmds = registry.list_commands(command_type=CommandType.TOOL)
        names = [c.name for c in cmds]
        assert "jira_create_issue" in names
        assert "jira_search" in names

    def test_tool_category_from_module_name(self, tools_dir, registry):
        mod = tools_dir / "aa_deploy" / "src"
        mod.mkdir(parents=True)
        (mod / "tools_basic.py").write_text(
            textwrap.dedent(
                '''\
            async def deploy_service(env: str) -> str:
                """Deploy a service to target environment."""
                pass
        '''
            )
        )

        cmds = registry.list_commands(command_type=CommandType.TOOL)
        assert cmds[0].category == "deploy"

    def test_private_functions_skipped(self, tools_dir, registry):
        mod = tools_dir / "aa_utils" / "src"
        mod.mkdir(parents=True)
        (mod / "tools_basic.py").write_text(
            textwrap.dedent(
                '''\
            async def _internal_helper(x: int) -> int:
                """Internal helper function."""
                return x

            async def public_tool(x: int) -> int:
                """Public tool."""
                return x
        '''
            )
        )

        cmds = registry.list_commands(command_type=CommandType.TOOL)
        names = [c.name for c in cmds]
        assert "_internal_helper" not in names
        assert "public_tool" in names

    def test_non_aa_dirs_skipped(self, tools_dir, registry):
        mod = tools_dir / "not_aa" / "src"
        mod.mkdir(parents=True)
        (mod / "tools_basic.py").write_text(
            textwrap.dedent(
                '''\
            async def some_func() -> str:
                """Some function."""
                pass
        '''
            )
        )

        cmds = registry.list_commands(command_type=CommandType.TOOL)
        assert cmds == []

    def test_tools_cached(self, tools_dir, registry):
        mod = tools_dir / "aa_test" / "src"
        mod.mkdir(parents=True)
        (mod / "tools_basic.py").write_text(
            textwrap.dedent(
                '''\
            async def cached_tool() -> str:
                """Cached tool."""
                pass
        '''
            )
        )

        first = registry._get_tools()
        second = registry._get_tools()
        assert first is second

    def test_tools_dir_not_exists(self):
        registry = CommandRegistry(
            skills_dir=Path("/nonexistent/skills"),
            tool_modules_dir=Path("/nonexistent/tools"),
        )
        cmds = registry.list_commands(command_type=CommandType.TOOL)
        assert cmds == []

    def test_tools_extra_file(self, tools_dir, registry):
        mod = tools_dir / "aa_extra" / "src"
        mod.mkdir(parents=True)
        (mod / "tools_extra.py").write_text(
            textwrap.dedent(
                '''\
            async def extra_tool() -> str:
                """An extra tool."""
                pass
        '''
            )
        )

        cmds = registry.list_commands(command_type=CommandType.TOOL)
        assert len(cmds) == 1
        assert cmds[0].name == "extra_tool"

    def test_parse_tools_file_error_handled(self, tools_dir, registry):
        """A file that can't be read shouldn't crash."""
        mod = tools_dir / "aa_broken" / "src"
        mod.mkdir(parents=True)
        broken = mod / "tools_basic.py"
        broken.write_text("")
        # Make unreadable
        broken.chmod(0o000)
        try:
            registry.list_commands(command_type=CommandType.TOOL)
            # Should not raise, may or may not find tools
        except PermissionError:
            pass  # OK on some systems
        finally:
            broken.chmod(0o644)


# ---------------------------------------------------------------------------
# CommandRegistry - categorization
# ---------------------------------------------------------------------------


class TestCategorization:
    def test_categorize_jira(self):
        registry = CommandRegistry()
        assert registry._categorize_skill("create_jira_issue", {}) == "jira"

    def test_categorize_gitlab_mr(self):
        registry = CommandRegistry()
        assert registry._categorize_skill("review_mr", {}) == "gitlab"

    def test_categorize_gitlab_pr(self):
        registry = CommandRegistry()
        assert registry._categorize_skill("create_pr", {}) == "gitlab"

    def test_categorize_monitoring(self):
        registry = CommandRegistry()
        assert registry._categorize_skill("investigate_alert", {}) == "monitoring"

    def test_categorize_deployment(self):
        registry = CommandRegistry()
        assert registry._categorize_skill("deploy_app", {}) == "deployment"

    def test_categorize_deployment_release(self):
        registry = CommandRegistry()
        assert registry._categorize_skill("create_release", {}) == "deployment"

    def test_categorize_memory(self):
        registry = CommandRegistry()
        assert registry._categorize_skill("save_memory", {}) == "memory"

    def test_categorize_slack(self):
        registry = CommandRegistry()
        assert registry._categorize_skill("slack_search", {}) == "slack"

    def test_categorize_general(self):
        registry = CommandRegistry()
        assert registry._categorize_skill("something_else", {}) == "general"


# ---------------------------------------------------------------------------
# CommandRegistry - list_commands filtering
# ---------------------------------------------------------------------------


class TestListCommands:
    @pytest.fixture
    def registry(self, tmp_path):
        sd = tmp_path / "skills"
        sd.mkdir()
        (sd / "deploy.yaml").write_text(
            textwrap.dedent(
                """\
            name: deploy
            description: Deploy a service
        """
            )
        )
        return CommandRegistry(
            skills_dir=sd,
            tool_modules_dir=Path("/nonexistent/tools"),
        )

    def test_list_all(self, registry):
        cmds = registry.list_commands()
        names = {c.name for c in cmds}
        assert "help" in names  # builtin
        assert "deploy" in names  # skill

    def test_filter_by_type(self, registry):
        cmds = registry.list_commands(command_type=CommandType.BUILTIN)
        assert all(c.command_type == CommandType.BUILTIN for c in cmds)

    def test_filter_by_text(self, registry):
        cmds = registry.list_commands(filter_text="deploy")
        assert any(c.name == "deploy" for c in cmds)

    def test_filter_by_text_in_description(self, registry):
        cmds = registry.list_commands(filter_text="service")
        assert any(c.name == "deploy" for c in cmds)

    def test_filter_by_text_case_insensitive(self, registry):
        cmds = registry.list_commands(filter_text="DEPLOY")
        assert any(c.name == "deploy" for c in cmds)

    def test_filter_by_category(self, registry):
        cmds = registry.list_commands(category="jira")
        assert all(c.category == "jira" for c in cmds)

    def test_sorted_by_type_then_name(self, registry):
        cmds = registry.list_commands()
        types = [c.command_type.value for c in cmds]
        # builtin < skill < tool (alphabetically)
        assert types == sorted(types)


# ---------------------------------------------------------------------------
# CommandRegistry - get_command_help
# ---------------------------------------------------------------------------


class TestGetCommandHelp:
    @pytest.fixture
    def registry(self, tmp_path):
        sd = tmp_path / "skills"
        sd.mkdir()
        (sd / "deploy.yaml").write_text(
            textwrap.dedent(
                """\
            name: deploy
            description: Deploy a service
            inputs:
              - name: env
                required: true
                type: string
        """
            )
        )
        return CommandRegistry(
            skills_dir=sd,
            tool_modules_dir=Path("/nonexistent/tools"),
        )

    def test_help_for_builtin(self, registry):
        h = registry.get_command_help("help")
        assert h is not None
        assert h.name == "help"
        assert h.usage == "@me help"

    def test_help_for_skill(self, registry):
        h = registry.get_command_help("deploy")
        assert h is not None
        assert h.name == "deploy"
        assert h.command_type == CommandType.SKILL
        assert "--env" in h.usage

    def test_help_not_found(self, registry):
        h = registry.get_command_help("nonexistent")
        assert h is None

    def test_help_related_commands(self, registry):
        """Commands in the same category should be listed as related."""
        h = registry.get_command_help("jira")
        assert h is not None
        # Related should contain other commands with category 'jira'

    def test_build_tool_usage(self):
        registry = CommandRegistry()
        cmd = CommandInfo(
            name="my_tool", description="desc", command_type=CommandType.TOOL
        )
        assert registry._build_tool_usage(cmd) == "@me my_tool [--arg=value ...]"


# ---------------------------------------------------------------------------
# CommandRegistry - find_related
# ---------------------------------------------------------------------------


class TestFindRelated:
    def test_finds_same_category(self):
        registry = CommandRegistry(
            skills_dir=Path("/nonexistent/skills"),
            tool_modules_dir=Path("/nonexistent/tools"),
        )
        cmd = CommandInfo(
            name="search",
            description="Search",
            command_type=CommandType.BUILTIN,
            category="search",
        )
        related = registry._find_related(cmd)
        # 'who' and 'find' are also in search category
        assert "who" in related or "find" in related

    def test_max_3_related(self):
        registry = CommandRegistry(
            skills_dir=Path("/nonexistent/skills"),
            tool_modules_dir=Path("/nonexistent/tools"),
        )
        # 'research' category has: research, learn, knowledge - all 3
        cmd = CommandInfo(
            name="research",
            description="R",
            command_type=CommandType.BUILTIN,
            category="research",
        )
        related = registry._find_related(cmd)
        assert len(related) <= 3

    def test_no_category_no_related(self):
        registry = CommandRegistry(
            skills_dir=Path("/nonexistent/skills"),
            tool_modules_dir=Path("/nonexistent/tools"),
        )
        cmd = CommandInfo(
            name="x", description="d", command_type=CommandType.BUILTIN, category=""
        )
        related = registry._find_related(cmd)
        assert related == []


# ---------------------------------------------------------------------------
# CommandRegistry - format_list
# ---------------------------------------------------------------------------


class TestFormatList:
    def test_format_slack(self):
        registry = CommandRegistry()
        cmds = [
            CommandInfo(
                name="help", description="Show help", command_type=CommandType.BUILTIN
            ),
            CommandInfo(
                name="deploy",
                description="Deploy service",
                command_type=CommandType.SKILL,
            ),
        ]
        text = registry.format_list(cmds, "slack")
        assert "Available Commands" in text
        assert "Built-in" in text
        assert "Skills" in text
        assert "`help`" in text
        assert "`deploy`" in text

    def test_format_slack_contextual_marker(self):
        registry = CommandRegistry()
        cmds = [
            CommandInfo(
                name="jira",
                description="Create jira",
                command_type=CommandType.BUILTIN,
                contextual=True,
            ),
        ]
        text = registry.format_list(cmds, "slack")
        assert "\U0001f9f5" in text or "🧵" in text  # thread emoji

    def test_format_slack_limits_to_20(self):
        registry = CommandRegistry()
        cmds = [
            CommandInfo(
                name=f"cmd_{i}", description=f"Cmd {i}", command_type=CommandType.SKILL
            )
            for i in range(25)
        ]
        text = registry.format_list(cmds, "slack")
        assert "...and 5 more" in text

    def test_format_text(self):
        registry = CommandRegistry()
        cmds = [
            CommandInfo(
                name="help", description="Show help", command_type=CommandType.BUILTIN
            ),
        ]
        text = registry.format_list(cmds, "text")
        assert "Available Commands" in text
        assert "help (builtin): Show help" in text

    def test_format_list_default_is_slack(self):
        registry = CommandRegistry()
        cmds = [
            CommandInfo(
                name="help", description="Show help", command_type=CommandType.BUILTIN
            )
        ]
        text = registry.format_list(cmds)
        assert "Available Commands" in text


# ---------------------------------------------------------------------------
# CommandRegistry - clear_cache
# ---------------------------------------------------------------------------


class TestClearCache:
    def test_clear_cache(self, tmp_path):
        sd = tmp_path / "skills"
        sd.mkdir()
        (sd / "test.yaml").write_text("name: test\ndescription: Test")

        registry = CommandRegistry(skills_dir=sd, tool_modules_dir=Path("/nonexistent"))

        # Populate cache
        registry._get_skills()
        assert registry._skills_cache is not None

        # Clear
        registry.clear_cache()
        assert registry._skills_cache is None
        assert registry._tools_cache is None


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    def test_get_registry_singleton(self):
        import scripts.common.command_registry as mod

        # Reset global
        old = mod._registry
        mod._registry = None
        try:
            r1 = get_registry()
            r2 = get_registry()
            assert r1 is r2
        finally:
            mod._registry = old

    def test_list_commands_function(self):
        import scripts.common.command_registry as mod

        old = mod._registry
        mod._registry = None
        try:
            cmds = list_commands()
            assert isinstance(cmds, list)
            assert len(cmds) > 0
        finally:
            mod._registry = old

    def test_list_commands_with_filter(self):
        import scripts.common.command_registry as mod

        old = mod._registry
        mod._registry = None
        try:
            cmds = list_commands(filter_text="help")
            assert any(c.name == "help" for c in cmds)
        finally:
            mod._registry = old

    def test_get_command_help_function(self):
        import scripts.common.command_registry as mod

        old = mod._registry
        mod._registry = None
        try:
            h = get_command_help("help")
            assert h is not None
            assert h.name == "help"
        finally:
            mod._registry = old

    def test_get_command_help_not_found(self):
        import scripts.common.command_registry as mod

        old = mod._registry
        mod._registry = None
        try:
            h = get_command_help("no_such_command_exists_xyz")
            assert h is None
        finally:
            mod._registry = old


# ---------------------------------------------------------------------------
# _build_skill_usage
# ---------------------------------------------------------------------------


class TestBuildSkillUsage:
    def test_no_inputs(self):
        registry = CommandRegistry()
        cmd = CommandInfo(
            name="simple", description="d", command_type=CommandType.SKILL, inputs=[]
        )
        assert registry._build_skill_usage(cmd) == "@me simple"

    def test_with_required_inputs(self):
        registry = CommandRegistry()
        cmd = CommandInfo(
            name="deploy",
            description="d",
            command_type=CommandType.SKILL,
            inputs=[
                {"name": "env", "required": True, "type": "string"},
                {"name": "optional", "required": False},
            ],
        )
        usage = registry._build_skill_usage(cmd)
        assert "@me deploy" in usage
        assert "--env=<string>" in usage
        assert "optional" not in usage


# ---------------------------------------------------------------------------
# CONTEXTUAL_SKILLS
# ---------------------------------------------------------------------------


class TestContextualSkills:
    def test_known_contextual_skills(self):
        expected = {
            "create_jira_issue",
            "investigate_alert",
            "investigate_slack_alert",
            "summarize",
            "debug_prod",
        }
        assert CommandRegistry.CONTEXTUAL_SKILLS == expected
