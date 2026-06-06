"""
review_monitor.py — Buchmarketing Agentur
═══════════════════════════════════════════════════════════════
Sucht neue Rezensionen und Erwähnungen zum aktiven Buch und schreibt
neue Treffer in den Google-Sheets-Tab 'Rezension'.

Quellen v1:
- Amazon / LovelyBooks / Thalia / Hugendubel / Goodreads (über DDGS-Suche)
- allgemeine Web-Erwähnungen (Blogs, Presse, YouTube, Instagram etc.)
- zeitbasiert anhand letzter Ausführung via Konfiguration-Tab

Ziele:
- aktive Buchtitel-Daten laden
- neue Rezensionen / Erwähnungen finden
- Dubletten über Link vermeiden
- Treffer sauber in 'Rezension' eintragen
- Telegram-Zusammenfassung senden
- Zeitpunkt des letzten Laufs speichern

Zielspalten in 'Rezension':
ID | Datum | Medium/Name | Typ | Link | Zitat | Sterne / Bewertung | Status

Starten:
    python review_monitor.py
═══════════════════════════════════════════════════════════════
"""

import html
import re
from datetime import datetime
from urllib.parse import urlparse

from ddgs import DDGS

import utils_system as utils


# ─────────────────────────────────────────────────────────────
# KONFIGURATION
# ─────────────────────────────────────────────────────────────

BOOKS_TAB = "Books"
REVIEWS_TAB = "Rezension"
GENERAL_TAB = "Allgemeines"
CONFIG_TAB = "Konfiguration"
LOG_TAB = "Logbuch"

DEFAULT_MAX_RESULTS_PER_QUERY = 8
DEFAULT_QUERY_DAYS = 30
LAST_RUN_KEY = "letzter_review_run"
NEW_STATUS = "Neu gefunden"

PLATFORM_RULES = [
    ("amazon.", "Amazon", "Shop"),
    ("lovelybooks.", "LovelyBooks", "Community"),
    ("thalia.", "Thalia", "Shop"),
    ("hugendubel.", "Hugendubel", "Shop"),
    ("goodreads.", "Goodreads", "Community"),
    ("instagram.com", "Instagram", "Instagram"),
    ("youtube.com", "YouTube", "YouTube"),
    ("youtu.be", "YouTube", "YouTube"),
    ("tiktok.com", "TikTok", "Social"),
    ("facebook.com", "Facebook", "Social"),
]


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

def log(level: str, message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{level}] {ts} — {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "review_monitor.py", level, message]])
    except Exception as e:
        print(f"[WARNUNG] Logbuch konnte nicht geschrieben werden: {e}", flush=True)


# ─────────────────────────────────────────────────────────────
# CONFIG / SHEETS
# ─────────────────────────────────────────────────────────────

def get_config_value(key: str, default=""):
    try:
        value = utils.get_value_by_key(CONFIG_TAB, key)
        return value if value not in (None, "") else default
    except:
        return default


def set_config_value(key: str, value: str):
    try:
        client = utils.get_google_client()
        sheet = client.open_by_key(utils.SPREADSHEET_ID).worksheet(CONFIG_TAB)
        cell = sheet.find(key, in_column=1)
        if cell:
            sheet.update_cell(cell.row, 2, str(value))
        else:
            sheet.append_row([key, str(value), "Automatisch gesetzt durch review_monitor.py"])
    except Exception as e:
        log("WARNUNG", f"Konfiguration konnte nicht gespeichert werden ({key}): {e}")


def get_sheet_rows(tab_name: str):
    try:
        return utils.get_sheet_data(tab_name)
    except Exception as e:
        log("WARNUNG", f"Tab konnte nicht geladen werden ({tab_name}): {e}")
        return []


def get_active_book():
    books = get_sheet_rows(BOOKS_TAB)
    if books:
        try:
            books.sort(key=lambda x: str(x.get("erscheinungsdatum", "0000-00-00")), reverse=True)
        except:
            pass
        return books[0]

    return {
        "titel": get_config_value("buchtitel", "") or get_general_value("buchtitel", "What is Love?"),
        "autorin": get_general_value("autorin_name", "Anni E. Lindner"),
    }


def get_general_value(key: str, default=""):
    try:
        value = utils.get_value_by_key(GENERAL_TAB, key)
        return value if value not in (None, "") else default
    except:
        return default


def build_existing_links():
    links = set()
    for row in get_sheet_rows(REVIEWS_TAB):
        link = str(row.get("Link", "")).strip().lower()
        if link:
            links.add(link)
    return links


# ─────────────────────────────────────────────────────────────
# SUCHLOGIK
# ─────────────────────────────────────────────────────────────

def get_query_days():
    last_run = str(get_config_value(LAST_RUN_KEY, "")).strip()
    if not last_run:
        return DEFAULT_QUERY_DAYS

    try:
        last_dt = datetime.fromisoformat(last_run)
        delta_days = (datetime.now() - last_dt).days
        return max(1, min(30, delta_days + 1))
    except:
        return DEFAULT_QUERY_DAYS


