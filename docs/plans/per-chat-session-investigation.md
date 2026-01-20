# Per-Chat Session Investigation Report

**Date:** 2026-01-19  
**Issue:** Multiple Cursor chats share the same session ID instead of each having unique sessions

## Executive Summary

The per-chat session feature is **not working** because the MCP protocol's stdio transport (used by Cursor) does not provide a unique chat/conversation identifier. All chats connect to the same MCP server process and appear identical from the server's perspective.

---

## Part 1: MCP Protocol Analysis - Unique Identifiers

### What MCP Provides

| Transport | Session ID Available? | How It Works |
|-----------|----------------------|--------------|
| **Streamable HTTP** | ✅ Yes | Server generates `MCP-Session-Id` header during initialization; client includes it in all subsequent requests |
| **HTTP + SSE** | ✅ Yes | Same as Streamable HTTP |
| **stdio** | ❌ No | No HTTP headers exist; single implicit session per process lifetime |

### Key Finding: stdio Has No Session Identifier

From the MCP specification (2025-11-25):

> "The stdio transport assumes a local subprocess communication model... There is **no built-in support for session IDs** in stdio. Because everything occurs in a single process instance, it implicitly handles one 'session' per invocation."

**Cursor uses stdio transport**, which means:
- No `MCP-Session-Id` header
- No way to distinguish between different chats
- All tool calls appear to come from the same "client"

### What We Tested

```python
# From debug_mcp_roots tool output:
ctx.client_id = None          # Not provided by Cursor
ctx.request_id = 23           # Just an incrementing counter, not chat-specific
ctx.session.list_roots()      # Returns workspace path, same for all chats
```

The only identifier available is the **workspace URI** (`file:///home/daoneill/src/redhat-ai-workflow`), which is identical for all chats in the same Cursor window.

---

## Part 2: Alternative Architectures

### Option A: Explicit Session ID Passing (Recommended)

**Concept:** The AI assistant remembers its session ID and passes it with every tool call.

**Implementation:**
```python
# Tool signature change
async def session_start(ctx: Context, session_id: str = "") -> list[TextContent]:
    """
    If session_id is provided, resume that session.
    If empty, create a new session and return the ID.
    """
    if session_id:
        # Resume existing session
        session = workspace.get_session(session_id)
        if session:
            workspace.set_active_session(session_id)
            return [TextContent(text=f"Resumed session {session_id}")]
    
    # Create new session
    session = workspace.create_session()
    return [TextContent(text=f"Created session {session.session_id}")]

# All other tools would need session_id parameter
async def memory_read(ctx: Context, key: str, session_id: str = "") -> list[TextContent]:
    workspace = await get_workspace(ctx)
    if session_id:
        workspace.set_active_session(session_id)
    # ... rest of implementation
```

**Pros:**
- Works with current MCP/Cursor architecture
- No infrastructure changes needed
- Session isolation is explicit and controllable

**Cons:**
- Requires AI to track and pass session_id on every call
- Adds parameter to many tools
- AI might forget to pass it (though we can add reminders in tool descriptions)

**Effort:** Medium (modify ~20 core tools)

---

### Option B: One MCP Server Per Chat

**Concept:** Cursor spawns a separate MCP server process for each chat.

**Implementation:** Modify `.mcp.json` or use Cursor's MCP extension API to spawn per-chat servers.

```json
{
  "mcpServers": {
    "aa_workflow_chat_1": {
      "command": "bash",
      "args": ["-c", "... --session-id=chat_1"]
    },
    "aa_workflow_chat_2": {
      "command": "bash", 
      "args": ["-c", "... --session-id=chat_2"]
    }
  }
}
```

**Pros:**
- True isolation - each chat has its own process/memory
- No code changes to tools needed

**Cons:**
- Resource intensive (multiple Python processes)
- Requires manual config or Cursor extension to manage
- Tool state not shared (might be desired or not)
- Cursor doesn't support dynamic server spawning per chat

**Effort:** High (requires Cursor extension changes or manual management)

---

### Option C: Request Correlation via Timing/Heuristics

**Concept:** Use timing patterns to guess which requests belong to the same conversation.

**Implementation:**
```python
class ConversationTracker:
    def __init__(self):
        self.conversations = {}  # conversation_id -> last_request_time
        self.request_to_conv = {}  # Maps request patterns to conversations
    
    def get_conversation_id(self, ctx) -> str:
        # Heuristic: requests within 30 seconds are same conversation
        # Use request patterns, tool sequences, etc.
        ...
```

**Pros:**
- No changes to tool signatures
- Transparent to AI

**Cons:**
- Unreliable - heuristics can fail
- Race conditions with parallel chats
- Complex to implement correctly

