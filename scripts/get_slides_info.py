#!/usr/bin/env python3
"""Get Google Slides presentation info."""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


PRESENTATION_ID = "179sD9l3SNJIqvUMKlaF0An-ttAx7yLLTUoj-xKdjos8"


def _slide_title(slide: dict) -> str:
    """Return the first non-empty text run of a slide, truncated to 60 chars."""
    for elem in slide.get("pageElements", []):
        text = elem.get("shape", {}).get("text")
        if not text:
            continue
        for text_elem in text.get("textElements", []):
            content = text_elem.get("textRun", {}).get("content", "").strip()
            if content:
                return content[:60]
    return ""


def main():
    """Print the title and slide list of the presentation."""
    # Resolved at runtime: the project root is only on sys.path after the insert above.
    slides_tools = importlib.import_module("tool_modules.aa_google_slides.src.tools_basic")

    service, error = slides_tools.get_slides_service()
    if error:
        # Do not print the raw error: it can include credential details.
        print("Error: could not connect to Google Slides API (check OAuth credentials)")
        return 1

    print("Connected to Google Slides API")
    deck = service.presentations().get(presentationId=PRESENTATION_ID).execute()
    print(f"Title: {deck.get('title')}")
    print(f"Slides: {len(deck.get('slides', []))}")

    for i, slide in enumerate(deck.get("slides", []), 1):
        print(f"  {i}. {slide.get('objectId')} - {_slide_title(slide)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
