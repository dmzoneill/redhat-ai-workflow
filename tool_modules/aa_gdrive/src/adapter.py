"""
Google Drive Memory Adapter - Memory source for searching Drive files.

This adapter exposes Google Drive search as a memory source,
allowing the memory abstraction layer to query documents.
"""

import logging
from typing import Any

from services.memory_abstraction.models import (
    AdapterResult,
    HealthStatus,
    MemoryItem,
    SourceFilter,
)
from services.memory_abstraction.registry import memory_adapter

logger = logging.getLogger(__name__)


@memory_adapter(
    name="gdrive",
    display_name="Google Drive",
    capabilities={"query", "search"},
    intent_keywords=[
        "drive",
        "google drive",
        "document",
        "file",
        "spreadsheet",
        "sheet",
        "slides",
        "presentation",
        "pdf",
        "shared",
        "doc",
        "docs",
        "find file",
        "search drive",
        "my files",
        "shared with me",
    ],
    priority=45,
    latency_class="slow",  # External Google Drive API
)
class GoogleDriveAdapter:
    """
    Adapter for Google Drive file search.

    Provides semantic search over Google Drive files,
    including content search within documents.
    """

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Query Google Drive for files matching the question.

        Args:
            question: Natural language question about files
            filter: Optional filter with limit

        Returns:
            AdapterResult with matching files
        """
        try:
            from tool_modules.aa_gdrive.src.tools_basic import get_drive_service
        except ImportError:
            try:
                from .tools_basic import get_drive_service
            except ImportError:
                return AdapterResult(
                    source="gdrive",
                    found=False,
                    items=[],
                    error="Google Drive tools not available",
                )

        service, error = get_drive_service()
        if error:
            return AdapterResult(
                source="gdrive",
                found=False,
                items=[],
                error=error,
            )

        try:
            limit = filter.limit if filter else 5

            # Search for files
            results = (
                service.files()
                .list(
                    q=f"fullText contains '{question}' and trashed = false",
                    pageSize=limit,
                    fields="files(id, name, mimeType, size, modifiedTime, webViewLink, owners)",
                    orderBy="modifiedTime desc",
                )
                .execute()
            )

            files = results.get("files", [])

            if not files:
                return AdapterResult(
                    source="gdrive",
                    found=False,
                    items=[],
                )

            items = []
            for f in files:
                # Build summary
                mime = f.get("mimeType", "")
                file_type = "file"
                if "document" in mime:
                    file_type = "Google Doc"
                elif "spreadsheet" in mime:
                    file_type = "Google Sheet"
                elif "presentation" in mime:
                    file_type = "Google Slides"
                elif "pdf" in mime:
                    file_type = "PDF"
                elif "folder" in mime:
                    file_type = "folder"

                owner = ""
                if f.get("owners"):
                    owner = f.get("owners", [{}])[0].get("displayName", "")

                summary = f"{file_type}: {f['name']}"
                if owner:
                    summary += f" (by {owner})"

                # Try to get content snippet for docs
                content = f"File: {f['name']}\nType: {file_type}"
                if f.get("webViewLink"):
                    content += f"\nLink: {f['webViewLink']}"

                items.append(
                    MemoryItem(
                        source="gdrive",
                        type="file",
                        relevance=0.7,  # Default relevance for search results
                        summary=summary,
                        content=content,
                        metadata={
                            "file_id": f.get("id"),
                            "name": f.get("name"),
                            "mime_type": mime,
                            "modified": f.get("modifiedTime"),
                            "link": f.get("webViewLink"),
                            "owner": owner,
                        },
                    )
                )

            return AdapterResult(
                source="gdrive",
                found=True,
                items=items,
            )

        except Exception as e:
            logger.error(f"Google Drive query failed: {e}")
            return AdapterResult(
                source="gdrive",
                found=False,
                items=[],
                error=str(e),
            )

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Semantic search (same as query for Drive)."""
        return await self.query(query, filter)

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Google Drive adapter is read-only."""
        return AdapterResult(
            source="gdrive",
            found=False,
            items=[],
            error="Google Drive adapter is read-only. Use Drive tools to create/modify files.",
        )

    async def health_check(self) -> HealthStatus:
        """Check if Google Drive is accessible."""
        try:
            from tool_modules.aa_gdrive.src.tools_basic import get_drive_service
        except ImportError:
            try:
                from .tools_basic import get_drive_service
            except ImportError:
                return HealthStatus(
                    healthy=False,
                    error="Google Drive tools not available",
                )

        try:
            service, error = get_drive_service()
            if error:
                return HealthStatus(healthy=False, error=error)

            # Try to get about info
            about = service.about().get(fields="user").execute()
            user = about.get("user", {})

            return HealthStatus(
                healthy=True,
                details={
                    "user": user.get("emailAddress", "unknown"),
                    "display_name": user.get("displayName", "unknown"),
                },
            )
        except ImportError:
            return HealthStatus(
                healthy=False,
                error="Google Drive tools not available",
            )
        except Exception as e:
            return HealthStatus(healthy=False, error=str(e))
