import base64
import io
import mimetypes
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from gapi import RETRIES


# Google Workspace mimeTypes → text-friendly export formats
_EXPORT_MAP = {
    "application/vnd.google-apps.document": ("text/plain", "plain text"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", "CSV"),
    "application/vnd.google-apps.presentation": ("text/plain", "plain text"),
    "application/vnd.google-apps.drawing": ("image/svg+xml", "SVG"),
}

_FILE_FIELDS = (
    "id, name, mimeType, size, createdTime, modifiedTime, "
    "webViewLink, owners, parents, trashed"
)


class DriveService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("drive", "v3", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ search / list

    def search_files(
        self,
        query: str,
        max_results: int = 20,
        include_trashed: bool = False,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search files using Drive query syntax (e.g. "name contains 'invoice'")."""
        q = query
        if not include_trashed:
            q = f"({query}) and trashed = false"

        result = self.service.files().list(
            q=q,
            pageSize=min(max_results, 100),
            pageToken=page_token,
            fields=f"files({_FILE_FIELDS}), nextPageToken",
            orderBy="modifiedTime desc",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute(num_retries=RETRIES)

        files = [self._parse_file(f) for f in result.get("files", [])]
        return {
            "count": len(files),
            "files": files,
            "nextPageToken": result.get("nextPageToken"),
        }

    def list_recent(
        self, max_results: int = 20, page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """List recently modified files."""
        result = self.service.files().list(
            q="trashed = false",
            pageSize=min(max_results, 100),
            pageToken=page_token,
            fields=f"files({_FILE_FIELDS}), nextPageToken",
            orderBy="modifiedTime desc",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute(num_retries=RETRIES)

        files = [self._parse_file(f) for f in result.get("files", [])]
        return {
            "count": len(files),
            "files": files,
            "nextPageToken": result.get("nextPageToken"),
        }

    # ------------------------------------------------------------------ read

    def get_file(self, file_id: str) -> Dict[str, Any]:
        """Get file metadata."""
        f = self.service.files().get(
            fileId=file_id, fields="*", supportsAllDrives=True
        ).execute(num_retries=RETRIES)
        return self._parse_file(f)

    def read_content(
        self,
        file_id: str,
        save_path: Optional[str] = None,
        export_mime: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read file content.

        Workspace files are exported (using ``export_mime`` if given, else the
        ``_EXPORT_MAP`` default, else PDF). Non-Workspace text files are read as
        UTF-8. Everything else is treated as binary: saved to ``save_path`` if
        provided, otherwise returned as base64 (guarded for very large files).
        """
        meta = self.service.files().get(
            fileId=file_id,
            fields=f"{_FILE_FIELDS}",
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        mime_type = meta.get("mimeType", "")
        is_workspace = (
            mime_type in _EXPORT_MAP
            or mime_type.startswith("application/vnd.google-apps")
        )

        result: Dict[str, Any] = {**self._parse_file(meta)}

        if is_workspace:
            if export_mime:
                effective_mime = export_mime
            elif mime_type in _EXPORT_MAP:
                effective_mime = _EXPORT_MAP[mime_type][0]
            else:
                effective_mime = "application/pdf"

            raw = self.service.files().export(
                fileId=file_id, mimeType=effective_mime
            ).execute(num_retries=RETRIES)
            if isinstance(raw, str):
                raw = raw.encode("utf-8")

            if self._is_text_mime(effective_mime):
                result["content"] = raw.decode("utf-8", errors="replace")
                return result
            return self._binary_result(result, raw, meta, effective_mime, save_path)

        if mime_type.startswith("text/") or mime_type == "application/json":
            raw = self.service.files().get_media(
                fileId=file_id, supportsAllDrives=True
            ).execute(num_retries=RETRIES)
            content = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
            result["content"] = content
            return result

        raw = self.service.files().get_media(
            fileId=file_id, supportsAllDrives=True
        ).execute(num_retries=RETRIES)
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return self._binary_result(result, raw, meta, mime_type, save_path)

    # ------------------------------------------------------------------ write

    def upload_file(
        self,
        name: str,
        content: str = "",
        mime_type: str = "text/plain",
        parent_folder_id: Optional[str] = None,
        source_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload/create a new file from text content or a local file."""
        metadata: Dict[str, Any] = {"name": name}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]

        if source_path:
            if mime_type == "text/plain":
                guessed, _ = mimetypes.guess_type(source_path)
                if guessed:
                    mime_type = guessed
            media = MediaFileUpload(
                source_path, mimetype=mime_type, resumable=True
            )
        else:
            media = MediaIoBaseUpload(
                io.BytesIO(content.encode("utf-8")),
                mimetype=mime_type,
                resumable=False,
            )

        f = self.service.files().create(
            body=metadata,
            media_body=media,
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        return self._parse_file(f)

    def update_file(self, file_id: str, content: str, mime_type: str = "text/plain") -> Dict[str, Any]:
        """Update an existing file's content."""
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype=mime_type,
            resumable=False,
        )

        f = self.service.files().update(
            fileId=file_id,
            media_body=media,
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        return self._parse_file(f)

    def create_folder(self, name: str, parent_folder_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a new folder."""
        metadata: Dict[str, Any] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]

        f = self.service.files().create(
            body=metadata,
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        return self._parse_file(f)

    def move_file(self, file_id: str, new_parent_id: str) -> Dict[str, Any]:
        """Move a file to a different folder."""
        current = self.service.files().get(
            fileId=file_id, fields="parents", supportsAllDrives=True
        ).execute(num_retries=RETRIES)
        previous_parents = ",".join(current.get("parents", []))

        f = self.service.files().update(
            fileId=file_id,
            addParents=new_parent_id,
            removeParents=previous_parents,
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        return self._parse_file(f)

    def rename_file(self, file_id: str, new_name: str) -> Dict[str, Any]:
        """Rename a file."""
        f = self.service.files().update(
            fileId=file_id,
            body={"name": new_name},
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        return self._parse_file(f)

    def trash_file(self, file_id: str) -> Dict[str, Any]:
        """Move a file to trash."""
        f = self.service.files().update(
            fileId=file_id,
            body={"trashed": True},
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        return self._parse_file(f)

    def untrash_file(self, file_id: str) -> Dict[str, Any]:
        """Restore a file from trash."""
        f = self.service.files().update(
            fileId=file_id,
            body={"trashed": False},
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        return self._parse_file(f)

    def copy_file(
        self,
        file_id: str,
        name: Optional[str] = None,
        parent_folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a copy of a file."""
        body: Dict[str, Any] = {}
        if name:
            body["name"] = name
        if parent_folder_id:
            body["parents"] = [parent_folder_id]

        f = self.service.files().copy(
            fileId=file_id,
            body=body,
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        return self._parse_file(f)

    def export_file(
        self,
        file_id: str,
        mime_type: str,
        save_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Export a Workspace file to the given mimeType."""
        raw = self.service.files().export(
            fileId=file_id, mimeType=mime_type
        ).execute(num_retries=RETRIES)
        if isinstance(raw, str):
            raw = raw.encode("utf-8")

        if save_path:
            with open(save_path, "wb") as fh:
                fh.write(raw)
            return {"file_id": file_id, "mimeType": mime_type, "saved_to": save_path}

        if len(raw) > 10_000_000:
            return {
                "file_id": file_id,
                "mimeType": mime_type,
                "data_base64": None,
                "note": (
                    f"Export is {len(raw)} bytes (>10MB). Pass save_path to write "
                    "it to disk instead of returning base64."
                ),
            }

        return {
            "file_id": file_id,
            "mimeType": mime_type,
            "data_base64": base64.b64encode(raw).decode(),
        }

    # ------------------------------------------------------------------ sharing / permissions

    def share_file(
        self,
        file_id: str,
        role: str = "reader",
        type: str = "user",
        email: Optional[str] = None,
        domain: Optional[str] = None,
        notify: bool = True,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Grant a permission on a file."""
        perm: Dict[str, Any] = {"role": role, "type": type}
        if type in ("user", "group"):
            perm["emailAddress"] = email
        elif type == "domain":
            perm["domain"] = domain

        # sendNotificationEmail is only valid for user/group grants.
        send_notification = notify if type in ("user", "group") else False

        result = self.service.permissions().create(
            fileId=file_id,
            body=perm,
            sendNotificationEmail=send_notification,
            emailMessage=message if message else None,
            supportsAllDrives=True,
            fields="id,type,role,emailAddress,domain",
        ).execute(num_retries=RETRIES)

        return {"file_id": file_id, "permission": result}

    def list_permissions(self, file_id: str) -> Dict[str, Any]:
        """List all permissions on a file."""
        result = self.service.permissions().list(
            fileId=file_id,
            fields="permissions(id,type,role,emailAddress,domain,displayName)",
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        return {"file_id": file_id, "permissions": result.get("permissions", [])}

    def remove_permission(self, file_id: str, permission_id: str) -> Dict[str, Any]:
        """Remove a permission from a file."""
        self.service.permissions().delete(
            fileId=file_id,
            permissionId=permission_id,
            supportsAllDrives=True,
        ).execute(num_retries=RETRIES)

        return {"removed": True, "file_id": file_id, "permission_id": permission_id}

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _is_text_mime(mime_type: str) -> bool:
        """Whether a mimeType should be decoded as UTF-8 text."""
        return (
            mime_type.startswith("text/")
            or mime_type in ("application/csv", "text/csv")
            or mime_type in ("application/json", "text/json")
            or mime_type in ("application/xhtml+xml", "text/html")
            or mime_type.endswith("+json")
            or mime_type.endswith("+xml")
            or "csv" in mime_type
            or "html" in mime_type
        )

    def _binary_result(
        self,
        result: Dict[str, Any],
        raw: bytes,
        meta: Dict[str, Any],
        mime_type: str,
        save_path: Optional[str],
    ) -> Dict[str, Any]:
        """Populate a read result for binary content (save, base64, or note)."""
        if save_path:
            with open(save_path, "wb") as fh:
                fh.write(raw)
            result["content"] = (
                f"[Binary file: {meta.get('name')} ({mime_type}, "
                f"{len(raw)} bytes) saved to disk.]"
            )
            result["saved_to"] = save_path
            return result

        if len(raw) > 10_000_000:
            result["content"] = (
                f"[Binary file: {meta.get('name')} ({mime_type}, {len(raw)} bytes) "
                "is too large to return inline. Pass save_path to write it to disk.]"
            )
            return result

        result["content"] = (
            f"[Binary file: {meta.get('name')} ({mime_type}, {len(raw)} bytes). "
            "Content returned as base64 in data_base64.]"
        )
        result["data_base64"] = base64.b64encode(raw).decode()
        return result

    def _parse_file(self, f: Dict[str, Any]) -> Dict[str, Any]:
        owners = [
            {"email": o.get("emailAddress", ""), "name": o.get("displayName", "")}
            for o in f.get("owners", [])
        ]

        return {
            "id": f.get("id", ""),
            "name": f.get("name", ""),
            "mimeType": f.get("mimeType", ""),
            "size": f.get("size"),
            "createdTime": f.get("createdTime", ""),
            "modifiedTime": f.get("modifiedTime", ""),
            "webViewLink": f.get("webViewLink", ""),
            "owners": owners,
            "parents": f.get("parents", []),
            "trashed": f.get("trashed", False),
            "isFolder": f.get("mimeType") == "application/vnd.google-apps.folder",
        }
