"""
Gmail MCP Tools

Provides tools for interacting with Gmail:
- List emails (inbox, sent, starred, etc.)
- Search emails
- Read email content
- Get email threads

Uses the same OAuth credentials as Google Calendar (shared token).

Setup:
1. Ensure Google Calendar OAuth is configured (~/.config/google-calendar/credentials.json)
2. Run google_calendar_status() to authenticate (creates shared token)
3. Gmail tools will use the same token
"""

import base64
import logging
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.tool_registry import ToolRegistry
from server.utils import load_config

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _get_google_config_dir() -> Path:
    """Get Google config directory (shared with calendar)."""
    config = load_config()
    gc_config = config.get("google_calendar", {}).get("config_dir")
    if gc_config:
        import os

        return Path(os.path.expanduser(gc_config))
    paths_cfg = config.get("paths", {})
    gc_config = paths_cfg.get("google_calendar_config")
    if gc_config:
        import os

        return Path(os.path.expanduser(gc_config))
    return Path.home() / ".config" / "google-calendar"


CONFIG_DIR = _get_google_config_dir()
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"

# Scopes - same as calendar (shared token)
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/presentations.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_gmail_service():
    """
    Get authenticated Gmail service.

    Uses the same OAuth token as Google Calendar.
    Returns (service, error_message).
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return (
            None,
            "Google API libraries not installed. Run: "
            "uv add google-api-python-client google-auth-httplib2 google-auth-oauthlib",
        )

    creds = None

    # Try to load existing token
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            pass

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        except Exception:
            creds = None

    # Need to authenticate via calendar first
    if not creds or not creds.valid:
        return (
            None,
            f"Not authenticated. Run `google_calendar_status()` first to authenticate.\n"
            f"Token file: {TOKEN_FILE}",
        )

    try:
        service = build("gmail", "v1", credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Failed to build Gmail service: {e}"


def _decode_body(payload: dict) -> str:
    """Decode email body from payload."""
    body = ""

    if "body" in payload and payload["body"].get("data"):
        try:
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
        except Exception:
            pass

    # Check parts for multipart messages
    if "parts" in payload:
        for part in payload["parts"]:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain":
                if part.get("body", {}).get("data"):
                    try:
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                            "utf-8"
                        )
                        break
                    except Exception:
                        pass
            elif mime_type.startswith("multipart/"):
                # Recursively check nested parts
                nested = _decode_body(part)
                if nested:
                    body = nested
                    break

    return body


def _get_header(headers: list, name: str) -> str:
    """Get header value by name."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _format_email_date(date_str: str) -> str:
    """Format email date string."""
    if not date_str:
        return "unknown"
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return date_str[:20] if len(date_str) > 20 else date_str


def _clean_email_body(body: str, max_length: int = 2000) -> str:
    """Clean and truncate email body."""
    # Remove excessive whitespace
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = re.sub(r" {2,}", " ", body)

    # Truncate if too long
    if len(body) > max_length:
        body = body[:max_length] + "\n\n... (truncated)"

    return body.strip()


# ==================== TOOL IMPLEMENTATIONS ====================


async def _gmail_list_emails_impl(
    label: str = "INBOX",
    max_results: int = 10,
    unread_only: bool = False,
) -> str:
    """List emails from a label/folder."""
    service, error = get_gmail_service()
    if error:
        return f"❌ {error}"

    try:
        # Build query
        query = ""
        if unread_only:
            query = "is:unread"

        results = (
            service.users()
            .messages()
            .list(
                userId="me",
                labelIds=[label],
                q=query,
                maxResults=max_results,
            )
            .execute()
        )

        messages = results.get("messages", [])

        if not messages:
            return f"📧 No emails in {label}"

        lines = [
            f"# 📧 {label}",
            f"Showing {len(messages)} email(s)",
            "",
        ]

        for msg in messages:
            # Get message details
            msg_data = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )

            headers = msg_data.get("payload", {}).get("headers", [])
            subject = _get_header(headers, "Subject") or "(no subject)"
            from_addr = _get_header(headers, "From")
            date = _get_header(headers, "Date")

            # Check if unread
            labels = msg_data.get("labelIds", [])
            unread = "UNREAD" in labels
            star = "⭐ " if "STARRED" in labels else ""
            unread_mark = "🔵 " if unread else ""

            lines.append(f"## {unread_mark}{star}{subject}")
            lines.append(f"- **From:** {from_addr}")
            lines.append(f"- **Date:** {_format_email_date(date)}")
            lines.append(f"- **ID:** `{msg['id']}`")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list emails: {e}"


