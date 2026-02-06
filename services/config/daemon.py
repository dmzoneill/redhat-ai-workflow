#!/usr/bin/env python3
"""
Config Daemon - Centralized configuration service.

A standalone service that owns and caches all static configuration:
- skills/*.yaml - skill definitions
- personas/*.yaml - persona definitions
- config.json - project configuration
- tool_modules/ metadata - tool counts, module info

All consumers (UI, MCP server, skills engine, tools) query this daemon
via D-Bus instead of reading files directly.

Features:
- In-memory caching with file watchers for invalidation
- Single source of truth for configuration
- D-Bus IPC for external queries
- Graceful shutdown handling
- Systemd watchdog support

Usage:
    python -m services.config                # Run daemon
    python -m services.config --status       # Check if running
    python -m services.config --stop         # Stop running daemon
    python -m services.config --dbus         # Enable D-Bus IPC

Systemd:
    systemctl --user start bot-config
    systemctl --user status bot-config
    systemctl --user stop bot-config

D-Bus:
    Service: com.aiworkflow.BotConfig
    Path: /com/aiworkflow/BotConfig
"""

import ast
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
PERSONAS_DIR = PROJECT_ROOT / "personas"
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"
CONFIG_FILE = PROJECT_ROOT / "config.json"

logger = logging.getLogger(__name__)


