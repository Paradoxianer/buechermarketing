"""
review_monitor.py v3.2 (AI Scoring)
✅ Amazon + LovelyBooks + Web
✅ AI-basierter Relevanzscore (0–100)
✅ nur Treffer >= Mindestscore werden übernommen
✅ Dublettenfilter gegen bestehende Rezensionen
✅ speichert letzter_review_run in Konfiguration
✅ Allgemeines als Primärquelle, Books als Beschreibungs-Fallback
✅ kompatibel mit telegram_controller und erweitertem Rezension-Tab

Erwartete Spalten in 'Rezension':
ID | Datum | Medium/Name | Typ | Link | Zitat | Sterne / Bewertung | Status | AI Score | AI Begründung
"""

import json
import re
import time
import traceback
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

import utils_system as utils

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:8b"

MIN_SCORE = 60
DEFAULT_MAX_RESULTS = 8
LAST_RUN_KEY = "letzter_review_run"

BOOKS_TAB = "Books"
GENERAL_TAB = "Allgemeines"
CONFIG_TAB = "Konfiguration"
REVIEWS_TAB = "Rezension"
LOG_TAB = "Logbuch"

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}


# -----------------------------
# LOGGING
# -----------------------------

def log(level, message):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {message}", flush=True)
    try:
        utils.write_to_sheet(LOG_TAB, [[ts, "review_monitor.py", level, message]])
    except Exception:
        pass


# -----------------------------
# TELEGRAM
# -----------------------------

def send_telegram(msg):
    try:
        utils.send_telegram(msg)
    except Exception as e:
        log("WARNUNG", f"Telegram Fehler: {e}")


# -----------------------------
# KONFIGURATION / SHEETS
# -----------------------------

def get_config_value(key, default=""):
    try:
        value = utils.get_value_by_key(CONFIG_TAB, key)
        return value if value not in (None, "") else default
    except Exception:
        return default


def set_config_value(key, value):
    try:
        client = utils.get_google_client()
        sheet = client.open_by_key(utils.SPREADSHEET_ID).worksheet(CONFIG_TAB)
        cell = sheet.find(key, in_column=1)
        if cell:
            sheet.update_cell(cell.row, 2, str(value))
        else:
            sheet.append_row([key, str(value), "Automatisch gesetzt durch review_monitor.py"])
    except Exception as e:
        log("WARNUNG", f"Config konnte nicht gespeichert werden ({key}): {e}")


def get_sheet_rows(tab_name):
    try:
        return utils.get_sheet_data(tab_name)
    except Exception as e:
        log("WARNUNG", f"Tab konnte nicht geladen werden ({tab_name}): {e}")
        return []


def pick_value(row, candidates):
    for key in candidates:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def get_general_value(key, default=""):
    try:
        value = utils.get_value_by_key(GENERAL_TAB, key)
        return value if value not in (None, "") else default
    except Exception:
        return default


def build_general_book():
    titel = get_general_value("buchtitel", "") or get_general_value("book_name", "")
    return {
        "titel": titel,
        "autorin": get_general_value("autorin_name", ""),
        "beschreibung": "",
        "genre": get_general_value("genre", ""),
        "zielsetzung": get_general_value("zielsetzung", ""),
        "amazon_link": get_general_value("amazon_link", "") or get_general_value("amazon_url", ""),
        "lovelybooks_url": get_general_value("lovelybooks_url", ""),
    }


def enrich_book_from_books(book):
    books = get_sheet_rows(BOOKS_TAB)
    if not books:
        return book

    ziel_titel = (book.get("titel") or "").strip().lower()
    ziel_autorin = (book.get("autorin") or "").strip().lower()

    exact_match = None
    fallback_match = None

    for row in books:
        row_titel = pick_value(row, ["titel", "Titel", "Buchtitel", "buchtitel"]).lower()
        row_autorin = pick_value(row, ["autorin", "Autorin", "autor", "Autor", "autorin_name"]).lower()

        if ziel_titel and row_titel == ziel_titel and (not ziel_autorin or row_autorin == ziel_autorin):
            exact_match = row
            break
        if ziel_titel and row_titel == ziel_titel:
            fallback_match = row

    matched = exact_match or fallback_match
    if not matched:
        return book

    beschreibung = pick_value(matched, ["beschreibung", "Beschreibung", "Klappentext", "Kurzbeschreibung"])
    genre = pick_value(matched, ["genre", "Genre"])
    amazon_link = pick_value(matched, ["amazon_link", "Amazon_Link", "amazon_url", "Amazon_URL"])
    lovelybooks_url = pick_value(matched, ["lovelybooks_url", "LovelyBooks_URL", "lovelybooks_link"])

    if beschreibung:
        book["beschreibung"] = beschreibung
    if genre and not book.get("genre"):
        book["genre"] = genre
    if amazon_link and not book.get("amazon_link"):
        book["amazon_link"] = amazon_link
    if lovelybooks_url and not book.get("lovelybooks_url"):
        book["lovelybooks_url"] = lovelybooks_url

    return book


