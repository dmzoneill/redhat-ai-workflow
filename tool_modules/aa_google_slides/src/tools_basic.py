"""
Google Slides MCP Tools

Provides tools for creating and managing Google Slides presentations.

Features:
- List presentations from Google Drive
- Create new presentations from templates or scratch
- Add/edit/delete slides
- Update slide content (text, images, shapes)
- Export presentations to PDF

Setup:
1. Uses same OAuth credentials as Google Calendar
2. Requires presentations and drive.file scopes (already in calendar config)
3. Run google_slides_status() to verify authentication
"""

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from server.tool_registry import ToolRegistry
from server.utils import load_config

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource


def _get_google_config_dir() -> Path:
    """Get Google config directory from config.json or default."""
    config = load_config()
    # Check google_calendar.config_dir (shared OAuth)
    gc_config = config.get("google_calendar", {}).get("config_dir")
    if gc_config:
        return Path(os.path.expanduser(gc_config))
    # Fallback to paths.google_calendar_config
    paths_cfg = config.get("paths", {})
    gc_config = paths_cfg.get("google_calendar_config")
    if gc_config:
        return Path(os.path.expanduser(gc_config))
    # Default
    return Path.home() / ".config" / "google-calendar"


# Config paths - use shared OAuth with Google Calendar
CONFIG_DIR = _get_google_config_dir()
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"
SERVICE_ACCOUNT_FILE = CONFIG_DIR / "service_account.json"

# Scopes required (same as calendar - presentations and drive.file already included)
SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/presentations.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _try_load_oauth_token(credentials_cls, scopes):
    """Try to load OAuth token from file."""
    if TOKEN_FILE.exists():
        try:
            return credentials_cls.from_authorized_user_file(str(TOKEN_FILE), scopes)
        except Exception:
            pass
    return None


def _try_refresh_credentials(creds, request_cls):
    """Try to refresh expired credentials."""
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(request_cls())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            return creds
        except Exception:
            pass
    return None


def _try_service_account(service_account, scopes):
    """Try to load service account credentials."""
    if SERVICE_ACCOUNT_FILE.exists():
        try:
            return service_account.Credentials.from_service_account_file(str(SERVICE_ACCOUNT_FILE), scopes=scopes)
        except Exception:
            pass
    return None


def _try_oauth_flow(scopes):
    """Try to run OAuth flow for new credentials."""
    if CREDENTIALS_FILE.exists():
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow

            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), scopes)
            creds = flow.run_local_server(port=0)
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            return creds, None
        except Exception as e:
            return None, f"OAuth flow failed: {e}"
    return None, f"No credentials found. Add credentials.json to {CONFIG_DIR}"


