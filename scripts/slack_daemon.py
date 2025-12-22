#!/usr/bin/env python3
"""
Autonomous Slack Agent Daemon

A standalone process that monitors Slack and responds using the AI Workflow
tools and skills. Runs outside of Cursor with full access to all capabilities.

Features:
- Continuous Slack monitoring with configurable poll interval
- Intent detection and routing to appropriate tools
- Optional LLM integration for intelligent responses
- Rich terminal UI with status display
- Graceful shutdown handling

Usage:
    python scripts/slack_daemon.py                    # Run with defaults
    python scripts/slack_daemon.py --llm              # Enable LLM responses
    python scripts/slack_daemon.py --dry-run          # Process but don't respond
    python scripts/slack_daemon.py --verbose          # Detailed logging

Environment Variables:
    SLACK_XOXC_TOKEN      - Slack web client token (required)
    SLACK_D_COOKIE        - Slack session cookie (required)
    SLACK_WATCHED_CHANNELS - Channels to monitor
    SLACK_WATCHED_KEYWORDS - Keywords to trigger on
    OPENAI_API_KEY        - For LLM integration (optional)
    OPENAI_BASE_URL       - Custom API endpoint (optional)
"""

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "aa-slack"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "aa-jira"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "aa-gitlab"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "aa-git"))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "mcp-servers" / "aa-slack" / ".env")
load_dotenv()

# Import Slack components
from src.slack_client import SlackSession
from src.persistence import SlackStateDB, PendingMessage
from src.listener import SlackListener, ListenerConfig

logger = logging.getLogger(__name__)


# =============================================================================
# TERMINAL UI
# =============================================================================


class TerminalUI:
    """Rich terminal output for the daemon."""

    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
    }

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.start_time = time.time()
        self.messages_processed = 0
        self.messages_responded = 0
        self.errors = 0

    def clear_line(self):
        """Clear current line."""
        print("\r\033[K", end="")

    def print_header(self):
        """Print startup header."""
        print(f"""
{self.COLORS['cyan']}╔══════════════════════════════════════════════════════════════════╗
║  {self.COLORS['bold']}🤖 AI Workflow - Autonomous Slack Agent{self.COLORS['reset']}{self.COLORS['cyan']}                          ║
║                                                                    ║
║  Monitoring Slack channels for messages...                         ║
║  Press Ctrl+C to stop                                              ║
╚══════════════════════════════════════════════════════════════════╝{self.COLORS['reset']}
""")

    def print_status(self, listener_stats: dict):
        """Print current status."""
        uptime = time.time() - self.start_time
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)

        status = f"{self.COLORS['dim']}[{hours:02d}:{minutes:02d}:{seconds:02d}]{self.COLORS['reset']} "
        status += f"📊 Polls: {listener_stats.get('polls', 0)} | "
        status += f"📬 Seen: {listener_stats.get('messages_seen', 0)} | "
        status += f"✅ Processed: {self.messages_processed} | "
        status += f"💬 Responded: {self.messages_responded}"

        if self.errors > 0:
            status += f" | {self.COLORS['red']}❌ Errors: {self.errors}{self.COLORS['reset']}"

        self.clear_line()
        print(status, end="", flush=True)

    def print_message(self, msg: PendingMessage, intent: str):
        """Print incoming message."""
        print(f"\n{self.COLORS['yellow']}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{self.COLORS['reset']}")
        print(f"{self.COLORS['bold']}📩 New Message{self.COLORS['reset']}")
        print(f"   Channel: #{msg.channel_name}")
        print(f"   From: {msg.user_name}")
        print(f"   Intent: {self.COLORS['cyan']}{intent}{self.COLORS['reset']}")
        print(f"   Text: {msg.text[:100]}{'...' if len(msg.text) > 100 else ''}")

    def print_response(self, response: str, success: bool):
        """Print outgoing response."""
        status = f"{self.COLORS['green']}✅{self.COLORS['reset']}" if success else f"{self.COLORS['red']}❌{self.COLORS['reset']}"
        print(f"   Response: {status}")
        if self.verbose:
            print(f"   {self.COLORS['dim']}{response[:200]}...{self.COLORS['reset']}")
        print(f"{self.COLORS['yellow']}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{self.COLORS['reset']}")

    def print_error(self, error: str):
        """Print error message."""
        print(f"\n{self.COLORS['red']}❌ Error: {error}{self.COLORS['reset']}")
        self.errors += 1

    def print_shutdown(self):
        """Print shutdown message."""
        print(f"\n\n{self.COLORS['cyan']}Shutting down gracefully...{self.COLORS['reset']}")
        print(f"   📊 Total processed: {self.messages_processed}")
        print(f"   💬 Total responded: {self.messages_responded}")
        print(f"   ❌ Total errors: {self.errors}")
        print(f"{self.COLORS['green']}Goodbye! 👋{self.COLORS['reset']}\n")


