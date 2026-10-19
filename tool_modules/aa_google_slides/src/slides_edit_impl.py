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

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from fastmcp import FastMCP  # noqa: E402  # pylint: disable=wrong-import-position

# Setup project path for server imports (must be before server imports)
from tool_modules.common import (  # noqa: E402  # pylint: disable=wrong-import-position
    PROJECT_ROOT,
)

__project_root__ = PROJECT_ROOT  # Module initialization

# pylint: disable-next=wrong-import-position
from server.tool_registry import (  # noqa: E402
    ToolRegistry,
)

if TYPE_CHECKING:
    pass

# pylint: disable-next=ungrouped-imports,wrong-import-position
from tool_modules.aa_google_slides.src.slides_tools_impl import (  # noqa: E402
    _google_slides_add_slide_impl,
    _google_slides_add_text_box_impl,
    _google_slides_build_from_outline_impl,
    _google_slides_create_impl,
    _google_slides_delete_slide_impl,
    _google_slides_export_pdf_impl,
    _google_slides_get_impl,
    _google_slides_list_impl,
    _google_slides_status_impl,
    _google_slides_update_text_impl,
    get_drive_service,
    get_slides_service,
)


async def _google_slides_get_slide_impl(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    presentation_id: str,
    slide_id: str,
) -> str:
    """Get detailed information about a specific slide."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:  # pylint: disable=too-many-nested-blocks
        presentation = (
            service.presentations().get(presentationId=presentation_id).execute()
        )

        # Find the slide
        target_slide = None
        slide_index = 0
        for i, slide in enumerate(presentation.get("slides", []), 1):
            if slide.get("objectId") == slide_id:
                target_slide = slide
                slide_index = i
                break

        if not target_slide:
            return f"❌ Slide not found: `{slide_id}`"

        lines = [
            f"# Slide {slide_index}: `{slide_id}`",
            "",
            f"**Presentation:** {presentation.get('title', 'Untitled')}",
            "",
            "## Elements",
            "",
        ]

        for elem in target_slide.get("pageElements", []):
            elem_id = elem.get("objectId", "")
            elem_type = "unknown"
            details = ""

            if "shape" in elem:
                shape = elem["shape"]
                shape_type = shape.get("shapeType", "SHAPE")
                elem_type = f"shape ({shape_type})"

                # Get placeholder info
                placeholder = shape.get("placeholder", {})
                if placeholder:
                    elem_type = f"placeholder ({placeholder.get('type', 'UNKNOWN')})"

                # Get text content
                if "text" in shape:
                    text_content = []
                    for text_element in shape["text"].get("textElements", []):
                        if "textRun" in text_element:
                            text_content.append(
                                text_element["textRun"].get("content", "").strip()
                            )
                    if text_content:
                        preview = " ".join(text_content)[:80]
                        details = (
                            f'Text: "{preview}..."'
                            if len(preview) >= 80
                            else f'Text: "{preview}"'
                        )

            elif "image" in elem:
                elem_type = "image"
                image = elem["image"]
                source_url = image.get("sourceUrl", "")
                if source_url:
                    details = f"Source: {source_url[:60]}..."

            elif "table" in elem:
                table = elem["table"]
                rows = table.get("rows", 0)
                cols = table.get("columns", 0)
                elem_type = f"table ({rows}x{cols})"

            elif "line" in elem:
                elem_type = "line"

            elif "video" in elem:
                elem_type = "video"

            # Get position/size
            size = elem.get("size", {})

            lines.append(f"### `{elem_id}`")
            lines.append(f"- **Type:** {elem_type}")
            if details:
                lines.append(f"- **{details}**")
            if size:
                w = size.get("width", {}).get("magnitude", 0)
                h = size.get("height", {}).get("magnitude", 0)
                # Convert EMU to points (914400 EMU per inch, 72 points per inch)
                w_pt = w / 914400 * 72
                h_pt = h / 914400 * 72
                lines.append(f"- **Size:** {w_pt:.0f} x {h_pt:.0f} pt")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"❌ Failed to get slide: {e}"


# pylint: disable-next=too-many-arguments,too-many-locals,too-many-positional-arguments
async def _google_slides_add_image_impl(
    presentation_id: str,
    slide_id: str,
    image_url: str,
    x: float = 100,
    y: float = 100,
    width: float = 400,
    height: float = 300,
) -> str:
    """Add an image to a slide from a URL."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        import uuid  # pylint: disable=import-outside-toplevel

        element_id = f"image_{uuid.uuid4().hex[:8]}"

        # Convert points to EMU (914400 EMU per inch, 72 points per inch)
        emu_per_pt = 914400 / 72

        requests = [
            {
                "createImage": {
                    "objectId": element_id,
                    "url": image_url,
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
            }
        ]

        service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": requests}
        ).execute()

        lines = [
            "✅ **Image Added**",
            "",
            f"**Element ID:** `{element_id}`",
            f"**Position:** ({x}, {y}) pt",
            f"**Size:** {width} x {height} pt",
            f"**Source:** {image_url[:80]}...",
            "",
            f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit",
        ]

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        error_str = str(e)
        if "INVALID_URL" in error_str or "Could not fetch" in error_str:
            return (
                "❌ Invalid or inaccessible image URL. "
                "The URL must be publicly accessible.\n\n"
                f"URL: {image_url}\n\n"
                "Tip: Upload the image to Google Drive and use "
                "google_slides_add_image_from_drive instead."
            )
        return f"❌ Failed to add image: {e}"


