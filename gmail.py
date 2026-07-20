import base64
import mimetypes
import os
import re
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class GmailService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("gmail", "v1", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ profile

    def get_profile(self) -> Dict[str, Any]:
        return self.service.users().getProfile(userId="me").execute()

    # ------------------------------------------------------------------ search / read

    def search_messages(
        self,
        query: str,
        max_results: int = 20,
        page_token: Optional[str] = None,
        include_body: bool = False,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "userId": "me",
            "q": query,
            "maxResults": min(max_results, 100),
        }
        if page_token:
            params["pageToken"] = page_token

        result = self.service.users().messages().list(**params).execute()
        raw_messages = result.get("messages", [])

        messages = []
        for raw in raw_messages:
            fmt = "full" if include_body else "metadata"
            msg = self._get_raw_message(raw["id"], format=fmt)
            messages.append(self._parse_message(msg))

        return {
            "messages": messages,
            "nextPageToken": result.get("nextPageToken"),
            "resultSizeEstimate": result.get("resultSizeEstimate", 0),
        }

    def get_message(self, message_id: str) -> Dict[str, Any]:
        msg = self._get_raw_message(message_id, format="full")
        return self._parse_message(msg)

    def get_thread(self, thread_id: str) -> Dict[str, Any]:
        thread = self.service.users().threads().get(userId="me", id=thread_id).execute()
        messages = [self._parse_message(m) for m in thread.get("messages", [])]
        return {
            "id": thread["id"],
            "messageCount": len(messages),
            "messages": messages,
        }

    # ------------------------------------------------------------------ send / draft

    def _build_message(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        html_body: str = "",
        attachments: Optional[List[str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Build a MIME message and return the raw base64url-encoded string."""
        if html_body or attachments:
            msg: MIMEText | MIMEMultipart = MIMEMultipart("mixed")
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(body, "plain"))
            if html_body:
                alt.attach(MIMEText(html_body, "html"))
            msg.attach(alt)

            for path in attachments or []:
                with open(path, "rb") as fh:
                    file_data = fh.read()
                ctype, _ = mimetypes.guess_type(path)
                if ctype is None:
                    ctype = "application/octet-stream"
                maintype, subtype = ctype.split("/", 1)
                part = MIMEBase(maintype, subtype)
                part.set_payload(file_data)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=os.path.basename(path),
                )
                msg.attach(part)
        else:
            msg = MIMEText(body, "plain")

        msg["to"] = to
        msg["subject"] = subject
        if cc:
            msg["cc"] = cc
        if bcc:
            msg["bcc"] = bcc
        for key, value in (headers or {}).items():
            msg[key] = value

        return self._encode(msg)

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        html_body: str = "",
        attachments: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        raw = self._build_message(
            to, subject, body, cc, bcc, html_body, attachments
        )
        body_payload: Dict[str, Any] = {"raw": raw}
        if thread_id:
            body_payload["threadId"] = thread_id

        return self.service.users().messages().send(
            userId="me", body=body_payload
        ).execute()

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        html_body: str = "",
        attachments: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        raw = self._build_message(
            to, subject, body, cc, bcc, html_body, attachments
        )
        message: Dict[str, Any] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id

        return self.service.users().drafts().create(
            userId="me", body={"message": message}
        ).execute()

    def reply_message(
        self,
        message_id: str,
        body: str,
        reply_all: bool = False,
        html_body: str = "",
        attachments: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        original = self._get_raw_message(message_id, format="full")
        payload = original.get("payload", {})
        headers: Dict[str, str] = {}
        for h in payload.get("headers", []):
            headers[h["name"].lower()] = h["value"]

        own_address = ""
        try:
            own_address = self.get_profile().get("emailAddress", "")
        except Exception:
            own_address = ""

        to = headers.get("from", "")
        cc = ""
        if reply_all:
            extra = []
            for field in ("to", "cc"):
                value = headers.get(field, "")
                if value:
                    extra.append(value)
            recipients = [
                addr.strip()
                for addr in ",".join(extra).split(",")
                if addr.strip()
            ]
            if own_address:
                recipients = [
                    addr
                    for addr in recipients
                    if own_address.lower() not in addr.lower()
                ]
            cc = ", ".join(recipients)

        subject = headers.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject

        reply_headers: Dict[str, str] = {}
        orig_message_id = headers.get("message-id", "")
        if orig_message_id:
            reply_headers["In-Reply-To"] = orig_message_id
            existing_refs = headers.get("references", "")
            reply_headers["References"] = (
                (existing_refs + " " + orig_message_id).strip()
                if existing_refs
                else orig_message_id
            )

        raw = self._build_message(
            to,
            subject,
            body,
            cc=cc,
            html_body=html_body,
            attachments=attachments,
            headers=reply_headers,
        )
        body_payload: Dict[str, Any] = {"raw": raw}
        thread_id = original.get("threadId")
        if thread_id:
            body_payload["threadId"] = thread_id

        return self.service.users().messages().send(
            userId="me", body=body_payload
        ).execute()

    def forward_message(
        self,
        message_id: str,
        to: str,
        body: str = "",
        cc: str = "",
        bcc: str = "",
    ) -> Dict[str, Any]:
        original = self._get_raw_message(message_id, format="full")
        parsed = self._parse_message(original)

        forwarded = body
        if forwarded:
            forwarded += "\n\n"
        forwarded += "---------- Forwarded message ----------\n"
        forwarded += f"From: {parsed.get('from', '')}\n"
        forwarded += f"Date: {parsed.get('date', '')}\n"
        forwarded += f"Subject: {parsed.get('subject', '')}\n"
        forwarded += f"To: {parsed.get('to', '')}\n\n"
        forwarded += parsed.get("body", "")

        orig_subject = parsed.get("subject", "")
        subject = "Fwd: " + orig_subject

        return self.send_message(to, subject, forwarded, cc=cc, bcc=bcc)

    def list_drafts(self, max_results: int = 20) -> List[Dict[str, Any]]:
        result = self.service.users().drafts().list(
            userId="me", maxResults=min(max_results, 50)
        ).execute()

        drafts = []
        for draft in result.get("drafts", []):
            details = self.service.users().drafts().get(
                userId="me", id=draft["id"], format="full"
            ).execute()
            msg = self._parse_message(details.get("message", {}))
            msg["draft_id"] = draft["id"]
            drafts.append(msg)

        return drafts

    # ------------------------------------------------------------------ send draft / attachments

    def send_draft(self, draft_id: str) -> Dict[str, Any]:
        """Send an existing draft."""
        result = self.service.users().drafts().send(
            userId="me", body={"id": draft_id}
        ).execute()
        msg = result.get("message", result)
        return {
            "status": "sent",
            "message_id": msg.get("id", ""),
            "thread_id": msg.get("threadId", ""),
        }

    def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        save_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download an attachment from a message."""
        msg = self._get_raw_message(message_id, format="full")
        payload = msg.get("payload", {})

        # Find the attachment part to get filename and mime type
        filename = ""
        mime_type = ""
        for part in self._iter_parts(payload):
            body = part.get("body", {})
            if body.get("attachmentId") == attachment_id:
                filename = part.get("filename", "")
                mime_type = part.get("mimeType", "")
                break

        att = self.service.users().messages().attachments().get(
            userId="me", messageId=message_id, id=attachment_id
        ).execute()

        data = att.get("data", "")
        raw = base64.urlsafe_b64decode(data.encode())

        result: Dict[str, Any] = {
            "attachment_id": attachment_id,
            "message_id": message_id,
            "filename": filename,
            "mimeType": mime_type,
            "size": att.get("size", 0),
        }

        if save_path:
            with open(save_path, "wb") as fh:
                fh.write(raw)
            result["saved_to"] = save_path
        else:
            result["data_base64"] = base64.b64encode(raw).decode()

        return result

    def list_attachments(self, message_id: str) -> List[Dict[str, Any]]:
        """List all attachments on a message."""
        msg = self._get_raw_message(message_id, format="full")
        payload = msg.get("payload", {})
        attachments = []

        for part in self._iter_parts(payload):
            body = part.get("body", {})
            if body.get("attachmentId"):
                attachments.append({
                    "attachment_id": body["attachmentId"],
                    "filename": part.get("filename", ""),
                    "mimeType": part.get("mimeType", ""),
                    "size": body.get("size", 0),
                })

        return attachments

    @staticmethod
    def _iter_parts(payload: Dict[str, Any]):
        """Recursively yield all MIME parts."""
        yield payload
        for part in payload.get("parts", []):
            yield from GmailService._iter_parts(part)

    # ------------------------------------------------------------------ labels

    def list_labels(self) -> List[Dict[str, Any]]:
        result = self.service.users().labels().list(userId="me").execute()
        return [
            {"id": lbl["id"], "name": lbl["name"], "type": lbl.get("type", "")}
            for lbl in result.get("labels", [])
        ]

    def modify_labels(
        self,
        message_id: str,
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels

        return self.service.users().messages().modify(
            userId="me", id=message_id, body=body
        ).execute()

    def trash_message(self, message_id: str) -> Dict[str, Any]:
        return self.service.users().messages().trash(
            userId="me", id=message_id
        ).execute()

    def untrash_message(self, message_id: str) -> Dict[str, Any]:
        return self.service.users().messages().untrash(
            userId="me", id=message_id
        ).execute()

    def create_label(
        self,
        name: str,
        label_list_visibility: str = "labelShow",
        message_list_visibility: str = "show",
    ) -> Dict[str, Any]:
        body = {
            "name": name,
            "labelListVisibility": label_list_visibility,
            "messageListVisibility": message_list_visibility,
        }
        return self.service.users().labels().create(
            userId="me", body=body
        ).execute()

    def update_label(
        self,
        label_id: str,
        name: Optional[str] = None,
        label_list_visibility: Optional[str] = None,
        message_list_visibility: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if label_list_visibility is not None:
            body["labelListVisibility"] = label_list_visibility
        if message_list_visibility is not None:
            body["messageListVisibility"] = message_list_visibility

        return self.service.users().labels().patch(
            userId="me", id=label_id, body=body
        ).execute()

    def delete_label(self, label_id: str) -> Dict[str, Any]:
        self.service.users().labels().delete(
            userId="me", id=label_id
        ).execute()
        return {"deleted": True, "label_id": label_id}

    def batch_modify(
        self,
        message_ids: List[str],
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"ids": message_ids}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels

        self.service.users().messages().batchModify(
            userId="me", body=body
        ).execute()
        return {"modified": len(message_ids)}

    def modify_thread_labels(
        self,
        thread_id: str,
        add_labels: Optional[List[str]] = None,
        remove_labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels

        return self.service.users().threads().modify(
            userId="me", id=thread_id, body=body
        ).execute()

    def mark_read(self, message_id: str) -> Dict[str, Any]:
        return self.modify_labels(message_id, remove_labels=["UNREAD"])

    def mark_unread(self, message_id: str) -> Dict[str, Any]:
        return self.modify_labels(message_id, add_labels=["UNREAD"])

    # ------------------------------------------------------------------ filters

    def list_filters(self) -> Dict[str, Any]:
        return self.service.users().settings().filters().list(
            userId="me"
        ).execute()

    def create_filter(
        self,
        criteria: Dict[str, Any],
        action: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.service.users().settings().filters().create(
            userId="me", body={"criteria": criteria, "action": action}
        ).execute()

    def delete_filter(self, filter_id: str) -> Dict[str, Any]:
        self.service.users().settings().filters().delete(
            userId="me", id=filter_id
        ).execute()
        return {"deleted": True, "filter_id": filter_id}

    # ------------------------------------------------------------------ vacation

    def get_vacation(self) -> Dict[str, Any]:
        return self.service.users().settings().getVacation(
            userId="me"
        ).execute()

    def set_vacation(
        self,
        enabled: bool,
        subject: str = "",
        body: str = "",
        html_body: str = "",
        restrict_to_contacts: bool = False,
        restrict_to_domain: bool = False,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> Dict[str, Any]:
        vacation_body: Dict[str, Any] = {
            "enableAutoReply": enabled,
            "restrictToContacts": restrict_to_contacts,
            "restrictToDomain": restrict_to_domain,
        }
        if subject:
            vacation_body["responseSubject"] = subject
        if body:
            vacation_body["responseBodyPlainText"] = body
        if html_body:
            vacation_body["responseBodyHtml"] = html_body
        if start_time is not None:
            vacation_body["startTime"] = str(start_time)
        if end_time is not None:
            vacation_body["endTime"] = str(end_time)

        return self.service.users().settings().updateVacation(
            userId="me", body=vacation_body
        ).execute()

    # ------------------------------------------------------------------ internals

    def _get_raw_message(self, message_id: str, format: str = "full") -> Dict[str, Any]:
        return self.service.users().messages().get(
            userId="me", id=message_id, format=format
        ).execute()

    def _parse_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        payload = msg.get("payload", {})
        headers: Dict[str, str] = {}
        for h in payload.get("headers", []):
            headers[h["name"].lower()] = h["value"]

        body = self._extract_body(payload)

        return {
            "id": msg.get("id", ""),
            "threadId": msg.get("threadId", ""),
            "labels": msg.get("labelIds", []),
            "snippet": msg.get("snippet", ""),
            "date": headers.get("date", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "subject": headers.get("subject", "(no subject)"),
            "body": body,
        }

    def _extract_body(self, payload: Dict[str, Any]) -> str:
        if not payload:
            return ""

        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")

        if body_data:
            decoded = base64.urlsafe_b64decode(body_data.encode()).decode(
                "utf-8", errors="replace"
            )
            if "html" in mime_type:
                decoded = re.sub(r"<[^>]+>", " ", decoded)
                decoded = (
                    decoded.replace("&nbsp;", " ")
                    .replace("&lt;", "<")
                    .replace("&gt;", ">")
                    .replace("&amp;", "&")
                    .replace("&quot;", '"')
                )
                decoded = re.sub(r"\s+", " ", decoded)
            return decoded.strip()

        parts = payload.get("parts", [])

        # Prefer text/plain parts
        for part in parts:
            if part.get("mimeType") == "text/plain":
                result = self._extract_body(part)
                if result:
                    return result

        # Fallback: any part that returns content
        for part in parts:
            result = self._extract_body(part)
            if result:
                return result

        return ""

    @staticmethod
    def _encode(msg: MIMEText | MIMEMultipart) -> str:
        return base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
