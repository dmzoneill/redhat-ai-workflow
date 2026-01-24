# Skill Confirmation System - Detailed Plan

## Overview

This document outlines the design for adding user confirmation capabilities to the skill execution engine. The goal is to allow skills to pause execution, request user input, and optionally involve Claude (the AI) in interpreting errors and suggesting fixes.

## Problem Statement

### Current Limitations

1. **Skills run to completion** - Once `skill_run()` is called, the entire skill executes without pause
2. **No user confirmation for destructive actions** - Skills like `release_aa_backend_prod` immediately start creating MRs
3. **Error recovery is limited** - `@auto_heal` only handles auth/network errors with fixed patterns
4. **AI is not involved in remediation** - Claude sees the output after execution, not during

### Current Auto-Heal Flow (No AI Involvement)

```
Tool fails with "unauthorized" error
    ↓
@auto_heal decorator detects pattern (regex match)
    ↓
Runs kube_login() automatically
    ↓
Retries tool
    ↓
Claude sees final result
```

The AI is **not consulted** during this process - it's purely pattern-based.

## Proposed Solution

### Three-Layer Confirmation System

```
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 1: Learned Solutions (No Prompt)                              │
│ - Check memory for previously learned preferences                   │
│ - Auto-proceed if user said "always proceed" before                 │
│ - Auto-apply known fixes from memory                                │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (if no learned solution)
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 2: AI-Assisted Decision (Claude Interprets)                   │
│ - Present error/confirmation context to Claude                      │
│ - Claude analyzes and suggests action                               │
│ - Claude can propose code fixes for tool errors                     │
│ - User confirms Claude's suggestion                                 │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (if AI unavailable or user wants manual)
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 3: Direct User Prompt (Fallback)                              │
│ - VS Code extension panel                                           │
│ - Zenity/desktop dialog                                             │
│ - CLI input (if TTY available)                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## How Claude Helps During Execution

### Scenario 1: Confirmation Before Destructive Action

**Skill step:**
```yaml
- name: confirm_release
  confirm:
    message: |
      Ready to release {{ commit_sha }} to production.
      This will create an app-interface MR.
    options:
      - label: "Proceed"
        value: "proceed"
      - label: "Cancel"
        value: "cancel"
    ai_assist: true  # Ask Claude to review before prompting
  output: user_confirmation
```

**Flow with AI assistance:**

```
1. Skill reaches confirm: step
    ↓
2. Engine pauses execution
    ↓
3. Engine sends context to Claude via MCP response:
   {
     "status": "awaiting_confirmation",
     "context": {
       "skill": "release_aa_backend_prod",
       "step": "confirm_release",
       "message": "Ready to release abc123 to production...",
       "variables": {
         "commit_sha": "abc123",
         "quay_image_exists": true,
         "staging_tests_passed": true
       }
     },
     "question": "Should I proceed with this release?"
   }
    ↓
4. Claude receives this and can:
   - Review the context (commit SHA, test status, etc.)
   - Ask the user clarifying questions
   - Recommend proceeding or not
   - Explain risks
    ↓
5. User tells Claude "yes, proceed" or "no, cancel"
    ↓
6. Claude calls skill_continue() with the decision
    ↓
7. Skill resumes with user's choice
```

### Scenario 2: Error Recovery with AI Analysis

**When a tool fails with an unknown error:**

```
1. Tool fails with error: "manifest unknown: abc123"
    ↓
2. @auto_heal checks patterns - no match for "manifest unknown"
    ↓
3. Engine checks memory for known fixes - none found
    ↓
4. Engine pauses and sends to Claude:
   {
     "status": "error_recovery_needed",
     "context": {
       "skill": "test_mr_ephemeral",
       "step": "deploy_image",
       "tool": "bonfire_deploy",
       "error": "manifest unknown: abc123",
       "args": {"image_tag": "abc123", "namespace": "ephemeral-xxx"},
       "recent_steps": [...],
       "tool_source_hint": "tool_modules/aa_bonfire/src/tools_basic.py"
     },
     "question": "This tool failed. Can you help diagnose and fix it?"
   }
    ↓
5. Claude analyzes:
   - "The error 'manifest unknown' means the image tag doesn't exist in Quay"
   - "The tag 'abc123' is only 7 characters - Quay needs full 40-char SHA"
   - "I can see the tool is using inputs.commit_sha directly"
    ↓
6. Claude proposes fix:
   - "The issue is the short SHA. Let me check if there's a full SHA available..."
   - Calls git_show or quay_list_tags to find full SHA
   - "Found full SHA: abc123def456... I'll retry with that"
    ↓
7. Claude calls skill_retry_step() with corrected args:
   {
     "step": "deploy_image",
     "args": {"image_tag": "abc123def456789..."}
   }
    ↓
8. If successful, Claude can optionally fix the tool:
   - "This is a common issue. Should I fix the tool to auto-expand short SHAs?"
   - User: "Yes"
   - Claude calls debug_tool() and applies fix
   - Logs fix to memory for future reference
```

### Scenario 3: Interactive Compute Block Error

**When a compute block has a Python error:**

```
1. Compute block fails: "'dict' object has no attribute 'issue_key'"
    ↓
2. Engine detects error pattern (dict attribute access)
    ↓
3. Engine can auto-fix simple cases:
   - inputs.issue_key → inputs.get("issue_key")
    ↓