def get_book():
    book = build_general_book()
    book = enrich_book_from_books(book)

    if not book.get("titel"):
        book["titel"] = "What is Love?"
    if not book.get("autorin"):
        book["autorin"] = "Anni E. Lindner"

    return book


def get_existing_links():
    links = set()
    for row in get_sheet_rows(REVIEWS_TAB):
        link = str(row.get("Link", "")).strip().lower()
        if link:
            links.add(link)
    return links


def get_last_run_iso():
    return str(get_config_value(LAST_RUN_KEY, "")).strip()


# -----------------------------
# LLM (OLLAMA)
# -----------------------------

def generate(prompt):
    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=900,
        )
        return r.json().get("response", "")
    except Exception as e:
        log("WARNUNG", f"LLM Fehler: {e}")
        return ""


# -----------------------------
# QUICK FILTER
# -----------------------------

def is_german(text):
    text = (text or "").lower()
    german_words = ["und", "der", "die", "das", "nicht", "ein", "eine", "buch"]
    hits = sum(1 for w in german_words if w in text)
    return hits >= 2


def is_noise(text):
    noise = ["song", "lyrics", "spotify", "album", "musik"]
    t = (text or "").lower()
    return any(n in t for n in noise)


def clean_text(text, limit=800):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text[:limit]


def extract_rating(text):
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


# -----------------------------
# AI SCORE
# -----------------------------

def ai_score(book, text, link):
    prompt = f"""
Du bist ein Bewertungssystem für Buch-Referenzen.

BUCH:
Titel: {book.get('titel')}
Autor: {book.get('autorin')}
Genre: {book.get('genre')}
Zielsetzung: {book.get('zielsetzung')}
Beschreibung:
{book.get('beschreibung')}

TEXT:
{text}

Link:
{link}

AUFGABE:
Bewerte von 0 bis 100 wie wahrscheinlich es ist, dass dieser Text genau dieses Buch beschreibt oder eine relevante Erwähnung dazu ist.

WICHTIG:
- Sprache ist Deutsch
- Song/Film/etc. = niedriger Score
- echte Rezension = hoher Score
- relevante Social-Erwähnung / Ankündigung / Post zum Buch = mittlerer bis hoher Score
- Wenn Titel und Autor klar passen, bewerte höher
- Antworte streng nur als JSON

FORMAT:
{{
  "score": 0,
  "reason": "kurz"
}}
"""

    raw = generate(prompt)
    try:
        json_text = re.search(r"\{.*\}", raw, re.DOTALL).group()
        data = json.loads(json_text)
        score = int(data.get("score", 0))
        score = max(0, min(100, score))
        return {"score": score, "reason": str(data.get("reason", "")).strip()}
    except Exception:
        return {"score": 0, "reason": "parse_error"}


# -----------------------------
# PLATTFORM-HILFEN
# -----------------------------

def detect_type_and_source(link, fallback_title=""):
    link_l = (link or "").lower()
    domain = urlparse(link).netloc.replace("www.", "")

    if "amazon." in link_l:
        return "Amazon", "Amazon"
    if "lovelybooks." in link_l:
        return "LovelyBooks", "LovelyBooks"
    if "thalia." in link_l:
        return "Thalia", "Thalia"
    if "hugendubel." in link_l:
        return "Hugendubel", "Hugendubel"
    if "goodreads." in link_l:
        return "Goodreads", "Goodreads"
    if "youtube.com" in link_l or "youtu.be" in link_l:
        return "YouTube", "YouTube"
    if "instagram.com" in link_l:
        return "Instagram", "Instagram"
    if "facebook.com" in link_l:
        return "Facebook", "Facebook"
    if any(k in (fallback_title or "").lower() for k in ["zeitung", "magazin", "feuilleton", "presse"]):
        return fallback_title or domain, "Presse"
    if any(k in (fallback_title or "").lower() for k in ["blog", "rezension", "review", "bookstagram"]):
        return fallback_title or domain, "Blog"
    return domain or fallback_title or "Web", "Web"


