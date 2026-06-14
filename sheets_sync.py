import asyncio
import json
import sys
import threading
from functools import lru_cache

from config import (
    GOOGLE_SERVICE_ACCOUNT_JSON,
    GOOGLE_SHEETS_SPREADSHEET_ID,
    GOOGLE_SHEETS_TAB_NAME,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADERS = [
    "Номер транзакции",
    "Дата и время",
    "Тег отправителя",
    "Тег получателя",
    "Сколько",
    "Комментарий",
]

_sync_lock = threading.Lock()
_headers_checked = False
_warning_keys = set()


def _warn_once(key, message):
    if key in _warning_keys:
        return
    _warning_keys.add(key)
    print(message, file=sys.stderr)


def _sheet_range(cells):
    tab_name = GOOGLE_SHEETS_TAB_NAME.replace("'", "''")
    return f"'{tab_name}'!{cells}"


@lru_cache(maxsize=1)
def _get_sheets_service():
    if not GOOGLE_SERVICE_ACCOUNT_JSON or not GOOGLE_SHEETS_SPREADSHEET_ID:
        _warn_once(
            "sheets_not_configured",
            "Google Sheets sync is disabled: GOOGLE_SERVICE_ACCOUNT_JSON is not set.",
        )
        return None

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        _warn_once(
            "sheets_missing_deps",
            "Google Sheets sync is disabled: install google-api-python-client and google-auth.",
        )
        return None

    try:
        credentials_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=SCOPES,
        )
        return build("sheets", "v4", credentials=credentials, cache_discovery=False)
    except Exception as exc:
        _warn_once(
            "sheets_bad_credentials",
            f"Google Sheets sync is disabled: could not load service account JSON ({exc}).",
        )
        return None


def _ensure_headers(values_api):
    global _headers_checked
    if _headers_checked:
        return

    response = values_api.get(
        spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
        range=_sheet_range("A1:F1"),
    ).execute()
    current_headers = response.get("values", [])
    if not current_headers:
        values_api.update(
            spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
            range=_sheet_range("A1:F1"),
            valueInputOption="USER_ENTERED",
            body={"values": [HEADERS]},
        ).execute()

    _headers_checked = True


def _transaction_exists(values_api, transaction_id):
    response = values_api.get(
        spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
        range=_sheet_range("A:A"),
    ).execute()
    existing_ids = {str(row[0]) for row in response.get("values", []) if row}
    return str(transaction_id) in existing_ids


def _append_transaction_sync(transaction_id, created_at, actor_tag, target_tag, amount, comment):
    with _sync_lock:
        service = _get_sheets_service()
        if not service:
            return False

        values_api = service.spreadsheets().values()
        _ensure_headers(values_api)

        if _transaction_exists(values_api, transaction_id):
            return True

        values_api.append(
            spreadsheetId=GOOGLE_SHEETS_SPREADSHEET_ID,
            range=_sheet_range("A:F"),
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={
                "values": [[
                    transaction_id,
                    created_at,
                    actor_tag or "",
                    target_tag or "",
                    amount,
                    comment or "",
                ]]
            },
        ).execute()
        return True


async def append_transaction_to_sheet(transaction_id, created_at, actor_tag, target_tag, amount, comment):
    try:
        return await asyncio.to_thread(
            _append_transaction_sync,
            transaction_id,
            created_at,
            actor_tag,
            target_tag,
            amount,
            comment,
        )
    except Exception as exc:
        print(
            f"Could not sync transaction {transaction_id} to Google Sheets: {exc}",
            file=sys.stderr,
        )
        return False
