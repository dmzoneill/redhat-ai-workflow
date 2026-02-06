"""
Gmail Memory Adapter - Memory source for searching emails.

This adapter exposes Gmail search as a memory source,
allowing the memory abstraction layer to query email history.
"""

import logging
from typing import Any

from services.memory_abstraction.models import AdapterResult, HealthStatus, MemoryItem, SourceFilter
from services.memory_abstraction.registry import memory_adapter

logger = logging.getLogger(__name__)


@memory_adapter(
    name="gmail",
    display_name="Gmail",
    capabilities={"query", "search"},
    intent_keywords=[
        "email",
        "gmail",
        "mail",
        "inbox",
        "sent",
        "message",
        "from",
        "to",
        "subject",
        "attachment",
        "unread",
        "received",
        "correspondence",
        "thread",
        "reply",
    ],
    priority=45,
    latency_class="slow",  # External Gmail API
)
class GmailAdapter:
    """
    Adapter for Gmail email search.

    Provides search over Gmail messages,
    including subject, sender, and content.
    """

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Query Gmail for emails matching the question.

        Args:
            question: Natural language question about emails
            filter: Optional filter with limit

        Returns:
            AdapterResult with matching emails
        """
        try:
            from tool_modules.aa_gmail.src.tools_basic import _format_email_date, _get_header, get_gmail_service
        except ImportError:
            try:
                from .tools_basic import _format_email_date, _get_header, get_gmail_service
            except ImportError:
                return AdapterResult(
                    source="gmail",
                    found=False,
                    items=[],
                    error="Gmail tools not available",
                )

        service, error = get_gmail_service()
        if error:
            return AdapterResult(
                source="gmail",
                found=False,
                items=[],
                error=error,
            )

        try:
            limit = filter.limit if filter else 5

            # Search for emails
            results = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=question,
                    maxResults=limit,
                )
                .execute()
            )

            messages = results.get("messages", [])

            if not messages:
                return AdapterResult(
                    source="gmail",
                    found=False,
                    items=[],
                )

            items = []
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
                snippet = msg_data.get("snippet", "")

                # Check labels
                labels = msg_data.get("labelIds", [])
                unread = "UNREAD" in labels

                summary = f"Email from {from_addr}: {subject}"

                content = f"Subject: {subject}\n"
                content += f"From: {from_addr}\n"
                content += f"Date: {_format_email_date(date)}\n"
                content += f"\n{snippet}"

                items.append(
                    MemoryItem(
                        source="gmail",
                        type="email",
                        relevance=0.8 if unread else 0.6,
                        summary=summary,
                        content=content,
                        metadata={
                            "message_id": msg["id"],
                            "thread_id": msg_data.get("threadId"),
                            "subject": subject,
                            "from": from_addr,
                            "date": date,
                            "unread": unread,
                            "labels": labels,
                        },
                    )
                )

            return AdapterResult(
                source="gmail",
                found=True,
                items=items,
            )

        except Exception as e:
            logger.error(f"Gmail query failed: {e}")
            return AdapterResult(
                source="gmail",
                found=False,
                items=[],
                error=str(e),
            )

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Semantic search (same as query for Gmail)."""
        return await self.query(query, filter)

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Gmail adapter is read-only."""
        return AdapterResult(
            source="gmail",
            found=False,
            items=[],
            error="Gmail adapter is read-only.",
        )

    async def health_check(self) -> HealthStatus:
        """Check if Gmail is accessible."""
        try:
            from tool_modules.aa_gmail.src.tools_basic import get_gmail_service
        except ImportError:
            try:
                from .tools_basic import get_gmail_service
            except ImportError:
                return HealthStatus(
                    healthy=False,
                    error="Gmail tools not available",
                )

        try:
            service, error = get_gmail_service()
            if error:
                return HealthStatus(healthy=False, error=error)

            # Try to get profile
            profile = service.users().getProfile(userId="me").execute()

            return HealthStatus(
                healthy=True,
                details={
                    "email": profile.get("emailAddress", "unknown"),
                    "messages_total": profile.get("messagesTotal", 0),
                },
            )
        except ImportError:
            return HealthStatus(
                healthy=False,
                error="Gmail tools not available",
            )
        except Exception as e:
            return HealthStatus(healthy=False, error=str(e))