# -----------------------------
# AMAZON
# -----------------------------

def get_amazon_review_url(url):
    match = re.search(r"/dp/([A-Z0-9]+)", str(url))
    if not match:
        return None
    asin = match.group(1)
    return {
        "product_url": f"https://www.amazon.de/dp/{asin}",
        "reviews_url": f"https://www.amazon.de/product-reviews/{asin}",
    }


def parse_amazon_reviews_from_html(html, link):
    soup = BeautifulSoup(html, "html.parser")
    reviews = []

    for block in soup.select('[data-hook="review"]')[:5]:
        body_el = block.select_one('[data-hook="review-body"]')
        rating_el = block.select_one('[data-hook="review-star-rating"], [data-hook="cmps-review-star-rating"]')
        text = clean_text(body_el.get_text(" ", strip=True) if body_el else "")
        rating = clean_text(rating_el.get_text(" ", strip=True) if rating_el else "")
        if not text:
            continue
        reviews.append({
            "source": "Amazon",
            "type": "Amazon",
            "text": text,
            "link": link,
            "rating": rating,
            "score": 100,
            "reason": "Direkter Amazon-Rezensionstreffer",
        })

    return reviews


def fetch_amazon(book):
    urls = get_amazon_review_url(book.get("amazon_link"))
    if not urls:
        log("INFO", "Amazon-Link nicht vorhanden")
        return []

    for label, url in [("Produktseite", urls["product_url"]), ("Review-Seite", urls["reviews_url"])]:
        log("INFO", f"Amazon {label}: {url}")
        try:
            r = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
            html = r.text
        except Exception as e:
            log("WARNUNG", f"Amazon Request Fehler ({label}): {e}")
            continue

        html_l = html.lower()
        if "captcha" in html_l or "anmelden" in html_l or "login" in html_l:
            log("WARNUNG", f"Amazon blockiert oder Login nötig ({label})")
            continue

        reviews = parse_amazon_reviews_from_html(html, url)
        if reviews:
            return reviews

    return []


# -----------------------------
# LOVELYBOOKS
# -----------------------------

