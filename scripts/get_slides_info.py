#!/usr/bin/env python3
"""Get Google Slides presentation info."""
import sys

sys.path.insert(0, "/home/daoneill/src/redhat-ai-workflow")

from tool_modules.aa_google_slides.src.tools_basic import get_slides_service  # noqa: E402

PRESENTATION_ID = "179sD9l3SNJIqvUMKlaF0An-ttAx7yLLTUoj-xKdjos8"


def main():
    service, error = get_slides_service()
    if error:
        print(f"Error: {error}")
        return 1

    print("Connected to Google Slides API")
    pres = service.presentations().get(presentationId=PRESENTATION_ID).execute()
    print(f'Title: {pres.get("title")}')
    print(f'Slides: {len(pres.get("slides", []))}')

    for i, slide in enumerate(pres.get("slides", []), 1):
        elems = slide.get("pageElements", [])
        title = ""
        for elem in elems:
            if "shape" in elem and "text" in elem.get("shape", {}):
                text_elems = elem["shape"]["text"].get("textElements", [])
                for te in text_elems:
                    if "textRun" in te:
                        content = te["textRun"].get("content", "").strip()
                        if content:
                            title = content[:60]
                            break
                if title:
                    break
        print(f'  {i}. {slide.get("objectId")} - {title}')

    return 0


if __name__ == "__main__":
    sys.exit(main())