async def _gmail_search_impl(
    query: str,
    max_results: int = 10,
) -> str:
    """Search emails."""
    service, error = get_gmail_service()
    if error:
        return f"❌ {error}"

    try:
        results = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=max_results,
            )
            .execute()
        )

        messages = results.get("messages", [])

        if not messages:
            return f"🔍 No emails found matching '{query}'"

        lines = [
            f"# 🔍 Search Results for '{query}'",
            f"Found {len(messages)} email(s)",
            "",
        ]

        for msg in messages:
            msg_data = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )

            headers = msg_data.get("payload", {}).get("headers", [])
            subject = _get_header(headers, "Subject") or "(no subject)"
            from_addr = _get_header(headers, "From")
            date = _get_header(headers, "Date")
            snippet = msg_data.get("snippet", "")[:100]

            lines.append(f"## {subject}")
            lines.append(f"- **From:** {from_addr}")
            lines.append(f"- **Date:** {_format_email_date(date)}")
            lines.append(f"- **Preview:** {snippet}...")
            lines.append(f"- **ID:** `{msg['id']}`")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Search failed: {e}"


async def _gmail_read_email_impl(
    message_id: str,
    max_body_length: int = 5000,
) -> str:
    """Read a specific email."""
    service, error = get_gmail_service()
    if error:
        return f"❌ {error}"

    try:
        msg_data = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        payload = msg_data.get("payload", {})
        headers = payload.get("headers", [])

        subject = _get_header(headers, "Subject") or "(no subject)"
        from_addr = _get_header(headers, "From")
        to_addr = _get_header(headers, "To")
        cc_addr = _get_header(headers, "Cc")
        date = _get_header(headers, "Date")

        # Decode body
        body = _decode_body(payload)
        body = _clean_email_body(body, max_body_length)

        lines = [
            f"# 📧 {subject}",
            "",
            f"**From:** {from_addr}",
            f"**To:** {to_addr}",
        ]

        if cc_addr:
            lines.append(f"**CC:** {cc_addr}")

        lines.append(f"**Date:** {_format_email_date(date)}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(body if body else "(No text content)")

        # Check for attachments
        attachments = []
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("filename"):
                    attachments.append(
                        {
                            "name": part["filename"],
                            "size": part.get("body", {}).get("size", 0),
                            "mime": part.get("mimeType", ""),
                        }
                    )

        if attachments:
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append("## 📎 Attachments")
            for att in attachments:
                lines.append(
                    f"- **{att['name']}** ({att['mime']}, {att['size']} bytes)"
                )

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to read email: {e}"


async def _gmail_get_thread_impl(
    thread_id: str,
    max_messages: int = 10,
) -> str:
    """Get all messages in an email thread."""
    service, error = get_gmail_service()
    if error:
        return f"❌ {error}"

    try:
        thread = (
            service.users()
            .threads()
            .get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )

        messages = thread.get("messages", [])

        if not messages:
            return f"📧 No messages in thread {thread_id}"

        # Get subject from first message
        first_headers = messages[0].get("payload", {}).get("headers", [])
        subject = _get_header(first_headers, "Subject") or "(no subject)"

        lines = [
            f"# 📧 Thread: {subject}",
            f"{len(messages)} message(s) in thread",
            "",
        ]

        for i, msg in enumerate(messages[:max_messages]):
            headers = msg.get("payload", {}).get("headers", [])
            from_addr = _get_header(headers, "From")
            date = _get_header(headers, "Date")
            snippet = msg.get("snippet", "")[:150]

            lines.append(f"## Message {i + 1}")
            lines.append(f"- **From:** {from_addr}")
            lines.append(f"- **Date:** {_format_email_date(date)}")
            lines.append(f"- **Preview:** {snippet}...")
            lines.append(f"- **ID:** `{msg['id']}`")
            lines.append("")

        if len(messages) > max_messages:
            lines.append(f"*... and {len(messages) - max_messages} more messages*")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to get thread: {e}"


async def _gmail_list_labels_impl() -> str:
    """List all Gmail labels."""
    service, error = get_gmail_service()
    if error:
        return f"❌ {error}"

    try:
        results = service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])

        if not labels:
            return "📧 No labels found"

        lines = [
            "# 📧 Gmail Labels",
            "",
        ]

        # Separate system and user labels
        system_labels = []
        user_labels = []

        for label in labels:
            if label.get("type") == "system":
                system_labels.append(label)
            else:
                user_labels.append(label)

        if system_labels:
            lines.append("## System Labels")
            for label in sorted(system_labels, key=lambda x: x.get("name", "")):
                lines.append(f"- `{label['id']}` - {label.get('name', label['id'])}")
            lines.append("")

        if user_labels:
            lines.append("## User Labels")
            for label in sorted(user_labels, key=lambda x: x.get("name", "")):
                lines.append(f"- `{label['id']}` - {label.get('name', label['id'])}")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list labels: {e}"


