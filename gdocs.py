from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class DocsService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("docs", "v1", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ read

    def get_text(self, document_id: str) -> Dict[str, Any]:
        """Read the full text content of a Google Doc."""
        doc = self.service.documents().get(documentId=document_id).execute()

        text_parts = []
        for element in doc.get("body", {}).get("content", []):
            paragraph = element.get("paragraph", {})
            for el in paragraph.get("elements", []):
                text_run = el.get("textRun", {})
                if text_run.get("content"):
                    text_parts.append(text_run["content"])

        tabs = []
        for tab in doc.get("tabs", []):
            tab_props = tab.get("tabProperties", {})
            tabs.append({
                "tabId": tab_props.get("tabId", ""),
                "title": tab_props.get("title", ""),
            })

        return {
            "documentId": doc.get("documentId", ""),
            "title": doc.get("title", ""),
            "text": "".join(text_parts),
            "tabs": tabs if tabs else None,
        }

    # ------------------------------------------------------------------ write

    def create(self, title: str, body_text: str = "") -> Dict[str, Any]:
        """Create a new Google Doc, optionally with initial text."""
        doc = self.service.documents().create(body={"title": title}).execute()
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
            ).execute()

        return {
            "documentId": doc_id,
            "title": doc.get("title", title),
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }

    def write_text(self, document_id: str, text: str, index: int = 1) -> Dict[str, Any]:
        """Insert text at a specific position in a Doc."""
        self.service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": index},
                            "text": text,
                        }
                    }
                ]
            },
        ).execute()

        return {
            "documentId": document_id,
            "inserted": len(text),
            "at_index": index,
        }

    def replace_text(
        self, document_id: str, find: str, replace: str, match_case: bool = True
    ) -> Dict[str, Any]:
        """Find and replace text throughout a Doc."""
        result = self.service.documents().batchUpdate(
            documentId=document_id,
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
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": start_index, "endIndex": end_index},
                    "textStyle": style,
                    "fields": ",".join(fields),
                }
            })

        # Paragraph/heading style
        if named_style:
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": start_index, "endIndex": end_index},
                    "paragraphStyle": {"namedStyleType": named_style},
                    "fields": "namedStyleType",
                }
            })

        if not requests:
            return {"documentId": document_id, "error": "No formatting specified"}

        self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": requests},
        ).execute()

        return {
            "documentId": document_id,
            "formatted": {"start": start_index, "end": end_index},
        }
