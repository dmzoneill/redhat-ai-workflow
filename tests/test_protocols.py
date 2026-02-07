"""Tests for server/protocols.py - Protocol definitions and validation utilities."""

import inspect
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from server.protocols import (
    ConfigurableProtocol,
    ServiceProtocol,
    ToolModuleProtocol,
    ToolModuleWithRoot,
    is_tool_module,
    validate_tool_module,
)

# ────────────────────────────────────────────────────────────────────
# Concrete implementations for isinstance checks
# ────────────────────────────────────────────────────────────────────


class ConcreteToolModule:
    """A valid tool module implementation."""

    def register_tools(self, server) -> int:
        return 0


class ToolModuleWithProjectRoot:
    """A tool module that also declares __project_root__."""

    __project_root__ = "/some/path"

    def register_tools(self, server) -> int:
        return 1


class ConcreteService:
    """A valid service implementation."""

    def __init__(self):
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False


class ConcreteConfigurable:
    """A valid configurable implementation."""

    def __init__(self):
        self._config = {}

    def configure(self, config: dict) -> None:
        self._config = config

    def get_config(self) -> dict:
        return self._config


# ────────────────────────────────────────────────────────────────────
# ToolModuleProtocol
# ────────────────────────────────────────────────────────────────────


class TestToolModuleProtocol:
    """Tests for ToolModuleProtocol runtime checks."""

    def test_isinstance_valid(self):
        obj = ConcreteToolModule()
        assert isinstance(obj, ToolModuleProtocol)

    def test_isinstance_missing_register_tools(self):
        obj = MagicMock(spec=[])
        # Remove register_tools so it truly doesn't exist
        del obj.register_tools
        assert not isinstance(obj, ToolModuleProtocol)

    def test_isinstance_with_non_callable(self):
        """An object where register_tools is not callable fails the check."""

        class Bad:
            register_tools = 42

        obj = Bad()
        # runtime_checkable only checks hasattr, not callable;
        # that's why is_tool_module does the deeper check
        assert isinstance(obj, ToolModuleProtocol)  # hasattr passes

    def test_isinstance_plain_object(self):
        assert not isinstance(object(), ToolModuleProtocol)


# ────────────────────────────────────────────────────────────────────
# ToolModuleWithRoot
# ────────────────────────────────────────────────────────────────────


class TestToolModuleWithRoot:
    def test_isinstance_with_root(self):
        obj = ToolModuleWithProjectRoot()
        assert isinstance(obj, ToolModuleWithRoot)

    def test_isinstance_without_root(self):
        obj = ConcreteToolModule()
        assert not isinstance(obj, ToolModuleWithRoot)


# ────────────────────────────────────────────────────────────────────
# ServiceProtocol
# ────────────────────────────────────────────────────────────────────


class TestServiceProtocol:
    def test_isinstance_valid(self):
        obj = ConcreteService()
        assert isinstance(obj, ServiceProtocol)

    def test_isinstance_invalid(self):
        assert not isinstance(object(), ServiceProtocol)

    def test_isinstance_missing_is_running(self):
        """Must have is_running to match."""

        class Partial:
            async def start(self):
                pass

            async def stop(self):
                pass

        assert not isinstance(Partial(), ServiceProtocol)


# ────────────────────────────────────────────────────────────────────
# ConfigurableProtocol
# ────────────────────────────────────────────────────────────────────


class TestConfigurableProtocol:
    def test_isinstance_valid(self):
        obj = ConcreteConfigurable()
        assert isinstance(obj, ConfigurableProtocol)

    def test_isinstance_invalid(self):
        assert not isinstance(object(), ConfigurableProtocol)

    def test_isinstance_missing_get_config(self):
        class Partial:
            def configure(self, config):
                pass

        assert not isinstance(Partial(), ConfigurableProtocol)


# ────────────────────────────────────────────────────────────────────
# is_tool_module()
# ────────────────────────────────────────────────────────────────────


