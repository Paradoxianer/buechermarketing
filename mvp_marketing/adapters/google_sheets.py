from typing import Any


class GoogleSheetsAdapter:
    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run
        self._utils = None
        if not dry_run:
            import utils_system as utils  # lazy import, keeps tests/env robust

            self._utils = utils

    def _get_existing_ids(self, sheet_name: str, id_column: str) -> set[str]:
        if self.dry_run:
            return set()
        rows = self._utils.get_sheet_data(sheet_name)
        return {str(r.get(id_column, "")).strip() for r in rows if str(r.get(id_column, "")).strip()}

    def upsert_rows(self, sheet_name: str, headers: list[str], rows: list[dict[str, Any]], id_column: str = "id") -> int:
        if not rows:
            return 0
        if self.dry_run:
            return len(rows)

        client = self._utils.get_google_client()
        book = client.open_by_key(self._utils.SPREADSHEET_ID)
        try:
            book.worksheet(sheet_name)
        except Exception:
            book.add_worksheet(title=sheet_name, rows=1000, cols=max(10, len(headers)))
            book.worksheet(sheet_name).append_row(headers)

        existing = self._get_existing_ids(sheet_name, id_column)
        new_rows = [r for r in rows if str(r.get(id_column, "")).strip() not in existing]
        if not new_rows:
            return 0
        values = [[r.get(h, "") for h in headers] for r in new_rows]
        self._utils.write_to_sheet(sheet_name, values)
        return len(values)
