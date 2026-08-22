from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gapi import RETRIES


class DocsService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("docs", "v1", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ read

    def _extract_text(self, content_list: List[Dict[str, Any]]) -> str:
        """Walk paragraph elements' textRuns and return the concatenated string."""
        text_parts = []
        for element in content_list:
            paragraph = element.get("paragraph", {})
            for el in paragraph.get("elements", []):
                text_run = el.get("textRun", {})
                if text_run.get("content"):
                    text_parts.append(text_run["content"])
        return "".join(text_parts)

    def get_text(self, document_id: str, include_tabs: bool = True) -> Dict[str, Any]:
        """Read the full text content of a Google Doc."""
        doc = self.service.documents().get(
            documentId=document_id, includeTabsContent=True
        ).execute(num_retries=RETRIES)

        flat_tabs: List[Dict[str, Any]] = []

        def _walk_tabs(tab_list: List[Dict[str, Any]], nesting_level: int) -> None:
            for i, tab in enumerate(tab_list):
                tab_props = tab.get("tabProperties", {})
                content = (
                    tab.get("documentTab", {}).get("body", {}).get("content", [])
                )
                flat_tabs.append({
                    "tabId": tab_props.get("tabId", ""),
                    "title": tab_props.get("title", ""),
                    "index": i,
                    "nestingLevel": nesting_level,
                    "text": self._extract_text(content),
                })
                _walk_tabs(tab.get("childTabs", []), nesting_level + 1)

        _walk_tabs(doc.get("tabs", []), 0)

        if flat_tabs:
            text = "\n\n".join(tab["text"] for tab in flat_tabs)
            tabs: Optional[List[Dict[str, Any]]] = flat_tabs
        else:
            text = self._extract_text(doc.get("body", {}).get("content", []))
            tabs = None

        return {
            "documentId": doc.get("documentId", ""),
            "title": doc.get("title", ""),
            "text": text,
            "tabs": tabs,
        }

    # ------------------------------------------------------------------ write

    def _location(self, index: int, tab_id: Optional[str]) -> Dict[str, Any]:
        """Build a Docs API location object, including tabId when provided."""
        location: Dict[str, Any] = {"index": index}
        if tab_id is not None:
            location["tabId"] = tab_id
        return location

    def create(self, title: str, body_text: str = "") -> Dict[str, Any]:
        """Create a new Google Doc, optionally with initial text."""
        doc = self.service.documents().create(body={"title": title}).execute(num_retries=RETRIES)
        doc_id = doc["documentId"]

        if body_text:
            self.service.documents().batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": 1},
                                "text": body_text,
                            }
                        }
                    ]
                },
            ).execute(num_retries=RETRIES)

        return {
            "documentId": doc_id,
            "title": doc.get("title", title),
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }

    def write_text(
        self, document_id: str, text: str, index: int = 1, tab_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Insert text at a specific position in a Doc."""
        self.service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "insertText": {
                            "location": self._location(index, tab_id),
                            "text": text,
                        }
                    }
                ]
            },
        ).execute(num_retries=RETRIES)

        return {
            "documentId": document_id,
            "inserted": len(text),
            "at_index": index,
        }

    def replace_text(
        self,
        document_id: str,
        find: str,
        replace: str,
        match_case: bool = True,
        tab_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Find and replace text throughout a Doc."""
        replace_all_text: Dict[str, Any] = {
            "containsText": {
                "text": find,
                "matchCase": match_case,
            },
            "replaceText": replace,
        }
        if tab_ids is not None:
            replace_all_text["tabsCriteria"] = {"tabIds": tab_ids}

        result = self.service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "replaceAllText": replace_all_text
                    }
                ]
            },
        ).execute(num_retries=RETRIES)

        replies = result.get("replies", [{}])
        occurrences = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)

        return {
            "documentId": document_id,
            "find": find,
            "replace": replace,
            "occurrencesChanged": occurrences,
        }

    def format_text(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        underline: Optional[bool] = None,
        font_size: Optional[int] = None,
        link_url: Optional[str] = None,
        named_style: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Format a range of text in a Doc.

        named_style can be: NORMAL_TEXT, HEADING_1 through HEADING_6, TITLE, SUBTITLE
        """
        requests: List[Dict[str, Any]] = []

        # Text style formatting
        style: Dict[str, Any] = {}
        fields = []

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
        if link_url is not None:
            style["link"] = {"url": link_url}
            fields.append("link")

        if fields:
            text_range: Dict[str, Any] = {
                "startIndex": start_index,
                "endIndex": end_index,
            }
            if tab_id is not None:
                text_range["tabId"] = tab_id
            requests.append({
                "updateTextStyle": {
                    "range": text_range,
                    "textStyle": style,
                    "fields": ",".join(fields),
                }
            })

        # Paragraph/heading style
        if named_style:
            paragraph_range: Dict[str, Any] = {
                "startIndex": start_index,
                "endIndex": end_index,
            }
            if tab_id is not None:
                paragraph_range["tabId"] = tab_id
            requests.append({
                "updateParagraphStyle": {
                    "range": paragraph_range,
                    "paragraphStyle": {"namedStyleType": named_style},
                    "fields": "namedStyleType",
                }
            })

        if not requests:
            return {"documentId": document_id, "error": "No formatting specified"}

        self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": requests},
        ).execute(num_retries=RETRIES)

        return {
            "documentId": document_id,
            "formatted": {"start": start_index, "end": end_index},
        }

    def insert_table(
        self,
        document_id: str,
        rows: int,
        columns: int,
        index: int = 1,
        tab_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a table at a specific position in a Doc."""
        self.service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "insertTable": {
                            "rows": rows,
                            "columns": columns,
                            "location": self._location(index, tab_id),
                        }
                    }
                ]
            },
        ).execute(num_retries=RETRIES)

        return {
            "documentId": document_id,
            "rows": rows,
            "columns": columns,
            "at_index": index,
        }

    def insert_image(
        self,
        document_id: str,
        image_url: str,
        index: int = 1,
        width_pt: Optional[float] = None,
        height_pt: Optional[float] = None,
        tab_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert an inline image at a specific position in a Doc."""
        insert_image: Dict[str, Any] = {
            "uri": image_url,
            "location": self._location(index, tab_id),
        }

        object_size: Dict[str, Any] = {}
        if width_pt is not None:
            object_size["width"] = {"magnitude": width_pt, "unit": "PT"}
        if height_pt is not None:
            object_size["height"] = {"magnitude": height_pt, "unit": "PT"}
        if object_size:
            insert_image["objectSize"] = object_size

        self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertInlineImage": insert_image}]},
        ).execute(num_retries=RETRIES)

        return {
            "documentId": document_id,
            "image_url": image_url,
            "at_index": index,
        }

    def insert_page_break(
        self, document_id: str, index: int = 1, tab_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Insert a page break at a specific position in a Doc."""
        self.service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "insertPageBreak": {
                            "location": self._location(index, tab_id),
                        }
                    }
                ]
            },
        ).execute(num_retries=RETRIES)

        return {
            "documentId": document_id,
            "at_index": index,
        }

    def create_bullets(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        ordered: bool = False,
        tab_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply bullet or numbered list formatting to a range of paragraphs."""
        bullet_range: Dict[str, Any] = {
            "startIndex": start_index,
            "endIndex": end_index,
        }
        if tab_id is not None:
            bullet_range["tabId"] = tab_id

        preset = (
            "NUMBERED_DECIMAL_ALPHA_ROMAN"
            if ordered
            else "BULLET_DISC_CIRCLE_SQUARE"
        )

        self.service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "createParagraphBullets": {
                            "range": bullet_range,
                            "bulletPreset": preset,
                        }
                    }
                ]
            },
        ).execute(num_retries=RETRIES)

        return {
            "documentId": document_id,
            "range": {"start": start_index, "end": end_index},
            "ordered": ordered,
        }

    def batch_update(
        self, document_id: str, requests: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Execute a raw list of Docs API batchUpdate requests."""
        result = self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": requests},
        ).execute(num_retries=RETRIES)

        return {
            "documentId": document_id,
            "replies": result.get("replies", []),
        }