class ConfigDaemon(DaemonDBusBase, BaseDaemon):
    """Config daemon with D-Bus support - owns all static configuration."""

    # BaseDaemon configuration
    name = "config"
    description = "Config Daemon - Centralized configuration service"

    # D-Bus configuration
    # Note: Using "BotConfig" instead of "Config" due to D-Bus name resolution issues
    # with the shorter name (possibly conflicts with system services)
    service_name = "com.aiworkflow.BotConfig"
    object_path = "/com/aiworkflow/BotConfig"
    interface_name = "com.aiworkflow.BotConfig"

    def __init__(self, verbose: bool = False, enable_dbus: bool = False):
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)

        # Caches
        self._skills_cache: dict[str, dict] | None = None
        self._skills_list_cache: list[dict] | None = None
        self._personas_cache: dict[str, dict] | None = None
        self._personas_list_cache: list[dict] | None = None
        self._tool_modules_cache: list[dict] | None = None
        self._config_cache: dict | None = None

        # Cache timestamps
        self._skills_loaded_at: datetime | None = None
        self._personas_loaded_at: datetime | None = None
        self._tool_modules_loaded_at: datetime | None = None
        self._config_loaded_at: datetime | None = None

        # File watchers
        self._watchers: list[asyncio.Task] = []

        # Register D-Bus handlers
        self.register_handler("get_skills_list", self._handle_get_skills_list)
        self.register_handler("get_skill_definition", self._handle_get_skill_definition)
        self.register_handler("get_personas_list", self._handle_get_personas_list)
        self.register_handler("get_persona_definition", self._handle_get_persona_definition)
        self.register_handler("get_tool_modules", self._handle_get_tool_modules)
        self.register_handler("get_config", self._handle_get_config)
        self.register_handler("invalidate_cache", self._handle_invalidate_cache)
        self.register_handler("get_state", self._handle_get_state)

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return config-specific statistics."""
        return {
            "skills_count": len(self._skills_cache) if self._skills_cache else 0,
            "personas_count": len(self._personas_cache) if self._personas_cache else 0,
            "tool_modules_count": len(self._tool_modules_cache) if self._tool_modules_cache else 0,
            "skills_loaded_at": self._skills_loaded_at.isoformat() if self._skills_loaded_at else None,
            "personas_loaded_at": self._personas_loaded_at.isoformat() if self._personas_loaded_at else None,
            "config_loaded_at": self._config_loaded_at.isoformat() if self._config_loaded_at else None,
        }

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        stats = await self.get_service_stats()
        return {
            "status": "running" if self.is_running else "stopped",
            "cache_valid": all(
                [
                    self._skills_cache is not None or self._skills_list_cache is not None,
                    self._personas_cache is not None or self._personas_list_cache is not None,
                    self._tool_modules_cache is not None,
                ]
            ),
            **stats,
        }

    async def _handle_get_state(self, **kwargs) -> dict:
        """Get full daemon state for UI."""
        stats = await self.get_service_stats()
        return {
            "success": True,
            "state": {
                **stats,
                "running": True,
                "cache_valid": all(
                    [
                        self._skills_cache is not None,
                        self._personas_cache is not None,
                        self._tool_modules_cache is not None,
                    ]
                ),
            },
        }

    async def _handle_get_skills_list(self, **kwargs) -> dict:
        """Get list of all skills with metadata."""
        try:
            skills = self._load_skills_list()
            return {"success": True, "skills": skills}
        except Exception as e:
            logger.error(f"Failed to get skills list: {e}")
            return {"success": False, "error": str(e), "skills": []}

    async def _handle_get_skill_definition(self, name: str = None, **kwargs) -> dict:
        """Get full skill definition by name."""
        if not name:
            return {"success": False, "error": "name required"}

        try:
            skill = self._load_skill_definition(name)
            if skill:
                return {"success": True, "skill": skill}
            return {"success": False, "error": f"Skill '{name}' not found"}
        except Exception as e:
            logger.error(f"Failed to get skill definition: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_personas_list(self, **kwargs) -> dict:
        """Get list of all personas with metadata."""
        try:
            personas = self._load_personas_list()
            return {"success": True, "personas": personas}
        except Exception as e:
            logger.error(f"Failed to get personas list: {e}")
            return {"success": False, "error": str(e), "personas": []}

    async def _handle_get_persona_definition(self, name: str = None, **kwargs) -> dict:
        """Get full persona definition by name."""
        if not name:
            return {"success": False, "error": "name required"}

        try:
            persona = self._load_persona_definition(name)
            if persona:
                return {"success": True, "persona": persona}
            return {"success": False, "error": f"Persona '{name}' not found"}
        except Exception as e:
            logger.error(f"Failed to get persona definition: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_tool_modules(self, **kwargs) -> dict:
        """Get list of all tool modules with metadata."""
        try:
            modules = self._load_tool_modules()
            return {"success": True, "modules": modules}
        except Exception as e:
            logger.error(f"Failed to get tool modules: {e}")
            return {"success": False, "error": str(e), "modules": []}

    async def _handle_get_config(self, **kwargs) -> dict:
        """Get project configuration."""
        try:
            config = self._load_config()
            return {"success": True, "config": config}
        except Exception as e:
            logger.error(f"Failed to get config: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_invalidate_cache(self, cache_type: str = "all", **kwargs) -> dict:
        """Invalidate cache(s) to force reload."""
        try:
            if cache_type in ("all", "skills"):
                self._skills_cache = None
                self._skills_list_cache = None
                self._skills_loaded_at = None
                logger.info("Skills cache invalidated")

            if cache_type in ("all", "personas"):
                self._personas_cache = None
                self._personas_list_cache = None
                self._personas_loaded_at = None
                logger.info("Personas cache invalidated")

            if cache_type in ("all", "tool_modules"):
                self._tool_modules_cache = None
                self._tool_modules_loaded_at = None
                logger.info("Tool modules cache invalidated")

            if cache_type in ("all", "config"):
                self._config_cache = None
                self._config_loaded_at = None
                logger.info("Config cache invalidated")

            return {"success": True, "invalidated": cache_type}
        except Exception as e:
            logger.error(f"Failed to invalidate cache: {e}")
            return {"success": False, "error": str(e)}

    # ==================== Cache Loading ====================

    def _load_skills_list(self) -> list[dict]:
        """Load list of all skills with metadata."""
        if self._skills_list_cache is not None:
            return self._skills_list_cache

        skills = []
        if not SKILLS_DIR.exists():
            return skills

        for file in sorted(SKILLS_DIR.glob("*.yaml")):
            try:
                content = file.read_text()
                data = yaml.safe_load(content)
                if data:
                    name = data.get("name", file.stem)
                    skills.append(
                        {
                            "name": name,
                            "description": data.get("description", "")[:200],
                            "version": data.get("version", "1.0"),
                            "inputs": [
                                {
                                    "name": inp.get("name"),
                                    "type": inp.get("type", "string"),
                                    "required": inp.get("required", False),
                                    "description": inp.get("description", ""),
                                }
                                for inp in data.get("inputs", [])
                            ],
                            "step_count": len(data.get("steps", [])),
                            "file": str(file),
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to parse skill {file}: {e}")

        self._skills_list_cache = skills
        self._skills_loaded_at = datetime.now()
        logger.info(f"Loaded {len(skills)} skills")
        return skills

    def _load_skill_definition(self, name: str) -> dict | None:
        """Load full skill definition by name."""
        # Check cache first
        if self._skills_cache is None:
            self._skills_cache = {}

        if name in self._skills_cache:
            return self._skills_cache[name]

        # Try to find and load the skill
        skill_file = SKILLS_DIR / f"{name}.yaml"
        if not skill_file.exists():
            return None

        try:
            content = skill_file.read_text()
            data = yaml.safe_load(content)
            if data:
                # Store raw YAML content too for display
                data["_raw_yaml"] = content
                self._skills_cache[name] = data
                return data
        except Exception as e:
            logger.error(f"Failed to load skill {name}: {e}")

        return None

    def _load_personas_list(self) -> list[dict]:
        """Load list of all personas with metadata."""
        if self._personas_list_cache is not None:
            return self._personas_list_cache

        # Ensure tool modules are loaded so we can count tools per module/tier
        tool_modules = self._load_tool_modules()
        # Build lookup: module_name -> {core: N, basic: M, extra: P, total: T}
        default_tier = {"core": 0, "basic": 0, "extra": 0}
        tool_counts_by_module = {
            m["name"]: m.get("tier_counts", {"core": 0, "basic": m["tool_count"], "extra": 0}) for m in tool_modules
        }

        personas = []
        if not PERSONAS_DIR.exists():
            return personas

        for file in sorted(PERSONAS_DIR.glob("*.yaml")):
            try:
                content = file.read_text()
                data = yaml.safe_load(content)
                if data and data.get("name"):
                    tool_module_names = data.get("tools", [])
                    # Calculate actual tool count by summing tools from each module
                    # Handle tier suffixes: _core, _basic, _extra
                    tool_count = 0
                    for mod in tool_module_names:
                        base = mod.replace("_core", "").replace("_basic", "")
                        base_name = base.replace("_extra", "").replace("_style", "")
                        tier_counts = tool_counts_by_module.get(base_name, default_tier)

                        if mod.endswith("_core"):
                            # Only core tools
                            tool_count += tier_counts.get("core", 0)
                        elif mod.endswith("_basic"):
                            # Core + basic tools (basic includes core when loaded)
                            tool_count += tier_counts.get("core", 0) + tier_counts.get("basic", 0)
                        elif mod.endswith("_extra"):
                            # Only extra tools
                            tool_count += tier_counts.get("extra", 0)
                        elif mod.endswith("_style"):
                            # Style tools (separate count)
                            tool_count += tier_counts.get("style", 0)
                        else:
                            # No suffix: load core if exists, else basic
                            if tier_counts.get("core", 0) > 0:
                                tool_count += tier_counts.get("core", 0)
                            else:
                                tool_count += tier_counts.get("basic", 0)

                    personas.append(
                        {
                            "name": data.get("name"),
                            "description": data.get("description", ""),
                            "tools": tool_module_names,
                            "tool_count": tool_count,
                            "skills": data.get("skills", []),
                            "skills_count": len(data.get("skills", [])),
                            "file": str(file),
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to parse persona {file}: {e}")

        self._personas_list_cache = personas
        self._personas_loaded_at = datetime.now()
        logger.info(f"Loaded {len(personas)} personas")
        return personas

    def _load_persona_definition(self, name: str) -> dict | None:
        """Load full persona definition by name."""
        if self._personas_cache is None:
            self._personas_cache = {}

        if name in self._personas_cache:
            return self._personas_cache[name]

        persona_file = PERSONAS_DIR / f"{name}.yaml"
        if not persona_file.exists():
            return None

        try:
            content = persona_file.read_text()
            data = yaml.safe_load(content)
            if data:
                data["_raw_yaml"] = content
                self._personas_cache[name] = data
                return data
        except Exception as e:
            logger.error(f"Failed to load persona {name}: {e}")

        return None

    def _load_tool_modules(self) -> list[dict]:
        """Load list of all tool modules with metadata including tool details and tier counts."""
        if self._tool_modules_cache is not None:
            return self._tool_modules_cache

        modules = []
        if not TOOL_MODULES_DIR.exists():
            return modules

        for module_dir in sorted(TOOL_MODULES_DIR.iterdir()):
            if not module_dir.is_dir() or not module_dir.name.startswith("aa_"):
                continue

            module_name = module_dir.name.replace("aa_", "")
            src_dir = module_dir / "src"

            # Parse tools from source files, tracking by tier
            tools = []
            tier_counts = {"core": 0, "basic": 0, "extra": 0, "style": 0}
            description = ""

            if src_dir.exists():
                # Parse each tier file separately
                for tier_name, filename in [
                    ("core", "tools_core.py"),
                    ("basic", "tools_basic.py"),
                    ("extra", "tools_extra.py"),
                    ("style", "tools_style.py"),
                ]:
                    tier_file = src_dir / filename
                    if tier_file.exists():
                        try:
                            parsed_tools = self._parse_tools_from_file(tier_file)
                            for tool in parsed_tools:
                                tool["tier"] = tier_name
                            tools.extend(parsed_tools)
                            tier_counts[tier_name] = len(parsed_tools)
                        except Exception as e:
                            logger.debug(f"Failed to parse {tier_file}: {e}")

                # Also check legacy tools.py (treat as basic)
                legacy_file = src_dir / "tools.py"
                if legacy_file.exists() and tier_counts["basic"] == 0:
                    try:
                        parsed_tools = self._parse_tools_from_file(legacy_file)
                        for tool in parsed_tools:
                            tool["tier"] = "basic"
                        tools.extend(parsed_tools)
                        tier_counts["basic"] = len(parsed_tools)
                    except Exception as e:
                        logger.debug(f"Failed to parse {legacy_file}: {e}")

                # For workflow module, analyze tools_core.py and tools_basic.py imports
                # to determine which source files belong to which tier
                if module_name == "workflow" and tier_counts["basic"] == 0 and tier_counts["core"] == 0:
                    # Determine which tool files are imported by each tier file
                    core_imports = self._get_workflow_tier_imports(src_dir / "tools_core.py")
                    basic_imports = self._get_workflow_tier_imports(src_dir / "tools_basic.py")

                    # Scan all Python files that might contain tools
                    for py_file in src_dir.glob("*.py"):
                        # Skip the tier files themselves and __init__.py
                        if py_file.name in ("tools_core.py", "tools_basic.py", "tools_extra.py", "__init__.py"):
                            continue

                        try:
                            parsed_tools = self._parse_tools_from_file(py_file)
                            if not parsed_tools:
                                continue

                            # Determine tier based on which file imports this module
                            file_stem = py_file.stem  # e.g., "memory_tools", "skill_engine"
                            if file_stem in core_imports:
                                tier = "core"
                            elif file_stem in basic_imports:
                                tier = "basic"
                            else:
                                tier = "extra"  # Not imported by core or basic

                            for tool in parsed_tools:
                                tool["tier"] = tier
                            tools.extend(parsed_tools)
                            tier_counts[tier] += len(parsed_tools)
                        except Exception as e:
                            logger.debug(f"Failed to parse {py_file}: {e}")

            # Try to get module description from README
            readme = module_dir / "README.md"
            if readme.exists():
                try:
                    content = readme.read_text()
                    # Get first paragraph after title
                    lines = content.split("\n")
                    for i, line in enumerate(lines):
                        if line.strip() and not line.startswith("#"):
                            description = line.strip()
                            break
                except Exception:
                    pass

            modules.append(
                {
                    "name": module_name,
                    "full_name": module_dir.name,
                    "path": str(module_dir),
                    "tool_count": len(tools),
                    "tier_counts": tier_counts,
                    "tools": tools,
                    "description": description,
                }
            )

        self._tool_modules_cache = modules
        self._tool_modules_loaded_at = datetime.now()
        logger.info(f"Loaded {len(modules)} tool modules with tool details")
        return modules

    def _parse_tools_from_file(self, filepath: Path) -> list[dict]:
        """Parse tool definitions from a Python file using AST."""
        tools = []

        try:
            source = filepath.read_text()
            tree = ast.parse(source)
        except (SyntaxError, OSError) as e:
            logger.debug(f"Could not parse {filepath}: {e}")
            return tools

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                # Check if this function has @registry.tool() or similar decorator
                is_tool = False
                for decorator in node.decorator_list:
                    decorator_name = self._get_decorator_name(decorator)
                    if decorator_name == "tool":
                        is_tool = True
                        break

                if is_tool:
                    # Get docstring
                    docstring = ast.get_docstring(node) or ""
                    first_line = docstring.split("\n")[0].strip() if docstring else ""

                    # Parse function parameters
                    params = self._parse_function_params(node, docstring)

                    tools.append(
                        {
                            "name": node.name,
                            "description": first_line,
                            "parameters": params,
                            "source_file": str(filepath),
                            "line_number": node.lineno,
                        }
                    )

        return tools

    def _get_workflow_tier_imports(self, tier_file: Path) -> set[str]:
        """Parse a workflow tier file to find which modules it imports for tool registration.

        Looks for patterns like:
        - from .memory_tools import register_memory_tools
        - from .skill_engine import register_skill_tools

        Returns set of module stems (e.g., {'memory_tools', 'skill_engine'})
        """
        imports = set()
        if not tier_file.exists():
            return imports

        try:
            source = tier_file.read_text()
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            return imports

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                # Handle both ".memory_tools" and "memory_tools"
                if module.startswith("."):
                    module = module[1:]
                # Check if any imported name contains "register" (tool registration function)
                has_register = any("register" in alias.name.lower() for alias in node.names)
                if has_register and module:
                    imports.add(module)

        return imports

    def _get_decorator_name(self, decorator: ast.expr) -> str:
        """Extract decorator name from AST node."""
        if isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Attribute):
                return decorator.func.attr
            elif isinstance(decorator.func, ast.Name):
                return decorator.func.id
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr
        elif isinstance(decorator, ast.Name):
            return decorator.id
        return ""

    def _parse_function_params(self, node: ast.AsyncFunctionDef, docstring: str) -> list[dict]:
        """Parse function parameters from AST and docstring."""
        params = []

        # Parse Args section from docstring for descriptions
        param_docs = {}
        if docstring and "Args:" in docstring:
            in_args = False
            current_param = None
            for line in docstring.split("\n"):
                stripped = line.strip()
                if stripped == "Args:":
                    in_args = True
                    continue
                if in_args:
                    if stripped.startswith("Returns:") or stripped.startswith("Raises:"):
                        break
                    # Check for param definition (name: description or name (type): description)
                    match = re.match(r"(\w+)(?:\s*\([^)]+\))?:\s*(.*)", stripped)
                    if match:
                        current_param = match.group(1)
                        param_docs[current_param] = match.group(2)
                    elif current_param and stripped:
                        # Continuation of previous param description
                        param_docs[current_param] += " " + stripped

        # Get parameters from function signature
        for arg in node.args.args:
            param_name = arg.arg
            if param_name in ("self", "ctx"):
                continue

            # Get type annotation
            param_type = "any"
            if arg.annotation:
                param_type = self._get_type_name(arg.annotation)

            # Check if required (no default value)
            # Count defaults from the end
            num_defaults = len(node.args.defaults)
            num_args = len(node.args.args)
            arg_index = node.args.args.index(arg)
            has_default = arg_index >= (num_args - num_defaults)

            params.append(
                {
                    "name": param_name,
                    "type": param_type,
                    "required": not has_default,
                    "description": param_docs.get(param_name, ""),
                }
            )

        return params

    def _get_type_name(self, annotation: ast.expr) -> str:
        """Extract type name from annotation AST node."""
        if isinstance(annotation, ast.Name):
            return annotation.id
        elif isinstance(annotation, ast.Constant):
            return str(annotation.value)
        elif isinstance(annotation, ast.Subscript):
            # Handle Optional[X], List[X], etc.
            if isinstance(annotation.value, ast.Name):
                base = annotation.value.id
                if base == "Optional":
                    inner = self._get_type_name(annotation.slice)
                    return f"{inner}?"
                return base
        elif isinstance(annotation, ast.BinOp):
            # Handle X | None (Python 3.10+ union syntax)
            if isinstance(annotation.op, ast.BitOr):
                left = self._get_type_name(annotation.left)
                right = self._get_type_name(annotation.right)
                if right == "None":
                    return f"{left}?"
                return f"{left}|{right}"
        return "any"

    def _load_config(self) -> dict:
        """Load project configuration."""
        if self._config_cache is not None:
            return self._config_cache

        if not CONFIG_FILE.exists():
            return {}

        try:
            content = CONFIG_FILE.read_text()
            self._config_cache = json.loads(content)
            self._config_loaded_at = datetime.now()
            logger.info("Loaded config.json")
            return self._config_cache
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    # ==================== File Watching ====================

    async def _watch_directory(self, directory: Path, cache_type: str):
        """Watch a directory for changes and invalidate cache."""
        try:
            from watchfiles import awatch

            logger.info(f"Starting file watcher for {directory}")
            async for changes in awatch(directory):
                logger.info(f"Detected changes in {directory}: {len(changes)} files")
                await self._handle_invalidate_cache(cache_type=cache_type)
        except ImportError:
            logger.warning("watchfiles not installed - file watching disabled")
        except Exception as e:
            logger.error(f"File watcher error for {directory}: {e}")

    async def _start_file_watchers(self):
        """Start file watchers for all config directories."""
        try:
            if SKILLS_DIR.exists():
                self._watchers.append(asyncio.create_task(self._watch_directory(SKILLS_DIR, "skills")))
            if PERSONAS_DIR.exists():
                self._watchers.append(asyncio.create_task(self._watch_directory(PERSONAS_DIR, "personas")))
            if TOOL_MODULES_DIR.exists():
                self._watchers.append(asyncio.create_task(self._watch_directory(TOOL_MODULES_DIR, "tool_modules")))
        except Exception as e:
            logger.warning(f"Failed to start file watchers: {e}")

    # ==================== Lifecycle ====================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        logger.info("Config daemon starting...")

        # Pre-load caches
        self._load_skills_list()
        self._load_personas_list()
        self._load_tool_modules()
        self._load_config()

        # Start file watchers
        await self._start_file_watchers()

        # Start D-Bus service if enabled
        if self.enable_dbus:
            try:
                await self.start_dbus()
                logger.info(f"D-Bus service started: {self.service_name}")
            except Exception as e:
                logger.error(f"Failed to start D-Bus: {e}")

        self.is_running = True
        logger.info("Config daemon ready")

    async def run_daemon(self):
        """Main daemon loop - wait for shutdown."""
        # The D-Bus library uses add_reader() to process messages via the event loop
        await self._shutdown_event.wait()

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Config daemon shutting down...")

        # Cancel file watchers
        for watcher in self._watchers:
            watcher.cancel()

        # Stop D-Bus
        if self.enable_dbus:
            await self.stop_dbus()

        self.is_running = False
        await super().shutdown()
        logger.info("Config daemon stopped")

    async def health_check(self) -> dict:
        """Perform a health check on the config daemon."""
        self._last_health_check = time.time()

        checks = {
            "running": self.is_running,
            "skills_loaded": self._skills_cache is not None or self._skills_list_cache is not None,
            "personas_loaded": self._personas_cache is not None or self._personas_list_cache is not None,
            "tool_modules_loaded": self._tool_modules_cache is not None,
            "config_loaded": self._config_cache is not None,
        }

        healthy = all(checks.values())

        return {
            "healthy": healthy,
            "checks": checks,
            "message": "Config daemon is healthy" if healthy else "Some caches not loaded",
            "timestamp": self._last_health_check,
        }


if __name__ == "__main__":
    ConfigDaemon.main()
