"""Protocol definitions for MCP server components.

This module defines Protocol classes (structural subtyping) for key interfaces
in the MCP server architecture. Using Protocols instead of ABCs allows for
duck typing while still providing type safety and IDE support.

Usage:
    from server.protocols import ToolModuleProtocol, ServiceProtocol

    # Type checking
    def load_module(module: ToolModuleProtocol) -> int:
        return module.register_tools(server)

    # Runtime validation
    if is_tool_module(some_module):
        some_module.register_tools(server)
"""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fastmcp import FastMCP


@runtime_checkable
class ToolModuleProtocol(Protocol):
    """Protocol for tool modules that can be loaded by PersonaLoader.

    Tool modules must have:
    - register_tools(server): Function that registers tools with FastMCP server
    - __project_root__ (optional): Path to project root for imports

    Example implementation:
        # tool_modules/aa_example/src/tools_basic.py

        from pathlib import Path
        from fastmcp import FastMCP
        from tool_modules.common import PROJECT_ROOT

        __project_root__ = PROJECT_ROOT

        def register_tools(server: FastMCP) -> int:
            '''Register tools with the MCP server.'''
            from server.tool_registry import ToolRegistry
            registry = ToolRegistry(server)

            @registry.tool()
            async def example_tool(arg: str) -> str:
                '''Example tool.'''
                return f"Result: {arg}"

            return registry.count
    """

    def register_tools(self, server: "FastMCP") -> int:
        """Register tools with the FastMCP server.

        Args:
            server: FastMCP server instance to register tools with

        Returns:
            Number of tools registered
        """
        ...


@runtime_checkable
class ToolModuleWithRoot(ToolModuleProtocol, Protocol):
    """Tool module that also declares its project root."""

    __project_root__: Any  # Usually Path


@runtime_checkable
class ServiceProtocol(Protocol):
    """Protocol for background services/daemons.

    Services must implement:
    - start(): Begin service operation
    - stop(): Gracefully stop service
    - is_running: Property indicating current state
    """

    @property
    def is_running(self) -> bool:
        """Whether the service is currently running."""
        ...

    async def start(self) -> None:
        """Start the service."""
        ...

    async def stop(self) -> None:
        """Stop the service gracefully."""
        ...


@runtime_checkable
class ConfigurableProtocol(Protocol):
    """Protocol for components that can be configured.

    Configurable components must implement:
    - configure(config): Apply configuration
    - get_config(): Return current configuration
    """

    def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration to the component.

        Args:
            config: Configuration dictionary
        """
        ...

    def get_config(self) -> dict[str, Any]:
        """Get current configuration.

        Returns:
            Current configuration dictionary
        """
        ...


def is_tool_module(obj: Any) -> bool:
    """Check if an object is a valid tool module.

    This performs runtime validation that the object has the required
    register_tools function with the correct signature.

    Args:
        obj: Object to check (usually a module)

    Returns:
        True if the object implements ToolModuleProtocol
    """
    if not hasattr(obj, "register_tools"):
        return False

    register_fn = obj.register_tools  # type: ignore[union-attr]
    if not callable(register_fn):
        return False

    # Check function signature has at least one parameter (server)
    import inspect

    try:
        sig = inspect.signature(register_fn)
        params = list(sig.parameters.values())
        # Should have at least one parameter (server)
        if len(params) < 1:
            return False
        # First param should not be *args or **kwargs
        if params[0].kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            return False
        return True
    except (ValueError, TypeError):
        # Can't inspect signature, assume it's valid if callable
        return True


def validate_tool_module(module: Any, module_name: str) -> list[str]:
    """Validate a tool module and return any issues found.

    Args:
        module: Module to validate
        module_name: Name of the module (for error messages)

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    # Check register_tools exists
    if not hasattr(module, "register_tools"):
        errors.append(f"{module_name}: Missing register_tools function")
        return errors

    register_fn = module.register_tools  # type: ignore[union-attr]

    # Check it's callable
    if not callable(register_fn):
        errors.append(f"{module_name}: register_tools is not callable")
        return errors

    # Check signature
    import inspect

    try:
        sig = inspect.signature(register_fn)
        params = list(sig.parameters.values())

        if len(params) < 1:
            errors.append(
                f"{module_name}: register_tools must accept at least one parameter (server)"
            )

        # Check return type annotation if present
        if sig.return_annotation != inspect.Signature.empty:
            if sig.return_annotation not in (int, "int", None):
                errors.append(
                    f"{module_name}: register_tools should return int, "
                    f"got {sig.return_annotation}"
                )

    except (ValueError, TypeError) as e:
        errors.append(f"{module_name}: Could not inspect register_tools signature: {e}")

    # Check for __project_root__ (recommended but not required)
    if not hasattr(module, "__project_root__"):
        # This is a warning, not an error
        pass

    return errors
