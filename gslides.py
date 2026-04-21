from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class SlidesService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("slides", "v1", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ read

    def get_text(self, presentation_id: str) -> Dict[str, Any]:
        """Read all text from a presentation, organized by slide."""
        pres = self.service.presentations().get(
            presentationId=presentation_id
        ).execute()

        slides = []
        for i, slide in enumerate(pres.get("slides", []), 1):
            text_parts = []
            for element in slide.get("pageElements", []):
                shape = element.get("shape", {})
                text_content = shape.get("text", {})
                for text_el in text_content.get("textElements", []):
                    text_run = text_el.get("textRun", {})
                    if text_run.get("content"):
                        text_parts.append(text_run["content"])

            slides.append({
                "slideNumber": i,
                "objectId": slide.get("objectId", ""),
                "text": "".join(text_parts).strip(),
            })

        return {
            "presentationId": pres.get("presentationId", ""),
            "title": pres.get("title", ""),
            "slideCount": len(slides),
            "slides": slides,
        }

    def get_metadata(self, presentation_id: str) -> Dict[str, Any]:
        """Get presentation metadata (title, slide count, dimensions)."""
        pres = self.service.presentations().get(
            presentationId=presentation_id
        ).execute()

        page_size = pres.get("pageSize", {})
        width = page_size.get("width", {})
        height = page_size.get("height", {})

        slides_meta = []
        for i, slide in enumerate(pres.get("slides", []), 1):
            layout = slide.get("slideProperties", {}).get("layoutObjectId", "")
            notes = ""
            notes_page = slide.get("slideProperties", {}).get("notesPage", {})
            for element in notes_page.get("pageElements", []):
                shape = element.get("shape", {})
                for text_el in shape.get("text", {}).get("textElements", []):
                    text_run = text_el.get("textRun", {})
                    if text_run.get("content"):
                        notes += text_run["content"]

            slides_meta.append({
                "slideNumber": i,
                "objectId": slide.get("objectId", ""),
                "layoutId": layout,
                "speakerNotes": notes.strip(),
            })

        return {
            "presentationId": pres.get("presentationId", ""),
            "title": pres.get("title", ""),
            "slideCount": len(slides_meta),
            "pageWidth": f"{width.get('magnitude', 0)}{width.get('unit', '')}",
            "pageHeight": f"{height.get('magnitude', 0)}{height.get('unit', '')}",
            "slides": slides_meta,
        }

    # ------------------------------------------------------------------ write

    def create(self, title: str) -> Dict[str, Any]:
        """Create a new presentation."""
        pres = self.service.presentations().create(
            body={"title": title}
        ).execute()

        return {
            "presentationId": pres.get("presentationId", ""),
            "title": pres.get("title", title),
            "url": f"https://docs.google.com/presentation/d/{pres.get('presentationId', '')}/edit",
            "slideCount": len(pres.get("slides", [])),
        }

    def add_slide(
        self,
        presentation_id: str,
        layout: str = "BLANK",
        insertion_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Add a new slide. Layout can be: BLANK, TITLE, TITLE_AND_BODY, etc."""
        request: Dict[str, Any] = {
            "createSlide": {
                "slideLayoutReference": {"predefinedLayout": layout},
            }
        }
        if insertion_index is not None:
            request["createSlide"]["insertionIndex"] = insertion_index

        result = self.service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [request]},
        ).execute()

        reply = result.get("replies", [{}])[0]
        object_id = reply.get("createSlide", {}).get("objectId", "")

        return {
            "presentationId": presentation_id,
            "slideObjectId": object_id,
            "layout": layout,
        }

    def replace_text(
        self,
        presentation_id: str,
        find: str,
        replace: str,
        match_case: bool = True,
    ) -> Dict[str, Any]:
        """Find and replace text across the entire presentation."""
        result = self.service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {
                                "text": find,
                                "matchCase": match_case,
                            },
                            "replaceText": replace,
                        }
                    }
                ]
            },
        ).execute()

        replies = result.get("replies", [{}])
        occurrences = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)

        return {
            "presentationId": presentation_id,
            "find": find,
            "replace": replace,
            "occurrencesChanged": occurrences,
        }

    def insert_text(
        self,
        presentation_id: str,
        object_id: str,
        text: str,
        insertion_index: int = 0,
    ) -> Dict[str, Any]:
        """Insert text into a specific shape/text box on a slide."""
        self.service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={
                "requests": [
                    {
                        "insertText": {
                            "objectId": object_id,
                            "insertionIndex": insertion_index,
                            "text": text,
                        }
                    }
                ]
            },
        ).execute()

        return {
            "presentationId": presentation_id,
            "objectId": object_id,
            "inserted": len(text),
        }