**Effort:** High, unreliable

---

### Option D: Switch to HTTP Transport

**Concept:** Run MCP server as HTTP service instead of stdio.

**Implementation:**
```json
{
  "mcpServers": {
    "aa_workflow": {
      "url": "http://localhost:8765/mcp",
      "transport": "streamable-http"
    }
  }
}
```

**Pros:**
- Full `MCP-Session-Id` support
- Proper session management per spec
- Can scale horizontally

**Cons:**
- Cursor's HTTP transport support is buggy (known issues with session ID handling)
- More complex deployment (need to run HTTP server)
- Network latency vs stdio

**Effort:** Medium-High (server changes + Cursor config + debugging Cursor bugs)

---

## Part 3: How Other MCP Servers Handle This

### Pattern 1: Accept stdio Limitations (Most Common)

Most MCP servers using stdio simply accept single-session semantics:
- One conversation per process
- State is process-global
- Users restart server to reset state

**Examples:** Most filesystem, git, database MCP servers

### Pattern 2: Stateless Tools

Design tools to be stateless - all context passed in parameters:
```python
async def git_commit(message: str, repo_path: str, branch: str) -> str:
    # No session state needed - everything is in parameters
```

**Examples:** Simple utility MCP servers

### Pattern 3: External State Store

Store state externally (Redis, file, database) keyed by user-provided identifier:
```python
async def save_context(user_id: str, context: dict) -> str:
    redis.set(f"context:{user_id}", json.dumps(context))
```

**Examples:** Production MCP servers (Lambda MCP Server uses DynamoDB)

### Pattern 4: HTTP Transport with Proper Sessions

Use HTTP transport which has native session support:
```typescript
// Server generates session ID on initialize
res.setHeader('MCP-Session-Id', generateUUID());

// Client includes it on all requests
const sessionId = req.headers['mcp-session-id'];
const state = sessionStore.get(sessionId);
```

**Examples:** `example-mcp-server-streamable-http`, production deployments

---

## Recommendation

### Short Term: Option A (Explicit Session ID)

1. Add `session_id` parameter to `session_start`, `session_info`, and key workflow tools
2. Update tool descriptions to remind AI to track and pass session ID
3. Add `session_list` tool to show all sessions (already exists)
4. Add `session_switch(session_id)` tool to change active session

**Changes needed:**
```python
# session_tools.py
async def session_start(ctx: Context, agent: str = "", project: str = "", 
                        name: str = "", session_id: str = "") -> list[TextContent]:
    """
    Start or resume a session.
    
    IMPORTANT: Save the returned session_id and pass it to subsequent 
    session_info() calls to maintain your session identity.
    
    Args:
        session_id: If provided, resume this session instead of creating new one
        ...
    """

# meta_tools.py  
async def session_info(ctx: Context, session_id: str = "") -> list[TextContent]:
    """
    Show session info.
    
    Args:
        session_id: Your session ID (from session_start). If not provided,
                    shows the workspace's most recent active session.
    """
```

### Medium Term: Option D (HTTP Transport)

Once Cursor's HTTP transport bugs are fixed:
1. Add HTTP server mode to our MCP server (already partially exists via `--web`)
2. Implement proper `MCP-Session-Id` handling
3. Switch Cursor config to use HTTP transport

---

## Current Code Analysis

The existing `workspace_state.py` architecture is **correct** for multi-session support:

```python
class WorkspaceState:
    sessions: dict[str, ChatSession]  # Multiple sessions per workspace ✓
    active_session_id: str | None     # Tracks "current" session ✓

class ChatSession:
    session_id: str      # Unique per session ✓
    persona: str         # Per-session persona ✓
    issue_key: str       # Per-session context ✓
```

The problem is **how we identify which session to use**:

```python
# Current (broken): Always uses workspace's active_session_id
session = workspace.get_active_session()  # Same for all chats!

# Fixed: Use explicit session_id parameter
session = workspace.get_session(session_id) if session_id else workspace.get_active_session()
```

---

## Action Items

1. **Immediate:** Add `session_id` parameter to `session_info` tool
2. **Short term:** Add `session_id` to `session_start` for resume capability  
3. **Short term:** Update CLAUDE.md/cursorrules to instruct AI to track session IDs
4. **Medium term:** Evaluate HTTP transport once Cursor fixes bugs
5. **Long term:** Request Cursor add chat identifier to MCP context

---

## References

- [MCP Specification - Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [Cursor Forum - MCP Session Management Bug](https://forum.cursor.com/t/mcp-client-wrong-handling-of-http-not-found-in-session-management-stateful-mcp-server/134781)
- [Example MCP Server with Sessions](https://github.com/yigitkonur/example-mcp-server-streamable-http)