4. For complex errors, send to Claude:
   {
     "status": "compute_error",
     "context": {
       "code": "result = inputs.issue_key.upper()",
       "error": "'dict' object has no attribute 'issue_key'",
       "available_variables": ["inputs", "memory", "resolved_repo"],
       "inputs_keys": ["issue_key", "repo"]
     },
     "question": "This compute block failed. What's wrong?"
   }
    ↓
5. Claude analyzes:
   - "The code uses inputs.issue_key but inputs is a dict"
   - "Should be inputs.get('issue_key', '').upper()"
   - "Also should handle None case"
    ↓
6. Claude proposes fix and user confirms
    ↓
7. Engine retries with fixed code
    ↓
8. Claude optionally updates the skill YAML permanently
```

## Implementation Details

### New Step Type: `confirm:`

```yaml
# Skill YAML syntax
steps:
  - name: confirm_action
    confirm:
      title: "Confirmation Required"
      message: |
        {{ template_variables_supported }}
      options:
        - label: "Proceed"
          value: "proceed"
          description: "Continue with the action"
        - label: "Cancel"
          value: "cancel"
          description: "Abort the skill"
      ai_assist: true          # Optional: involve Claude
      timeout: 300             # Seconds to wait (default: 300)
      default: "cancel"        # Default if timeout
      learn_preference: true   # Remember user's choice
    output: confirmation_result
```

### Skill Engine Changes

**New file: `tool_modules/aa_workflow/src/confirmation_engine.py`**

```python
"""
Confirmation Engine - Multi-backend user confirmation system.

Provides:
- ConfirmationEngine: Dispatches confirmation requests to backends
- Supports: VS Code extension, Zenity/desktop, CLI, AI-assisted
- Memory-based learning to reduce repeated prompts
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# File paths for IPC with VS Code extension
CONFIG_DIR = Path.home() / ".config" / "aa-workflow"
CONFIRMATION_REQUEST_FILE = CONFIG_DIR / "confirmation_request.json"
CONFIRMATION_RESPONSE_DIR = CONFIG_DIR / "confirmation_responses"


class ConfirmationBackend(ABC):
    """Base class for confirmation backends."""

    @abstractmethod
    async def request(
        self,
        execution_id: str,
        title: str,
        message: str,
        options: list[dict],
        context: dict | None = None,
        timeout: int = 300,
    ) -> dict | None:
        """
        Request user confirmation.

        Args:
            execution_id: Unique ID for this confirmation request
            title: Dialog title
            message: Message to display
            options: List of {label, value, description} dicts
            context: Additional context for AI-assisted mode
            timeout: Seconds to wait for response

        Returns:
            {
                "selected": "value",
                "source": "vscode|zenity|cli|ai",
                "ai_analysis": "..." (if AI-assisted)
            }
            or None if cancelled/timeout
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available."""
        pass


class VSCodeConfirmationBackend(ConfirmationBackend):
    """
    VS Code extension confirmation via file-based IPC.

    Flow:
    1. Write request to ~/.config/aa-workflow/confirmation_request.json
    2. VS Code extension watches this file
    3. Extension shows QuickPick or panel dialog
    4. Extension writes response to ~/.config/aa-workflow/confirmation_responses/{execution_id}.json
    5. We read the response
    """

    def is_available(self) -> bool:
        """Check if VS Code extension is likely running."""
        # Check if the config dir exists (extension creates it)
        return CONFIG_DIR.exists()

    async def request(
        self,
        execution_id: str,
        title: str,
        message: str,
        options: list[dict],
        context: dict | None = None,
        timeout: int = 300,
    ) -> dict | None:
        # Ensure directories exist
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIRMATION_RESPONSE_DIR.mkdir(parents=True, exist_ok=True)

        # Write request
        request = {
            "execution_id": execution_id,
            "title": title,
            "message": message,
            "options": options,
            "context": context,
            "timestamp": datetime.now().isoformat(),
            "timeout": timeout,
        }

        with open(CONFIRMATION_REQUEST_FILE, "w") as f:
            json.dump(request, f, indent=2)

        # Wait for response
        response_file = CONFIRMATION_RESPONSE_DIR / f"{execution_id}.json"
        start_time = asyncio.get_event_loop().time()

        while True:
            if response_file.exists():
                try:
                    with open(response_file) as f:
                        response = json.load(f)
                    # Clean up
                    response_file.unlink()
                    return response
                except Exception as e:
                    logger.error(f"Error reading response: {e}")
                    return None

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                logger.warning(f"Confirmation timeout after {timeout}s")
                return None

            await asyncio.sleep(0.5)


class ZenityConfirmationBackend(ConfirmationBackend):
    """
    Linux desktop dialog via Zenity.

    Falls back to kdialog on KDE systems.
    """

    def __init__(self):
        self._zenity_available: bool | None = None
        self._kdialog_available: bool | None = None

    def is_available(self) -> bool:
        """Check if Zenity or kdialog is available."""
        import shutil

        if self._zenity_available is None:
            self._zenity_available = shutil.which("zenity") is not None
        if self._kdialog_available is None:
            self._kdialog_available = shutil.which("kdialog") is not None

        # Also check DISPLAY is set (X11/Wayland)
        import os
        has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

        return has_display and (self._zenity_available or self._kdialog_available)

    async def request(
        self,
        execution_id: str,
        title: str,
        message: str,
        options: list[dict],
        context: dict | None = None,
        timeout: int = 300,
    ) -> dict | None:
        import shutil

        if shutil.which("zenity"):
            return await self._request_zenity(title, message, options, timeout)
        elif shutil.which("kdialog"):
            return await self._request_kdialog(title, message, options, timeout)
        return None

    async def _request_zenity(
        self,
        title: str,
        message: str,
        options: list[dict],
        timeout: int,
    ) -> dict | None:
        """Show Zenity list dialog."""
        cmd = [
            "zenity",
            "--list",
            "--title", title,
            "--text", message,
            "--column", "Option",
            "--column", "Description",
            "--width", "500",
            "--height", "400",
            "--timeout", str(timeout),
        ]

        for opt in options:
            cmd.extend([opt["label"], opt.get("description", "")])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode == 0:
            selected_label = stdout.decode().strip()
            # Find the value for this label
            for opt in options:
                if opt["label"] == selected_label:
                    return {"selected": opt["value"], "source": "zenity"}

        return None

    async def _request_kdialog(
        self,
        title: str,
        message: str,
        options: list[dict],
        timeout: int,
    ) -> dict | None:
        """Show KDialog menu."""
        cmd = [
            "kdialog",
            "--title", title,
            "--menu", message,
        ]

        for opt in options:
            cmd.extend([opt["value"], opt["label"]])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode == 0:
            selected_value = stdout.decode().strip()
            return {"selected": selected_value, "source": "kdialog"}

        return None


class CLIConfirmationBackend(ConfirmationBackend):
    """
    CLI confirmation via stdin.

    Only works if stdin is a TTY.
    """

    def is_available(self) -> bool:
        """Check if stdin is a TTY."""
        import sys
        return sys.stdin.isatty()

    async def request(
        self,
        execution_id: str,
        title: str,
        message: str,
        options: list[dict],
        context: dict | None = None,
        timeout: int = 300,
    ) -> dict | None:
        import sys

        if not sys.stdin.isatty():
            return None

        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}")
        print(f"\n{message}\n")

        for i, opt in enumerate(options, 1):
            desc = f" - {opt['description']}" if opt.get("description") else ""
            print(f"  {i}. {opt['label']}{desc}")

        print()

        while True:
            try:
                choice = input(f"Enter choice (1-{len(options)}): ")
                choice_num = int(choice)
                if 1 <= choice_num <= len(options):
                    selected = options[choice_num - 1]
                    return {"selected": selected["value"], "source": "cli"}
                print(f"Invalid choice. Please enter 1-{len(options)}")
            except (ValueError, KeyboardInterrupt, EOFError):
                return None


class AIAssistedConfirmationBackend(ConfirmationBackend):
    """
    AI-assisted confirmation that returns control to Claude.

    Instead of prompting the user directly, this backend returns
    a special response that tells the skill engine to pause and
    return context to Claude for analysis.
    """

    def is_available(self) -> bool:
        """Always available - it's a passthrough to Claude."""
        return True

    async def request(
        self,
        execution_id: str,
        title: str,
        message: str,
        options: list[dict],
        context: dict | None = None,
        timeout: int = 300,
    ) -> dict | None:
        # This backend doesn't actually prompt - it signals
        # the skill engine to return control to Claude
        return {
            "selected": "__AI_ASSIST__",
            "source": "ai",
            "context": context,
            "message": message,
            "options": options,
        }