# pylint: disable-next=too-many-arguments,too-many-locals,too-many-positional-arguments
async def _google_slides_add_image_from_drive_impl(
    presentation_id: str,
    slide_id: str,
    drive_file_id: str,
    x: float = 100,
    y: float = 100,
    width: float = 400,
    height: float = 300,
) -> str:
    """Add an image to a slide from Google Drive."""
    service, error = get_slides_service()
    drive_service, drive_error = get_drive_service()

    if error:
        return f"❌ {error}"
    if drive_error:
        return f"❌ {drive_error}"

    if not service or not drive_service:
        return "❌ Google services not available"

    try:
        import uuid  # pylint: disable=import-outside-toplevel

        element_id = f"image_{uuid.uuid4().hex[:8]}"

        # Get the Drive file's web content link
        file_info = (
            drive_service.files()
            .get(fileId=drive_file_id, fields="webContentLink,name,mimeType")
            .execute()
        )

        # For images in Drive, we need to use the export link format
        # or make the file publicly accessible
        image_url = f"https://drive.google.com/uc?export=view&id={drive_file_id}"

        # Convert points to EMU
        emu_per_pt = 914400 / 72

        requests = [
            {
                "createImage": {
                    "objectId": element_id,
                    "url": image_url,
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
            }
        ]

        service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": requests}
        ).execute()

        lines = [
            "✅ **Image Added from Drive**",
            "",
            f"**Element ID:** `{element_id}`",
            f"**File:** {file_info.get('name', 'Unknown')}",
            f"**Position:** ({x}, {y}) pt",
            f"**Size:** {width} x {height} pt",
            "",
            f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit",
        ]

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        error_str = str(e)
        if "Could not fetch" in error_str:
            return (
                "❌ Could not access Drive file. "
                "Make sure the file is shared or you have access.\n\n"
                f"File ID: {drive_file_id}\n\n"
                "Tip: Share the file with 'Anyone with the link' "
                "or use google_slides_upload_image."
            )
        return f"❌ Failed to add image from Drive: {e}"


# pylint: disable-next=too-many-arguments,too-many-locals,too-many-positional-arguments
async def _google_slides_upload_image_impl(
    presentation_id: str,
    slide_id: str,
    local_path: str,
    x: float = 100,
    y: float = 100,
    width: float = 400,
    height: float = 300,
) -> str:
    """Upload a local image file and add it to a slide."""
    from pathlib import Path  # pylint: disable=import-outside-toplevel

    drive_service, drive_error = get_drive_service()

    if drive_error:
        return f"❌ {drive_error}"

    if not drive_service:
        return "❌ Google Drive service not available"

    local_path = Path(local_path).expanduser()
    if not local_path.exists():
        return f"❌ File not found: {local_path}"

    # Determine MIME type
    suffix = local_path.suffix.lower()
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }
    mime_type = mime_types.get(suffix, "image/png")

    try:
        from googleapiclient.http import (  # pylint: disable=import-outside-toplevel
            MediaFileUpload,
        )

        # Upload to Drive first
        file_metadata = {
            "name": local_path.name,
            "parents": [],  # Root folder
        }

        media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)

        uploaded_file = (
            drive_service.files()
            .create(
                body=file_metadata, media_body=media, fields="id,name,webContentLink"
            )
            .execute()
        )

        file_id = uploaded_file.get("id")

        # Make it publicly accessible for Slides to use
        drive_service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        # Now add to slide
        result = await _google_slides_add_image_from_drive_impl(
            presentation_id, slide_id, file_id, x, y, width, height
        )

        if result.startswith("✅"):
            return result.replace(
                "**Image Added from Drive**",
                f"**Image Uploaded & Added**\n\n**Uploaded:** `{local_path.name}` → Drive",
            )
        return result

    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"❌ Failed to upload image: {e}"