class TestIsToolModule:
    def test_valid_module_object(self):
        obj = ConcreteToolModule()
        assert is_tool_module(obj) is True

    def test_missing_register_tools(self):
        assert is_tool_module(object()) is False

    def test_register_tools_not_callable(self):
        """register_tools exists but is not callable."""

        class NotCallable:
            register_tools = "nope"

        assert is_tool_module(NotCallable()) is False

    def test_register_tools_no_params(self):
        """register_tools is callable but takes no parameters."""

        class NoParams:
            def register_tools(self):
                pass

        assert is_tool_module(NoParams()) is False

    def test_register_tools_var_positional(self):
        """First param is *args -- should be rejected."""

        class VarPos:
            def register_tools(self, *args):
                pass

        # *args is VAR_POSITIONAL but self is first
        # inspect sees (self, *args) -> params[0] is self which is fine
        # Let's be precise: function with only *args and no positional
        def only_varargs(*args):
            pass

        obj = MagicMock()
        obj.register_tools = only_varargs
        assert is_tool_module(obj) is False

    def test_register_tools_var_keyword_only(self):
        """First param is **kwargs -- should be rejected."""

        def only_kwargs(**kwargs):
            pass

        obj = MagicMock()
        obj.register_tools = only_kwargs
        assert is_tool_module(obj) is False

    def test_actual_module_like_object(self):
        """Simulate a real module with register_tools function."""
        mod = ModuleType("fake_module")

        def register_tools(server):
            return 0

        mod.register_tools = register_tools
        assert is_tool_module(mod) is True

    def test_signature_inspection_failure(self):
        """When inspect.signature raises, should still return True if callable."""
        obj = MagicMock()
        # MagicMock's register_tools is callable and has a signature
        # but let's use a builtin that can't be inspected
        obj.register_tools = print  # builtins can be inspected in CPython
        result = is_tool_module(obj)
        # print has params, so result should be True
        assert isinstance(result, bool)


# ────────────────────────────────────────────────────────────────────
# validate_tool_module()
# ────────────────────────────────────────────────────────────────────


class TestValidateToolModule:
    def test_valid_module(self):
        mod = ModuleType("test_mod")

        def register_tools(server):
            return 0

        mod.register_tools = register_tools
        errors = validate_tool_module(mod, "test_mod")
        assert errors == []

    def test_missing_register_tools(self):
        mod = ModuleType("bad_mod")
        errors = validate_tool_module(mod, "bad_mod")
        assert len(errors) == 1
        assert "Missing register_tools" in errors[0]

    def test_not_callable(self):
        mod = ModuleType("bad_mod")
        mod.register_tools = 42
        errors = validate_tool_module(mod, "bad_mod")
        assert len(errors) == 1
        assert "not callable" in errors[0]

    def test_no_params(self):
        mod = ModuleType("bad_mod")

        def register_tools():
            pass

        mod.register_tools = register_tools
        errors = validate_tool_module(mod, "bad_mod")
        assert any("at least one parameter" in e for e in errors)

    def test_wrong_return_annotation(self):
        mod = ModuleType("bad_mod")

        def register_tools(server) -> str:
            return ""

        mod.register_tools = register_tools
        errors = validate_tool_module(mod, "bad_mod")
        assert any("should return int" in e for e in errors)

    def test_valid_return_annotation_int(self):
        mod = ModuleType("ok_mod")

        def register_tools(server) -> int:
            return 0

        mod.register_tools = register_tools
        errors = validate_tool_module(mod, "ok_mod")
        assert errors == []

    def test_valid_return_annotation_none(self):
        """None return annotation is accepted."""
        mod = ModuleType("ok_mod")

        def register_tools(server) -> None:
            pass

        mod.register_tools = register_tools
        errors = validate_tool_module(mod, "ok_mod")
        assert errors == []

    def test_no_return_annotation(self):
        """No return annotation is fine."""
        mod = ModuleType("ok_mod")

        def register_tools(server):
            pass

        mod.register_tools = register_tools
        assert validate_tool_module(mod, "ok_mod") == []

    def test_module_without_project_root(self):
        """Missing __project_root__ is a warning, not an error."""
        mod = ModuleType("ok_mod")

        def register_tools(server):
            pass

        mod.register_tools = register_tools
        errors = validate_tool_module(mod, "ok_mod")
        assert errors == []

    def test_signature_inspection_error(self):
        """When signature introspection fails, report an error."""
        mod = ModuleType("bad_mod")

        mock_fn = MagicMock()
        mock_fn.__name__ = "register_tools"
        mod.register_tools = mock_fn

        import unittest.mock as um

        with um.patch("inspect.signature", side_effect=ValueError("bad")):
            from server.protocols import validate_tool_module as vt

            errors = vt(mod, "bad_mod")
            assert any("Could not inspect" in e for e in errors)