def get_slides_service() -> tuple["Resource | None", str | None]:
    """
    Get authenticated Google Slides service.

    Returns:
        Tuple of (service, error_message). Service is None if auth failed.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return (
            None,
            "Google API libraries not installed. Run: "
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib",
        )

    # Try OAuth token, refresh if needed, then service account
    creds = _try_load_oauth_token(Credentials, SCOPES)
    refreshed = _try_refresh_credentials(creds, Request)
    if refreshed:
        creds = refreshed
    if not creds:
        creds = _try_service_account(service_account, SCOPES)

    # Need to authenticate with OAuth flow
    if not creds or not creds.valid:
        creds, error = _try_oauth_flow(SCOPES)
        if error:
            return None, error

    try:
        service = build("slides", "v1", credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Failed to build slides service: {e}"


def get_drive_service() -> tuple["Resource | None", str | None]:
    """
    Get authenticated Google Drive service.

    Returns:
        Tuple of (service, error_message). Service is None if auth failed.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return (
            None,
            "Google API libraries not installed. Run: "
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib",
        )

    # Try OAuth token, refresh if needed, then service account
    creds = _try_load_oauth_token(Credentials, SCOPES)
    refreshed = _try_refresh_credentials(creds, Request)
    if refreshed:
        creds = refreshed
    if not creds:
        creds = _try_service_account(service_account, SCOPES)

    # Need to authenticate with OAuth flow
    if not creds or not creds.valid:
        creds, error = _try_oauth_flow(SCOPES)
        if error:
            return None, error

    try:
        service = build("drive", "v3", credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Failed to build drive service: {e}"


# ==================== TOOL IMPLEMENTATIONS ====================


async def _google_slides_status_impl() -> str:
    """Check Google Slides integration status and configuration."""
    lines = [
        "# Google Slides Integration Status",
        "",
        f"**Config directory:** `{CONFIG_DIR}`",
        "",
    ]

    # Check credentials
    if CREDENTIALS_FILE.exists():
        lines.append("✅ OAuth credentials file found")
    else:
        lines.append("❌ OAuth credentials not found")
        lines.append(f"   Add `credentials.json` to `{CONFIG_DIR}`")

    if SERVICE_ACCOUNT_FILE.exists():
        lines.append("✅ Service account file found")
    else:
        lines.append("⚪ Service account not configured (optional)")

    if TOKEN_FILE.exists():
        lines.append("✅ OAuth token cached (authenticated)")
    else:
        lines.append("⚪ No cached token (will need to authenticate)")

    lines.append("")

    # Try to connect
    service, error = get_slides_service()

    if service:
        lines.append("✅ **Connected to Google Slides API**")
    else:
        lines.append(f"❌ **Not connected:** {error}")

    # Check Drive connection
    drive_service, drive_error = get_drive_service()
    if drive_service:
        lines.append("✅ **Connected to Google Drive API**")
    else:
        lines.append(f"❌ **Drive not connected:** {drive_error}")

    lines.append("")
    lines.append("## Required Scopes")
    lines.append("")
    for scope in SCOPES:
        lines.append(f"- `{scope}`")

    lines.append("")
    lines.append("## Setup Instructions")
    lines.append("")
    lines.append("Google Slides uses the same OAuth as Google Calendar.")
    lines.append("If Calendar is working, Slides should work too.")
    lines.append("")
    lines.append("If not authenticated:")
    lines.append("1. Delete `~/.config/google-calendar/token.json`")
    lines.append("2. Run `google_calendar_status()` to re-authenticate")
    lines.append("3. Approve the additional scopes for Slides and Drive")

    return "\n".join(lines)


async def _google_slides_list_impl(
    max_results: int = 20,
    search_query: str = "",
) -> str:
    """List Google Slides presentations from Drive."""
    drive_service, error = get_drive_service()

    if error:
        return f"❌ {error}"

    if not drive_service:
        return "❌ Google Drive service not available"

    try:
        # Build query for Google Slides files
        query = "mimeType='application/vnd.google-apps.presentation'"
        if search_query:
            query += f" and name contains '{search_query}'"

        results = (
            drive_service.files()
            .list(
                q=query,
                pageSize=max_results,
                fields="files(id, name, modifiedTime, webViewLink, owners)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        files = results.get("files", [])

        if not files:
            if search_query:
                return f"📊 No presentations found matching '{search_query}'"
            return "📊 No presentations found in your Drive"

        lines = [
            "# 📊 Your Google Slides Presentations",
            "",
            f"Found {len(files)} presentation(s)",
            "",
        ]

        for f in files:
            modified = f.get("modifiedTime", "")[:10]
            name = f.get("name", "Untitled")
            file_id = f.get("id", "")
            link = f.get("webViewLink", "")

            lines.append(f"## {name}")
            lines.append(f"- **ID:** `{file_id}`")
            lines.append(f"- **Modified:** {modified}")
            lines.append(f"- **Link:** {link}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("**To view a presentation:**")
        lines.append("```")
        lines.append(f'google_slides_get("{files[0]["id"]}")')
        lines.append("```")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list presentations: {e}"


async def _google_slides_get_impl(
    presentation_id: str,
) -> str:
    """Get details of a specific presentation."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        presentation = service.presentations().get(presentationId=presentation_id).execute()

        title = presentation.get("title", "Untitled")
        slides = presentation.get("slides", [])
        page_size = presentation.get("pageSize", {})

        width = page_size.get("width", {}).get("magnitude", 0)
        height = page_size.get("height", {}).get("magnitude", 0)
        unit = page_size.get("width", {}).get("unit", "EMU")

        lines = [
            f"# 📊 {title}",
            "",
            f"**Presentation ID:** `{presentation_id}`",
            f"**Total Slides:** {len(slides)}",
            f"**Page Size:** {width} x {height} {unit}",
            f"**Link:** https://docs.google.com/presentation/d/{presentation_id}/edit",
            "",
            "## Slides",
            "",
        ]

        for i, slide in enumerate(slides, 1):
            slide_id = slide.get("objectId", "")
            page_elements = slide.get("pageElements", [])

            # Try to extract title from first text element
            slide_title = f"Slide {i}"
            for elem in page_elements:
                if "shape" in elem:
                    shape = elem["shape"]
                    if "text" in shape:
                        text_content = shape["text"].get("textElements", [])
                        for text_elem in text_content:
                            if "textRun" in text_elem:
                                content = text_elem["textRun"].get("content", "").strip()
                                if content and len(content) < 100:
                                    slide_title = content[:50]
                                    break
                        break

            lines.append(f"### {i}. {slide_title}")
            lines.append(f"- **Slide ID:** `{slide_id}`")
            lines.append(f"- **Elements:** {len(page_elements)}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        error_str = str(e)
        if "404" in error_str or "notFound" in error_str:
            return f"❌ Presentation not found: `{presentation_id}`"
        return f"❌ Failed to get presentation: {e}"


async def _google_slides_create_impl(
    title: str,
    template_id: str = "",
) -> str:
    """Create a new presentation."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        if template_id:
            # Copy from template
            drive_service, drive_error = get_drive_service()
            if drive_error:
                return f"❌ {drive_error}"

            copied = drive_service.files().copy(fileId=template_id, body={"name": title}).execute()
            presentation_id = copied.get("id")
        else:
            # Create blank presentation
            body = {"title": title}
            presentation = service.presentations().create(body=body).execute()
            presentation_id = presentation.get("presentationId")

        link = f"https://docs.google.com/presentation/d/{presentation_id}/edit"

        lines = [
            "✅ **Presentation Created**",
            "",
            f"**Title:** {title}",
            f"**ID:** `{presentation_id}`",
            f"**Link:** {link}",
            "",
        ]

        if template_id:
            lines.append(f"📋 Copied from template: `{template_id}`")
        else:
            lines.append("📄 Created blank presentation")

        lines.append("")
        lines.append("**Next steps:**")
        lines.append("```")
        lines.append(f'google_slides_add_slide("{presentation_id}", "TITLE_AND_BODY")')
        lines.append("```")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to create presentation: {e}"


async def _google_slides_add_slide_impl(
    presentation_id: str,
    layout: str = "BLANK",
    title: str = "",
    body: str = "",
    insert_at: int = -1,
) -> str:
    """Add a new slide to a presentation."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    # Valid predefined layouts
    valid_layouts = [
        "BLANK",
        "CAPTION_ONLY",
        "TITLE",
        "TITLE_AND_BODY",
        "TITLE_AND_TWO_COLUMNS",
        "TITLE_ONLY",
        "SECTION_HEADER",
        "SECTION_TITLE_AND_DESCRIPTION",
        "ONE_COLUMN_TEXT",
        "MAIN_POINT",
        "BIG_NUMBER",
    ]

    if layout.upper() not in valid_layouts:
        return f"❌ Invalid layout. Valid options: {', '.join(valid_layouts)}"

    try:
        # Generate unique object ID
        import uuid

        slide_id = f"slide_{uuid.uuid4().hex[:8]}"

        requests = [
            {
                "createSlide": {
                    "objectId": slide_id,
                    "slideLayoutReference": {"predefinedLayout": layout.upper()},
                }
            }
        ]

        # If insert_at specified, add insertion index
        if insert_at >= 0:
            requests[0]["createSlide"]["insertionIndex"] = insert_at

        # Execute slide creation
        response = (
            service.presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()
        )

        # If title or body provided, add text
        if title or body:
            # Get the slide to find placeholder IDs
            presentation = service.presentations().get(presentationId=presentation_id).execute()

            text_requests = []
            for slide in presentation.get("slides", []):
                if slide.get("objectId") == slide_id:
                    for elem in slide.get("pageElements", []):
                        placeholder = elem.get("shape", {}).get("placeholder", {})
                        placeholder_type = placeholder.get("type", "")
                        elem_id = elem.get("objectId", "")

                        if placeholder_type == "TITLE" and title:
                            text_requests.append(
                                {
                                    "insertText": {
                                        "objectId": elem_id,
                                        "text": title,
                                        "insertionIndex": 0,
                                    }
                                }
                            )
                        elif placeholder_type == "BODY" and body:
                            text_requests.append(
                                {
                                    "insertText": {
                                        "objectId": elem_id,
                                        "text": body,
                                        "insertionIndex": 0,
                                    }
                                }
                            )

            if text_requests:
                service.presentations().batchUpdate(
                    presentationId=presentation_id, body={"requests": text_requests}
                ).execute()

        lines = [
            "✅ **Slide Added**",
            "",
            f"**Slide ID:** `{slide_id}`",
            f"**Layout:** {layout}",
        ]

        if title:
            lines.append(f"**Title:** {title}")
        if body:
            lines.append(f"**Body:** {body[:50]}...")

        lines.append("")
        lines.append(f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to add slide: {e}"


async def _google_slides_update_text_impl(
    presentation_id: str,
    object_id: str,
    text: str,
    replace_all: bool = True,
) -> str:
    """Update text in a slide element."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        requests = []

        if replace_all:
            # Delete all existing text first
            requests.append(
                {
                    "deleteText": {
                        "objectId": object_id,
                        "textRange": {"type": "ALL"},
                    }
                }
            )

        # Insert new text
        requests.append(
            {
                "insertText": {
                    "objectId": object_id,
                    "text": text,
                    "insertionIndex": 0,
                }
            }
        )

        service.presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()

        lines = [
            "✅ **Text Updated**",
            "",
            f"**Object ID:** `{object_id}`",
            f"**New Text:** {text[:100]}{'...' if len(text) > 100 else ''}",
            "",
            f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit",
        ]

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to update text: {e}"


async def _google_slides_delete_slide_impl(
    presentation_id: str,
    slide_id: str,
) -> str:
    """Delete a slide from a presentation."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        requests = [{"deleteObject": {"objectId": slide_id}}]

        service.presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()

        lines = [
            "✅ **Slide Deleted**",
            "",
            f"**Deleted Slide ID:** `{slide_id}`",
            "",
            f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit",
        ]

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to delete slide: {e}"


async def _google_slides_add_text_box_impl(
    presentation_id: str,
    slide_id: str,
    text: str,
    x: float = 100,
    y: float = 100,
    width: float = 300,
    height: float = 50,
) -> str:
    """Add a text box to a slide."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        import uuid

        element_id = f"textbox_{uuid.uuid4().hex[:8]}"

        # Convert points to EMU (914400 EMU per inch, 72 points per inch)
        emu_per_pt = 914400 / 72

        requests = [
            {
                "createShape": {
                    "objectId": element_id,
                    "shapeType": "TEXT_BOX",
                    "elementProperties": {
                        "pageObjectId": slide_id,
                        "size": {
                            "width": {"magnitude": width * emu_per_pt, "unit": "EMU"},
                            "height": {"magnitude": height * emu_per_pt, "unit": "EMU"},
                        },
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": x * emu_per_pt,
                            "translateY": y * emu_per_pt,
                            "unit": "EMU",
                        },
                    },
                }
            },
            {
                "insertText": {
                    "objectId": element_id,
                    "text": text,
                    "insertionIndex": 0,
                }
            },
        ]

        service.presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()

        lines = [
            "✅ **Text Box Added**",
            "",
            f"**Element ID:** `{element_id}`",
            f"**Text:** {text[:50]}{'...' if len(text) > 50 else ''}",
            f"**Position:** ({x}, {y})",
            f"**Size:** {width} x {height}",
            "",
            f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit",
        ]

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to add text box: {e}"


async def _google_slides_export_pdf_impl(
    presentation_id: str,
    output_path: str = "",
) -> str:
    """Export a presentation to PDF."""
    drive_service, error = get_drive_service()

    if error:
        return f"❌ {error}"

    if not drive_service:
        return "❌ Google Drive service not available"

    try:
        # Get presentation title for filename
        slides_service, _ = get_slides_service()
        if slides_service:
            presentation = slides_service.presentations().get(presentationId=presentation_id).execute()
            title = presentation.get("title", "presentation")
        else:
            title = "presentation"

        # Sanitize filename
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()

        if not output_path:
            output_path = f"{safe_title}.pdf"

        # Export as PDF
        request = drive_service.files().export_media(fileId=presentation_id, mimeType="application/pdf")

        # Download the file
        from io import BytesIO

        from googleapiclient.http import MediaIoBaseDownload

        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        # Write to file
        output_path = Path(output_path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "wb") as f:
            f.write(fh.getvalue())

        lines = [
            "✅ **PDF Exported**",
            "",
            f"**Presentation:** {title}",
            f"**Output:** `{output_path}`",
            f"**Size:** {len(fh.getvalue()) / 1024:.1f} KB",
        ]

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to export PDF: {e}"


async def _google_slides_build_from_outline_impl(
    presentation_id: str,
    outline: str,
) -> str:
    """Build slides from a markdown-style outline.

    Outline format:
    # Section Title (creates section header slide)
    ## Slide Title
    - Bullet point 1
    - Bullet point 2
      - Sub-bullet
    """
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        import uuid

        lines_in = outline.strip().split("\n")
        slides_created = 0
        requests = []

        current_title = ""
        current_bullets = []

        def flush_slide():
            nonlocal slides_created, current_title, current_bullets
            if not current_title:
                return

            slide_id = f"slide_{uuid.uuid4().hex[:8]}"

            # Create slide
            requests.append(
                {
                    "createSlide": {
                        "objectId": slide_id,
                        "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                    }
                }
            )
            slides_created += 1

            current_title = ""
            current_bullets = []

        for line in lines_in:
            line = line.rstrip()
            if not line:
                continue

            if line.startswith("# "):
                # Section header
                flush_slide()
                section_title = line[2:].strip()

                slide_id = f"slide_{uuid.uuid4().hex[:8]}"
                requests.append(
                    {
                        "createSlide": {
                            "objectId": slide_id,
                            "slideLayoutReference": {"predefinedLayout": "SECTION_HEADER"},
                        }
                    }
                )
                slides_created += 1

            elif line.startswith("## "):
                # New slide title
                flush_slide()
                current_title = line[3:].strip()

            elif line.startswith("- ") or line.startswith("  - "):
                # Bullet point
                current_bullets.append(line)

        # Flush last slide
        flush_slide()

        if not requests:
            return "❌ No valid slides found in outline. Use # for sections, ## for slide titles."

        # Execute all requests
        service.presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()

        lines = [
            "✅ **Slides Built from Outline**",
            "",
            f"**Slides Created:** {slides_created}",
            f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit",
            "",
            "Note: Text content needs to be added separately using `google_slides_update_text`",
        ]

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to build slides: {e}"


# ==================== TOOL REGISTRATION ====================


def register_tools(server: "FastMCP") -> int:
    """Register Google Slides tools with the MCP server.

    Args:
        server: FastMCP server instance to register tools with

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    @registry.tool()
    async def google_slides_status() -> str:
        """
        Check Google Slides integration status and configuration.

        Returns:
            Configuration status and setup instructions if needed
        """
        return await _google_slides_status_impl()

    @registry.tool()
    async def google_slides_list(
        max_results: int = 20,
        search_query: str = "",
    ) -> str:
        """
        List Google Slides presentations from your Drive.

        Args:
            max_results: Maximum number of presentations to return (default: 20)
            search_query: Optional search term to filter by name

        Returns:
            List of presentations with IDs and links
        """
        return await _google_slides_list_impl(max_results, search_query)

    @registry.tool()
    async def google_slides_get(
        presentation_id: str,
    ) -> str:
        """
        Get details of a specific presentation including all slides.

        Args:
            presentation_id: The presentation ID (from google_slides_list or URL)

        Returns:
            Presentation details and slide listing
        """
        return await _google_slides_get_impl(presentation_id)

    @registry.tool()
    async def google_slides_create(
        title: str,
        template_id: str = "",
    ) -> str:
        """
        Create a new Google Slides presentation.

        Args:
            title: Title for the new presentation
            template_id: Optional - ID of an existing presentation to use as template

        Returns:
            New presentation ID and link
        """
        return await _google_slides_create_impl(title, template_id)

    @registry.tool()
    async def google_slides_add_slide(
        presentation_id: str,
        layout: str = "BLANK",
        title: str = "",
        body: str = "",
        insert_at: int = -1,
    ) -> str:
        """
        Add a new slide to a presentation.

        Args:
            presentation_id: The presentation ID
            layout: Slide layout (BLANK, TITLE, TITLE_AND_BODY, SECTION_HEADER, etc.)
            title: Optional title text for the slide
            body: Optional body text for the slide
            insert_at: Position to insert (-1 for end)

        Returns:
            New slide ID and confirmation
        """
        return await _google_slides_add_slide_impl(presentation_id, layout, title, body, insert_at)

    @registry.tool()
    async def google_slides_update_text(
        presentation_id: str,
        object_id: str,
        text: str,
        replace_all: bool = True,
    ) -> str:
        """
        Update text in a slide element (text box, title, body).

        Args:
            presentation_id: The presentation ID
            object_id: The element ID to update (from google_slides_get)
            text: New text content
            replace_all: Replace all existing text (default: True)

        Returns:
            Confirmation of text update
        """
        return await _google_slides_update_text_impl(presentation_id, object_id, text, replace_all)

    @registry.tool()
    async def google_slides_delete_slide(
        presentation_id: str,
        slide_id: str,
    ) -> str:
        """
        Delete a slide from a presentation.

        Args:
            presentation_id: The presentation ID
            slide_id: The slide ID to delete (from google_slides_get)

        Returns:
            Confirmation of deletion
        """
        return await _google_slides_delete_slide_impl(presentation_id, slide_id)

    @registry.tool()
    async def google_slides_add_text_box(
        presentation_id: str,
        slide_id: str,
        text: str,
        x: float = 100,
        y: float = 100,
        width: float = 300,
        height: float = 50,
    ) -> str:
        """
        Add a text box to a slide at a specific position.

        Args:
            presentation_id: The presentation ID
            slide_id: The slide ID to add the text box to
            text: Text content for the text box
            x: X position in points (default: 100)
            y: Y position in points (default: 100)
            width: Width in points (default: 300)
            height: Height in points (default: 50)

        Returns:
            New text box element ID
        """
        return await _google_slides_add_text_box_impl(presentation_id, slide_id, text, x, y, width, height)

    @registry.tool()
    async def google_slides_export_pdf(
        presentation_id: str,
        output_path: str = "",
    ) -> str:
        """
        Export a presentation to PDF.

        Args:
            presentation_id: The presentation ID
            output_path: Output file path (default: uses presentation title)

        Returns:
            Path to exported PDF file
        """
        return await _google_slides_export_pdf_impl(presentation_id, output_path)

    @registry.tool()
    async def google_slides_build_from_outline(
        presentation_id: str,
        outline: str,
    ) -> str:
        """
        Build slides from a markdown-style outline.

        Creates slides based on markdown headings:
        - # Section Title -> Section header slide
        - ## Slide Title -> Title and body slide
        - Bullet points are noted but need separate text updates

        Args:
            presentation_id: The presentation ID to add slides to
            outline: Markdown-style outline text

        Returns:
            Number of slides created
        """
        return await _google_slides_build_from_outline_impl(presentation_id, outline)

    return registry.count