async def _google_slides_replace_image_impl(
    presentation_id: str,
    image_id: str,
    new_image_url: str,
) -> str:
    """Replace an existing image with a new one."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        requests = [
            {
                "replaceImage": {
                    "imageObjectId": image_id,
                    "url": new_image_url,
                    "imageReplaceMethod": "CENTER_INSIDE",
                }
            }
        ]

        service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": requests}
        ).execute()

        lines = [
            "✅ **Image Replaced**",
            "",
            f"**Image ID:** `{image_id}`",
            f"**New Source:** {new_image_url[:80]}...",
            "",
            f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit",
        ]

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"❌ Failed to replace image: {e}"


async def _google_slides_delete_element_impl(
    presentation_id: str,
    element_id: str,
) -> str:
    """Delete an element (image, text box, shape) from a slide."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        requests = [{"deleteObject": {"objectId": element_id}}]

        service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": requests}
        ).execute()

        lines = [
            "✅ **Element Deleted**",
            "",
            f"**Element ID:** `{element_id}`",
            "",
            f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit",
        ]

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"❌ Failed to delete element: {e}"


async def _google_slides_move_slide_impl(
    presentation_id: str,
    slide_id: str,
    new_index: int,
) -> str:
    """Move a slide to a new position."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        requests = [
            {
                "updateSlidesPosition": {
                    "slideObjectIds": [slide_id],
                    "insertionIndex": new_index,
                }
            }
        ]

        service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": requests}
        ).execute()

        lines = [
            "✅ **Slide Moved**",
            "",
            f"**Slide ID:** `{slide_id}`",
            f"**New Position:** {new_index + 1}",
            "",
            f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit",
        ]

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"❌ Failed to move slide: {e}"


async def _google_slides_duplicate_slide_impl(
    presentation_id: str,
    slide_id: str,
) -> str:
    """Duplicate a slide."""
    service, error = get_slides_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Slides service not available"

    try:
        import uuid  # pylint: disable=import-outside-toplevel

        new_slide_id = f"slide_{uuid.uuid4().hex[:8]}"

        requests = [
            {
                "duplicateObject": {
                    "objectId": slide_id,
                    "objectIds": {slide_id: new_slide_id},
                }
            }
        ]

        service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": requests}
        ).execute()

        lines = [
            "✅ **Slide Duplicated**",
            "",
            f"**Original:** `{slide_id}`",
            f"**New Slide:** `{new_slide_id}`",
            "",
            f"**Edit:** https://docs.google.com/presentation/d/{presentation_id}/edit",
        ]

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"❌ Failed to duplicate slide: {e}"


# ==================== TOOL REGISTRATION ====================


def register_tools(server: "FastMCP") -> int:  # pylint: disable=too-many-locals
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
        return await _google_slides_add_slide_impl(
            presentation_id, layout, title, body, insert_at
        )

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
        return await _google_slides_update_text_impl(
            presentation_id, object_id, text, replace_all
        )

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
    async def google_slides_add_text_box(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
        return await _google_slides_add_text_box_impl(
            presentation_id, slide_id, text, x, y, width, height
        )

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

    @registry.tool()
    async def google_slides_get_slide(
        presentation_id: str,
        slide_id: str,
    ) -> str:
        """
        Get detailed information about a specific slide including all elements.

        Args:
            presentation_id: The presentation ID
            slide_id: The slide ID to inspect

        Returns:
            Detailed slide info with all element IDs and types
        """
        return await _google_slides_get_slide_impl(presentation_id, slide_id)

    @registry.tool()
    async def google_slides_add_image(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        presentation_id: str,
        slide_id: str,
        image_url: str,
        x: float = 100,
        y: float = 100,
        width: float = 400,
        height: float = 300,
    ) -> str:
        """
        Add an image to a slide from a publicly accessible URL.

        Args:
            presentation_id: The presentation ID
            slide_id: The slide ID to add the image to
            image_url: Public URL of the image (must be accessible by Google)
            x: X position in points (default: 100)
            y: Y position in points (default: 100)
            width: Width in points (default: 400)
            height: Height in points (default: 300)

        Returns:
            New image element ID
        """
        return await _google_slides_add_image_impl(
            presentation_id, slide_id, image_url, x, y, width, height
        )

    @registry.tool()
    async def google_slides_add_image_from_drive(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        presentation_id: str,
        slide_id: str,
        drive_file_id: str,
        x: float = 100,
        y: float = 100,
        width: float = 400,
        height: float = 300,
    ) -> str:
        """
        Add an image to a slide from Google Drive.

        Args:
            presentation_id: The presentation ID
            slide_id: The slide ID to add the image to
            drive_file_id: Google Drive file ID of the image
            x: X position in points (default: 100)
            y: Y position in points (default: 100)
            width: Width in points (default: 400)
            height: Height in points (default: 300)

        Returns:
            New image element ID
        """
        return await _google_slides_add_image_from_drive_impl(
            presentation_id, slide_id, drive_file_id, x, y, width, height
        )

    @registry.tool()
    async def google_slides_upload_image(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        presentation_id: str,
        slide_id: str,
        local_path: str,
        x: float = 100,
        y: float = 100,
        width: float = 400,
        height: float = 300,
    ) -> str:
        """
        Upload a local image file and add it to a slide.

        Uploads the image to Google Drive first, then adds it to the slide.

        Args:
            presentation_id: The presentation ID
            slide_id: The slide ID to add the image to
            local_path: Path to local image file (png, jpg, gif, webp, svg)
            x: X position in points (default: 100)
            y: Y position in points (default: 100)
            width: Width in points (default: 400)
            height: Height in points (default: 300)

        Returns:
            New image element ID
        """
        return await _google_slides_upload_image_impl(
            presentation_id, slide_id, local_path, x, y, width, height
        )

    @registry.tool()
    async def google_slides_replace_image(
        presentation_id: str,
        image_id: str,
        new_image_url: str,
    ) -> str:
        """
        Replace an existing image with a new one.

        Args:
            presentation_id: The presentation ID
            image_id: The image element ID to replace (from google_slides_get_slide)
            new_image_url: Public URL of the new image

        Returns:
            Confirmation of replacement
        """
        return await _google_slides_replace_image_impl(
            presentation_id, image_id, new_image_url
        )

    @registry.tool()
    async def google_slides_delete_element(
        presentation_id: str,
        element_id: str,
    ) -> str:
        """
        Delete an element (image, text box, shape) from a slide.

        Args:
            presentation_id: The presentation ID
            element_id: The element ID to delete (from google_slides_get_slide)

        Returns:
            Confirmation of deletion
        """
        return await _google_slides_delete_element_impl(presentation_id, element_id)

    @registry.tool()
    async def google_slides_move_slide(
        presentation_id: str,
        slide_id: str,
        new_index: int,
    ) -> str:
        """
        Move a slide to a new position in the presentation.

        Args:
            presentation_id: The presentation ID
            slide_id: The slide ID to move
            new_index: New position (0-based index)

        Returns:
            Confirmation of move
        """
        return await _google_slides_move_slide_impl(
            presentation_id, slide_id, new_index
        )

    @registry.tool()
    async def google_slides_duplicate_slide(
        presentation_id: str,
        slide_id: str,
    ) -> str:
        """
        Duplicate a slide.

        Args:
            presentation_id: The presentation ID
            slide_id: The slide ID to duplicate

        Returns:
            New slide ID
        """
        return await _google_slides_duplicate_slide_impl(presentation_id, slide_id)

    return registry.count