# =============================================================================
# INTENT DETECTION
# =============================================================================


@dataclass
class Intent:
    """Detected intent from a message."""

    type: str
    confidence: float
    entities: dict = field(default_factory=dict)
    requires_confirmation: bool = False


class IntentDetector:
    """Detects intent from Slack messages."""

    PATTERNS = {
        "jira_query": [
            (r"AAP-\d+", 0.95),
            (r"\b(issue|ticket|story|bug|epic)\b", 0.6),
            (r"\bjira\b", 0.7),
        ],
        "mr_status": [
            (r"!\d+", 0.95),
            (r"\b(MR|PR|merge request|pull request)\s*#?\d+", 0.9),
        ],
        "check_my_prs": [
            (r"\bmy\s+(MRs?|PRs?|merge requests?|pull requests?)\b", 0.85),
        ],
        "prod_debug": [
            (r"\b(prod|production)\s+(down|issue|problem|error)\b", 0.9),
            (r"\b(alert|incident|outage)\b", 0.8),
        ],
        "start_work": [
            (r"\b(start|begin|pick up|work on)\s+(AAP-\d+)", 0.9),
        ],
        "standup": [
            (r"\b(standup|stand-up|status update|daily)\b", 0.85),
        ],
        "help": [
            (r"\b(help|how do|what is|explain|guide)\b", 0.7),
        ],
    }

    def detect(self, text: str, is_mention: bool = False) -> Intent:
        """Detect intent from message text."""
        text_lower = text.lower()
        best_intent = Intent(type="general", confidence=0.5)

        for intent_type, patterns in self.PATTERNS.items():
            for pattern, base_confidence in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    confidence = base_confidence
                    if is_mention:
                        confidence = min(1.0, confidence + 0.1)

                    if confidence > best_intent.confidence:
                        best_intent = Intent(
                            type=intent_type,
                            confidence=confidence,
                            entities=self._extract_entities(text, intent_type),
                            requires_confirmation=intent_type in ["prod_debug", "start_work"],
                        )

        return best_intent

    def _extract_entities(self, text: str, intent_type: str) -> dict:
        """Extract entities based on intent type."""
        entities = {}

        # Extract Jira keys
        jira_keys = re.findall(r"AAP-\d+", text, re.IGNORECASE)
        if jira_keys:
            entities["issue_keys"] = [k.upper() for k in jira_keys]

        # Extract MR IDs
        mr_ids = re.findall(r"!(\d+)", text)
        if mr_ids:
            entities["mr_ids"] = mr_ids

        return entities


# =============================================================================
# TOOL EXECUTOR
# =============================================================================


