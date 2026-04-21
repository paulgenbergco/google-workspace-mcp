import io
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


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
    ) -> Dict[str, Any]:
        """Search files using Drive query syntax (e.g. "name contains 'invoice'")."""
        q = query
        if not include_trashed:
            q = f"({query}) and trashed = false"

        result = self.service.files().list(
            q=q,
            pageSize=min(max_results, 100),
            fields=f"files({_FILE_FIELDS}), nextPageToken",
            orderBy="modifiedTime desc",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        files = [self._parse_file(f) for f in result.get("files", [])]
        return {
            "count": len(files),
            "files": files,
            "nextPageToken": result.get("nextPageToken"),
        }

    def list_recent(self, max_results: int = 20) -> Dict[str, Any]:
        """List recently modified files."""
        result = self.service.files().list(
            q="trashed = false",
            pageSize=min(max_results, 100),
            fields=f"files({_FILE_FIELDS}), nextPageToken",
            orderBy="modifiedTime desc",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        files = [self._parse_file(f) for f in result.get("files", [])]
        return {"count": len(files), "files": files}

    # ------------------------------------------------------------------ read

    def get_file(self, file_id: str) -> Dict[str, Any]:
        """Get file metadata."""
        f = self.service.files().get(
            fileId=file_id, fields="*", supportsAllDrives=True
        ).execute()
        return self._parse_file(f)

    def read_content(self, file_id: str) -> Dict[str, Any]:
        """Read file content. Exports Workspace files to text-friendly formats."""
        meta = self.service.files().get(
            fileId=file_id,
            fields=f"{_FILE_FIELDS}",
            supportsAllDrives=True,
        ).execute()

        mime_type = meta.get("mimeType", "")
        export_config = _EXPORT_MAP.get(mime_type)

        if export_config:
            export_mime, label = export_config
            res = self.service.files().export(
                fileId=file_id, mimeType=export_mime
            ).execute()
            content = res if isinstance(res, str) else res.decode("utf-8", errors="replace")
        elif mime_type.startswith("text/") or mime_type == "application/json":
            res = self.service.files().get_media(
                fileId=file_id, supportsAllDrives=True
            ).execute()
            content = res if isinstance(res, str) else res.decode("utf-8", errors="replace")
        else:
            content = (
                f"[Binary file: {meta.get('name')} ({mime_type}, "
                f"{meta.get('size', 'unknown')} bytes). Use webViewLink to open.]"
            )

        return {
            **self._parse_file(meta),
            "content": content,
        }

    # ------------------------------------------------------------------ write

    def upload_file(
        self,
        name: str,
        content: str,
        mime_type: str = "text/plain",
        parent_folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload/create a new file with text content."""
        metadata: Dict[str, Any] = {"name": name}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]

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
        ).execute()

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
        ).execute()

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
        ).execute()

        return self._parse_file(f)

    def move_file(self, file_id: str, new_parent_id: str) -> Dict[str, Any]:
        """Move a file to a different folder."""
        current = self.service.files().get(
            fileId=file_id, fields="parents", supportsAllDrives=True
        ).execute()
        previous_parents = ",".join(current.get("parents", []))

        f = self.service.files().update(
            fileId=file_id,
            addParents=new_parent_id,
            removeParents=previous_parents,
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute()

        return self._parse_file(f)

    def rename_file(self, file_id: str, new_name: str) -> Dict[str, Any]:
        """Rename a file."""
        f = self.service.files().update(
            fileId=file_id,
            body={"name": new_name},
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute()

        return self._parse_file(f)

    def trash_file(self, file_id: str) -> Dict[str, Any]:
        """Move a file to trash."""
        f = self.service.files().update(
            fileId=file_id,
            body={"trashed": True},
            fields=_FILE_FIELDS,
            supportsAllDrives=True,
        ).execute()

        return self._parse_file(f)

    # ------------------------------------------------------------------ internals

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