async def _gmail_unread_count_impl() -> str:
    """Get count of unread emails."""
    service, error = get_gmail_service()
    if error:
        return f"❌ {error}"

    try:
        # Get INBOX label info
        label = service.users().labels().get(userId="me", id="INBOX").execute()

        unread = label.get("messagesUnread", 0)
        total = label.get("messagesTotal", 0)

        lines = [
            "# 📧 Inbox Status",
            "",
            f"**Unread:** {unread}",
            f"**Total:** {total}",
        ]

        if unread > 0:
            lines.append("")
            lines.append(
                "Use `gmail_list_emails(unread_only=True)` to see unread messages."
            )

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to get unread count: {e}"


async def _gmail_status_impl() -> str:
    """Check Gmail integration status."""
    lines = [
        "# Gmail Integration Status",
        "",
        f"**Config directory:** `{CONFIG_DIR}`",
        "",
    ]

    if CREDENTIALS_FILE.exists():
        lines.append("✅ OAuth credentials file found")
    else:
        lines.append("❌ OAuth credentials not found")

    if TOKEN_FILE.exists():
        lines.append("✅ OAuth token cached")
    else:
        lines.append("⚪ No cached token")

    lines.append("")

    service, error = get_gmail_service()
    if service:
        lines.append("✅ **Connected to Gmail**")
        try:
            profile = service.users().getProfile(userId="me").execute()
            lines.append(f"   Email: {profile.get('emailAddress', '?')}")
            lines.append(f"   Messages: {profile.get('messagesTotal', '?')}")
            lines.append(f"   Threads: {profile.get('threadsTotal', '?')}")
        except Exception as e:
            lines.append(f"   (Could not fetch profile: {e})")
    else:
        lines.append(f"❌ **Not connected:** {error}")

    return "\n".join(lines)


# ==================== TOOL REGISTRATION ====================


def register_tools(server: "FastMCP") -> int:
    """Register Gmail tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def gmail_list_emails(
        label: str = "INBOX",
        max_results: int = 10,
        unread_only: bool = False,
    ) -> str:
        """
        List emails from a label/folder.

        Args:
            label: Gmail label (INBOX, SENT, STARRED, DRAFT, SPAM, TRASH, or custom)
            max_results: Maximum number of emails (default: 10)
            unread_only: Only show unread emails (default: False)

        Returns:
            List of emails with subject, sender, date
        """
        return await _gmail_list_emails_impl(label, max_results, unread_only)

    @registry.tool()
    async def gmail_search(
        query: str,
        max_results: int = 10,
    ) -> str:
        """
        Search emails using Gmail search syntax.

        Examples:
            - "from:john@example.com" - emails from John
            - "subject:meeting" - emails with 'meeting' in subject
            - "has:attachment" - emails with attachments
            - "after:2024/01/01" - emails after date
            - "is:unread" - unread emails
            - "label:work" - emails with label

        Args:
            query: Gmail search query
            max_results: Maximum results (default: 10)

        Returns:
            List of matching emails
        """
        return await _gmail_search_impl(query, max_results)

    @registry.tool()
    async def gmail_read_email(
        message_id: str,
        max_body_length: int = 5000,
    ) -> str:
        """
        Read a specific email's full content.

        Args:
            message_id: The email message ID (from gmail_list_emails or gmail_search)
            max_body_length: Maximum body length to return (default: 5000)

        Returns:
            Full email content including headers and body
        """
        return await _gmail_read_email_impl(message_id, max_body_length)

    @registry.tool()
    async def gmail_get_thread(
        thread_id: str,
        max_messages: int = 10,
    ) -> str:
        """
        Get all messages in an email thread/conversation.

        Args:
            thread_id: The thread ID
            max_messages: Maximum messages to return (default: 10)

        Returns:
            List of messages in the thread
        """
        return await _gmail_get_thread_impl(thread_id, max_messages)

    @registry.tool()
    async def gmail_list_labels() -> str:
        """
        List all Gmail labels (folders).

        Returns:
            List of system and user labels with their IDs
        """
        return await _gmail_list_labels_impl()

    @registry.tool()
    async def gmail_unread_count() -> str:
        """
        Get count of unread emails in inbox.

        Returns:
            Unread and total message counts
        """
        return await _gmail_unread_count_impl()

    @registry.tool()
    async def gmail_status() -> str:
        """
        Check Gmail integration status.

        Returns:
            Connection status and account info
        """
        return await _gmail_status_impl()

    return registry.count
