"""ChatSession: state of one chat session within a Cursor workspace."""

from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Generic, TypedDict, TypeVar, Unpack, overload

from server import workspace_defaults
from server.workspace_defaults import MAX_FILTER_CACHE_SIZE, SESSION_STALE_HOURS, as_aware, now

_T = TypeVar("_T")


def _default_persona() -> str:
    """Default persona, resolved when the session is created."""
    return workspace_defaults.get_default_persona()


@dataclass
class _SessionContext:
    """What the session works on."""

    persona: str = field(default_factory=_default_persona)
    project: str | None = None  # Per-session project (can differ from workspace default)
    is_project_auto_detected: bool = False  # True if project was auto-detected from workspace path
    issue_key: str | None = None
    branch: str | None = None
    name: str | None = None  # Optional user-friendly name


@dataclass
class _ToolState:
    """Dual tool count system and the NPU tool filter cache."""

    static_tool_count: int = 0  # Baseline from persona YAML (calculated from tool modules)
    dynamic_tool_count: int = 0  # Context-aware from NPU filter (updated on each filter call)
    last_filter_message: str | None = None  # Message that triggered last NPU filter
    last_filter_time: datetime | None = None  # When last NPU filter was run
    tool_filter_cache: dict[str, list[str]] = field(default_factory=dict)  # Keyed by message hash


@dataclass
class _Activity:
    """Timestamps and tool call tracking."""

    started_at: datetime = field(default_factory=now)
    last_activity: datetime = field(default_factory=now)
    last_tool: str | None = None  # Last tool called in this session
    last_tool_time: datetime | None = None  # When the last tool was called
    tool_call_count: int = 0  # Total tool calls in this session


@dataclass
class _SessionCaches:
    """Meeting references and memory abstraction caches (per session to avoid cross-chat interference)."""

    # [{"meeting_id": 1, "title": "Sprint Planning", "date": "2025-01-20", "matches": 3}, ...]
    meeting_references: list[dict] = field(default_factory=list)
    intent_cache: dict[str, dict] = field(default_factory=dict)  # {query_hash: IntentClassification}
    memory_query_cache: dict[str, dict] = field(default_factory=dict)  # {query_hash: QueryResult}


_GROUPS: dict[str, type] = {
    "_context": _SessionContext,
    "_tools": _ToolState,
    "_activity": _Activity,
    "_caches": _SessionCaches,
}
_FIELD_GROUP = {f.name: group for group, cls in _GROUPS.items() for f in fields(cls)}


class ChatSessionFields(TypedDict, total=False):
    """Optional keyword arguments of :class:`ChatSession`."""

    persona: str
    project: str | None
    is_project_auto_detected: bool
    issue_key: str | None
    branch: str | None
    name: str | None
    static_tool_count: int
    dynamic_tool_count: int
    last_filter_message: str | None
    last_filter_time: datetime | None
    tool_filter_cache: dict[str, list[str]]
    started_at: datetime
    last_activity: datetime
    last_tool: str | None
    last_tool_time: datetime | None
    tool_call_count: int
    meeting_references: list[dict]
    intent_cache: dict[str, dict]
    memory_query_cache: dict[str, dict]


class _Delegated(Generic[_T]):
    """Attribute stored on one of the session's field groups."""

    def __init__(self, group: str) -> None:
        self.group = group
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, obj: None, objtype: type | None = None) -> "_Delegated[_T]": ...

    @overload
    def __get__(self, obj: object, objtype: type | None = None) -> _T: ...

    def __get__(self, obj: object | None, objtype: type | None = None) -> "_T | _Delegated[_T]":
        if obj is None:
            return self
        return getattr(getattr(obj, self.group), self.name)

    def __set__(self, obj: object, value: _T) -> None:
        setattr(getattr(obj, self.group), self.name, value)


