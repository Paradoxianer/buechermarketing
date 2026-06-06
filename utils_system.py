import os
import gspread
import requests
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials

# Umgebungsvariablen aus .env laden
load_dotenv()

# ── Konfiguration ─────────────────────────────────────────────
CREDENTIALS_FILE = os.getenv("GOOGLE_KEY_PATH")
SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Mail / IMAP / SMTP
IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT = int(os.getenv("IMAP_PORT", 143))
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
MAIL_USER = os.getenv("MAIL_USER")
MAIL_PASS = os.getenv("MAIL_PASS")

# FTP Zugangsdaten
FTP_HOST       = os.getenv("FTP_HOST")
FTP_USER       = os.getenv("FTP_USER")
FTP_PASSWORD   = os.getenv("FTP_PASS")
FTP_PORT       = int(os.getenv("FTP_PORT", 21))
FTP_REMOTE_DIR = os.getenv("FTP_REMOTE_DIR", "/")


# ── Google Sheets ─────────────────────────────────────────────

def get_google_client():
    """Erstellt den autorisierten gspread-Client."""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    return gspread.authorize(creds)

def get_sheet_data(worksheet_name: str) -> list:
    """Gibt alle Zeilen eines Tabs als Liste von Dicts zurück."""
    client = get_google_client()
    sheet  = client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
    return sheet.get_all_records()

def get_value_by_key(worksheet_name: str, key_name: str):
    """Gibt den Value zu einem Key aus einem Key/Value-Tab zurück."""
    data = get_sheet_data(worksheet_name)
    for row in data:
        if row.get("Key") == key_name:
            return row.get("Value")
    return None

def get_content_by_category(category: str) -> list:
    """Gibt alle Website_Content-Zeilen eines Bereichs zurück."""
    data = get_sheet_data("Website_Content")
    return [row for row in data if row.get("Bereich") == category]

def write_to_sheet(worksheet_name: str, data_list: list):
    """
    Hängt Zeilen an einen Tab an.
    data_list = [[wert1, wert2, ...], [wert1, wert2, ...], ...]
    """
    client = get_google_client()
    sheet  = client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
    sheet.append_rows(data_list)


# ── Telegram ──────────────────────────────────────────────────

def send_telegram(message: str, parse_mode: str = "HTML"):
    """Sendet eine Nachricht an den konfigurierten Telegram-Chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": parse_mode
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"❌ Telegram Fehler: {e}")
        return None

def check_telegram_updates() -> list:
    """
    Holt neue Updates ohne Offset-Verwaltung.
    Hinweis: telegram_controller.py nutzt seine eigene
    Long-Polling-Schleife — diese Funktion für einfache
    Einzel-Abfragen in anderen Scripts.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        return response.json().get("result", [])
    except Exception as e:
        print(f"❌ Fehler beim Abrufen der Updates: {e}")
        return []


# ── Helfer ────────────────────────────────────────────────────

def get_active_book_title() -> str:
    """Holt den Buchtitel aus dem Tab 'Allgemeines'."""
    data = get_sheet_data("Allgemeines")
    for row in data:
        if row.get("Key") == "buchtitel":
            return row.get("Value")
    return None
