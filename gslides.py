import uuid
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

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _gen_id(prefix: str = "obj") -> str:
        """Generate a unique object id for a slide element."""
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> Dict[str, float]:
        """Convert '#RRGGBB' or 'RRGGBB' to an RGB dict of 0..1 floats."""
        h = hex_color.lstrip("#")
        return {
            "red": int(h[0:2], 16) / 255.0,
            "green": int(h[2:4], 16) / 255.0,
            "blue": int(h[4:6], 16) / 255.0,
        }

    @staticmethod
    def _pt(mag: float) -> Dict[str, Any]:
        """Return a PT magnitude dict."""
        return {"magnitude": mag, "unit": "PT"}

    def _element_properties(
        self,
        slide_object_id: str,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> Dict[str, Any]:
        """Build elementProperties (page, size, transform) for a new element."""
        return {
            "pageObjectId": slide_object_id,
            "size": {
                "width": self._pt(width),
                "height": self._pt(height),
            },
            "transform": {
                "scaleX": 1,
                "scaleY": 1,
                "translateX": x,
                "translateY": y,
                "unit": "PT",
            },
        }

    # -------------------------------------------------------------- write (advanced)

    def batch_update(
        self,
        presentation_id: str,
        requests: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute a raw list of batchUpdate requests."""
        result = self.service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        ).execute()

        return {
            "presentationId": presentation_id,
            "replies": result.get("replies", []),
        }

    def create_textbox(
        self,
        presentation_id: str,
        slide_object_id: str,
        text: str = "",
        x: float = 100,
        y: float = 100,
        width: float = 300,
        height: float = 100,
        object_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a text box on a slide, optionally with initial text."""
        obj_id = object_id or self._gen_id("txt")

        requests: List[Dict[str, Any]] = [
            {
                "createShape": {
                    "objectId": obj_id,
                    "shapeType": "TEXT_BOX",
                    "elementProperties": self._element_properties(
                        slide_object_id, x, y, width, height
                    ),
                }
            }
        ]
        if text:
            requests.append(
                {
                    "insertText": {
                        "objectId": obj_id,
                        "insertionIndex": 0,
                        "text": text,
                    }
                }
            )

        self.service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        ).execute()

        return {
            "presentationId": presentation_id,
            "objectId": obj_id,
        }

    def create_image(
        self,
        presentation_id: str,
        slide_object_id: str,
        image_url: str,
        x: float = 100,
        y: float = 100,
        width: float = 300,
        height: float = 200,
        object_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert an image from a URL onto a slide."""
        obj_id = object_id or self._gen_id("img")

        requests: List[Dict[str, Any]] = [
            {
                "createImage": {
                    "objectId": obj_id,
                    "url": image_url,
                    "elementProperties": self._element_properties(
                        slide_object_id, x, y, width, height
                    ),
                }
            }
        ]

        self.service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        ).execute()

        return {
            "presentationId": presentation_id,
            "objectId": obj_id,
        }

    def delete_object(
        self,
        presentation_id: str,
        object_id: str,
    ) -> Dict[str, Any]:
        """Delete an object (shape, image, etc.) from a presentation."""
        self.service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{"deleteObject": {"objectId": object_id}}]},
        ).execute()

        return {
            "presentationId": presentation_id,
            "deleted": object_id,
        }

    def duplicate_object(
        self,
        presentation_id: str,
        object_id: str,
    ) -> Dict[str, Any]:
        """Duplicate an object and return the new object's id."""
        result = self.service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{"duplicateObject": {"objectId": object_id}}]},
        ).execute()

        reply = result.get("replies", [{}])[0]
        new_object_id = reply.get("duplicateObject", {}).get("objectId", "")

        return {
            "presentationId": presentation_id,
            "objectId": new_object_id,
        }

    def format_text(
        self,
        presentation_id: str,
        object_id: str,
        start_index: Optional[int] = None,
        end_index: Optional[int] = None,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        underline: Optional[bool] = None,
        font_size: Optional[int] = None,
        font_family: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply text styling to a range of text within a shape.

        A FIXED_RANGE is only used when BOTH start_index and end_index are
        given; if either bound is omitted the whole shape's text is styled
        (a lone bound would produce a null in the range, which the API rejects).
        """
        if start_index is not None and end_index is not None:
            text_range: Dict[str, Any] = {
                "type": "FIXED_RANGE",
                "startIndex": start_index,
                "endIndex": end_index,
            }
        else:
            text_range = {"type": "ALL"}

        style: Dict[str, Any] = {}
        fields: List[str] = []

        if bold is not None:
            style["bold"] = bold
            fields.append("bold")
        if italic is not None:
            style["italic"] = italic
            fields.append("italic")
        if underline is not None:
            style["underline"] = underline
            fields.append("underline")
        if font_size is not None:
            style["fontSize"] = {"magnitude": font_size, "unit": "PT"}
            fields.append("fontSize")
        if font_family is not None:
            style["fontFamily"] = font_family
            fields.append("fontFamily")
        if color is not None:
            style["foregroundColor"] = {
                "opaqueColor": {"rgbColor": self._hex_to_rgb(color)}
            }
            fields.append("foregroundColor")

        request = {
            "updateTextStyle": {
                "objectId": object_id,
                "textRange": text_range,
                "style": style,
                "fields": ",".join(fields),
            }
        }

        self.service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [request]},
        ).execute()

        return {
            "presentationId": presentation_id,
            "objectId": object_id,
            "formatted": True,
        }

    def set_speaker_notes(
        self,
        presentation_id: str,
        slide_object_id: str,
        text: str,
    ) -> Dict[str, Any]:
        """Set (replace) the speaker notes for a slide."""
        page = self.service.presentations().pages().get(
            presentationId=presentation_id,
            pageObjectId=slide_object_id,
        ).execute()

        notes_id = (
            page["slideProperties"]["notesPage"]["notesProperties"][
                "speakerNotesObjectId"
            ]
        )

        insert_request = {
            "insertText": {
                "objectId": notes_id,
                "insertionIndex": 0,
                "text": text,
            }
        }
        delete_request = {
            "deleteText": {
                "objectId": notes_id,
                "textRange": {"type": "ALL"},
            }
        }

        try:
            self.service.presentations().batchUpdate(
                presentationId=presentation_id,
                body={"requests": [delete_request, insert_request]},
            ).execute()
        except Exception:
            # deleteText errors when the notes shape is empty; retry insert only.
            self.service.presentations().batchUpdate(
                presentationId=presentation_id,
                body={"requests": [insert_request]},
            ).execute()

        return {
            "presentationId": presentation_id,
            "slideObjectId": slide_object_id,
            "notesObjectId": notes_id,
        }