class ConfirmationEngine:
    """
    Multi-backend confirmation dispatcher.

    Tries backends in order until one succeeds:
    1. Memory (learned preferences)
    2. AI-assisted (if enabled)
    3. VS Code extension
    4. Zenity/desktop
    5. CLI
    """

    def __init__(self, memory_helper=None):
        self.memory = memory_helper
        self.backends = [
            VSCodeConfirmationBackend(),
            ZenityConfirmationBackend(),
            CLIConfirmationBackend(),
        ]
        self.ai_backend = AIAssistedConfirmationBackend()

    async def request_confirmation(
        self,
        execution_id: str,
        skill_name: str,
        step_name: str,
        title: str,
        message: str,
        options: list[dict],
        context: dict | None = None,
        ai_assist: bool = False,
        learn_preference: bool = True,
        timeout: int = 300,
    ) -> dict | None:
        """
        Request user confirmation.

        Args:
            execution_id: Unique execution ID
            skill_name: Name of the skill
            step_name: Name of the confirmation step
            title: Dialog title
            message: Message to display
            options: List of options
            context: Additional context for AI
            ai_assist: Whether to involve Claude
            learn_preference: Whether to remember user's choice
            timeout: Seconds to wait

        Returns:
            Response dict or None
        """
        confirm_key = f"{skill_name}:{step_name}"

        # 1. Check memory for learned preference
        if self.memory and learn_preference:
            learned = self._check_learned_preference(confirm_key)
            if learned:
                logger.info(f"Using learned preference for {confirm_key}: {learned}")
                return {
                    "selected": learned["default_choice"],
                    "source": "memory",
                    "learned": True,
                }

        # 2. If AI-assist enabled, return control to Claude
        if ai_assist:
            return await self.ai_backend.request(
                execution_id, title, message, options, context, timeout
            )

        # 3. Try each backend
        for backend in self.backends:
            if not backend.is_available():
                continue

            try:
                result = await backend.request(
                    execution_id, title, message, options, context, timeout
                )
                if result:
                    # Learn from this choice if requested
                    if learn_preference and result.get("selected") == "__ALWAYS__":
                        self._save_learned_preference(confirm_key, options[0]["value"])
                        result["selected"] = options[0]["value"]

                    return result
            except Exception as e:
                logger.warning(f"Backend {backend.__class__.__name__} failed: {e}")
                continue

        logger.error("All confirmation backends failed")
        return None

    def _check_learned_preference(self, confirm_key: str) -> dict | None:
        """Check memory for a learned preference."""
        if not self.memory:
            return None

        try:
            learned = self.memory.read(f"learned/confirmations")
            if learned and confirm_key in learned:
                pref = learned[confirm_key]
                if pref.get("auto_proceed"):
                    return pref
        except Exception:
            pass

        return None

    def _save_learned_preference(self, confirm_key: str, default_choice: str) -> None:
        """Save a learned preference to memory."""
        if not self.memory:
            return

        try:
            learned = self.memory.read("learned/confirmations") or {}
            learned[confirm_key] = {
                "auto_proceed": True,
                "default_choice": default_choice,
                "learned_at": datetime.now().isoformat(),
            }
            self.memory.write("learned/confirmations", learned)
            logger.info(f"Saved learned preference: {confirm_key} -> {default_choice}")
        except Exception as e:
            logger.warning(f"Failed to save learned preference: {e}")
