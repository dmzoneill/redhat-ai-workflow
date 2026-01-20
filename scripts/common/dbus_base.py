#!/usr/bin/env python3
# flake8: noqa: F821
# Note: F821 disabled because D-Bus type annotations like "s", "i", "b"
# are valid dbus-next signatures but flake8 misinterprets them as undefined names.
"""
Base D-Bus Interface for AI Workflow Daemons

Provides reusable D-Bus IPC infrastructure for all daemons:
- Base service interface with common properties/methods
- Client class for communicating with daemons
- Factory functions for creating service-specific interfaces

Usage:
    # In your daemon:
    from scripts.common.dbus_base import create_dbus_service, DaemonDBusBase

    class MyDaemon(DaemonDBusBase):
        service_name = "com.aiworkflow.MyService"
        object_path = "/com/aiworkflow/MyService"
        interface_name = "com.aiworkflow.MyService"

        async def get_service_stats(self) -> dict:
            return {"my_stat": 42}

    # Start D-Bus
    await daemon.start_dbus()
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Type, TypeVar

# Check for dbus availability
try:
    from dbus_next.aio import MessageBus
    from dbus_next.constants import PropertyAccess
    from dbus_next.service import ServiceInterface, dbus_property, method
    from dbus_next.service import signal as dbus_signal

    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False

    # Create dummy decorators for when dbus-next isn't installed
    def dbus_property(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def method(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def dbus_signal(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    class ServiceInterface:
        def __init__(self, name):
            self.name = name

    class PropertyAccess:
        READ = "read"


logger = logging.getLogger(__name__)

T = TypeVar("T", bound="DaemonDBusBase")


@dataclass
class ServiceConfig:
    """Configuration for a D-Bus service."""

    service_name: str
    object_path: str
    interface_name: str


# =============================================================================
# BASE DAEMON CLASS
# =============================================================================


class DaemonDBusBase(ABC):
    """
    Base class for daemons with D-Bus support.

    Subclasses must define:
    - service_name: D-Bus service name (e.g., "com.aiworkflow.CronScheduler")
    - object_path: D-Bus object path (e.g., "/com/aiworkflow/CronScheduler")
    - interface_name: D-Bus interface name (e.g., "com.aiworkflow.CronScheduler")

    And implement:
    - get_service_stats(): Return service-specific stats as dict
    - get_service_status(): Return detailed status as dict
    """

    # Subclasses must override these
    service_name: str = ""
    object_path: str = ""
    interface_name: str = ""

    def __init__(self):
        self.is_running = False
        self.start_time: float | None = None

        self._bus: Optional["MessageBus"] = None
        self._dbus_interface: Optional["BaseDaemonDBusInterface"] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutdown_requested = False

        # Custom method handlers (for service-specific methods)
        self._custom_handlers: dict[str, Callable] = {}

    @abstractmethod
    async def get_service_stats(self) -> dict:
        """Return service-specific statistics."""
        pass

    @abstractmethod
    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        pass

    def get_base_stats(self) -> dict:
        """Get common daemon statistics."""
        return {
            "running": self.is_running,
            "uptime": time.time() - self.start_time if self.start_time else 0,
            "service_name": self.service_name,
        }

    async def start_dbus(self):
        """Start the D-Bus service."""
        if not DBUS_AVAILABLE:
            logger.warning("D-Bus not available (dbus-next not installed)")
            return False

        if not self.service_name:
            logger.error("service_name not set on daemon class")
            return False

        try:
            self._event_loop = asyncio.get_running_loop()
            self._bus = await MessageBus().connect()

            # Create the interface dynamically
            self._dbus_interface = create_daemon_interface(self)

            self._bus.export(self.object_path, self._dbus_interface)
            await self._bus.request_name(self.service_name)

            logger.info(f"D-Bus service started: {self.service_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to start D-Bus: {e}")
            return False

    async def stop_dbus(self):
        """Stop the D-Bus service."""
        if self._bus:
            self._bus.disconnect()
            self._bus = None
            logger.info(f"D-Bus service stopped: {self.service_name}")

    def request_shutdown(self):
        """Request graceful shutdown."""
        self._shutdown_requested = True

    def register_handler(self, name: str, handler: Callable):
        """Register a custom D-Bus method handler."""
        self._custom_handlers[name] = handler

    async def call_handler(self, name: str, *args) -> Any:
        """Call a registered handler."""
        if name not in self._custom_handlers:
            return {"error": f"Unknown handler: {name}"}

        handler = self._custom_handlers[name]
        if asyncio.iscoroutinefunction(handler):
            return await handler(*args)
        return handler(*args)

    # Signal emission helpers
    def emit_status_changed(self, status: str):
        """Emit status changed signal."""
        if self._dbus_interface and hasattr(self._dbus_interface, "StatusChanged"):
            self._dbus_interface.StatusChanged(status)

    def emit_event(self, event_type: str, data: str):
        """Emit generic event signal."""
        if self._dbus_interface and hasattr(self._dbus_interface, "Event"):
            self._dbus_interface.Event(event_type, data)


# =============================================================================
# D-BUS INTERFACE FACTORY
# =============================================================================


def create_daemon_interface(daemon: DaemonDBusBase) -> "ServiceInterface":
    """
    Create a D-Bus interface for a daemon.

    This dynamically creates a ServiceInterface subclass with the daemon's
    interface_name and methods bound to the daemon instance.
    """
    if not DBUS_AVAILABLE:
        raise RuntimeError("dbus-next not installed")

    class DynamicDaemonInterface(ServiceInterface):
        """Dynamically created D-Bus interface."""

        def __init__(self, daemon_instance: DaemonDBusBase):
            super().__init__(daemon_instance.interface_name)
            self._daemon = daemon_instance

        # ==================== Properties ====================

        @dbus_property(access=PropertyAccess.READ)
        def Running(self) -> "b":
            """Whether the daemon is running."""
            return self._daemon.is_running

        @dbus_property(access=PropertyAccess.READ)
        def Uptime(self) -> "d":
            """Daemon uptime in seconds."""
            if self._daemon.start_time:
                return time.time() - self._daemon.start_time
            return 0.0

        @dbus_property(access=PropertyAccess.READ)
        def Stats(self) -> "s":
            """JSON stats about the daemon."""
            # Return synchronous base stats - async stats via GetStats method
            return json.dumps(self._daemon.get_base_stats())

        # ==================== Methods ====================

        @method()
        async def GetStatus(self) -> "s":
            """Get daemon status as JSON."""
            try:
                base = self._daemon.get_base_stats()
                service = await self._daemon.get_service_status()
                return json.dumps({**base, **service})
            except Exception as e:
                logger.error(f"GetStatus error: {e}")
                return json.dumps({"running": self._daemon.is_running, "error": str(e)})

        @method()
        async def GetStats(self) -> "s":
            """Get daemon stats as JSON."""
            try:
                base = self._daemon.get_base_stats()
                service = await self._daemon.get_service_stats()
                return json.dumps({**base, **service})
            except Exception as e:
                logger.error(f"GetStats error: {e}")
                return json.dumps({"error": str(e)})

        @method()
        async def Shutdown(self) -> "s":
            """Gracefully shutdown the daemon."""
            self._daemon.request_shutdown()
            return json.dumps({"success": True, "message": "Shutdown initiated"})

        @method()
        async def CallMethod(self, method_name: "s", args_json: "s") -> "s":
            """Call a custom registered method."""
            try:
                args = json.loads(args_json) if args_json else []
                if not isinstance(args, list):
                    args = [args]

                result = await self._daemon.call_handler(method_name, *args)
                return json.dumps(result)
            except Exception as e:
                logger.error(f"CallMethod error: {e}")
                return json.dumps({"error": str(e)})

        # ==================== Signals ====================

        @dbus_signal()
        def StatusChanged(self, status: "s") -> None:
            """Emitted when daemon status changes."""
            pass

        @dbus_signal()
        def Event(self, event_type: "s", data: "s") -> None:
            """Generic event signal."""
            pass

    return DynamicDaemonInterface(daemon)


# =============================================================================
# D-BUS CLIENT
# =============================================================================


class DaemonClient:
    """
    Generic client for communicating with AI Workflow daemons via D-Bus.

    Usage:
        client = DaemonClient(
            service_name="com.aiworkflow.CronScheduler",
            object_path="/com/aiworkflow/CronScheduler",
            interface_name="com.aiworkflow.CronScheduler",
        )
        await client.connect()
        status = await client.get_status()
        await client.disconnect()
    """

    def __init__(
        self,
        service_name: str,
        object_path: str,
        interface_name: str,
    ):
        self.service_name = service_name
        self.object_path = object_path
        self.interface_name = interface_name

        self._bus: Optional["MessageBus"] = None
        self._proxy = None

    async def connect(self) -> bool:
        """Connect to the D-Bus service."""
        if not DBUS_AVAILABLE:
            print("Error: dbus-next not installed")
            return False

        try:
            self._bus = await MessageBus().connect()
            introspection = await self._bus.introspect(self.service_name, self.object_path)
            self._proxy = self._bus.get_proxy_object(
                self.service_name,
                self.object_path,
                introspection,
            )
            return True
        except Exception as e:
            print(f"Failed to connect to {self.service_name}: {e}")
            print("Is the daemon running?")
            return False

    async def disconnect(self):
        """Disconnect from D-Bus."""
        if self._bus:
            self._bus.disconnect()

    def _get_interface(self):
        """Get the D-Bus interface."""
        if not self._proxy:
            raise RuntimeError("Not connected")
        return self._proxy.get_interface(self.interface_name)

    async def get_status(self) -> dict:
        """Get daemon status."""
        interface = self._get_interface()
        result = await interface.call_get_status()
        return json.loads(result)

    async def get_stats(self) -> dict:
        """Get daemon stats."""
        interface = self._get_interface()
        result = await interface.call_get_stats()
        return json.loads(result)

    async def shutdown(self) -> dict:
        """Shutdown the daemon."""
        interface = self._get_interface()
        result = await interface.call_shutdown()
        return json.loads(result)

    async def call_method(self, method_name: str, args: list = None) -> dict:
        """Call a custom method on the daemon."""
        interface = self._get_interface()
        args_json = json.dumps(args or [])
        result = await interface.call_call_method(method_name, args_json)
        return json.loads(result)

    @property
    def is_running(self) -> bool:
        """Check if connected to a running daemon."""
        return self._proxy is not None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def get_client(service: str) -> DaemonClient:
    """
    Get a client for a known service.

    Args:
        service: Service name - "cron", "meet", or "slack"

    Returns:
        Configured DaemonClient instance
    """
    services = {
        "cron": ServiceConfig(
            service_name="com.aiworkflow.CronScheduler",
            object_path="/com/aiworkflow/CronScheduler",
            interface_name="com.aiworkflow.CronScheduler",
        ),
        "meet": ServiceConfig(
            service_name="com.aiworkflow.MeetBot",
            object_path="/com/aiworkflow/MeetBot",
            interface_name="com.aiworkflow.MeetBot",
        ),
        "slack": ServiceConfig(
            service_name="com.aiworkflow.SlackAgent",
            object_path="/com/aiworkflow/SlackAgent",
            interface_name="com.aiworkflow.SlackAgent",
        ),
    }

    if service not in services:
        raise ValueError(f"Unknown service: {service}. Known: {list(services.keys())}")

    config = services[service]
    return DaemonClient(
        service_name=config.service_name,
        object_path=config.object_path,
        interface_name=config.interface_name,
    )


async def check_daemon_status(service: str) -> dict:
    """
    Quick check if a daemon is running and get its status.

    Args:
        service: Service name - "cron", "meet", or "slack"

    Returns:
        Status dict or {"running": False, "error": "..."} if not running
    """
    client = get_client(service)
    try:
        if await client.connect():
            status = await client.get_status()
            await client.disconnect()
            return status
    except Exception as e:
        return {"running": False, "error": str(e)}

    return {"running": False, "error": "Could not connect"}