def build_queries(book: dict):
    titel = str(book.get("titel") or book.get("Titel") or "").strip()
    autorin = str(book.get("autorin") or book.get("Autorin") or "").strip()

    base = f'"{titel}" "{autorin}"'.strip()
    if not titel:
        raise ValueError("Kein aktiver Buchtitel gefunden")

    queries = [
        f'{base} site:amazon.de',
        f'{base} site:lovelybooks.de',
        f'{base} site:thalia.de',
        f'{base} site:hugendubel.de',
        f'{base} rezension',
        f'{base} buchbesprechung',
        f'{base} review',
        f'{base} site:youtube.com',
        f'{base} site:instagram.com',
        f'{base} site:goodreads.com',
    ]

    seen = set()
    deduped = []
    for q in queries:
        norm = q.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(q)
    return deduped


def detect_platform(link: str, title: str):
    link_l = (link or "").lower()
    title_l = (title or "").lower()

    for marker, medium_name, typ in PLATFORM_RULES:
        if marker in link_l:
            return medium_name, typ

    if any(k in title_l for k in ["rezension", "review", "buchblog", "bookstagram"]):
        return title or "Web-Erwähnung", "Blog"
    if any(k in title_l for k in ["zeitung", "magazin", "feuilleton", "presse"]):
        return title or "Presse-Erwähnung", "Presse"
    return title or urlparse(link).netloc or "Web-Erwähnung", "Web"


def clean_snippet(text: str):
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:400]


def extract_rating(text: str):
    text = (text or "").strip()

    patterns = [
        r"(\d(?:[\.,]\d)?)\s*/\s*5",
        r"(\d(?:[\.,]\d)?)\s+von\s+5",
        r"([1-5])\s+sterne",
        r"([★☆]{3,5})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def build_review_rows(book: dict, max_results_per_query: int):
    existing_links = build_existing_links()
    results = []
    seen_new_links = set()
    query_days = get_query_days()
    queries = build_queries(book)

    with DDGS() as ddgs:
        for query in queries:
            try:
                hits = list(ddgs.text(query, max_results=max_results_per_query))
            except Exception as e:
                log("WARNUNG", f"Suche fehlgeschlagen für Query '{query}': {e}")
                continue

            for hit in hits:
                link = str(hit.get("href", "")).strip()
                title = str(hit.get("title", "")).strip()
                snippet = clean_snippet(hit.get("body", ""))

                if not link:
                    continue

                link_key = link.lower()
                if link_key in existing_links or link_key in seen_new_links:
                    continue

                medium_name, typ = detect_platform(link, title)
                rating = extract_rating(f"{title} {snippet}")
                datum = datetime.now().strftime("%Y-%m-%d")
                review_id = f"rev_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(results)+1:02d}"

                results.append([
                    review_id,
                    datum,
                    medium_name,
                    typ,
                    link,
                    snippet,
                    rating,
                    NEW_STATUS,
                ])
                seen_new_links.add(link_key)

            log("INFO", f"Review-Suche: Query verarbeitet '{query}' (Fenster ca. {query_days} Tage)")

    return results


# ─────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────

def send_summary_to_telegram(book: dict, new_rows: list):
    titel = html.escape(str(book.get("titel") or book.get("Titel") or "Unbekannt"))
    lines = [
        "📚 <b>Rezensions-Monitor abgeschlossen</b>",
        "",
        f"Buch: <b>{titel}</b>",
        f"Neue Treffer: {len(new_rows)}",
    ]

    if new_rows:
        lines.append("")
        lines.append("<b>Vorschau:</b>")
        for row in new_rows[:5]:
            medium = html.escape(str(row[2]))
            typ = html.escape(str(row[3]))
            snippet = html.escape(str(row[5])[:120])
            lines.append(f"- {medium} ({typ}): {snippet}")

    try:
        utils.send_telegram("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        log("WARNUNG", f"Telegram-Zusammenfassung fehlgeschlagen: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    log("INFO", "Rezensions-Monitor gestartet")

    book = get_active_book()
    max_results_raw = get_config_value("review_max_results_per_query", str(DEFAULT_MAX_RESULTS_PER_QUERY))
    try:
        max_results = max(3, min(15, int(max_results_raw)))
    except:
        max_results = DEFAULT_MAX_RESULTS_PER_QUERY

    rows = build_review_rows(book, max_results)

    if rows:
        utils.write_to_sheet(REVIEWS_TAB, rows)
        log("OK", f"{len(rows)} neue Rezensionen / Erwähnungen gespeichert")
    else:
        log("INFO", "Keine neuen Rezensionen / Erwähnungen gefunden")

    set_config_value(LAST_RUN_KEY, datetime.now().isoformat(timespec="seconds"))
    send_summary_to_telegram(book, rows)
    log("OK", "Rezensions-Monitor beendet")


if __name__ == "__main__":
    main()