class ToolExecutor:
    """Executes tools directly (not via MCP)."""

    def __init__(self, project_root: Path):
        self.project_root = project_root

    async def execute_jira_view(self, issue_key: str) -> str:
        """View a Jira issue."""
        try:
            result = subprocess.run(
                ["rh-issue", "view", issue_key],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return result.stdout
            return f"Error viewing {issue_key}: {result.stderr}"
        except Exception as e:
            return f"Error: {e}"

    async def execute_jira_search(self, query: str) -> str:
        """Search Jira issues."""
        try:
            result = subprocess.run(
                ["rh-issue", "search", query],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout if result.returncode == 0 else result.stderr
        except Exception as e:
            return f"Error: {e}"

    async def execute_gitlab_mr_view(self, mr_id: str) -> str:
        """View a GitLab MR."""
        try:
            # Use glab if available
            result = subprocess.run(
                ["glab", "mr", "view", mr_id],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout if result.returncode == 0 else result.stderr
        except Exception as e:
            return f"Error: {e}"

    async def execute_gitlab_mr_list(self, author: str = "") -> str:
        """List GitLab MRs."""
        try:
            cmd = ["glab", "mr", "list", "--state", "opened"]
            if author:
                cmd.extend(["--author", author])
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout if result.returncode == 0 else result.stderr
        except Exception as e:
            return f"Error: {e}"

    async def execute_git_status(self, repo: str = ".") -> str:
        """Get git status."""
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True,
                text=True,
                cwd=repo,
                timeout=10,
            )
            return result.stdout if result.returncode == 0 else result.stderr
        except Exception as e:
            return f"Error: {e}"

    async def execute_kubectl_pods(self, namespace: str) -> str:
        """Get pods in namespace."""
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "-n", namespace, "-o", "wide"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout if result.returncode == 0 else result.stderr
        except Exception as e:
            return f"Error: {e}"


# =============================================================================
# RESPONSE GENERATOR
# =============================================================================


class ResponseGenerator:
    """Generates responses for different intents."""

    def __init__(self, executor: ToolExecutor, use_llm: bool = False):
        self.executor = executor
        self.use_llm = use_llm
        self.llm_client = None

        if use_llm:
            self._init_llm()

    def _init_llm(self):
        """Initialize LLM client if available."""
        try:
            import httpx

            api_key = os.getenv("OPENAI_API_KEY")
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

            if api_key:
                self.llm_client = httpx.AsyncClient(
                    base_url=base_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=60.0,
                )
                logger.info("LLM client initialized")
            else:
                logger.warning("No OPENAI_API_KEY found, LLM disabled")
                self.use_llm = False
        except Exception as e:
            logger.warning(f"Could not initialize LLM: {e}")
            self.use_llm = False

    async def generate(self, message: PendingMessage, intent: Intent) -> str:
        """Generate a response for the given message and intent."""
        handlers = {
            "jira_query": self._handle_jira_query,
            "mr_status": self._handle_mr_status,
            "check_my_prs": self._handle_check_my_prs,
            "prod_debug": self._handle_prod_debug,
            "start_work": self._handle_start_work,
            "standup": self._handle_standup,
            "help": self._handle_help,
            "general": self._handle_general,
        }

        handler = handlers.get(intent.type, self._handle_general)
        return await handler(message, intent)

    async def _handle_jira_query(self, msg: PendingMessage, intent: Intent) -> str:
        """Handle Jira issue query."""
        issue_keys = intent.entities.get("issue_keys", [])
        if not issue_keys:
            return "I couldn't find a Jira issue key in your message. Try: `AAP-12345`"

        key = issue_keys[0]
        result = await self.executor.execute_jira_view(key)

        # Format for Slack
        if "Error" in result:
            return f"❌ Could not fetch {key}: {result}"

        # Truncate if too long
        if len(result) > 1500:
            result = result[:1500] + "\n\n_...truncated_"

        return f"📋 *{key}*\n\n```\n{result}\n```"

    async def _handle_mr_status(self, msg: PendingMessage, intent: Intent) -> str:
        """Handle MR status query."""
        mr_ids = intent.entities.get("mr_ids", [])
        if not mr_ids:
            return "I couldn't find an MR ID. Try: `!123`"

        mr_id = mr_ids[0]
        result = await self.executor.execute_gitlab_mr_view(mr_id)

        if len(result) > 1500:
            result = result[:1500] + "\n\n_...truncated_"

        return f"🦊 *MR !{mr_id}*\n\n```\n{result}\n```"

    async def _handle_check_my_prs(self, msg: PendingMessage, intent: Intent) -> str:
        """Handle 'my PRs' query."""
        result = await self.executor.execute_gitlab_mr_list(msg.user_name)

        if not result.strip():
            return f"🎉 No open MRs found for {msg.user_name}!"

        return f"📋 *Open MRs for {msg.user_name}*\n\n```\n{result[:1500]}\n```"

    async def _handle_prod_debug(self, msg: PendingMessage, intent: Intent) -> str:
        """Handle production debug request."""
        return """🚨 *Production Issue Detected*

I can help investigate! To proceed, reply with:
• `debug tower-analytics-prod` - Check main namespace
• `debug tower-analytics-prod-billing` - Check billing

Or provide more context about the issue you're seeing."""

    async def _handle_start_work(self, msg: PendingMessage, intent: Intent) -> str:
        """Handle start work request."""
        issue_keys = intent.entities.get("issue_keys", [])
        if not issue_keys:
            return "Please include a Jira issue key, e.g., `start AAP-12345`"

        key = issue_keys[0]
        return f"""🚀 *Ready to Start Work on {key}*

This will:
1. Create/checkout branch `{key.lower()}-...`
2. Update Jira status to In Progress

Reply `yes start {key}` to proceed, or `info {key}` for details first."""

    async def _handle_standup(self, msg: PendingMessage, intent: Intent) -> str:
        """Handle standup request."""
        # For now, return a template
        today = datetime.now().strftime("%Y-%m-%d")
        return f"""📊 *Standup for {today}*

To generate a full standup summary, I need to check:
• Your git commits from today
• Your Jira updates
• Your MR activity

Would you like me to generate this? Reply `yes standup`."""

    async def _handle_help(self, msg: PendingMessage, intent: Intent) -> str:
        """Handle help request."""
        return """👋 *AI Workflow Slack Agent*

I can help with:

📋 *Jira*
• `AAP-12345` - View issue details
• `my issues` - List your assigned issues

🦊 *GitLab*
• `!123` - View MR details
• `my MRs` - List your open MRs

📂 *Git*
• `start AAP-12345` - Start working on issue

🚨 *Production*
• `debug prod` - Debug production issues

📊 *Status*
• `standup` - Generate daily standup

Just mention me with your request!"""

    async def _handle_general(self, msg: PendingMessage, intent: Intent) -> str:
        """Handle general/unknown request."""
        if self.use_llm and self.llm_client:
            return await self._llm_response(msg)

        return f"""👋 Hi {msg.user_name}!

I received your message but I'm not sure what action to take:
> {msg.text[:150]}{"..." if len(msg.text) > 150 else ""}

Try:
• Include a Jira key: `AAP-12345`
• Include an MR: `!123`
• Ask for help: `help`"""

    async def _llm_response(self, msg: PendingMessage) -> str:
        """Generate response using LLM."""
        try:
            response = await self.llm_client.post(
                "/chat/completions",
                json={
                    "model": os.getenv("OPENAI_MODEL", "gpt-4"),
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a helpful AI assistant in a Slack channel. "
                                "Keep responses concise and use Slack formatting. "
                                "If you can't help, suggest specific commands."
                            ),
                        },
                        {"role": "user", "content": msg.text},
                    ],
                    "max_tokens": 500,
                },
            )

            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.warning(f"LLM error: {response.status_code}")
                return await self._handle_general.__wrapped__(self, msg, Intent(type="general", confidence=0.5))
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return f"I encountered an error. Please try a specific command like `help`."


