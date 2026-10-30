#!/usr/bin/env python3
"""Get Google Slides presentation info."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


PRESENTATION_ID = "179sD9l3SNJIqvUMKlaF0An-ttAx7yLLTUoj-xKdjos8"


def main():
    """Print the title and slide list of the presentation."""
    from tool_modules.aa_google_slides.src.tools_basic import (  # pylint: disable=import-outside-toplevel
        get_slides_service,
    )

    service, error = get_slides_service()
    if error:
        # Do not print the raw error: it can include credential details.
        print("Error: could not connect to Google Slides API (check OAuth credentials)")
        return 1

    print("Connected to Google Slides API")
    deck = service.presentations().get(presentationId=PRESENTATION_ID).execute()
    print(f"Title: {deck.get('title')}")
    print(f"Slides: {len(deck.get('slides', []))}")

    for i, slide in enumerate(deck.get("slides", []), 1):  # pylint: disable=too-many-nested-blocks
        elems = slide.get("pageElements", [])
        title = ""
        for elem in elems:
            if "shape" in elem and "text" in elem.get("shape", {}):
                text_elems = elem["shape"]["text"].get("textElements", [])
                for text_elem in text_elems:
                    if "textRun" in text_elem:
                        content = text_elem["textRun"].get("content", "").strip()
                        if content:
                            title = content[:60]
                            break
                if title:
                    break
        print(f"  {i}. {slide.get('objectId')} - {title}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
