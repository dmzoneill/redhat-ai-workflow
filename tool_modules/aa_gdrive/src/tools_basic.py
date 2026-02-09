"""
Google Drive MCP Tools

Provides tools for interacting with Google Drive:
- List files and folders
- Search for files by name or content
- Download file content
- Get file metadata

Uses the same OAuth credentials as Google Calendar (shared token).

Setup:
1. Ensure Google Calendar OAuth is configured (~/.config/google-calendar/credentials.json)
2. Run google_calendar_status() to authenticate (creates shared token)
3. Google Drive tools will use the same token
"""

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

from tool_modules.common import (
    PROJECT_ROOT,
    get_google_config_dir,
    get_google_oauth_scopes,
)

__project_root__ = PROJECT_ROOT

from server.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _escape_drive_query(text: str) -> str:
    """Escape special characters for Google Drive query syntax.

    Google Drive queries use single quotes for string values.
    Single quotes and backslashes in the search text need escaping.

    Args:
        text: The text to escape

    Returns:
        Escaped text safe for use in Drive query strings
    """
    # Escape backslashes first, then single quotes
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _validate_drive_file_id(file_id: str) -> str | None:
    """Validate a Google Drive file ID format.

    Drive file IDs are alphanumeric with underscores and hyphens.

    Args:
        file_id: The file ID to validate

    Returns:
        None if valid, error message string if invalid
    """
    if not file_id:
        return "❌ File ID cannot be empty"
    # Drive IDs are typically 28-44 chars, alphanumeric with - and _
    if not re.match(r"^[a-zA-Z0-9_-]{10,100}$", file_id):
        return "❌ Invalid file ID format"
    return None


# Shared Google config (single source of truth in tool_modules.common)
CONFIG_DIR = get_google_config_dir()
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"
SCOPES = get_google_oauth_scopes()