# =============================================================================
# MAIN DAEMON
# =============================================================================


class SlackDaemon:
    """Main autonomous Slack agent daemon."""

    def __init__(
        self,
        dry_run: bool = False,
        use_llm: bool = False,
        verbose: bool = False,
        poll_interval: float = 5.0,
    ):
        self.dry_run = dry_run
        self.use_llm = use_llm
        self.verbose = verbose
        self.poll_interval = poll_interval

        self.ui = TerminalUI(verbose=verbose)
        self.intent_detector = IntentDetector()
        self.executor = ToolExecutor(PROJECT_ROOT)
        self.response_generator = ResponseGenerator(self.executor, use_llm=use_llm)

        self.session: SlackSession | None = None
        self.state_db: SlackStateDB | None = None
        self.listener: SlackListener | None = None

        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self):
        """Initialize and start the daemon."""
        self.ui.print_header()

        # Initialize Slack session
        try:
            self.session = SlackSession.from_env()
            auth = await self.session.validate_session()
            print(f"✅ Authenticated as: {auth.get('user', 'unknown')}")
        except Exception as e:
            self.ui.print_error(f"Slack authentication failed: {e}")
            return

        # Initialize state database
        self.state_db = SlackStateDB()
        await self.state_db.connect()
        print("✅ State database connected")

        # Initialize listener
        config = ListenerConfig.from_env()
        config.poll_interval = self.poll_interval
        self.listener = SlackListener(self.session, self.state_db, config)

        print(f"✅ Watching {len(config.watched_channels)} channels")
        print(f"✅ Keywords: {', '.join(config.watched_keywords) or 'none'}")

        if self.dry_run:
            print(f"⚠️  DRY RUN MODE - no responses will be sent")

        print()

        # Start listener
        await self.listener.start()
        self._running = True

        # Main processing loop
        await self._main_loop()

    async def _main_loop(self):
        """Main processing loop."""
        while self._running:
            try:
                # Update status display
                self.ui.print_status(self.listener.stats)

                # Check for pending messages
                pending = await self.state_db.get_pending_messages(limit=10)

                for msg in pending:
                    await self._process_message(msg)

                # Wait before next check
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.ui.print_error(str(e))
                await asyncio.sleep(5)

    async def _process_message(self, msg: PendingMessage):
        """Process a single pending message."""
        # Detect intent
        intent = self.intent_detector.detect(msg.text, msg.is_mention)

        self.ui.print_message(msg, intent.type)
        self.ui.messages_processed += 1

        # Generate response
        response = await self.response_generator.generate(msg, intent)

        # Send response (unless dry run)
        success = True
        if not self.dry_run:
            try:
                thread_ts = msg.thread_ts or msg.timestamp
                await self.session.send_message(
                    channel_id=msg.channel_id,
                    text=response,
                    thread_ts=thread_ts,
                    typing_delay=True,
                )
                self.ui.messages_responded += 1
            except Exception as e:
                success = False
                self.ui.print_error(f"Failed to send: {e}")

        self.ui.print_response(response, success)

        # Mark as processed
        await self.state_db.mark_message_processed(msg.id)

    async def stop(self):
        """Stop the daemon gracefully."""
        self._running = False

        if self.listener:
            await self.listener.stop()

        if self.session:
            await self.session.close()

        if self.state_db:
            await self.state_db.close()

        self.ui.print_shutdown()

    def setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""

        def signal_handler(signum, frame):
            self._running = False
            self._shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Autonomous Slack Agent Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process messages but don't send responses",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Enable LLM for intelligent responses",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds (default: 5)",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )

    # Reduce noise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    daemon = SlackDaemon(
        dry_run=args.dry_run,
        use_llm=args.llm,
        verbose=args.verbose,
        poll_interval=args.poll_interval,
    )

    daemon.setup_signal_handlers()

    try:
        await daemon.start()
    except KeyboardInterrupt:
        pass
    finally:
        await daemon.stop()


if __name__ == "__main__":
    asyncio.run(main())

