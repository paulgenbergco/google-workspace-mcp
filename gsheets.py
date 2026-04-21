from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class SheetsService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("sheets", "v4", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ read

    def get_metadata(self, spreadsheet_id: str) -> Dict[str, Any]:
        """Get spreadsheet metadata (title, sheets/tabs, row/col counts)."""
        ss = self.service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="spreadsheetId,properties.title,sheets.properties",
        ).execute()

        sheets = []
        for s in ss.get("sheets", []):
            props = s.get("properties", {})
            grid = props.get("gridProperties", {})
            sheets.append({
                "sheetId": props.get("sheetId"),
                "title": props.get("title", ""),
                "index": props.get("index", 0),
                "rowCount": grid.get("rowCount", 0),
                "columnCount": grid.get("columnCount", 0),
            })

        return {
            "spreadsheetId": ss.get("spreadsheetId", ""),
            "title": ss.get("properties", {}).get("title", ""),
            "sheets": sheets,
        }

    def get_range(
        self,
        spreadsheet_id: str,
        range: str,
        value_render: str = "FORMATTED_VALUE",
    ) -> Dict[str, Any]:
        """Read a range using A1 notation (e.g. 'Sheet1!A1:D10')."""
        result = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range,
            valueRenderOption=value_render,
        ).execute()

        values = result.get("values", [])
        return {
            "spreadsheetId": spreadsheet_id,
            "range": result.get("range", range),
            "rowCount": len(values),
            "values": values,
        }

    def get_data(
        self,
        spreadsheet_id: str,
        sheet_name: Optional[str] = None,
        format: str = "csv",
    ) -> Dict[str, Any]:
        """Read entire sheet as CSV, JSON (list of row-dicts), or raw values."""
        range_str = sheet_name if sheet_name else "Sheet1"
        result = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_str,
            valueRenderOption="FORMATTED_VALUE",
        ).execute()

        values = result.get("values", [])

        if format == "csv":
            lines = []
            for row in values:
                escaped = []
                for cell in row:
                    s = str(cell)
                    if "," in s or '"' in s or "\n" in s:
                        s = '"' + s.replace('"', '""') + '"'
                    escaped.append(s)
                lines.append(",".join(escaped))
            content = "\n".join(lines)
        elif format == "json" and len(values) > 1:
            headers = values[0]
            rows = []
            for row in values[1:]:
                obj = {}
                for i, header in enumerate(headers):
                    obj[header] = row[i] if i < len(row) else ""
                rows.append(obj)
            content = rows
        else:
            content = values

        return {
            "spreadsheetId": spreadsheet_id,
            "sheet": range_str,
            "rowCount": len(values),
            "format": format,
            "content": content,
        }

    # ------------------------------------------------------------------ write

    def create(self, title: str, sheet_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """Create a new spreadsheet."""
        body: Dict[str, Any] = {"properties": {"title": title}}

        if sheet_names:
            body["sheets"] = [
                {"properties": {"title": name}} for name in sheet_names
            ]

        ss = self.service.spreadsheets().create(body=body).execute()
        return {
            "spreadsheetId": ss.get("spreadsheetId", ""),
            "title": ss.get("properties", {}).get("title", ""),
            "url": ss.get("spreadsheetUrl", ""),
            "sheets": [
                s.get("properties", {}).get("title", "")
                for s in ss.get("sheets", [])
            ],
        }

    def update_range(
        self,
        spreadsheet_id: str,
        range: str,
        values: List[List[Any]],
        input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        """Write values to a range using A1 notation."""
        result = self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range,
            valueInputOption=input_option,
            body={"values": values},
        ).execute()

        return {
            "spreadsheetId": spreadsheet_id,
            "updatedRange": result.get("updatedRange", range),
            "updatedRows": result.get("updatedRows", 0),
            "updatedColumns": result.get("updatedColumns", 0),
            "updatedCells": result.get("updatedCells", 0),
        }

    def append_rows(
        self,
        spreadsheet_id: str,
        range: str,
        values: List[List[Any]],
        input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        """Append rows to the end of a sheet/range."""
        result = self.service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range,
            valueInputOption=input_option,
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()

        updates = result.get("updates", {})
        return {
            "spreadsheetId": spreadsheet_id,
            "updatedRange": updates.get("updatedRange", ""),
            "updatedRows": updates.get("updatedRows", 0),
            "updatedCells": updates.get("updatedCells", 0),
        }

    def add_sheet(self, spreadsheet_id: str, title: str) -> Dict[str, Any]:
        """Add a new sheet/tab to a spreadsheet."""
        result = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {"addSheet": {"properties": {"title": title}}}
                ]
            },
        ).execute()

        reply = result.get("replies", [{}])[0]
        props = reply.get("addSheet", {}).get("properties", {})
        return {
            "spreadsheetId": spreadsheet_id,
            "sheetId": props.get("sheetId"),
            "title": props.get("title", title),
        }
