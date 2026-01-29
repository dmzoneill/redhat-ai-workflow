"""
External Sessions Reader

Reads and analyzes sessions from external AI tools:
- Claude Console (Claude Code CLI)
- Gemini (Google AI Studio exports)

This module enables:
1. Listing available sessions
2. Reading session contents
3. Extracting patterns and context
4. Importing sessions for analysis
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# Claude Code session locations
CLAUDE_CODE_DIR = Path.home() / ".claude"
CLAUDE_CONFIG_DIR = Path.home() / ".config" / "claude-code"

# Gemini import directory (user-specified)
GEMINI_IMPORT_DIR = Path.home() / ".config" / "aa-workflow" / "gemini_sessions"


class ClaudeSession:
    """Represents a Claude Code session."""

    def __init__(self, session_id: str, data: dict):
        self.session_id = session_id
        self.data = data
        self.messages = data.get("messages", [])
        self.created_at = data.get("created_at", "")
        self.updated_at = data.get("updated_at", "")
        self.project_path = data.get("project_path", "")

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def name(self) -> str:
        """Generate a name from the first user message or session ID."""
        for msg in self.messages:
            if msg.get("role") == "user":
                text = msg.get("content", "")[:50]
                return text + "..." if len(msg.get("content", "")) > 50 else text
        return f"Session {self.session_id[:8]}"

    def get_user_messages(self) -> list[str]:
        """Get all user messages."""
        return [msg.get("content", "") for msg in self.messages if msg.get("role") == "user"]

    def get_assistant_messages(self) -> list[str]:
        """Get all assistant messages."""
        return [msg.get("content", "") for msg in self.messages if msg.get("role") == "assistant"]

    def get_tool_calls(self) -> list[dict]:
        """Extract tool calls from the session."""
        tool_calls = []
        for msg in self.messages:
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                # Look for tool call patterns in Claude's output
                # This is a simplified extraction
                if "tool_use" in str(msg):
                    tool_calls.append(msg)
        return tool_calls

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.session_id,
            "name": self.name,
            "source": "claude",
            "message_count": self.message_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_path": self.project_path,
        }


class GeminiSession:
    """Represents a Gemini session (imported from AI Studio)."""

    def __init__(self, session_id: str, data: dict):
        self.session_id = session_id
        self.data = data
        self.messages = data.get("contents", [])
        self.model = data.get("model", "unknown")
        self.created_at = data.get("createTime", "")

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def name(self) -> str:
        """Generate a name from the first user message or session ID."""
        for msg in self.messages:
            if msg.get("role") == "user":
                parts = msg.get("parts", [])
                if parts and isinstance(parts[0], dict):
                    text = parts[0].get("text", "")[:50]
                    return text + "..." if len(parts[0].get("text", "")) > 50 else text
        return f"Gemini {self.session_id[:8]}"

    def get_user_messages(self) -> list[str]:
        """Get all user messages."""
        messages = []
        for msg in self.messages:
            if msg.get("role") == "user":
                parts = msg.get("parts", [])
                for part in parts:
                    if isinstance(part, dict) and "text" in part:
                        messages.append(part["text"])
        return messages

    def get_model_messages(self) -> list[str]:
        """Get all model messages."""
        messages = []
        for msg in self.messages:
            if msg.get("role") == "model":
                parts = msg.get("parts", [])
                for part in parts:
                    if isinstance(part, dict) and "text" in part:
                        messages.append(part["text"])
        return messages

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.session_id,
            "name": self.name,
            "source": "gemini",
            "model": self.model,
            "message_count": self.message_count,
            "created_at": self.created_at,
        }


def list_claude_sessions() -> list[ClaudeSession]:
    """
    List all available Claude Code sessions.

    Returns:
        List of ClaudeSession objects
    """
    sessions = []

    # Check both possible locations
    for base_dir in [CLAUDE_CODE_DIR, CLAUDE_CONFIG_DIR]:
        if not base_dir.exists():
            continue

        # Look for session files (JSONL format)
        projects_dir = base_dir / "projects"
        if projects_dir.exists():
            for project_dir in projects_dir.iterdir():
                if project_dir.is_dir():
                    for session_file in project_dir.glob("*.jsonl"):
                        try:
                            session = _load_claude_session(session_file)
                            if session:
                                sessions.append(session)
                        except Exception as e:
                            print(f"Error loading {session_file}: {e}")

    # Sort by updated_at descending
    sessions.sort(key=lambda s: s.updated_at, reverse=True)

    return sessions


def _load_claude_session(session_file: Path) -> Optional[ClaudeSession]:
    """Load a Claude session from a JSONL file."""
    messages = []
    metadata = {}

    try:
        with open(session_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "message":
                        messages.append(entry)
                    elif entry.get("type") == "metadata":
                        metadata = entry
                except json.JSONDecodeError:
                    continue

        if not messages:
            return None

        session_id = session_file.stem
        data = {
            "messages": messages,
            "created_at": metadata.get("created_at", ""),
            "updated_at": metadata.get("updated_at", ""),
            "project_path": str(session_file.parent),
        }

        return ClaudeSession(session_id, data)
    except IOError:
        return None


def list_gemini_sessions() -> list[GeminiSession]:
    """
    List all imported Gemini sessions.

    Returns:
        List of GeminiSession objects
    """
    sessions = []

    if not GEMINI_IMPORT_DIR.exists():
        return sessions

    for session_file in GEMINI_IMPORT_DIR.glob("*.json"):
        try:
            data = json.loads(session_file.read_text())
            session_id = session_file.stem
            sessions.append(GeminiSession(session_id, data))
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading {session_file}: {e}")

    # Sort by created_at descending
    sessions.sort(key=lambda s: s.created_at, reverse=True)

    return sessions


def import_gemini_session(file_path: str) -> Optional[GeminiSession]:
    """
    Import a Gemini session from an AI Studio export file.

    Args:
        file_path: Path to the exported JSON file

    Returns:
        The imported GeminiSession, or None if failed
    """
    source_path = Path(file_path)
    if not source_path.exists():
        return None

    try:
        data = json.loads(source_path.read_text())

        # Generate a session ID
        session_id = f"gemini_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Ensure import directory exists
        GEMINI_IMPORT_DIR.mkdir(parents=True, exist_ok=True)

        # Copy to import directory
        dest_path = GEMINI_IMPORT_DIR / f"{session_id}.json"
        dest_path.write_text(json.dumps(data, indent=2))

        return GeminiSession(session_id, data)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error importing Gemini session: {e}")
        return None


def get_claude_session(session_id: str) -> Optional[ClaudeSession]:
    """
    Get a specific Claude session by ID.

    Args:
        session_id: The session ID

    Returns:
        The ClaudeSession, or None if not found
    """
    for session in list_claude_sessions():
        if session.session_id == session_id:
            return session
    return None


def get_gemini_session(session_id: str) -> Optional[GeminiSession]:
    """
    Get a specific Gemini session by ID.

    Args:
        session_id: The session ID

    Returns:
        The GeminiSession, or None if not found
    """
    session_file = GEMINI_IMPORT_DIR / f"{session_id}.json"
    if not session_file.exists():
        return None

    try:
        data = json.loads(session_file.read_text())
        return GeminiSession(session_id, data)
    except (json.JSONDecodeError, IOError):
        return None


def extract_patterns(session: ClaudeSession | GeminiSession) -> dict:
    """
    Extract useful patterns from a session for learning.

    Args:
        session: The session to analyze

    Returns:
        Dict with extracted patterns
    """
    patterns = {
        "successful_prompts": [],
        "tool_usage": [],
        "common_phrases": [],
        "context_patterns": [],
    }

    if isinstance(session, ClaudeSession):
        user_messages = session.get_user_messages()
        assistant_messages = session.get_assistant_messages()
    else:
        user_messages = session.get_user_messages()
        assistant_messages = session.get_model_messages()

    # Extract successful prompts (user messages that got good responses)
    for i, user_msg in enumerate(user_messages):
        if i < len(assistant_messages):
            # Simple heuristic: longer responses = more helpful
            if len(assistant_messages[i]) > 500:
                patterns["successful_prompts"].append(user_msg[:200])

    # Extract tool usage patterns (for Claude)
    if isinstance(session, ClaudeSession):
        tool_calls = session.get_tool_calls()
        patterns["tool_usage"] = [str(tc)[:100] for tc in tool_calls[:10]]

    return patterns


def analyze_session(session_id: str, source: str = "claude") -> dict:
    """
    Analyze a session and return insights.

    Args:
        session_id: The session ID
        source: "claude" or "gemini"

    Returns:
        Analysis results
    """
    if source == "claude":
        session = get_claude_session(session_id)
    else:
        session = get_gemini_session(session_id)

    if not session:
        return {"error": "Session not found"}

    patterns = extract_patterns(session)

    return {
        "session": session.to_dict(),
        "patterns": patterns,
        "summary": {
            "total_messages": session.message_count,
            "successful_prompts_found": len(patterns["successful_prompts"]),
            "tool_calls_found": len(patterns["tool_usage"]),
        },
    }


# CLI interface for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: external_sessions.py <command> [args]")
        print("Commands: list-claude, list-gemini, analyze, import")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list-claude":
        sessions = list_claude_sessions()
        for s in sessions:
            print(json.dumps(s.to_dict(), indent=2))

    elif command == "list-gemini":
        sessions = list_gemini_sessions()
        for s in sessions:
            print(json.dumps(s.to_dict(), indent=2))

    elif command == "analyze" and len(sys.argv) >= 4:
        session_id = sys.argv[2]
        source = sys.argv[3]
        result = analyze_session(session_id, source)
        print(json.dumps(result, indent=2))

    elif command == "import" and len(sys.argv) >= 3:
        file_path = sys.argv[2]
        session = import_gemini_session(file_path)
        if session:
            print(f"Imported: {session.session_id}")
        else:
            print("Import failed")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
