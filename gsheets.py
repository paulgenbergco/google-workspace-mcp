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

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> Dict[str, float]:
        """Convert '#RRGGBB' or 'RRGGBB' to a color dict with floats 0..1."""
        h = hex_color.lstrip("#")
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return {"red": r / 255, "green": g / 255, "blue": b / 255}

    @staticmethod
    def _grid_range(
        sheet_id: int,
        start_row: Optional[int],
        end_row: Optional[int],
        start_col: Optional[int],
        end_col: Optional[int],
    ) -> Dict[str, Any]:
        """Build a GridRange (0-based, end exclusive). None bounds are omitted."""
        grid: Dict[str, Any] = {"sheetId": sheet_id}
        if start_row is not None:
            grid["startRowIndex"] = start_row
        if end_row is not None:
            grid["endRowIndex"] = end_row
        if start_col is not None:
            grid["startColumnIndex"] = start_col
        if end_col is not None:
            grid["endColumnIndex"] = end_col
        return grid

    # ------------------------------------------------------------------ batch / format

    def batch_update(
        self,
        spreadsheet_id: str,
        requests: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Raw batchUpdate passthrough for arbitrary requests."""
        result = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()

        return {
            "spreadsheetId": result.get("spreadsheetId", spreadsheet_id),
            "replies": result.get("replies", []),
        }

    def format_cells(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_col: int,
        end_col: int,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        font_size: Optional[int] = None,
        background_color: Optional[str] = None,
        text_color: Optional[str] = None,
        number_format: Optional[str] = None,
        horizontal_alignment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply cell formatting to a range via a repeatCell request."""
        cell_format: Dict[str, Any] = {}
        text_format: Dict[str, Any] = {}
        fields: List[str] = []

        if bold is not None:
            text_format["bold"] = bold
            fields.append("userEnteredFormat.textFormat.bold")
        if italic is not None:
            text_format["italic"] = italic
            fields.append("userEnteredFormat.textFormat.italic")
        if font_size is not None:
            text_format["fontSize"] = font_size
            fields.append("userEnteredFormat.textFormat.fontSize")
        if text_color is not None:
            text_format["foregroundColor"] = self._hex_to_rgb(text_color)
            fields.append("userEnteredFormat.textFormat.foregroundColor")

        if text_format:
            cell_format["textFormat"] = text_format

        if background_color is not None:
            cell_format["backgroundColor"] = self._hex_to_rgb(background_color)
            fields.append("userEnteredFormat.backgroundColor")

        if number_format is not None:
            number_types = {
                "CURRENCY",
                "PERCENT",
                "DATE",
                "TIME",
                "DATE_TIME",
                "SCIENTIFIC",
            }
            if number_format in number_types:
                cell_format["numberFormat"] = {"type": number_format}
            else:
                cell_format["numberFormat"] = {
                    "type": "NUMBER",
                    "pattern": number_format,
                }
            fields.append("userEnteredFormat.numberFormat")

        if horizontal_alignment is not None:
            cell_format["horizontalAlignment"] = horizontal_alignment
            fields.append("userEnteredFormat.horizontalAlignment")

        grid_range = self._grid_range(
            sheet_id, start_row, end_row, start_col, end_col
        )
        request = {
            "repeatCell": {
                "range": grid_range,
                "cell": {"userEnteredFormat": cell_format},
                "fields": ",".join(fields),
            }
        }

        self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [request]},
        ).execute()

        return {
            "spreadsheetId": spreadsheet_id,
            "formatted": grid_range,
        }

    def clear_range(self, spreadsheet_id: str, range: str) -> Dict[str, Any]:
        """Clear values from a range using A1 notation."""
        result = self.service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=range,
            body={},
        ).execute()

        return {
            "spreadsheetId": result.get("spreadsheetId", spreadsheet_id),
            "clearedRange": result.get("clearedRange", range),
        }

    def delete_sheet(self, spreadsheet_id: str, sheet_id: int) -> Dict[str, Any]:
        """Delete a sheet/tab by numeric sheetId."""
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
        ).execute()

        return {
            "spreadsheetId": spreadsheet_id,
            "deletedSheetId": sheet_id,
        }

    def rename_sheet(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        title: str,
    ) -> Dict[str, Any]:
        """Rename a sheet/tab by numeric sheetId."""
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheet_id,
                                "title": title,
                            },
                            "fields": "title",
                        }
                    }
                ]
            },
        ).execute()

        return {
            "spreadsheetId": spreadsheet_id,
            "sheetId": sheet_id,
            "title": title,
        }

    def duplicate_sheet(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        new_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Duplicate a sheet/tab by numeric sheetId."""
        duplicate: Dict[str, Any] = {"sourceSheetId": sheet_id}
        if new_title is not None:
            duplicate["newSheetName"] = new_title

        result = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"duplicateSheet": duplicate}]},
        ).execute()

        reply = result.get("replies", [{}])[0]
        props = reply.get("duplicateSheet", {}).get("properties", {})
        return {
            "spreadsheetId": spreadsheet_id,
            "sheetId": props.get("sheetId"),
            "title": props.get("title", new_title or ""),
        }

    def batch_get(
        self,
        spreadsheet_id: str,
        ranges: List[str],
        value_render: str = "FORMATTED_VALUE",
    ) -> Dict[str, Any]:
        """Read multiple ranges in one call using A1 notation."""
        result = self.service.spreadsheets().values().batchGet(
            spreadsheetId=spreadsheet_id,
            ranges=ranges,
            valueRenderOption=value_render,
        ).execute()

        value_ranges = [
            {
                "range": vr.get("range", ""),
                "values": vr.get("values", []),
            }
            for vr in result.get("valueRanges", [])
        ]
        return {
            "spreadsheetId": result.get("spreadsheetId", spreadsheet_id),
            "valueRanges": value_ranges,
        }

    def freeze(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        rows: int = 0,
        cols: int = 0,
    ) -> Dict[str, Any]:
        """Freeze the given number of rows and columns on a sheet."""
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheet_id,
                                "gridProperties": {
                                    "frozenRowCount": rows,
                                    "frozenColumnCount": cols,
                                },
                            },
                            "fields": (
                                "gridProperties.frozenRowCount,"
                                "gridProperties.frozenColumnCount"
                            ),
                        }
                    }
                ]
            },
        ).execute()

        return {
            "spreadsheetId": spreadsheet_id,
            "sheetId": sheet_id,
            "frozenRowCount": rows,
            "frozenColumnCount": cols,
        }

    def merge_cells(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_col: int,
        end_col: int,
        merge_type: str = "MERGE_ALL",
    ) -> Dict[str, Any]:
        """Merge a range of cells."""
        grid_range = self._grid_range(
            sheet_id, start_row, end_row, start_col, end_col
        )
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {"mergeCells": {"range": grid_range, "mergeType": merge_type}}
                ]
            },
        ).execute()

        return {
            "spreadsheetId": spreadsheet_id,
            "merged": grid_range,
            "mergeType": merge_type,
        }