class ChatSession:
    """State for a single chat session within a workspace.

    Each chat session maintains its own:
    - Session ID (generated on session_start())
    - Project (per-session, not per-workspace!)
    - Persona (developer, devops, incident, release)
    - Active issue and branch
    - Tool filter cache (for NPU results)

    Tool Counts:
    - static_tool_count: Baseline count from persona YAML (all tools available)
    - dynamic_tool_count: Context-aware count from NPU filter (tools for current message)
    - tool_count: Computed property returning dynamic if > 0, else static

    Constructed with keywords, like the dataclass it replaces: ``session_id`` and
    ``workspace_uri`` plus any of :class:`ChatSessionFields`.
    """

    MAX_INTENT_CACHE_SIZE = 100
    MAX_QUERY_CACHE_SIZE = 50

    persona: _Delegated[str] = _Delegated("_context")
    project: _Delegated[str | None] = _Delegated("_context")
    is_project_auto_detected: _Delegated[bool] = _Delegated("_context")
    issue_key: _Delegated[str | None] = _Delegated("_context")
    branch: _Delegated[str | None] = _Delegated("_context")
    name: _Delegated[str | None] = _Delegated("_context")
    static_tool_count: _Delegated[int] = _Delegated("_tools")
    dynamic_tool_count: _Delegated[int] = _Delegated("_tools")
    last_filter_message: _Delegated[str | None] = _Delegated("_tools")
    last_filter_time: _Delegated[datetime | None] = _Delegated("_tools")
    tool_filter_cache: _Delegated[dict[str, list[str]]] = _Delegated("_tools")
    started_at: _Delegated[datetime] = _Delegated("_activity")
    last_activity: _Delegated[datetime] = _Delegated("_activity")
    last_tool: _Delegated[str | None] = _Delegated("_activity")
    last_tool_time: _Delegated[datetime | None] = _Delegated("_activity")
    tool_call_count: _Delegated[int] = _Delegated("_activity")
    meeting_references: _Delegated[list[dict]] = _Delegated("_caches")
    intent_cache: _Delegated[dict[str, dict]] = _Delegated("_caches")
    memory_query_cache: _Delegated[dict[str, dict]] = _Delegated("_caches")

    def __init__(self, session_id: str, workspace_uri: str, **options: Unpack[ChatSessionFields]) -> None:
        values: dict[str, Any] = dict(options)
        unknown = set(values) - set(_FIELD_GROUP)
        if unknown:
            raise TypeError(f"ChatSession() got unexpected keyword argument(s): {', '.join(sorted(unknown))}")
        self.session_id = session_id
        self.workspace_uri = workspace_uri
        grouped: dict[str, dict[str, Any]] = {group: {} for group in _GROUPS}
        for key, value in values.items():
            grouped[_FIELD_GROUP[key]][key] = value
        self._context = _SessionContext(**grouped["_context"])
        self._tools = _ToolState(**grouped["_tools"])
        self._activity = _Activity(**grouped["_activity"])
        self._caches = _SessionCaches(**grouped["_caches"])

    def _state(self) -> tuple:
        """Everything that defines the session, for equality and repr."""
        return (self.session_id, self.workspace_uri, self._context, self._tools, self._activity, self._caches)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ChatSession):
            return NotImplemented
        return self._state() == other._state()

    def __repr__(self) -> str:
        return (
            f"ChatSession(session_id={self.session_id!r}, workspace_uri={self.workspace_uri!r}, "
            f"persona={self.persona!r}, project={self.project!r}, issue_key={self.issue_key!r})"
        )

    @property
    def tool_count(self) -> int:
        """Computed tool count: dynamic if available, else static.

        Returns dynamic_tool_count if > 0 (context-aware from NPU filter),
        otherwise returns static_tool_count (baseline from persona YAML).
        """
        return self.dynamic_tool_count if self.dynamic_tool_count > 0 else self.static_tool_count

    @tool_count.setter
    def tool_count(self, value: int) -> None:
        """Set the baseline count used when no dynamic count is active."""
        self._tools.static_tool_count = value

    # Backward compatibility property
    @property
    def active_tools(self) -> set[str]:
        """Deprecated: Use tool_count instead. Returns empty set for compatibility."""
        return set()

    @active_tools.setter
    def active_tools(self, value: set[str]) -> None:
        """Deprecated: Sets static_tool_count from the length of the provided set."""
        self._tools.static_tool_count = len(value) if value else 0

    def touch(self, tool_name: str | None = None) -> None:
        """Update last activity timestamp and optionally track tool call.

        Args:
            tool_name: Optional name of the tool that was called
        """
        self._activity.last_activity = now()
        if tool_name:
            self._activity.last_tool = tool_name
            self._activity.last_tool_time = now()
            self.tool_call_count += 1

    def is_stale(self, max_age_hours: int = SESSION_STALE_HOURS) -> bool:
        """Check if session is stale (no activity for max_age_hours).

        Args:
            max_age_hours: Maximum hours of inactivity before considered stale

        Returns:
            True if session is stale
        """
        age = now() - as_aware(self.last_activity)
        return age.total_seconds() > (max_age_hours * 3600)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "workspace_uri": self.workspace_uri,
            "persona": self.persona,
            "project": self.project,
            "is_project_auto_detected": self.is_project_auto_detected,
            "issue_key": self.issue_key,
            "branch": self.branch,
            # Dual tool counts
            "static_tool_count": self.static_tool_count,
            "dynamic_tool_count": self.dynamic_tool_count,
            "tool_count": self.tool_count,  # Computed for backward compat
            "last_filter_message": self.last_filter_message,
            "last_filter_time": self.last_filter_time.isoformat() if self.last_filter_time else None,
            # Timestamps
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "name": self.name,
            "last_tool": self.last_tool,
            "last_tool_time": self.last_tool_time.isoformat() if self.last_tool_time else None,
            "tool_call_count": self.tool_call_count,
            "meeting_references": self.meeting_references,
        }

    def clear_filter_cache(self) -> None:
        """Clear the tool filter cache (e.g., when persona changes)."""
        self.tool_filter_cache.clear()

    def add_to_filter_cache(self, key: str, tools: list[str]) -> None:
        """Add an entry to the filter cache with size limiting.

        Prevents unbounded memory growth by evicting oldest entries when
        cache exceeds MAX_FILTER_CACHE_SIZE.

        Args:
            key: Cache key (typically message hash)
            tools: List of tool names to cache
        """
        _put_bounded(self.tool_filter_cache, key, tools, MAX_FILTER_CACHE_SIZE)

    # ==================== Memory Abstraction Cache Methods ====================

    def cache_intent(self, query_hash: str, intent: dict) -> None:
        """Cache an intent classification result.

        Args:
            query_hash: Hash of the query
            intent: IntentClassification as dict
        """
        _put_bounded(self.intent_cache, query_hash, intent, self.MAX_INTENT_CACHE_SIZE)

    def get_cached_intent(self, query_hash: str) -> dict | None:
        """Get a cached intent classification.

        Args:
            query_hash: Hash of the query

        Returns:
            Cached IntentClassification as dict, or None if not cached
        """
        return self.intent_cache.get(query_hash)

    def cache_memory_query(self, query_hash: str, result: dict) -> None:
        """Cache a memory query result.

        Args:
            query_hash: Hash of the query
            result: QueryResult as dict
        """
        _put_bounded(self.memory_query_cache, query_hash, result, self.MAX_QUERY_CACHE_SIZE)

    def get_cached_memory_query(self, query_hash: str) -> dict | None:
        """Get a cached memory query result.

        Args:
            query_hash: Hash of the query

        Returns:
            Cached QueryResult as dict, or None if not cached
        """
        return self.memory_query_cache.get(query_hash)

    def clear_memory_caches(self) -> None:
        """Clear all memory-related caches."""
        self.intent_cache.clear()
        self.memory_query_cache.clear()


def _put_bounded(cache: dict, key: str, value: Any, max_size: int) -> None:
    """Insert into an insertion-ordered cache, evicting the oldest entries first."""
    while len(cache) >= max_size:
        del cache[next(iter(cache))]
    cache[key] = value