def fetch_lovely(book):
    url = book.get("lovelybooks_url")
    if not url:
        return []

    log("INFO", f"LovelyBooks: {url}")
    try:
        html = requests.get(url, headers=REQUEST_HEADERS, timeout=30).text
    except Exception as e:
        log("WARNUNG", f"LovelyBooks Request Fehler: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    reviews = []

    candidates = soup.select("div.user-content, div.comment, article, p")
    for block in candidates[:40]:
        text = clean_text(block.get_text(" ", strip=True))
        if len(text) < 80:
            continue
        reviews.append({
            "source": "LovelyBooks",
            "type": "LovelyBooks",
            "text": text,
            "link": url,
            "rating": extract_rating(text),
            "score": 100,
            "reason": "Direkter LovelyBooks-Treffer",
        })
        if len(reviews) >= 5:
            break

    return reviews


# -----------------------------
# WEB SEARCH
# -----------------------------

def build_queries(book):
    title = book.get("titel", "")
    author = book.get("autorin", "")
    base = f'"{title}" "{author}"'.strip()
    return [
        f"{base} rezension",
        f"{base} buch",
        f"{base}",
        f"{base} instagram",
        f"{base} youtube",
        f"{base} ankündigung",
        f"{base} site:instagram.com",
        f"{base} site:youtube.com",
        f"{base} lovelybooks",
        f"{base} amazon",
    ]


def enrich_result_text(link, fallback_text):
    try:
        r = requests.get(link, headers=REQUEST_HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "", 200)
        paragraphs = " ".join(clean_text(p.get_text(" ", strip=True), 300) for p in soup.find_all("p")[:5])
        merged = clean_text(" ".join([title, fallback_text or "", paragraphs]), 2000)
        return merged or clean_text(fallback_text, 1200)
    except Exception:
        return clean_text(fallback_text, 1200)


def search_web(book):
    queries = build_queries(book)
    results = []
    last_run = get_last_run_iso()
    log("INFO", f"Letzter Review-Run: {last_run or 'noch keiner'}")

    with DDGS() as ddgs:
        for q in queries:
            log("INFO", f"Suche: {q}")
            try:
                hits = list(ddgs.text(q, max_results=DEFAULT_MAX_RESULTS))
            except Exception as e:
                log("FEHLER", f"Search Fehler: {e}")
                continue

            for r in hits:
                text = r.get("body", "")
                title = r.get("title", "")
                link = r.get("href", "")
                if not text or not link:
                    continue
                if not is_german(f"{title} {text}"):
                    continue
                if is_noise(f"{title} {text}"):
                    continue

                enriched_text = enrich_result_text(link, f"{title} {text}")
                score_data = ai_score(book, enriched_text, link)
                score = score_data.get("score", 0)
                reason = score_data.get("reason", "")
                log("INFO", f"SCORE {score} → {title[:60]}")

                if score < MIN_SCORE:
                    continue

                source, typ = detect_type_and_source(link, title)
                results.append({
                    "source": source,
                    "type": typ,
                    "text": clean_text(enriched_text, 500),
                    "link": link,
                    "rating": extract_rating(f"{title} {text} {enriched_text}"),
                    "score": score,
                    "reason": reason,
                })
            time.sleep(2)

    return results


# -----------------------------
# SUMMARY
# -----------------------------

def summary(book, reviews):
    msg = "📚 <b>Review Monitor</b>\n\n"
    msg += f"<b>{book.get('titel')}</b>\n"
    msg += f"Treffer: {len(reviews)}\n\n"

    for r in reviews[:5]:
        msg += f"• {html_escape(r['source'])} / {html_escape(r.get('type', ''))} ({r.get('score', '')})\n"
        msg += f"{html_escape(r['text'][:100])}...\n"
        if r.get("link"):
            msg += f"<a href=\"{html_escape(r['link'])}\">Zum Treffer</a>\n"
        msg += "\n"
    return msg


def html_escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# -----------------------------
# MAIN
# -----------------------------

def run():
    try:
        log("INFO", "🚀 Start Review Monitor AI")
        book = get_book()
        log("INFO", f"Buch: {book.get('titel')} | Autorin: {book.get('autorin')}")

        existing_links = get_existing_links()
        all_results = []

        amazon = fetch_amazon(book)
        all_results.extend(amazon)
        time.sleep(2)

        lovely = fetch_lovely(book)
        all_results.extend(lovely)
        time.sleep(2)

        web = search_web(book)
        all_results.extend(web)

        if not all_results:
            set_config_value(LAST_RUN_KEY, datetime.now().isoformat(timespec="seconds"))
            send_telegram("⚠️ Keine relevanten Rezensionen gefunden")
            return

        seen = set(existing_links)
        unique = []
        for r in all_results:
            link = str(r.get("link", "")).strip().lower()
            text_key = clean_text(r.get("text", ""), 120)
            dedupe_key = f"{link}|{text_key}"
            if not link:
                continue
            if link in seen or dedupe_key in seen:
                continue
            seen.add(link)
            seen.add(dedupe_key)
            unique.append(r)

        if not unique:
            set_config_value(LAST_RUN_KEY, datetime.now().isoformat(timespec="seconds"))
            log("INFO", "Keine neuen Links nach Dedupe")
            send_telegram("ℹ️ Keine neuen Rezensionen seit dem letzten Lauf")
            return

        rows = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for i, r in enumerate(unique, start=1):
            rows.append([
                f"rev_{timestamp}_{i:02d}",
                datetime.now().strftime("%Y-%m-%d"),
                r.get("source", "Web"),
                r.get("type", "Rezension"),
                r.get("link", ""),
                r.get("text", ""),
                r.get("rating", ""),
                "Neu gefunden",
                r.get("score", ""),
                r.get("reason", ""),
            ])

        utils.write_to_sheet(REVIEWS_TAB, rows)
        set_config_value(LAST_RUN_KEY, datetime.now().isoformat(timespec="seconds"))

        log("INFO", f"{len(rows)} gespeichert")
        send_telegram(summary(book, unique))

    except Exception as e:
        log("FEHLER", "KRITISCH")
        log("FEHLER", str(e))
        traceback.print_exc()


if __name__ == "__main__":
    run()