```

### Skill Engine Integration

**Changes to `tool_modules/aa_workflow/src/skill_engine.py`:**

```python
# Add to imports
from .confirmation_engine import ConfirmationEngine

# Add to SkillExecutor.__init__
self.confirmation_engine = ConfirmationEngine(memory_helper=self._get_memory_helper())

# Add new method to handle confirm: steps
async def _process_confirm_step(
    self,
    step: dict,
    step_num: int,
    step_name: str,
    output_lines: list[str],
) -> bool:
    """
    Process a confirm: step.

    Returns:
        True to continue execution, False to abort
    """
    confirm_config = step["confirm"]

    # Template the message
    message = self._template(confirm_config.get("message", ""))
    title = confirm_config.get("title", "Confirmation Required")
    options = confirm_config.get("options", [
        {"label": "Proceed", "value": "proceed"},
        {"label": "Cancel", "value": "cancel"},
    ])

    # Add "Always proceed" option if learning is enabled
    if confirm_config.get("learn_preference", True):
        options = options + [
            {"label": "Always proceed (remember)", "value": "__ALWAYS__"}
        ]

    output_lines.append(f"⏸️ **Step {step_num}: {step_name}** (confirmation)")
    output_lines.append(f"   Awaiting user confirmation...")

    # Build context for AI-assisted mode
    context = {
        "skill_name": self.skill.get("name"),
        "step_name": step_name,
        "variables": {k: str(v)[:200] for k, v in self.context.items()},
        "previous_steps": self.step_results[-5:],
    }

    # Request confirmation
    result = await self.confirmation_engine.request_confirmation(
        execution_id=getattr(self, 'execution_id', 'unknown'),
        skill_name=self.skill.get("name", "unknown"),
        step_name=step_name,
        title=title,
        message=message,
        options=options,
        context=context,
        ai_assist=confirm_config.get("ai_assist", False),
        learn_preference=confirm_config.get("learn_preference", True),
        timeout=confirm_config.get("timeout", 300),
    )

    if result is None:
        output_lines.append("   ❌ Confirmation cancelled or timed out")
        return False

    # Handle AI-assisted mode
    if result.get("selected") == "__AI_ASSIST__":
        # Return special status to skill_run caller
        # This will be handled by the MCP tool to return control to Claude
        self._ai_assist_pending = {
            "type": "confirmation",
            "step": step_name,
            "message": message,
            "options": options,
            "context": context,
        }
        output_lines.append("   🤖 Returning to Claude for analysis...")
        return False  # Pause execution

    selected = result.get("selected")
    source = result.get("source", "unknown")

    output_lines.append(f"   ✅ User selected: {selected} (via {source})")

    # Store result
    output_name = step.get("output", step_name)
    self.context[output_name] = selected

    # Check if user cancelled
    if selected == "cancel":
        output_lines.append("   ⛔ User cancelled - aborting skill")
        return False

    return True

# Modify execute() to handle confirm: steps
async def execute(self) -> str:
    # ... existing code ...

    for step in self.skill.get("steps", []):
        # ... existing condition checks ...

        if "confirm" in step:
            should_continue = await self._process_confirm_step(
                step, step_num, step_name, output_lines
            )
            if not should_continue:
                if hasattr(self, '_ai_assist_pending'):
                    # Return special response for AI-assisted mode
                    return self._format_ai_assist_response(output_lines)
                break

        # ... rest of existing step handling ...