def get_drive_service():
    """
    Get authenticated Google Drive service.

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
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        except Exception:
            creds = None

    # Need to authenticate via calendar first
    if not creds or not creds.valid:
        return (
            None,
            "Not authenticated. Run `google_calendar_status()` first to authenticate.\n"
            f"Token file: {TOKEN_FILE}",
        )

    try:
        service = build("drive", "v3", credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Failed to build Drive service: {e}"


def _format_file_size(size_bytes: int | str | None) -> str:
    """Format file size in human-readable format."""
    if size_bytes is None:
        return "unknown"
    try:
        size = int(size_bytes)
    except (ValueError, TypeError):
        return "unknown"

    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _format_datetime(dt_str: str | None) -> str:
    """Format ISO datetime string."""
    if not dt_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return dt_str


# ==================== TOOL IMPLEMENTATIONS ====================


async def _gdrive_list_files_impl(
    folder_id: str = "root",
    max_results: int = 20,
    file_type: str = "",
) -> str:
    """List files in a Google Drive folder."""
    # Validate folder_id if not "root"
    if folder_id != "root":
        if error := _validate_drive_file_id(folder_id):
            return error

    service, error = get_drive_service()
    if error:
        return f"❌ {error}"

    try:
        # Build query - folder_id is validated above
        query_parts = [f"'{folder_id}' in parents", "trashed = false"]

        if file_type:
            mime_types = {
                "doc": "application/vnd.google-apps.document",
                "sheet": "application/vnd.google-apps.spreadsheet",
                "slide": "application/vnd.google-apps.presentation",
                "pdf": "application/pdf",
                "folder": "application/vnd.google-apps.folder",
                "image": "image/",
            }
            if file_type.lower() in mime_types:
                mime = mime_types[file_type.lower()]
                if mime.endswith("/"):
                    query_parts.append(f"mimeType contains '{mime}'")
                else:
                    query_parts.append(f"mimeType = '{mime}'")

        query = " and ".join(query_parts)

        results = (
            service.files()
            .list(
                q=query,
                pageSize=max_results,
                fields="files(id, name, mimeType, size, modifiedTime, webViewLink, owners)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        files = results.get("files", [])

        if not files:
            return f"📁 No files found in folder `{folder_id}`"

        lines = [
            "# 📁 Google Drive Files",
            "",
        ]

        # Separate folders and files
        folders = [
            f
            for f in files
            if f.get("mimeType") == "application/vnd.google-apps.folder"
        ]
        docs = [
            f
            for f in files
            if f.get("mimeType") != "application/vnd.google-apps.folder"
        ]

        if folders:
            lines.append("## 📂 Folders")
            for f in folders:
                lines.append(f"- **{f['name']}**")
                lines.append(f"  - ID: `{f['id']}`")
            lines.append("")

        if docs:
            lines.append("## 📄 Files")
            for f in docs:
                mime = f.get("mimeType", "")
                icon = "📄"
                if "document" in mime:
                    icon = "📝"
                elif "spreadsheet" in mime:
                    icon = "📊"
                elif "presentation" in mime:
                    icon = "📽️"
                elif "pdf" in mime:
                    icon = "📕"
                elif "image" in mime:
                    icon = "🖼️"

                lines.append(f"- {icon} **{f['name']}**")
                lines.append(f"  - ID: `{f['id']}`")
                lines.append(f"  - Modified: {_format_datetime(f.get('modifiedTime'))}")
                if f.get("size"):
                    lines.append(f"  - Size: {_format_file_size(f.get('size'))}")
                if f.get("webViewLink"):
                    lines.append(f"  - [Open in Drive]({f['webViewLink']})")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list files: {e}"


async def _gdrive_search_impl(
    query: str,
    max_results: int = 10,
    file_type: str = "",
) -> str:
    """Search for files in Google Drive."""
    service, error = get_drive_service()
    if error:
        return f"❌ {error}"

    try:
        # Build search query - escape user input to prevent query injection
        escaped_query = _escape_drive_query(query)
        query_parts = [f"fullText contains '{escaped_query}'", "trashed = false"]

        if file_type:
            mime_types = {
                "doc": "application/vnd.google-apps.document",
                "sheet": "application/vnd.google-apps.spreadsheet",
                "slide": "application/vnd.google-apps.presentation",
                "pdf": "application/pdf",
            }
            if file_type.lower() in mime_types:
                query_parts.append(f"mimeType = '{mime_types[file_type.lower()]}'")

        search_query = " and ".join(query_parts)

        results = (
            service.files()
            .list(
                q=search_query,
                pageSize=max_results,
                fields="files(id, name, mimeType, size, modifiedTime, webViewLink, parents)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        files = results.get("files", [])

        if not files:
            return f"🔍 No files found matching '{query}'"

        lines = [
            f"# 🔍 Search Results for '{query}'",
            f"Found {len(files)} file(s)",
            "",
        ]

        for f in files:
            mime = f.get("mimeType", "")
            icon = "📄"
            if "document" in mime:
                icon = "📝"
            elif "spreadsheet" in mime:
                icon = "📊"
            elif "presentation" in mime:
                icon = "📽️"
            elif "pdf" in mime:
                icon = "📕"

            lines.append(f"## {icon} {f['name']}")
            lines.append(f"- **ID:** `{f['id']}`")
            lines.append(f"- **Modified:** {_format_datetime(f.get('modifiedTime'))}")
            if f.get("size"):
                lines.append(f"- **Size:** {_format_file_size(f.get('size'))}")
            if f.get("webViewLink"):
                lines.append(f"- **Link:** {f['webViewLink']}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Search failed: {e}"


async def _gdrive_get_file_content_impl(
    file_id: str,
    max_chars: int = 10000,
) -> str:
    """Get the text content of a Google Drive file."""
    service, error = get_drive_service()
    if error:
        return f"❌ {error}"

    try:
        # Get file metadata first
        file_meta = (
            service.files().get(fileId=file_id, fields="name, mimeType").execute()
        )
        name = file_meta.get("name", "Unknown")
        mime_type = file_meta.get("mimeType", "")

        # For Google Docs, Sheets, Slides - export as text
        if mime_type == "application/vnd.google-apps.document":
            content = (
                service.files().export(fileId=file_id, mimeType="text/plain").execute()
            )
            content = content.decode("utf-8") if isinstance(content, bytes) else content
        elif mime_type == "application/vnd.google-apps.spreadsheet":
            content = (
                service.files().export(fileId=file_id, mimeType="text/csv").execute()
            )
            content = content.decode("utf-8") if isinstance(content, bytes) else content
        elif mime_type == "application/vnd.google-apps.presentation":
            content = (
                service.files().export(fileId=file_id, mimeType="text/plain").execute()
            )
            content = content.decode("utf-8") if isinstance(content, bytes) else content
        elif mime_type == "text/plain" or mime_type.startswith("text/"):
            # Plain text files - download directly
            content = service.files().get_media(fileId=file_id).execute()
            content = content.decode("utf-8") if isinstance(content, bytes) else content
        else:
            return (
                f"❌ Cannot extract text from file type: {mime_type}\n"
                "Supported types: Google Docs, Sheets, Slides, plain text"
            )

        # Truncate if too long
        if len(content) > max_chars:
            content = (
                content[:max_chars] + f"\n\n... (truncated, {len(content)} total chars)"
            )

        lines = [
            f"# 📄 {name}",
            f"**Type:** {mime_type}",
            "",
            "---",
            "",
            content,
        ]

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to get file content: {e}"


async def _gdrive_get_file_info_impl(file_id: str) -> str:
    """Get detailed metadata for a Google Drive file."""
    service, error = get_drive_service()
    if error:
        return f"❌ {error}"

    try:
        file_meta = (
            service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, size, createdTime, modifiedTime, "
                "webViewLink, webContentLink, owners, lastModifyingUser, "
                "parents, description, starred",
            )
            .execute()
        )

        lines = [
            f"# 📄 {file_meta.get('name', 'Unknown')}",
            "",
            f"**ID:** `{file_meta.get('id')}`",
            f"**Type:** {file_meta.get('mimeType')}",
        ]

        if file_meta.get("size"):
            lines.append(f"**Size:** {_format_file_size(file_meta.get('size'))}")

        lines.append(f"**Created:** {_format_datetime(file_meta.get('createdTime'))}")
        lines.append(f"**Modified:** {_format_datetime(file_meta.get('modifiedTime'))}")

        if file_meta.get("owners"):
            owners = [
                o.get("displayName", o.get("emailAddress", "?"))
                for o in file_meta["owners"]
            ]
            lines.append(f"**Owner:** {', '.join(owners)}")

        if file_meta.get("lastModifyingUser"):
            user = file_meta["lastModifyingUser"]
            lines.append(
                f"**Last Modified By:** {user.get('displayName', user.get('emailAddress', '?'))}"
            )

        if file_meta.get("description"):
            lines.append(f"**Description:** {file_meta['description']}")

        if file_meta.get("starred"):
            lines.append("⭐ **Starred**")

        lines.append("")

        if file_meta.get("webViewLink"):
            lines.append(f"**View:** {file_meta['webViewLink']}")

        if file_meta.get("webContentLink"):
            lines.append(f"**Download:** {file_meta['webContentLink']}")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to get file info: {e}"


async def _gdrive_list_shared_impl(max_results: int = 20) -> str:
    """List files shared with you."""
    service, error = get_drive_service()
    if error:
        return f"❌ {error}"

    try:
        results = (
            service.files()
            .list(
                q="sharedWithMe = true and trashed = false",
                pageSize=max_results,
                fields="files(id, name, mimeType, size, modifiedTime, webViewLink, owners)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        files = results.get("files", [])

        if not files:
            return "📁 No files shared with you"

        lines = [
            "# 🤝 Shared With Me",
            f"Showing {len(files)} most recent",
            "",
        ]

        for f in files:
            mime = f.get("mimeType", "")
            icon = "📄"
            if "document" in mime:
                icon = "📝"
            elif "spreadsheet" in mime:
                icon = "📊"
            elif "presentation" in mime:
                icon = "📽️"
            elif "folder" in mime:
                icon = "📂"

            owner = ""
            if f.get("owners"):
                owner = f" (from {f['owners'][0].get('displayName', '?')})"

            lines.append(f"- {icon} **{f['name']}**{owner}")
            lines.append(f"  - ID: `{f['id']}`")
            lines.append(f"  - Modified: {_format_datetime(f.get('modifiedTime'))}")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list shared files: {e}"


async def _gdrive_list_recent_impl(max_results: int = 20) -> str:
    """List recently accessed files."""
    service, error = get_drive_service()
    if error:
        return f"❌ {error}"

    try:
        results = (
            service.files()
            .list(
                q="trashed = false",
                pageSize=max_results,
                fields="files(id, name, mimeType, size, modifiedTime, viewedByMeTime, webViewLink)",
                orderBy="viewedByMeTime desc",
            )
            .execute()
        )

        files = results.get("files", [])

        if not files:
            return "📁 No recent files"

        lines = [
            "# 🕐 Recent Files",
            f"Showing {len(files)} most recently viewed",
            "",
        ]

        for f in files:
            mime = f.get("mimeType", "")
            icon = "📄"
            if "document" in mime:
                icon = "📝"
            elif "spreadsheet" in mime:
                icon = "📊"
            elif "presentation" in mime:
                icon = "📽️"
            elif "folder" in mime:
                icon = "📂"

            lines.append(f"- {icon} **{f['name']}**")
            lines.append(f"  - ID: `{f['id']}`")
            viewed = f.get("viewedByMeTime")
            if viewed:
                lines.append(f"  - Viewed: {_format_datetime(viewed)}")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list recent files: {e}"


async def _gdrive_status_impl() -> str:
    """Check Google Drive integration status."""
    lines = [
        "# Google Drive Integration Status",
        "",
        f"**Config directory:** `{CONFIG_DIR}`",
        "",
    ]

    if CREDENTIALS_FILE.exists():
        lines.append("✅ OAuth credentials file found")
    else:
        lines.append("❌ OAuth credentials not found")
        lines.append(f"   Add `credentials.json` to `{CONFIG_DIR}`")

    if TOKEN_FILE.exists():
        lines.append("✅ OAuth token cached")
    else:
        lines.append("⚪ No cached token")

    lines.append("")

    service, error = get_drive_service()
    if service:
        lines.append("✅ **Connected to Google Drive**")
        try:
            about = service.about().get(fields="user, storageQuota").execute()
            user = about.get("user", {})
            lines.append(
                f"   User: {user.get('displayName', '?')} ({user.get('emailAddress', '?')})"
            )
            quota = about.get("storageQuota", {})
            if quota.get("limit"):
                used = int(quota.get("usage", 0))
                limit = int(quota.get("limit", 1))
                pct = (used / limit) * 100
                lines.append(
                    f"   Storage: {_format_file_size(used)} / {_format_file_size(limit)} ({pct:.1f}%)"
                )
        except Exception as e:
            lines.append(f"   (Could not fetch details: {e})")
    else:
        lines.append(f"❌ **Not connected:** {error}")

    return "\n".join(lines)


# ==================== TOOL REGISTRATION ====================


def register_tools(server: "FastMCP") -> int:
    """Register Google Drive tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def gdrive_list_files(
        folder_id: str = "root",
        max_results: int = 20,
        file_type: str = "",
    ) -> str:
        """
        List files in a Google Drive folder.

        Args:
            folder_id: Folder ID to list (default: "root" for My Drive)
            max_results: Maximum number of files to return (default: 20)
            file_type: Filter by type: "doc", "sheet", "slide", "pdf", "folder", "image"

        Returns:
            List of files with metadata
        """
        return await _gdrive_list_files_impl(folder_id, max_results, file_type)

    @registry.tool()
    async def gdrive_search(
        query: str,
        max_results: int = 10,
        file_type: str = "",
    ) -> str:
        """
        Search for files in Google Drive by name or content.

        Args:
            query: Search query (searches file names and content)
            max_results: Maximum number of results (default: 10)
            file_type: Filter by type: "doc", "sheet", "slide", "pdf"

        Returns:
            List of matching files
        """
        return await _gdrive_search_impl(query, max_results, file_type)

    @registry.tool()
    async def gdrive_get_file_content(
        file_id: str,
        max_chars: int = 10000,
    ) -> str:
        """
        Get the text content of a Google Drive file.

        Supports Google Docs, Sheets (as CSV), Slides, and plain text files.

        Args:
            file_id: The file ID to read
            max_chars: Maximum characters to return (default: 10000)

        Returns:
            File content as text
        """
        return await _gdrive_get_file_content_impl(file_id, max_chars)

    @registry.tool()
    async def gdrive_get_file_info(file_id: str) -> str:
        """
        Get detailed metadata for a Google Drive file.

        Args:
            file_id: The file ID to get info for

        Returns:
            File metadata including owner, dates, links
        """
        return await _gdrive_get_file_info_impl(file_id)

    @registry.tool()
    async def gdrive_list_shared() -> str:
        """
        List files shared with you.

        Returns:
            List of files others have shared with you
        """
        return await _gdrive_list_shared_impl()

    @registry.tool()
    async def gdrive_list_recent(max_results: int = 20) -> str:
        """
        List recently accessed files.

        Args:
            max_results: Maximum number of files (default: 20)

        Returns:
            List of recently viewed files
        """
        return await _gdrive_list_recent_impl(max_results)

    @registry.tool()
    async def gdrive_status() -> str:
        """
        Check Google Drive integration status.

        Returns:
            Connection status and storage info
        """
        return await _gdrive_status_impl()

    return registry.count
