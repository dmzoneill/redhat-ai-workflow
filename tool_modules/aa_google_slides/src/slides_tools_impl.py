# pylint: disable=duplicate-code
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

import asyncio
import logging
from pathlib import Path
from typing import Any

# Setup project path for server imports (must be before server imports)
from tool_modules.common import (
    PROJECT_ROOT,
    get_google_config_dir,
    get_google_oauth_scopes,
)

logger = logging.getLogger(__name__)

__project_root__ = PROJECT_ROOT  # Module initialization

# Shared Google config (single source of truth in tool_modules.common)
CONFIG_DIR = get_google_config_dir()
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"
SERVICE_ACCOUNT_FILE = CONFIG_DIR / "service_account.json"
SCOPES = get_google_oauth_scopes()


def _try_load_oauth_token(credentials_cls, scopes):
    """Try to load OAuth token from file."""
    if TOKEN_FILE.exists():
        try:
            return credentials_cls.from_authorized_user_file(str(TOKEN_FILE), scopes)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Auth libraries raise provider-specific errors; fall through.
            logger.debug("Suppressed error in _try_load_oauth_token: %s", exc, exc_info=True)
    return None


def _try_refresh_credentials(creds, request_cls):
    """Try to refresh expired credentials."""
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(request_cls())
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            return creds
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Token refresh raises provider-specific errors; fall through.
            logger.debug("Suppressed error in _try_refresh_credentials: %s", exc, exc_info=True)
    return None


def _try_service_account(service_account, scopes):
    """Try to load service account credentials."""
    if SERVICE_ACCOUNT_FILE.exists():
        try:
            return service_account.Credentials.from_service_account_file(str(SERVICE_ACCOUNT_FILE), scopes=scopes)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Service-account load raises provider-specific errors; fall through.
            logger.debug("Suppressed error in _try_service_account: %s", exc, exc_info=True)
    return None


def _shared__try_oauth_flow(scopes):
    """Try to run OAuth flow for new credentials."""
    if CREDENTIALS_FILE.exists():
        try:
            # Optional dependency: installed only when Google OAuth is configured.
            from google_auth_oauthlib.flow import (  # pylint: disable=import-outside-toplevel
                InstalledAppFlow,
            )

            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), scopes)
            creds = flow.run_local_server(port=0)
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            return creds, None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # OAuth libraries raise provider-specific errors; return them as text.
            logger.exception("OAuth flow failed")
            return None, f"OAuth flow failed: {exc}"
    return None, f"No credentials found. Add credentials.json to {CONFIG_DIR}"


def _try_oauth_flow(scopes):
    return _shared__try_oauth_flow(scopes)


_try_oauth_flow.__doc__ = _shared__try_oauth_flow.__doc__


def _build_google_service(api: str, version: str, label: str):
    """Return an authenticated Google API service, or an error message."""
    try:
        # Optional dependency: Google API client libraries.
        from google.auth.transport.requests import (  # pylint: disable=import-outside-toplevel
            Request,
        )
        from google.oauth2 import (  # pylint: disable=import-outside-toplevel
            service_account,
        )
        from google.oauth2.credentials import (  # pylint: disable=import-outside-toplevel
            Credentials,
        )
        from googleapiclient.discovery import (  # pylint: disable=import-outside-toplevel
            build,
        )
    except ImportError:
        return (
            None,
            (
                "Google API libraries not installed. Run: "
                "uv add google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            ),
        )

    creds = _try_load_oauth_token(Credentials, SCOPES)
    refreshed = _try_refresh_credentials(creds, Request)
    if refreshed:
        creds = refreshed
    if not creds:
        creds = _try_service_account(service_account, SCOPES)

    if not creds or not creds.valid:
        creds, error = _try_oauth_flow(SCOPES)
        if error:
            return None, error

    try:
        service = build(api, version, credentials=creds)
        return service, None
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # API boundary: surface client/auth failures as a message.
        logger.exception("Failed to build %s service", label)
        return None, f"Failed to build {label} service: {exc}"


def get_slides_service():
    """Get authenticated Google Slides service."""
    return _build_google_service("slides", "v1", "slides")


def get_drive_service():
    """Get authenticated Google Drive service."""
    return _build_google_service("drive", "v3", "drive")


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

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to list presentations")
        return f"❌ Failed to list presentations: {e}"


async def _google_slides_get_impl(  # pylint: disable=too-many-locals
    presentation_id: str,
) -> str:
    """Get details of a specific presentation."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:  # pylint: disable=too-many-nested-blocks
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

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to get presentation")
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

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to create presentation")
        return f"❌ Failed to create presentation: {e}"


async def _google_slides_add_slide_impl(  # pylint: disable=too-many-branches,too-many-locals
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

    try:  # pylint: disable=too-many-nested-blocks
        # Generate unique object ID
        import uuid  # pylint: disable=import-outside-toplevel

        slide_id = f"slide_{uuid.uuid4().hex[:8]}"

        requests: list[dict[str, Any]] = [
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
        service.presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()

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

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to add slide")
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
        requests: list[dict[str, Any]] = []

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

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to update text")
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

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to delete slide")
        return f"❌ Failed to delete slide: {e}"


async def _google_slides_add_text_box_impl(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
        import uuid  # pylint: disable=import-outside-toplevel

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

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to add text box")
        return f"❌ Failed to add text box: {e}"


async def _google_slides_export_pdf_impl(  # pylint: disable=too-many-locals
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
        from io import BytesIO  # pylint: disable=import-outside-toplevel

        from googleapiclient.http import (  # pylint: disable=import-outside-toplevel
            MediaIoBaseDownload,
        )

        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        # Write to file
        pdf_path = Path(output_path).expanduser()
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(pdf_path.write_bytes, fh.getvalue())

        lines = [
            "✅ **PDF Exported**",
            "",
            f"**Presentation:** {title}",
            f"**Output:** `{pdf_path}`",
            f"**Size:** {len(fh.getvalue()) / 1024:.1f} KB",
        ]

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to export PDF")
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
        import uuid  # pylint: disable=import-outside-toplevel

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

            elif line.startswith(("- ", "  - ")):
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

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to build slides")
        return f"❌ Failed to build slides: {e}"
