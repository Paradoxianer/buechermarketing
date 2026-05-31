import os
import gspread
import requests
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials

# Umgebungsvariablen laden
load_dotenv()
# utils_system.py
load_dotenv()
# Debug: Prüfen ob Werte geladen wurden
print(f"DEBUG: GOOGLE_KEY_PATH ist: {os.getenv('GOOGLE_KEY_PATH')}")
print(f"DEBUG: SPREADSHEET_ID ist: {os.getenv('SPREADSHEET_ID')}")

# Konfiguration aus .env
CREDENTIALS_FILE = os.getenv("GOOGLE_KEY_PATH")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 🌐 FTP ZUGANGSDATEN
FTP_HOST = os.getenv("FTP_HOST")
FTP_USER = os.getenv("FTP_USER")
FTP_PASSWORD = os.getenv("FTP_PASS")
FTP_PORT = int(os.getenv("FTP_PORT", 21))
FTP_REMOTE_DIR = os.getenv("FTP_REMOTE_DIR", "/")

# --- GOOGLE SHEETS LOGIK ---




def get_google_client():
    """Erstellt den autorisierten Client für Google Services."""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    return gspread.authorize(creds)

def get_sheet_data(worksheet_name):
    """Holt alle Datensätze aus einem Blatt als Liste von Dictionaries."""
    client = get_google_client()
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
    return sheet.get_all_records()

def get_value_by_key(worksheet_name, key_name):
    """Hilfsfunktion: Holt gezielt einen Wert basierend auf einem Key."""
    data = get_sheet_data(worksheet_name)
    for row in data:
        if row.get("Key") == key_name:
            return row.get("Value")
    return None

def get_content_by_category(category):
    """Holt alle Inhalte eines Bereichs (z.B. 'FAQ' oder 'Impressum')."""
    data = get_sheet_data("Website_Content")
    return [row for row in data if row.get("Bereich") == category]

def write_to_sheet(worksheet_name, data_list):
    """Schreibt Datenzeilen in ein Blatt."""
    client = get_google_client()
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
    sheet.append_rows(data_list)

# --- TELEGRAM LOGIK ---

def send_telegram(message, parse_mode="HTML"):
    """Sendet eine Nachricht an den konfigurierten Chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode
    }
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        print(f"❌ Telegram Fehler: {e}")
        return None

def check_telegram_updates():
    """
    Holt sich neue Nachrichten/Befehle.
    Nützlich, damit der Marketing-Director oder Website-Bot auf Befehle wie 
    /generate_site oder /status reagieren kann.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        response = requests.get(url)
        return response.json().get("result", [])
    except Exception as e:
        print(f"❌ Fehler beim Abrufen der Updates: {e}")
        return []

# --- KOMPLEXE HELFER ---

def get_active_book_title():
    """Holt den Buchtitel direkt aus dem Blatt 'Allgemeines'."""
    data = get_sheet_data("Allgemeines")
    # Suche in der Liste der Dictionaries nach dem Key 'book_name'
    for row in data:
        if row.get("Key") == "book_name":
            return row.get("Value")
    return None