```

### VS Code Extension Changes

**New file: `extensions/aa_workflow_vscode/src/confirmationHandler.ts`**

```typescript
/**
 * Confirmation Handler
 *
 * Watches for confirmation requests from the MCP server and shows
 * VS Code dialogs or Command Center panels.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";

const CONFIG_DIR = path.join(os.homedir(), ".config", "aa-workflow");
const REQUEST_FILE = path.join(CONFIG_DIR, "confirmation_request.json");
const RESPONSE_DIR = path.join(CONFIG_DIR, "confirmation_responses");

interface ConfirmationRequest {
  execution_id: string;
  title: string;
  message: string;
  options: Array<{
    label: string;
    value: string;
    description?: string;
  }>;
  context?: any;
  timestamp: string;
  timeout: number;
}

export class ConfirmationHandler {
  private _watcher: fs.FSWatcher | undefined;
  private _lastProcessed: string = "";
  private _disposables: vscode.Disposable[] = [];

  constructor() {
    // Ensure directories exist
    if (!fs.existsSync(CONFIG_DIR)) {
      fs.mkdirSync(CONFIG_DIR, { recursive: true });
    }
    if (!fs.existsSync(RESPONSE_DIR)) {
      fs.mkdirSync(RESPONSE_DIR, { recursive: true });
    }
  }

  public start(): void {
    // Watch for confirmation requests
    try {
      this._watcher = fs.watch(CONFIG_DIR, (eventType, filename) => {
        if (filename === "confirmation_request.json") {
          this._onRequestFile();
        }
      });
    } catch (e) {
      console.error("Failed to start confirmation watcher:", e);
    }
  }

  private async _onRequestFile(): Promise<void> {
    try {
      if (!fs.existsSync(REQUEST_FILE)) {
        return;
      }

      const content = fs.readFileSync(REQUEST_FILE, "utf-8");
      const request: ConfirmationRequest = JSON.parse(content);

      // Don't process the same request twice
      if (request.timestamp === this._lastProcessed) {
        return;
      }
      this._lastProcessed = request.timestamp;

      // Show confirmation dialog
      await this._showConfirmation(request);
    } catch (e) {
      console.error("Error processing confirmation request:", e);
    }
  }

  private async _showConfirmation(request: ConfirmationRequest): Promise<void> {
    // Build QuickPick items
    const items = request.options.map((opt) => ({
      label: opt.label,
      description: opt.description,
      value: opt.value,
    }));

    // Show QuickPick
    const selected = await vscode.window.showQuickPick(items, {
      title: request.title,
      placeHolder: request.message.split("\n")[0], // First line as placeholder
      ignoreFocusOut: true, // Don't dismiss on focus loss
    });

    // Write response
    const response = {
      execution_id: request.execution_id,
      selected: selected?.value || null,
      source: "vscode",
      timestamp: new Date().toISOString(),
    };

    const responseFile = path.join(RESPONSE_DIR, `${request.execution_id}.json`);
    fs.writeFileSync(responseFile, JSON.stringify(response, null, 2));

    // Clean up request file
    try {
      fs.unlinkSync(REQUEST_FILE);
    } catch {
      // Ignore
    }
  }

  public dispose(): void {
    if (this._watcher) {
      this._watcher.close();
    }
    this._disposables.forEach((d) => d.dispose());
  }
}

// Registration
let handler: ConfirmationHandler | undefined;

export function registerConfirmationHandler(
  context: vscode.ExtensionContext
): ConfirmationHandler {
  handler = new ConfirmationHandler();
  handler.start();

  context.subscriptions.push({
    dispose: () => handler?.dispose(),
  });

  return handler;
}
```

### MCP Tool Changes for AI-Assisted Mode

**Changes to `skill_run` tool response:**

```python
# When skill pauses for AI-assisted confirmation
async def _skill_run_impl(...):
    # ... existing code ...

    result = await executor.execute()

    # Check if skill is paused for AI assistance
    if hasattr(executor, '_ai_assist_pending'):
        pending = executor._ai_assist_pending

        # Return special response that Claude can interpret
        return [TextContent(type="text", text=f"""
## ⏸️ Skill Paused - Confirmation Required

**Skill:** {executor.skill.get('name')}
**Step:** {pending['step']}

### Message
{pending['message']}

### Options
{chr(10).join(f"- **{opt['label']}**: {opt.get('description', '')}" for opt in pending['options'])}

### Context
```json
{json.dumps(pending['context'], indent=2)[:1000]}
```

---

**To continue, call:**
```python
skill_continue("{executor.execution_id}", choice="proceed")  # or "cancel"
```

Or tell me what you'd like to do and I'll help decide.
""")]

    # Normal completion
    return [TextContent(type="text", text=result)]
```

**New tool: `skill_continue`**

```python
@registry.tool()
async def skill_continue(
    execution_id: str,
    choice: str,
    reason: str = "",
) -> list[TextContent]:
    """
    Continue a paused skill execution.

    Use this after a skill pauses for confirmation.

    Args:
        execution_id: The execution ID from the paused skill
        choice: The selected option value (e.g., "proceed", "cancel")
        reason: Optional reason for the choice (for logging)

    Returns:
        Skill execution result
    """
    # Load saved execution state
    state_file = CONFIG_DIR / "paused_executions" / f"{execution_id}.json"
    if not state_file.exists():
        return [TextContent(type="text", text=f"❌ No paused execution found: {execution_id}")]

    state = json.loads(state_file.read_text())

    # Inject the user's choice
    state["confirmation_result"] = {
        "selected": choice,
        "source": "ai",
        "reason": reason,
    }

    # Resume execution
    executor = SkillExecutor.from_saved_state(state)
    result = await executor.resume()

    # Clean up
    state_file.unlink()

    return [TextContent(type="text", text=result)]
```

## Skills That Need Confirmation

### High Priority (Destructive/Production)

| Skill | Action | Confirmation Point |
|-------|--------|-------------------|
| `release_aa_backend_prod` | Creates prod MR | Before creating app-interface MR |
| `scale_deployment` | Changes replicas | Before scaling (especially prod) |
| `rollout_restart` | Restarts pods | Before restart |
| `hotfix` | Emergency changes | Before any changes |
| `cleanup_branches` | Deletes branches | Before deletion (already has dry_run) |

### Medium Priority (Reversible but Impactful)

| Skill | Action | Confirmation Point |
|-------|--------|-------------------|
| `close_issue` | Closes Jira | Before closing |
| `close_mr` | Closes MR | Before closing |
| `silence_alert` | Silences alerts | Before silencing |
| `cancel_pipeline` | Cancels CI | Before cancelling |

### Example: Updated `release_aa_backend_prod.yaml`

```yaml
steps:
  # ... validation steps ...

  - name: show_release_plan
    description: "Summarize what will be released"
    compute: |
      result = {
        "sha": inputs.commit_sha,
        "image_verified": quay_check.get("exists", False),
        "staging_sha": current_staging.get("sha", "unknown"),
        "components": ["main"] + (["billing"] if inputs.include_billing else []),
      }
    output: release_plan

  - name: confirm_release
    description: "Get user confirmation before proceeding"
    confirm:
      title: "🚀 Production Release Confirmation"
      message: |
        ## Release Summary

        **Commit SHA:** `{{ release_plan.sha }}`
        **Image Verified:** {{ "✅ Yes" if release_plan.image_verified else "❌ No" }}
        **Current Staging:** `{{ release_plan.staging_sha }}`
        **Components:** {{ release_plan.components | join(", ") }}

        This will create an app-interface MR to promote to production.

        {% if release_known_issues.has_known_issues %}
        ⚠️ **Known Issues:**
        {% for issue in release_known_issues.issues %}
        - {{ issue.pattern }}
        {% endfor %}
        {% endif %}
      options:
        - label: "Proceed with Release"
          value: "proceed"
          description: "Create app-interface MR for production"
        - label: "Cancel"
          value: "cancel"
          description: "Abort the release"
      ai_assist: true
      timeout: 600
    output: release_confirmation

  - name: create_appinterface_mr
    condition: "release_confirmation == 'proceed'"
    # ... rest of release steps ...
```

## Memory Schema for Learned Confirmations

**File: `memory/learned/confirmations.yaml`**

```yaml
# Learned user preferences for skill confirmations
# Auto-generated - do not edit manually

release_aa_backend_prod:confirm_release:
  auto_proceed: false  # User wants to be asked every time
  last_choice: "proceed"
  choice_history:
    - choice: "proceed"
      timestamp: "2024-01-15T10:30:00"
      context: "SHA abc123"
    - choice: "proceed"
      timestamp: "2024-01-14T14:20:00"
      context: "SHA def456"

cleanup_branches:confirm_delete:
  auto_proceed: true  # User said "always proceed"
  default_choice: "proceed"
  learned_at: "2024-01-10T09:00:00"

scale_deployment:confirm_scale:
  auto_proceed: false
  # Different behavior based on environment
  environment_rules:
    stage: "auto_proceed"
    production: "always_ask"
```

## Testing Plan

### Unit Tests

1. **ConfirmationEngine tests**
   - Test each backend in isolation
   - Test fallback chain
   - Test memory-based learning
   - Test timeout handling

2. **Skill engine integration tests**
   - Test `confirm:` step parsing
   - Test AI-assisted mode response format
   - Test `skill_continue` resumption

### Integration Tests

1. **VS Code extension tests**
   - Test file watcher
   - Test QuickPick dialog
   - Test response writing

2. **End-to-end tests**
   - Run skill with confirmation in Cursor
   - Verify Claude receives context
   - Verify skill resumes correctly

### Manual Testing

1. **Zenity backend**
   - Test on GNOME
   - Test on KDE (kdialog)
   - Test without display (should fall back)

2. **AI-assisted mode**
   - Test Claude's analysis quality
   - Test fix suggestions
   - Test learning from fixes

## Implementation Status (Updated 2026-01-23)

### Completed: WebSocket Real-Time Updates

We implemented a WebSocket-based system for real-time skill updates instead of file polling:

| Component | File | Status |
|-----------|------|--------|
| WebSocket Server | `server/websocket_server.py` | ✅ Complete |
| Skill Engine Integration | `tool_modules/aa_workflow/src/skill_engine.py` | ✅ Complete |
| MCP Server Startup | `server/main.py` | ✅ Complete |
| VS Code WebSocket Client | `extensions/aa_workflow_vscode/src/skillWebSocket.ts` | ✅ Complete |
| Toast UI Component | `extensions/aa_workflow_vscode/src/skillToast.ts` | ✅ Complete |
| Extension Integration | `extensions/aa_workflow_vscode/src/extension.ts` | ✅ Complete |
| Zenity Fallback | `server/websocket_server.py` | ✅ Complete |

### Features Implemented

1. **Real-time skill updates via WebSocket** (~10ms latency vs 15s polling)
2. **Status bar indicator** showing running skills and pending confirmations
3. **Toast notifications** for skill start/complete/fail
4. **Expandable webview panel** with step-by-step progress
5. **Confirmation dialogs** with countdown timer
6. **Timer pause** when user interacts with dialog
7. **Remember choice** options (per-error, per-skill, always)
8. **Zenity fallback** when VS Code extension not connected
9. **Window focus + notification sound** when confirmation needed

### WebSocket Event Types

```typescript
// Skill lifecycle
skill_started, skill_completed, skill_failed

// Step progress
step_started, step_completed, step_failed

// Auto-heal
auto_heal_triggered, auto_heal_completed

// Confirmations
confirmation_required, confirmation_answered, confirmation_expired
```

## Rollout Plan

### Phase 1: Core Infrastructure
- [x] Implement WebSocket server for real-time updates
- [x] Integrate WebSocket events into skill engine
- [x] Add VS Code WebSocket client
- [x] Implement toast UI with status bar
- [x] Add Zenity fallback for confirmations
- [ ] Implement `ConfirmationEngine` with memory-based learning
- [ ] Add `confirm:` step type to skill YAML
- [ ] Add `skill_continue` MCP tool
- [ ] Unit tests

### Phase 2: VS Code Integration
- [x] Implement `SkillToastManager` in extension
- [x] Add status bar with skill progress
- [ ] Add Command Center panel for confirmations
- [ ] Integration tests

### Phase 3: AI-Assisted Mode
- [ ] Implement AI context formatting
- [ ] Test Claude's interpretation
- [ ] Add fix suggestion flow
- [ ] Add learning from fixes

### Phase 4: Skill Updates
- [ ] Update `release_aa_backend_prod`
- [ ] Update `scale_deployment`
- [ ] Update `rollout_restart`
- [ ] Update `hotfix`
- [ ] Update other high-priority skills

### Phase 5: Documentation & Polish
- [ ] Update skill authoring docs
- [ ] Add examples
- [ ] Performance optimization
- [ ] Error handling improvements

## Open Questions

1. **State persistence**: How long should paused executions be kept?
2. **Concurrent confirmations**: What if multiple skills need confirmation simultaneously?
3. **Timeout behavior**: Should timeout proceed or cancel by default?
4. **AI token usage**: How much context should we send to Claude?
5. **Security**: Should some confirmations require re-authentication?

## Validation: The Learning System Architecture

### Design Philosophy

The skill engine was designed with a clear philosophy:

> **Skills provide deterministic patterns to Claude to prevent random/non-deterministic outcomes for everyday tasks.**

But we also want:
> **Claude to step in at runtime and fix tool errors, resulting in better skills over time.**

And we have:
> **Learning systems that log errors and their fixes, preloading fixes prior to running skills to improve valid outcomes over time.**

### Current Learning Systems (Validated)

#### 1. Memory Files

| File | Purpose | Used By |
|------|---------|---------|
| `memory/learned/patterns.yaml` | Error patterns with fixes | `_check_known_issues_sync()` |
| `memory/learned/tool_failures.yaml` | Auto-heal history | `@auto_heal` decorator, skill engine |
| `memory/learned/tool_fixes.yaml` | Claude-applied fixes | `learn_tool_fix()` tool |

#### 2. Preloading Known Issues (✅ Working)

Skills preload known issues at the start to warn about potential problems:

```yaml
# From test_mr_ephemeral.yaml - lines 1310-1327
- name: check_ephemeral_known_issues
  description: "Check for known ephemeral/bonfire issues"
  compute: |
    # Check known issues for bonfire and ephemeral
    bonfire_issues = memory.check_known_issues("bonfire", "") or {}
    quay_issues = memory.check_known_issues("quay", "") or {}
    konflux_issues = memory.check_known_issues("konflux", "") or {}

    all_issues = []
    for issues in [bonfire_issues, quay_issues, konflux_issues]:
        if issues and issues.get("matches"):
            all_issues.extend(issues.get("matches", [])[:2])

    result = {
        "has_known_issues": len(all_issues) > 0,
        "issues": all_issues[:5],
    }
  output: ephemeral_known_issues
```

This is displayed in the skill output:

```yaml
# From test_mr_ephemeral.yaml - lines 1693-1700
{% if ephemeral_known_issues and ephemeral_known_issues.has_known_issues %}
---

### 💡 Known Issues to Watch For

{% for issue in ephemeral_known_issues.issues[:3] %}
- {{ issue.pattern if issue.pattern else issue }}
{% endfor %}
{% endif %}
```

#### 3. Runtime Error Checking (✅ Working)

When a tool fails, the skill engine checks for known fixes:

```python
# From skill_engine.py - lines 1534-1540
# Check for known issues and attempt auto-fix
matches = _check_known_issues_sync(tool_name=tool_name, error_text=error_msg)
known_text = _format_known_issues(matches)

if matches:
    self._debug(f"  → Found {len(matches)} known issue(s), attempting auto-fix")
    fix_applied = await self._try_auto_fix(error_msg, matches)
```

#### 4. Layer 5 Learning (✅ Working)

When errors occur, they're sent to the learning system:

```python
# From skill_engine.py - lines 531-556
async def _learn_from_error(self, tool_name: str, params: dict, error_msg: str):
    """Send error to Layer 5 learning system (async).

    This is called when on_error: continue swallows an error.
    Layer 5 will:
    1. Classify the error (usage vs infrastructure)
    2. Extract patterns and prevention steps
    3. Merge with similar patterns
    4. Build confidence over time
    """
    if not self.usage_learner:
        return

    await self.usage_learner.learn_from_observation(
        tool_name=tool_name,
        params=params,
        error_message=error_msg,
        context={},
        success=False,
    )
```

#### 5. Auto-Heal Logging (✅ Working)

Successful auto-heals are logged to memory:

```yaml
# From memory/learned/tool_failures.yaml
failures:
- error_snippet: "HTTP 403 - access forbidden..."
  error_type: auth
  fix_applied: kube_login
  source: skill_engine
  success: true
  timestamp: '2026-01-18T16:18:51.837740'
  tool: gitlab_mr_list
```

### What's Missing: Claude's Runtime Involvement

The current system has a gap:

```
┌─────────────────────────────────────────────────────────────────────┐
│ CURRENT: Deterministic Only                                         │
│                                                                      │
│ Error → Pattern Match → Fixed Action → Retry                        │
│         (regex)         (kube_login)                                │
│                                                                      │
│ Claude sees output AFTER, cannot help DURING                        │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ PROPOSED: Deterministic + AI Fallback                               │
│                                                                      │
│ Error → Pattern Match → Fixed Action → Retry                        │
│         (regex)         (kube_login)                                │
│              │                                                       │
│              ▼ (no match)                                           │
│         Return to Claude with context                               │
│              │                                                       │
│              ▼                                                       │
│         Claude analyzes, proposes fix                               │
│              │                                                       │
│              ▼                                                       │
│         User confirms → Retry with fix                              │
│              │                                                       │
│              ▼                                                       │
│         Success → learn_tool_fix() → Pattern for next time          │
└─────────────────────────────────────────────────────────────────────┘
```

### The Learning Loop (How It Should Work)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        LEARNING LOOP                                  │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  1. SKILL STARTS                                                      │
│     │                                                                 │
│     ├─► Preload known issues from memory/learned/patterns.yaml       │
│     │   - check_known_issues("bonfire", "")                          │
│     │   - check_known_issues("quay", "")                             │
│     │                                                                 │
│     ├─► Display warnings to user                                     │
│     │   "💡 Known Issues to Watch For: ..."                          │
│     │                                                                 │
│  2. TOOL EXECUTES                                                     │
│     │                                                                 │
│     ├─► @auto_heal decorator catches error                           │
│     │   - Pattern match: "unauthorized" → kube_login()               │
│     │   - Log to tool_failures.yaml                                  │
│     │                                                                 │
│     ├─► If @auto_heal fails, skill engine checks:                    │
│     │   - _check_known_issues_sync(tool, error)                      │
│     │   - _try_auto_fix() based on matches                           │
│     │                                                                 │
│  3. UNKNOWN ERROR (no pattern match)                                  │
│     │                                                                 │
│     ├─► [CURRENT] Fail or continue with error                        │
│     │                                                                 │
│     └─► [PROPOSED] Return to Claude:                                 │
│         │                                                             │
│         ├─► Claude analyzes error + context                          │
│         │   "This error means X, the fix is Y"                       │
│         │                                                             │
│         ├─► Claude proposes fix                                      │
│         │   "Let me try with full SHA instead of short SHA"          │
│         │                                                             │
│         ├─► User confirms → skill_retry_step()                       │
│         │                                                             │
│         └─► Success → Claude calls learn_tool_fix()                  │
│             │                                                         │
│             └─► Pattern saved to memory/learned/tool_fixes.yaml      │
│                 │                                                     │
│                 └─► NEXT TIME: Auto-fixed without Claude             │
│                                                                       │
│  4. SKILL COMPLETES                                                   │
│     │                                                                 │
│     └─► Layer 5 learning extracts patterns                           │
│         - _learn_from_error() for any swallowed errors               │
│         - Builds confidence over time                                │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### Key Insight: Claude Improves Skills Over Time

The confirmation system isn't just about pausing for user input. It's about:

1. **Catching unknown errors** that deterministic patterns can't handle
2. **Involving Claude's reasoning** to diagnose and fix
3. **Learning from Claude's fixes** so they become deterministic patterns
4. **Reducing Claude's involvement over time** as patterns accumulate

```
Week 1: Claude fixes "manifest unknown" error manually
        → learn_tool_fix("bonfire_deploy", "manifest unknown", "Use full SHA")

Week 2: Same error → auto-fixed from memory, no Claude needed

Week 3: New error "namespace quota exceeded"
        → Claude diagnoses, fixes, learns

Week 4: Both errors auto-fixed, Claude only needed for new issues
```

### Validation Summary

| Component | Status | Notes |
|-----------|--------|-------|
| Preload known issues | ✅ Working | Skills call `check_known_issues()` at start |
| Runtime error checking | ✅ Working | `_check_known_issues_sync()` on tool failure |
| Auto-heal patterns | ✅ Working | `@auto_heal` decorator with regex patterns |
| Layer 5 learning | ✅ Working | `_learn_from_error()` on swallowed errors |
| Auto-heal logging | ✅ Working | Logs to `tool_failures.yaml` |
| Claude runtime involvement | ❌ Missing | Need confirmation system to return control |
| Learn from Claude fixes | ⚠️ Partial | `learn_tool_fix()` exists but not integrated |

### What This Plan Adds

1. **`confirm:` step type** - Pause skill for user/AI input
2. **AI-assisted error recovery** - Return control to Claude on unknown errors
3. **`skill_continue()`/`skill_retry_step()`** - Resume with Claude's fix
4. **Automatic learning** - Save Claude's fixes to memory
5. **Reduced prompts over time** - Memory-based auto-proceed

## References

- Current auto-heal implementation: `server/auto_heal_decorator.py`
- Skill engine: `tool_modules/aa_workflow/src/skill_engine.py`
- Error recovery: `scripts/common/skill_error_recovery.py`
- VS Code extension: `extensions/aa_workflow_vscode/src/`
- Notification engine: `tool_modules/aa_workflow/src/notification_engine.py`
- Memory patterns: `memory/learned/patterns.yaml`
- Tool failures log: `memory/learned/tool_failures.yaml`
- Known issues checker: `_check_known_issues_sync()` in skill_engine.py
